"""节能核验编排：从规范化计量、基线诊断到反事实节省量与可比较性裁定。

输出结构面向三类使用者：
- 研究员：假设、留时段验证、异常残差、外推范围、逐项诊断依据；
- 财务：站点合计 → 表段 → 调整记录的完整钻取链；
- 复核人：情景指纹与并排复核所需的全部输入回显。
"""
import math

from .adjustments import plan_adjustments
from .baseline import (
    BaselineError, build_baseline, counterfactual_series,
    EXTRAPOLATION_BLOCK_RATIO, HOLDOUT_CV_LIMIT,
)
from .metering import coverage, measured_days, normalize_meter, segments


Z_95 = 1.959963984540054
MIN_COVERAGE = 0.90
MIN_BASELINE_COVERAGE = 0.85


def _period_window(operations, site):
    rows = [row for row in operations if row["site"] == site]
    if not rows:
        raise BaselineError("站点缺少运营驱动记录：" + site)
    periods = {row["period"] for row in rows}
    if "baseline" not in periods or "report" not in periods:
        raise BaselineError("运营记录必须同时包含 baseline 与 report 两个时段")
    baseline = [row["day"] for row in rows if row["period"] == "baseline"]
    report = [row["day"] for row in rows if row["period"] == "report"]
    return (min(baseline), max(baseline)), (min(report), max(report))


def _meter_adjustment_variance(records, meter_id):
    """已入账调整的不确定性：资料未给误差时按日均影响量的 25% 取保守标准差。"""
    total = 0.0
    for row in records:
        if row["meter_id"] != meter_id or not row["applied"] or row["total_impact_kwh"] is None:
            continue
        total += (abs(row["total_impact_kwh"]) * 0.25) ** 2
    return total


