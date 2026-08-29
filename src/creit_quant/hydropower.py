"""508026 水电试点的数据整理与天气连接工具。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_METRICS_PATH = ROOT / "data" / "samples" / "508026_quarterly_operating_metrics.csv"
DEFAULT_ASSET_PATH = ROOT / "data" / "samples" / "508026_asset_metadata.csv"
DEFAULT_PRELISTING_METRICS_PATH = (
    ROOT / "data" / "samples" / "508026_prelisting_operating_metrics.csv"
)
DEFAULT_HYDROLOGY_MAPPING_PATH = (
    ROOT / "data" / "samples" / "508026_hydrology_mapping.csv"
)
DEFAULT_WEATHER_FEATURES_PATH = (
    ROOT / "data" / "samples" / "508026_quarterly_weather_reanalysis.csv"
)

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
PRELISTING_METRICS = {
    "power_generation",
    "utilization_hours",
    "hydrological_generation_potential",
    "curtailed_generation",
    "grid_connected_electricity",
    "average_inflow",
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


def load_prelisting_hydropower_metrics(
    path: str | Path = DEFAULT_PRELISTING_METRICS_PATH,
) -> pd.DataFrame:
    """读取招募说明书披露的上市前年度／年初至今经营数据。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    required = {
        "symbol",
        "asset_id",
        "period_start",
        "period_end",
        "period_type",
        "availability_class",
        "metric",
        "value",
        "unit",
        "publication_date",
        "source_url",
        "source_note",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"上市前水电指标文件缺少字段: {missing}")
    for column in ["period_start", "period_end", "publication_date"]:
        frame[column] = pd.to_datetime(frame[column], errors="raise")
    frame["value"] = pd.to_numeric(frame["value"], errors="raise")
    key = ["symbol", "asset_id", "period_start", "period_end", "metric"]
    if frame.duplicated(key).any():
        raise ValueError("上市前水电指标自然键存在重复")
    if not set(frame["metric"]).issubset(PRELISTING_METRICS):
        raise ValueError("上市前水电指标包含未注册指标")
    if not set(frame["period_type"]).issubset({"annual", "year_to_date"}):
        raise ValueError("上市前水电指标包含未知期间类型")
    if not frame["availability_class"].eq("pre_listing_disclosed_at_ipo").all():
        raise ValueError("上市前指标必须显式标记IPO披露可用性")
    if (frame["publication_date"] <= frame["period_end"]).any():
        raise ValueError("上市前指标发布时间必须晚于观察期末")

    annual = frame.loc[frame["period_type"].eq("annual")]
    wide = annual.pivot(index="period_end", columns="metric", values="value")
    identity_columns = {
        "power_generation",
        "curtailed_generation",
        "hydrological_generation_potential",
    }
    if identity_columns.issubset(wide.columns):
        error = (
            wide["power_generation"]
            + wide["curtailed_generation"]
            - wide["hydrological_generation_potential"]
        ).abs()
        if error.gt(0.011).any():
            raise ValueError("来水可发电量无法与发电量、弃水电量勾稽")
    return frame.sort_values(key).reset_index(drop=True)


def load_hydrology_mapping(
    path: str | Path = DEFAULT_HYDROLOGY_MAPPING_PATH,
) -> pd.DataFrame:
    """读取电站、集水区、河流和上游调节水库的关系表。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    required = {
        "symbol",
        "asset_id",
        "mapping_id",
        "mapping_type",
        "name",
        "relation",
        "coordinate_precision",
        "source_url",
        "source_note",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"水文映射文件缺少字段: {missing}")
    if frame["mapping_id"].duplicated().any():
        raise ValueError("水文映射标识不能重复")
    allowed = {"weather_proxy", "catchment", "upstream_reservoir", "river"}
    if not set(frame["mapping_type"]).issubset(allowed):
        raise ValueError("水文映射包含未知类型")
    located = frame[["latitude", "longitude"]].notna().any(axis=1)
    if frame.loc[located, ["latitude", "longitude"]].isna().any().any():
        raise ValueError("水文映射坐标必须成对填写")
    if not frame.loc[located, "latitude"].between(-90, 90).all():
        raise ValueError("水文映射纬度越界")
    if not frame.loc[located, "longitude"].between(-180, 180).all():
        raise ValueError("水文映射经度越界")
    return frame


def load_hydropower_weather_features(
    path: str | Path = DEFAULT_WEATHER_FEATURES_PATH,
) -> pd.DataFrame:
    """读取五一桥点位的季度再分析天气特征快照。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    required = {
        "symbol",
        "asset_id",
        "weather_point_id",
        "period_end",
        "data_kind",
        "latitude",
        "longitude",
        "precipitation_sum_mm",
        "rain_sum_mm",
        "snowfall_sum_cm",
        "temperature_2m_mean_c",
        "et0_fao_evapotranspiration_sum_mm",
        "weather_days",
        "source_url",
        "retrieved_at",
        "source_note",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"水电天气特征文件缺少字段: {missing}")
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="raise")
    frame["retrieved_at"] = pd.to_datetime(frame["retrieved_at"], errors="raise")
    if frame.duplicated(["weather_point_id", "period_end", "data_kind"]).any():
        raise ValueError("水电天气特征自然键存在重复")
    if not frame["data_kind"].eq("ex_post_reanalysis_era5").all():
        raise ValueError("再分析天气快照不得混入历史预报")
    periods = pd.PeriodIndex(frame["period_end"], freq="Q")
    expected = pd.period_range(periods.min(), periods.max(), freq="Q")
    if len(periods) != len(expected) or set(periods) != set(expected):
        raise ValueError("水电天气季度序列不连续")
    expected_days = frame["period_end"].dt.to_period("Q").map(
        lambda period: (period.end_time.normalize() - period.start_time.normalize()).days
        + 1
    )
    if not frame["weather_days"].eq(expected_days).all():
        raise ValueError("水电天气季度存在非完整日历覆盖")
    return frame.sort_values("period_end").reset_index(drop=True)


