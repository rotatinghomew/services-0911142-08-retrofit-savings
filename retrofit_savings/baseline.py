"""用能基线建模与反事实测算。

核心纪律：
- 基线只允许使用 period=baseline 的资料拟合，报告期用电不进入任何拟合步骤，
  因此不可能用报告期实际用电倒推出"总能节能"的基线。
- 驱动因素（室外温度、服务时长、使用人数）来自 operations 的逐日记录。
- 模型为可解释的线性日模型，含换表水平漂移指示项；残差按 AR(1) 估计，
  用 AR(1) 协方差修正参数与总量的标准误。
- 每项诊断（留时段验证、异常残差、外推范围）都产出机器可读的状态与依据，
  比较性不成立时由 verification 模块决定停止给出整体节能率。
"""
import math

import numpy as np

from .metering import measured_days


DRIVER_LABELS = {
    "intercept": "基准负荷（截距）",
    "temperature": "室外温度效应（kWh/℃）",
    "service_hours": "服务时长效应（kWh/小时）",
    "users": "使用人数效应（kWh/人）",
    "post_replacement": "换表后序列水平漂移（例行计量校正）",
}

MIN_BASELINE_DAYS = 30
MIN_HOLDOUT_DAYS = 7
# 超过该比例的报告期日落入基准期驱动因素支撑范围之外，即判为大范围外推。
EXTRAPOLATION_BLOCK_RATIO = 0.25
# 留时段验证误差（归一化 MAE）超过该值，视为模型外推不可靠。
HOLDOUT_CV_LIMIT = 0.20
# 学生化残差超过该值列为异常点（仅标记与留痕，不自动删除）。
OUTLIER_Z_LIMIT = 3.0


class BaselineError(ValueError):
    """基线不可建立或不可比较时抛出，消息直接面向研究员展示。"""


def _driver_matrix(operations, days, replacement_day):
    """按 days 顺序构造设计矩阵 [1, temperature, service_hours, users, post]。"""
    index = {row["day"]: row for row in operations}
    missing = [day for day in days if day not in index]
    if missing:
        raise BaselineError("驱动因素记录缺失，无法解释这些日期的用能：" + ",".join(map(str, missing[:8])))
    matrix = []
    for day in days:
        row = index[day]
        post = 1.0 if replacement_day is not None and day >= replacement_day else 0.0
        matrix.append([1.0, float(row["temperature"]), float(row["service_hours"]),
                       float(row["users"]), post])
    return np.asarray(matrix, dtype=float), index


def _ar1_phi(residuals):
    residuals = np.asarray(residuals, dtype=float)
    denominator = float(np.sum(residuals[:-1] ** 2))
    if denominator == 0.0:
        return 0.0
    return float(np.sum(residuals[1:] * residuals[:-1]) / denominator)


def _fit_ols(x, y):
    beta, sum_sq, rank, _ = np.linalg.lstsq(x, y, rcond=None)
    if rank < x.shape[1]:
        raise BaselineError("基准期驱动因素存在完全共线，模型无法识别独立效应")
    residuals = y - x @ beta
    df = x.shape[0] - x.shape[1]
    if df <= 0:
        raise BaselineError("基准期样本不足以估计基线参数")
    sigma2 = float(residuals @ residuals) / df
    xtx_inv = np.linalg.inv(x.T @ x)
    return beta, residuals, sigma2, xtx_inv


def _ar1_covariance(x, residuals, beta, phi):
    """AR(1) 残差结构下的参数协方差（可行 GLS 三明治形式）。

    方差按 AR(1) 协方差矩阵缩放，再以 OLS 三明治形式估计，
    避免对正态性与同方差做强假设。
    """
    n = x.shape[0]
    corr = np.fromfunction(lambda i, j: phi ** np.abs(i - j), (n, n), dtype=float)
    bread = np.linalg.inv(x.T @ x)
    meat = x.T @ corr @ x
    scale = float(residuals @ residuals) / (n - x.shape[1])
    return bread @ (meat * scale) @ bread


def _support_ranges(operations, baseline_days):
    """各业务驱动因素在整个基准期的观测支撑范围。

    留时段仍是基准期真实观测，应计入支撑域；换表指示是例行计量变量，
    其 0/1 取值由换表日决定，不属于业务外推，不参与外推判定。
    """
    index = {row["day"]: row for row in operations}
    names = ["temperature", "service_hours", "users"]
    columns = {name: [] for name in names}
    for day in baseline_days:
        row = index[day]
        columns["temperature"].append(float(row["temperature"]))
        columns["service_hours"].append(float(row["service_hours"]))
        columns["users"].append(float(row["users"]))
    return {name: {"min": float(min(values)), "max": float(max(values))}
            for name, values in columns.items()}