def evaluate_meter(data, site, segment, windows, baseline_window, holdout_days,
                   adjustment_records, applied_total):
    operations = [row for row in data["operations"] if row["site"] == site]
    (base_start, base_stop), (report_start, report_stop) = windows
    daily = normalize_meter(data, segment)

    baseline_cov = coverage(daily, base_start, base_stop)
    report_cov = coverage(daily, report_start, report_stop)
    comparability = []
    if baseline_cov["measured_share"] < MIN_BASELINE_COVERAGE:
        comparability.append("基准期计量覆盖率 %.1f%% 低于 %.0f%%"
                             % (baseline_cov["measured_share"] * 100, MIN_BASELINE_COVERAGE * 100))
    if report_cov["measured_share"] < MIN_COVERAGE:
        comparability.append("报告期计量覆盖率 %.1f%% 低于 %.0f%%"
                             % (report_cov["measured_share"] * 100, MIN_COVERAGE * 100))

    try:
        baseline = build_baseline(
            operations, daily, segment.replacement_day,
            baseline_start=baseline_window.get("start"),
            baseline_stop=baseline_window.get("stop"),
            holdout_days=holdout_days,
        )
        model_status = "fitted"
        model_message = "基线仅由基准期资料拟合，报告期用电未参与建模"
    except BaselineError as error:
        return {
            "meter_id": segment.meter_id, "boundary": segment.boundary,
            "sub_of": segment.sub_of, "model_status": "failed",
            "model_message": str(error),
            "baseline_window": {
                "start": baseline_window.get("start", base_start),
                "stop": baseline_window.get("stop", base_stop),
                "requested_start": baseline_window.get("start"),
                "requested_stop": baseline_window.get("stop"),
            },
            "baseline_coverage": baseline_cov, "report_coverage": report_cov,
            "counterfactual": None, "actual": None, "savings": None,
            "coefficients": [], "holdout": None, "residuals": None,
            "support": None, "ar1_phi": None,
            "blocking_reasons": [str(error)],
            "adjustments": [row for row in adjustment_records
                            if row["meter_id"] == segment.meter_id],
            "daily_metering": daily,
        }

    actual_pairs = measured_days(daily, report_start, report_stop)
    actual_by_day = dict(actual_pairs)
    forecast = counterfactual_series(
        baseline, operations, report_start, report_stop,
        segment.replacement_day, actual_by_day,
    )

    if not baseline["holdout"]["passed"]:
        comparability.append(
            "留时段验证误差 CV=%.1f%% 超过限值 %.0f%%，基线时间外推能力不足"
            % (baseline["holdout"]["cv"] * 100, HOLDOUT_CV_LIMIT * 100))
    if forecast["extrapolation_ratio"] > EXTRAPOLATION_BLOCK_RATIO:
        comparability.append(
            "报告期 %.1f%% 的日期驱动因素超出基准期支撑范围（限值 %.0f%%），"
            "反事实依赖大范围外推"
            % (forecast["extrapolation_ratio"] * 100, EXTRAPOLATION_BLOCK_RATIO * 100))
    if baseline["residuals"]["outliers"]:
        comparability.append(
            "基准期存在 %d 个学生化残差超 ±%.1f 的异常日，已留痕但未自动剔除"
            % (len(baseline["residuals"]["outliers"]), baseline["residuals"]["outlier_limit_z"]))

    observed_total = float(sum(value for _, value in actual_pairs))
    observed_days = len(actual_pairs)
    counterfactual = forecast["counterfactual_total_kwh"] + applied_total
    # 节省量 = 调整后反事实 − 实际观测；正值表示节省。
    saving = counterfactual - observed_total
    saving_rate = saving / counterfactual if counterfactual > 0 else None

    param_std = math.sqrt(max(forecast["param_variance_total"], 0.0))
    process_std = math.sqrt(max(forecast["process_variance_total"], 0.0))
    adjustment_std = math.sqrt(max(_meter_adjustment_variance(adjustment_records, segment.meter_id), 0.0))
    saving_std = math.sqrt(forecast["param_variance_total"]
                           + forecast["process_variance_total"]
                           + adjustment_std ** 2)

    meter_adjustments = [row for row in adjustment_records if row["meter_id"] == segment.meter_id]
    return {
        "meter_id": segment.meter_id, "boundary": segment.boundary,
        "sub_of": segment.sub_of, "model_status": model_status,
        "model_message": model_message,
        "baseline_coverage": baseline_cov,
        "report_coverage": report_cov,
        "coefficients": baseline["coefficients"],
        "holdout": baseline["holdout"],
        "residuals": baseline["residuals"],
        "support": baseline["support"],
        "baseline_window": baseline["baseline_window"],
        "ar1_phi": baseline["ar1_phi"],
        "counterfactual": {
            "total_kwh": forecast["counterfactual_total_kwh"],
            "adjusted_total_kwh": counterfactual,
            "adjustment_total_kwh": applied_total,
            "param_std_kwh": param_std,
            "process_std_kwh": process_std,
            "adjustment_std_kwh": adjustment_std,
            "extrapolated_days": forecast["extrapolated_days"],
            "extrapolation_ratio": forecast["extrapolation_ratio"],
            "daily": forecast["daily"],
        },
        "actual": {
            "observed_days": observed_days,
            "calendar_days": report_cov["calendar_days"],
            "observed_total_kwh": observed_total,
        },
        "savings": {
            "kwh": saving,
            "rate": saving_rate,
            "std_kwh": saving_std,
            "ci95_kwh": [saving - Z_95 * saving_std, saving + Z_95 * saving_std],
        },
        "blocking_reasons": comparability,
        "adjustments": meter_adjustments,
        "daily_metering": daily,
    }


