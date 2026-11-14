"""计量资料规范化：把原始表盘累计读数转换为可审计的日用能序列。

本模块只处理"例行计量条件"——倍率、换表重置、缺测——不做任何节能推断。
所有判断都保留原始依据（raw_delta、multiplier、status），便于财务钻取核对。
"""
from dataclasses import dataclass


# 换表日当天的差分跨越了累计读数重置，任何倍率都无法恢复该区间用量。
RESET_STATUS = "reset_excluded"
# 连续两天中任一天未读表，缺测不是零。
MISSING_STATUS = "missing_excluded"
MEASURED_STATUS = "measured"


@dataclass(frozen=True)
class MeterSegment:
    meter_id: str
    site: str
    boundary: str
    sub_of: str | None
    multiplier_before: float
    multiplier_after: float
    replacement_day: int | None


def segments(data, site):
    """返回站点下的表段，总表在前、分表在后，保持资料中的稳定顺序。"""
    result = []
    for row in data["meters"]:
        if row["site"] != site:
            continue
        result.append(MeterSegment(
            meter_id=row["meter_id"], site=row["site"], boundary=row["boundary"],
            sub_of=row["sub_of"], multiplier_before=float(row["multiplier_before"]),
            multiplier_after=float(row["multiplier_after"]),
            replacement_day=None if row["replacement_day"] is None else int(row["replacement_day"]),
        ))
    result.sort(key=lambda segment: (segment.sub_of is not None, segment.meter_id))
    return result


def multiplier_for(segment, day):
    """日用能归属日 day 使用的倍率：换表日起为换表后倍率。"""
    if segment.replacement_day is not None and day >= segment.replacement_day:
        return segment.multiplier_after
    return segment.multiplier_before


def normalize_meter(data, segment):
    """把单只表的累计读数规范化为逐日记录。

    输出每天一条：
      day, raw_delta（表盘原始差分，跨重置/缺测为 None）,
      multiplier, kwh（规范化日用能，不可计算为 None）,
      status, cumulative（当日表盘值）, quality
    规范化不修改任何原始事实，只追加派生列与状态依据。
    """
    readings = sorted(
        (row for row in data["readings"] if row["meter_id"] == segment.meter_id),
        key=lambda row: row["day"],
    )
    days = []
    by_day = {row["day"]: row for row in readings}
    if not readings:
        return []
    for day in range(readings[0]["day"], readings[-1]["day"] + 1):
        current = by_day.get(day)
        previous = by_day.get(day - 1)
        record = {
            "day": day,
            "raw_delta": None,
            "multiplier": multiplier_for(segment, day),
            "kwh": None,
            "status": MISSING_STATUS,
            "cumulative": None if current is None else current["cumulative"],
            "quality": None if current is None else current["quality"],
        }
        if current is None:
            days.append(record)
            continue
        if current["cumulative"] is None or previous is None or previous["cumulative"] is None:
            record["status"] = MISSING_STATUS
            days.append(record)
            continue
        raw_delta = current["cumulative"] - previous["cumulative"]
        record["raw_delta"] = raw_delta
        if segment.replacement_day is not None and day == segment.replacement_day:
            # 新序列从近零开始，原始差分为负值或小值，跨重置差分没有物理意义。
            record["status"] = RESET_STATUS
            days.append(record)
            continue
        record["kwh"] = raw_delta * record["multiplier"]
        record["status"] = MEASURED_STATUS
        days.append(record)
    return days


def measured_days(records, start=None, stop=None):
    """返回状态为 measured 的 (day, kwh) 列表，可选闭区间过滤。"""
    output = []
    for row in records:
        if start is not None and row["day"] < start:
            continue
        if stop is not None and row["day"] > stop:
            continue
        if row["status"] == MEASURED_STATUS:
            output.append((row["day"], row["kwh"]))
    return output


def coverage(records, start, stop):
    """统计区间内逐日记录的覆盖情况，缺测与重置分开列示依据。"""
    window = [row for row in records if start <= row["day"] <= stop]
    measured = [row for row in window if row["status"] == MEASURED_STATUS]
    missing = [row["day"] for row in window if row["status"] == MISSING_STATUS]
    reset = [row["day"] for row in window if row["status"] == RESET_STATUS]
    total = stop - start + 1
    return {
        "calendar_days": total,
        "measured_days": len(measured),
        "missing_days": missing,
        "reset_days": reset,
        "measured_share": round(len(measured) / total, 6) if total else 0.0,
    }