def _extrapolation(x_report, support):
    """逐日判断报告期业务驱动因素是否落在基准期支撑范围内（矩形支撑域）。"""
    name_to_column = {"temperature": 1, "service_hours": 2, "users": 3}
    flags = []
    reasons = []
    for row in x_report:
        outside = []
        for name, column in name_to_column.items():
            bound = support[name]
            if row[column] < bound["min"] or row[column] > bound["max"]:
                outside.append(name)
        flags.append(bool(outside))
        reasons.append(outside)
    return flags, reasons


def build_baseline(operations, daily_records, replacement_day, baseline_start=None,
                   baseline_stop=None, holdout_days=14):
    """用基准期资料建立可解释基线并完成全部诊断。

    daily_records 为 metering.normalize_meter 的逐日输出；
    baseline_start/stop 可由研究员收窄基准期（留痕到假设中）。
    holdout_days 为基准期末尾留出的连续验证天数。
    """
    if not isinstance(holdout_days, int) or holdout_days < MIN_HOLDOUT_DAYS:
        raise BaselineError("留时段验证至少保留 %d 天" % MIN_HOLDOUT_DAYS)
    baseline_rows = [row for row in operations if row["period"] == "baseline"]
    if not baseline_rows:
        raise BaselineError("资料中没有 period=baseline 的基准期记录")
    data_start = min(row["day"] for row in baseline_rows)
    data_stop = max(row["day"] for row in baseline_rows)
    start = data_start if baseline_start is None else int(baseline_start)
    stop = data_stop if baseline_stop is None else int(baseline_stop)
    if start < data_start or stop > data_stop or start >= stop:
        raise BaselineError("基准期窗口超出资料范围或起止倒置")

    usable = dict(measured_days(daily_records, start, stop))
    window_days = list(range(start, stop + 1))
    fit_days_all = [day for day in window_days if day in usable]
    if len(fit_days_all) < MIN_BASELINE_DAYS + holdout_days:
        raise BaselineError(
            "基准期可定量天数仅 %d，低于建模下限 %d（含留时段验证 %d 天）"
            % (len(fit_days_all), MIN_BASELINE_DAYS + holdout_days, holdout_days))

    holdout_set = set(fit_days_all[-holdout_days:])
    train_days = [day for day in fit_days_all if day not in holdout_set]
    holdout_list = sorted(holdout_set)

    x_train, _ = _driver_matrix(operations, train_days, replacement_day)
    y_train = np.asarray([usable[day] for day in train_days], dtype=float)
    beta, residuals, sigma2, xtx_inv = _fit_ols(x_train, y_train)
    phi = _ar1_phi(residuals)
    phi = max(-0.99, min(0.99, phi))
    covariance = _ar1_covariance(x_train, residuals, beta, phi)
    param_se = np.sqrt(np.clip(np.diag(covariance), 0.0, None))
    sigma = math.sqrt(sigma2)

    # 留时段验证：用训练段预测留出的连续时段，检验时间外推能力。
    x_hold, _ = _driver_matrix(operations, holdout_list, replacement_day)
    y_hold = np.asarray([usable[day] for day in holdout_list], dtype=float)
    predicted_hold = x_hold @ beta
    hold_errors = y_hold - predicted_hold
    holdout_mae = float(np.mean(np.abs(hold_errors)))
    holdout_cv = holdout_mae / float(np.mean(y_hold)) if np.mean(y_hold) != 0 else math.inf
    holdout_bias = float(np.mean(hold_errors))

    # 异常残差：学生化（仅标记，不改变拟合）。
    leverage = np.einsum("ij,jk,ik->i", x_train, xtx_inv, x_train)
    student = residuals / (sigma * np.sqrt(np.clip(1.0 - leverage, 1e-9, None)))
    outliers = [
        {"day": day, "kwh": float(usable[day]), "fitted": float(x_train[i] @ beta),
         "studentized_residual": float(student[i]),
         "flag": "outlier_residual" if abs(student[i]) > OUTLIER_Z_LIMIT else "within_range"}
        for i, day in enumerate(train_days)
    ]
    flagged = [row for row in outliers if row["flag"] == "outlier_residual"]

    support = _support_ranges(operations, fit_days_all)
    coefficients = []
    names = list(DRIVER_LABELS)
    for i, name in enumerate(names):
        coefficients.append({
            "term": name, "label": DRIVER_LABELS[name],
            "coefficient": float(beta[i]), "std_error": float(param_se[i]),
        })

    return {
        "terms": names,
        "coefficients": coefficients,
        "beta": beta,
        "covariance": covariance,
        "sigma": sigma,
        "ar1_phi": phi,
        "baseline_window": {"start": start, "stop": stop,
                            "requested_start": baseline_start, "requested_stop": baseline_stop},
        "train_days": train_days,
        "holdout_days": holdout_list,
        "holdout": {
            "mae_kwh": holdout_mae,
            "cv": float(holdout_cv),
            "bias_kwh": holdout_bias,
            "limit_cv": HOLDOUT_CV_LIMIT,
            "passed": bool(holdout_cv <= HOLDOUT_CV_LIMIT),
            "daily": [{"day": day, "actual_kwh": float(y_hold[i]),
                       "predicted_kwh": float(predicted_hold[i]),
                       "error_kwh": float(hold_errors[i])}
                      for i, day in enumerate(holdout_list)],
        },
        "residuals": {
            "sigma_kwh": sigma,
            "ar1_phi": phi,
            "outlier_limit_z": OUTLIER_Z_LIMIT,
            "outliers": flagged,
            "series": [{"day": int(day), "residual_kwh": float(residuals[i]),
                        "studentized_residual": float(student[i])}
                       for i, day in enumerate(train_days)],
        },
        "support": support,
        "extras": {"extrapolation_block_ratio": EXTRAPOLATION_BLOCK_RATIO,
                   "min_baseline_days": MIN_BASELINE_DAYS, "holdout_days": holdout_days},
    }