def run_verification(data, site, assumptions):
    """按研究员给定假设执行整站核验，assumptions 全部回显并参与情景指纹。"""
    assumptions = validate_assumptions(assumptions)
    windows = _period_window(data["operations"], site)
    meter_segments = segments(data, site)
    if not meter_segments:
        raise BaselineError("站点没有可核验的表段：" + site)

    applied_by_meter, adjustment_records, adjustment_blocks = plan_adjustments(
        data, site, meter_segments, windows[1][0], windows[1][1],
        assumptions["approvals"],
    )

    meter_results = []
    for segment in meter_segments:
        meter_results.append(evaluate_meter(
            data, site, segment, windows, assumptions["baseline_window"],
            assumptions["holdout_days"], adjustment_records,
            applied_by_meter.get(segment.meter_id, 0.0),
        ))

    main_meters = [row for row in meter_results if row["sub_of"] is None]
    blocking = list(adjustment_blocks)
    for row in meter_results:
        for reason in row["blocking_reasons"]:
            blocking.append({"meter_id": row["meter_id"], "reason": reason})

    # 站点合计以总表（whole_site）口径为准；分表是其内部构成，不与总表相加。
    comparable = [row for row in main_meters if row["model_status"] == "fitted"]
    totals = _aggregate(comparable)
    totals["computable"] = bool(comparable)
    overall_rate = None
    if not blocking and comparable and totals["counterfactual_kwh"] > 0:
        overall_rate = totals["savings_kwh"] / totals["counterfactual_kwh"]

    return {
        "site": site,
        "assumptions": assumptions,
        "periods": {"baseline": {"start": windows[0][0], "stop": windows[0][1]},
                    "report": {"start": windows[1][0], "stop": windows[1][1]}},
        "meters": meter_results,
        "adjustment_ledger": adjustment_records,
        "blocking_reasons": blocking,
        "comparable": not blocking and bool(comparable),
        "totals": totals,
        "overall_savings_rate": overall_rate,
        "method_notes": [
            "基线模型：日耗 ~ 室外温度 + 服务时长 + 使用人数 + 换表水平漂移指示，仅用基准期 OLS 拟合，残差按 AR(1) 修正标准误。",
            "报告期实际用电只用于事后对照与节省量计算，不参与任何拟合或模型选择。",
            "倍率、换表重置与序列漂移属例行计量条件，在计量规范化阶段处理；停楼与新增服务属单独调整，逐条批准留痕。",
            "总表与分表覆盖范围不同：站点合计只取总表口径，分表用于钻取构成，不与总表相加。",
            "无法比较时（覆盖率、留时段验证、外推范围、异常残差、未估计调整）停止给出整体节能率，只保留表段级线索。",
        ],
    }


def _aggregate(meter_results):
    counterfactual = sum(row["counterfactual"]["total_kwh"] for row in meter_results)
    adjusted = sum(row["counterfactual"]["adjusted_total_kwh"] for row in meter_results)
    actual = sum(row["actual"]["observed_total_kwh"] for row in meter_results)
    adjustment = sum(row["counterfactual"]["adjustment_total_kwh"] for row in meter_results)
    variance = sum(row["savings"]["std_kwh"] ** 2 for row in meter_results)
    saving = adjusted - actual
    return {
        "counterfactual_kwh": counterfactual,
        "adjusted_counterfactual_kwh": adjusted,
        "actual_kwh": actual,
        "adjustment_kwh": adjustment,
        "savings_kwh": saving,
        "savings_std_kwh": math.sqrt(max(variance, 0.0)),
        "savings_ci95_kwh": [saving - Z_95 * math.sqrt(max(variance, 0.0)),
                             saving + Z_95 * math.sqrt(max(variance, 0.0))],
        "meter_count": len(meter_results),
    }


def validate_assumptions(assumptions):
    """校验研究员假设并填充默认值；假设结构稳定，便于并排情景复核。"""
    assumptions = dict(assumptions or {})
    baseline_window = assumptions.get("baseline_window") or {}
    if not isinstance(baseline_window, dict):
        raise BaselineError("基准期窗口必须是对象 {start, stop}")
    clean_window = {}
    for key in ("start", "stop"):
        value = baseline_window.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise BaselineError("基准期" + key + "必须是整数日期或留空")
        clean_window[key] = value
    if "start" in clean_window and "stop" in clean_window and clean_window["start"] >= clean_window["stop"]:
        raise BaselineError("基准期窗口起始日必须早于结束日")

    holdout = assumptions.get("holdout_days", 14)
    if isinstance(holdout, bool) or not isinstance(holdout, int) or holdout < 7 or holdout > 60:
        raise BaselineError("留时段验证天数须为 7 至 60 的整数")

    approvals = assumptions.get("approvals") or {}
    if not isinstance(approvals, dict) or any(not isinstance(value, bool) for value in approvals.values()):
        raise BaselineError("批准覆盖必须是 调整编号→布尔值 的映射")

    label = assumptions.get("scenario_label", "当前情景")
    if not isinstance(label, str) or not label.strip() or len(label) > 80:
        raise BaselineError("情景名称应为 1 至 80 字")
    return {
        "baseline_window": clean_window,
        "holdout_days": holdout,
        "approvals": dict(approvals),
        "scenario_label": label.strip(),
    }
