"""508026 水电试点的数据整理与天气连接工具。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_METRICS_PATH = ROOT / "data" / "samples" / "508026_quarterly_operating_metrics.csv"
DEFAULT_ASSET_PATH = ROOT / "data" / "samples" / "508026_asset_metadata.csv"

METRIC_COLUMNS = [
    "symbol",
    "asset_id",
    "period_end",
    "metric",
    "value",
    "unit",
    "publication_date",
    "source_url",
    "source_note",
]
CORE_METRICS = {
    "power_generation",
    "utilization_hours",
    "settled_electricity",
    "settlement_tariff_excl_tax",
}


def load_hydropower_metrics(path: str | Path = DEFAULT_METRICS_PATH) -> pd.DataFrame:
    """读取并校验经人工核验的水电季度经营指标。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    missing = [column for column in METRIC_COLUMNS if column not in frame]
    if missing:
        raise ValueError(f"水电指标文件缺少字段: {missing}")
    frame = frame[METRIC_COLUMNS].copy()
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="raise")
    frame["publication_date"] = pd.to_datetime(frame["publication_date"], errors="raise")
    frame["value"] = pd.to_numeric(frame["value"], errors="raise")
    if frame[["symbol", "asset_id", "metric", "unit", "source_url"]].isna().any().any():
        raise ValueError("水电指标关键字段不能为空")
    duplicates = frame.duplicated(["symbol", "asset_id", "period_end", "metric"])
    if duplicates.any():
        raise ValueError("同一资产、季度和指标存在重复记录")
    if not set(frame["metric"]).issubset(CORE_METRICS):
        unknown = sorted(set(frame["metric"]).difference(CORE_METRICS))
        raise ValueError(f"发现未注册的水电指标: {unknown}")
    return frame.sort_values(["period_end", "metric"]).reset_index(drop=True)


def load_hydropower_asset(path: str | Path = DEFAULT_ASSET_PATH) -> pd.DataFrame:
    """读取水电底层资产与天气映射元数据。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    required = {"symbol", "asset_id", "latitude", "longitude", "coordinate_source_url"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"水电资产文件缺少字段: {missing}")
    if frame.duplicated(["symbol", "asset_id"]).any():
        raise ValueError("水电资产标识存在重复")
    return frame


def pivot_quarterly_metrics(metrics: pd.DataFrame) -> pd.DataFrame:
    """将来源可追溯的 long-format 指标转换为建模用季度宽表。"""

    panel = (
        metrics.pivot(
            index=["symbol", "asset_id", "period_end"], columns="metric", values="value"
        )
        .reset_index()
        .rename_axis(columns=None)
        .sort_values("period_end")
        .reset_index(drop=True)
    )
    panel["quarter"] = panel["period_end"].dt.to_period("Q").astype(str)
    panel["generation_yoy_pct"] = panel.groupby(["symbol", "asset_id"])[
        "power_generation"
    ].pct_change(4) * 100
    return panel


def aggregate_daily_weather(weather: pd.DataFrame) -> pd.DataFrame:
    """把 Open-Meteo 日频天气聚合到自然季度。

    当前聚合针对单一点位。降雨总量、雨日数和极值是水电试点的基础特征，
    但不能替代上游流域面雨量或真实来水量。
    """

    required = {"time", "precipitation_sum"}
    missing = sorted(required.difference(weather.columns))
    if missing:
        raise ValueError(f"天气数据缺少字段: {missing}")
    daily = weather.copy()
    daily["time"] = pd.to_datetime(daily["time"], errors="raise")
    daily["period_end"] = daily["time"].dt.to_period("Q").dt.end_time.dt.normalize()
    grouped = daily.groupby("period_end")
    result = grouped["precipitation_sum"].agg(
        precipitation_sum_mm="sum",
        precipitation_max_daily_mm="max",
        weather_days="count",
    )
    result["wet_days"] = grouped["precipitation_sum"].apply(lambda values: (values > 0.1).sum())
    if "temperature_2m_mean" in daily:
        result["temperature_2m_mean_c"] = grouped["temperature_2m_mean"].mean()
    return result.reset_index()


def join_operations_weather(metrics: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    """按季度连接经营指标与点位天气特征。"""

    operations = pivot_quarterly_metrics(metrics)
    quarterly_weather = aggregate_daily_weather(weather)
    return operations.merge(quarterly_weather, on="period_end", how="left", validate="one_to_one")


def assess_model_readiness(panel: pd.DataFrame, minimum_quarters: int = 12) -> dict[str, object]:
    """检查季度覆盖是否达到最小 nowcast 建模门槛。"""

    periods = pd.PeriodIndex(pd.to_datetime(panel["period_end"]), freq="Q")
    expected = pd.period_range(periods.min(), periods.max(), freq="Q") if len(periods) else periods
    complete_core = all(metric in panel and panel[metric].notna().all() for metric in CORE_METRICS)
    consecutive = len(periods) == len(expected) and set(periods) == set(expected)
    ready = len(periods) >= minimum_quarters and consecutive and complete_core
    reasons: list[str] = []
    if len(periods) < minimum_quarters:
        reasons.append(f"仅有 {len(periods)} 个季度，低于 {minimum_quarters} 个季度门槛")
    if not consecutive:
        reasons.append("季度序列不连续")
    if not complete_core:
        reasons.append("核心经营指标存在缺失")
    return {
        "ready": ready,
        "quarters": len(periods),
        "minimum_quarters": minimum_quarters,
        "consecutive": consecutive,
        "complete_core_metrics": complete_core,
        "reasons": reasons,
    }