def counterfactual_series(baseline, operations, report_start, report_stop, replacement_day,
                          actual_by_day):
    """报告期逐日反事实预测与不确定性（不接触报告期实际值做拟合）。"""
    days = list(range(report_start, report_stop + 1))
    x_report, index = _driver_matrix(operations, days, replacement_day)
    beta = baseline["beta"]
    covariance = baseline["covariance"]
    sigma = baseline["sigma"]
    phi = baseline["ar1_phi"]

    predicted = x_report @ beta
    param_var_daily = np.einsum("ij,jk,ik->i", x_report, covariance, x_report)

    flags, reasons = _extrapolation(x_report, baseline["support"])
    inflation = []
    for i, outside in enumerate(flags):
        if not outside:
            inflation.append(1.0)
            continue
        factor = 1.0
        column_of = {"temperature": 1, "service_hours": 2, "users": 3}
        for name in reasons[i]:
            bound = baseline["support"][name]
            value = x_report[i, column_of[name]]
            span = max(bound["max"] - bound["min"], 1e-9)
            distance = max(bound["min"] - value, value - bound["max"], 0.0) / span
            factor += min(2.0, distance)
        inflation.append(factor)
    inflation = np.asarray(inflation)

    daily = []
    for i, day in enumerate(days):
        actual = actual_by_day.get(day)
        daily.append({
            "day": day,
            "temperature": float(index[day]["temperature"]),
            "service_hours": float(index[day]["service_hours"]),
            "users": float(index[day]["users"]),
            "counterfactual_kwh": float(predicted[i]),
            "param_std_kwh": float(math.sqrt(max(param_var_daily[i], 0.0))),
            "process_std_kwh": float(sigma * inflation[i]),
            "outside_support": flags[i],
            "outside_terms": reasons[i],
            "actual_kwh": None if actual is None else float(actual),
            "observed": actual is not None,
        })

    # 总量层面的 AR(1) 过程噪声：Var(sum e) = sigma^2 * 1'Σ1，外推日按 inflation 缩放。
    n = len(days)
    corr = np.fromfunction(lambda i, j: phi ** np.abs(i - j), (n, n), dtype=float)
    scale = np.diag(inflation)
    process_var_total = float(sigma ** 2 * np.ones(n) @ scale @ corr @ scale @ np.ones(n))
    param_var_total = float(np.ones(n) @ x_report @ covariance @ x_report.T @ np.ones(n))
    return {
        "daily": daily,
        "counterfactual_total_kwh": float(np.sum(predicted)),
        "param_variance_total": param_var_total,
        "process_variance_total": process_var_total,
        "extrapolated_days": [row["day"] for row in daily if row["outside_support"]],
        "extrapolation_ratio": float(np.sum(flags) / n),
    }
