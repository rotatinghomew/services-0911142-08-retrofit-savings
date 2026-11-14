"""非例行调整的治理：停楼、新增服务等与计量例行条件分开列示。

规则：
- 例行计量条件（倍率、换表重置、序列水平漂移）在 metering/baseline 内处理，
  不进入本模块，也不需要业务批准。
- adjustments 表中的每条变化都是"单独调整"，必须逐条留痕：
  approved=false 的调整默认不入账（可由研究员在假设中显式批准后入账）；
  approved=true 但 impact_kwh=null 表示影响量尚未估计——不是零影响，
  该调整覆盖报告期时，整体节能率不得给出。
- 调整按表段边界分摊：whole_site 调整进总表，building 边界调整进对应分表；
  无法对应到表段的调整标记为 unresolved，同样阻止整体结论。
"""
from dataclasses import dataclass


ROUTINE_KINDS = {"meter_multiplier", "meter_reset", "meter_level_shift"}
ADJUSTMENT_KIND_LABELS = {
    "closure": "停用/封闭区域",
    "new_service": "新增服务（如托育）",
    "boundary_change": "计量边界变化",
    "other": "其他非例行变化",
}
# 调整对"反事实相对实际"的方向：
# closure：基准期包含该区域用能、报告期没有，反事实需向下扣除 → 符号为负。
# new_service：报告期新增基准期不存在的负荷，反事实需向上加回 → 符号为正。
KIND_SIGN = {"closure": -1.0, "new_service": 1.0, "boundary_change": 0.0, "other": 0.0}


@dataclass(frozen=True)
class AppliedAdjustment:
    adjustment: str
    kind: str
    kind_label: str
    start: int
    stop: int
    meter_id: str
    approved: bool
    applied: bool
    daily_impact_kwh: float | None
    total_impact_kwh: float | None
    sign: float
    basis: str
    blocking: bool
    note: str


def _overlap_days(start, stop, window_start, window_stop):
    lo = max(start, window_start)
    hi = min(stop, window_stop)
    return max(0, hi - lo + 1)


def plan_adjustments(data, site, meter_segments, report_start, report_stop, approvals):
    """把站点调整映射到表段并决定入账/阻止状态。

    approvals: {adjustment_id: bool}，研究员在假设中给出的批准覆盖；
    未出现的调整沿用资料中的 approved 字段。
    返回 (applied_by_meter, records, blocking_reasons)。
    """
    boundaries = {segment.meter_id: segment.boundary for segment in meter_segments}
    applied_by_meter = {segment.meter_id: 0.0 for segment in meter_segments}
    records = []
    blocking_reasons = []

    whole_meters = [meter_id for meter_id, boundary in boundaries.items()
                    if boundary == "whole_site"]
    building_meters = [meter_id for meter_id, boundary in boundaries.items()
                       if boundary != "whole_site"]

    for row in data["adjustments"]:
        if row["site"] != site:
            continue
        start, stop = int(row["start"]), int(row["stop"])
        overlap = _overlap_days(start, stop, report_start, report_stop)
        approved = bool(approvals.get(row["adjustment"], row["approved"]))
        approval_source = "researcher_override" if row["adjustment"] in approvals else "dataset"
        kind = row["kind"]
        sign = KIND_SIGN.get(kind, 0.0)

        # 边界路由必须唯一：一条调整只能落到一个表段，否则总表与分表会双重计算。
        # 停楼/封闭对应建筑分表（无分表时回落总表）；新增服务与边界变化对应总表口径。
        if kind == "closure":
            target_meters = building_meters or whole_meters
        elif kind in ("new_service", "boundary_change", "other"):
            target_meters = whole_meters
        else:
            target_meters = []

        impact = row.get("impact_kwh")
        impact = None if impact is None else float(impact)
        unresolved_boundary = not target_meters
        blocking = False
        note = ""
        total_impact = None
        daily_impact = None
        applied = False

        if unresolved_boundary:
            blocking = True
            note = "调整无法对应到任何表段边界，节能结论不可比较"
            blocking_reasons.append({"adjustment": row["adjustment"], "reason": note})
        elif overlap == 0:
            note = "调整窗口与报告期不重叠，不影响本次核验"
        elif not approved:
            note = "调整未获批准，默认不入账；可在假设中批准后作为情景复核"
        elif impact is None:
            blocking = True
            note = "调整已批准但影响量尚未估计（impact_kwh=null 不是零影响），不得给出整体节能率"
            blocking_reasons.append({"adjustment": row["adjustment"], "reason": note})
        elif sign == 0.0:
            blocking = True
            note = "该调整类型缺少预设方向规则，需要单独方法后再入账"
            blocking_reasons.append({"adjustment": row["adjustment"], "reason": note})
        else:
            # impact_kwh 语义为资料登记的日均影响量，按报告期重叠天数累计。
            daily_impact = impact
            total_impact = impact * overlap * sign
            applied = True
            note = "按登记日均影响量 %g kWh × 重叠 %d 天 × 方向 %+d 入账" % (impact, overlap, int(sign))
            for meter_id in target_meters:
                applied_by_meter[meter_id] += total_impact

        for meter_id in target_meters or [None]:
            records.append(AppliedAdjustment(
                adjustment=row["adjustment"], kind=kind,
                kind_label=ADJUSTMENT_KIND_LABELS.get(kind, kind),
                start=start, stop=stop, meter_id=meter_id, approved=approved,
                applied=applied, daily_impact_kwh=daily_impact,
                total_impact_kwh=total_impact, sign=sign,
                basis=approval_source, blocking=blocking, note=note,
            ).__dict__)

    return applied_by_meter, records, blocking_reasons