def build_prelisting_weather_panel(
    metrics: pd.DataFrame, weather: pd.DataFrame
) -> pd.DataFrame:
    """连接完整上市前年度经营指标和点位再分析天气。"""

    annual = metrics.loc[metrics["period_type"].eq("annual")]
    operations = annual.pivot(
        index=["symbol", "asset_id", "period_end"], columns="metric", values="value"
    ).reset_index()
    weather = weather.copy()
    weather["year"] = weather["period_end"].dt.year
    annual_weather = weather.groupby("year").agg(
        precipitation_sum_mm=("precipitation_sum_mm", "sum"),
        rain_sum_mm=("rain_sum_mm", "sum"),
        snowfall_sum_cm=("snowfall_sum_cm", "sum"),
        et0_fao_evapotranspiration_sum_mm=(
            "et0_fao_evapotranspiration_sum_mm",
            "sum",
        ),
        temperature_weighted_sum=(
            "temperature_2m_mean_c",
            lambda values: float(
                (values * weather.loc[values.index, "weather_days"]).sum()
            ),
        ),
        weather_days=("weather_days", "sum"),
    )
    annual_weather["temperature_2m_mean_c"] = (
        annual_weather.pop("temperature_weighted_sum") / annual_weather["weather_days"]
    )
    annual_weather["period_end"] = pd.to_datetime(
        annual_weather.index.astype(str) + "-12-31"
    )
    return operations.merge(
        annual_weather.reset_index(drop=True),
        on="period_end",
        how="left",
        validate="one_to_one",
    ).sort_values("period_end")


def audit_hydropower_extension(
    prelisting: pd.DataFrame,
    mapping: pd.DataFrame,
    weather: pd.DataFrame,
    documents: pd.DataFrame,
) -> dict[str, int]:
    """审计上市前经营数据、来源、水文关系和再分析天气之间的关联。"""

    asset_ids = set(mapping["asset_id"])
    if not set(prelisting["asset_id"]).issubset(asset_ids):
        raise ValueError("上市前水电指标存在未登记资产")
    if not set(weather["asset_id"]).issubset(asset_ids):
        raise ValueError("水电天气特征存在未登记资产")
    weather_mappings = set(
        mapping.loc[mapping["mapping_type"].eq("weather_proxy"), "mapping_id"]
    )
    if not set(weather["weather_point_id"]).issubset(weather_mappings):
        raise ValueError("水电天气点位未登记为天气代理")

    source_status = documents.set_index("source_url")["verification_status"]
    if not set(prelisting["source_url"]).issubset(source_status.index):
        raise ValueError("上市前水电指标存在未登记来源")
    if not source_status.loc[prelisting["source_url"].unique()].eq(
        "human_verified"
    ).all():
        raise ValueError("上市前水电指标来源尚未人工核验")

    panel = build_prelisting_weather_panel(prelisting, weather)
    weather_columns = [
        "precipitation_sum_mm",
        "rain_sum_mm",
        "snowfall_sum_cm",
        "temperature_2m_mean_c",
        "et0_fao_evapotranspiration_sum_mm",
    ]
    annual_core_metrics = {
        "power_generation",
        "utilization_hours",
        "hydrological_generation_potential",
        "curtailed_generation",
    }
    annual_metric_sets = (
        prelisting.loc[prelisting["period_type"].eq("annual")]
        .groupby("period_end")["metric"]
        .agg(set)
    )
    return {
        "prelisting_observations": len(prelisting),
        "complete_annual_years": int(
            annual_metric_sets.map(annual_core_metrics.issubset).sum()
        ),
        "year_to_date_observations": int(prelisting["period_type"].eq("year_to_date").sum()),
        "hydrology_mappings": len(mapping),
        "weather_quarters": len(weather),
        "annual_weather_join_rows": len(panel),
        "annual_weather_complete_rows": int(panel[weather_columns].notna().all(axis=1).sum()),
    }


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
    for source, target in [
        ("rain_sum", "rain_sum_mm"),
        ("snowfall_sum", "snowfall_sum_cm"),
        ("et0_fao_evapotranspiration", "et0_fao_evapotranspiration_sum_mm"),
    ]:
        if source in daily:
            result[target] = grouped[source].sum()
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
