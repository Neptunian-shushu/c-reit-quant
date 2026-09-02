"""508026 水电试点的数据整理与天气连接工具。"""

from __future__ import annotations

import hashlib
import json
import math
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
DEFAULT_WATERSHED_GEOJSON_PATH = (
    ROOT / "data" / "samples" / "508026_watershed_candidate.geojson"
)
DEFAULT_WATERSHED_METADATA_PATH = (
    ROOT / "data" / "samples" / "508026_watershed_proxy_metadata.csv"
)
DEFAULT_CATCHMENT_WEIGHTS_PATH = (
    ROOT / "data" / "samples" / "508026_catchment_grid_weights.csv"
)
DEFAULT_CATCHMENT_WEATHER_PATH = (
    ROOT / "data" / "samples" / "508026_quarterly_catchment_weather_reanalysis.csv"
)
DEFAULT_FIXED_LEAD_FORECAST_PATH = (
    ROOT / "data" / "samples" / "508026_quarterly_weather_forecast_lead24.csv"
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


def load_watershed_proxy(
    metadata_path: str | Path = DEFAULT_WATERSHED_METADATA_PATH,
    geojson_path: str | Path = DEFAULT_WATERSHED_GEOJSON_PATH,
) -> pd.DataFrame:
    """读取并校验MERIT自动划分的实验流域及其文件指纹。"""

    frame = pd.read_csv(metadata_path, dtype={"symbol": str})
    required = {
        "symbol",
        "asset_id",
        "watershed_id",
        "status",
        "modeled_area_km2",
        "official_area_km2",
        "relative_area_error_pct",
        "vertex_count",
        "content_sha256",
        "source_url",
        "license_note",
        "quality_note",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"实验流域元数据缺少字段: {missing}")
    if len(frame) != 1 or frame["watershed_id"].duplicated().any():
        raise ValueError("实验流域元数据必须恰好包含一个唯一流域")
    if not frame["status"].eq("experimental_area_mismatch").all():
        raise ValueError("自动划分流域不得冒充官方边界")
    expected_error = (frame["modeled_area_km2"] / frame["official_area_km2"] - 1) * 100
    if not (expected_error - frame["relative_area_error_pct"]).abs().lt(0.01).all():
        raise ValueError("实验流域面积差异计算错误")

    path = Path(geojson_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != frame.loc[0, "content_sha256"]:
        raise ValueError("实验流域GeoJSON指纹与元数据不一致")
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features", [])
    if len(features) != 1 or features[0].get("geometry", {}).get("type") != "Polygon":
        raise ValueError("实验流域GeoJSON必须包含一个Polygon")
    coordinates = features[0]["geometry"].get("coordinates", [[]])[0]
    if len(coordinates) != int(frame.loc[0, "vertex_count"]):
        raise ValueError("实验流域顶点数与元数据不一致")
    return frame


def load_catchment_grid_weights(
    path: str | Path = DEFAULT_CATCHMENT_WEIGHTS_PATH,
) -> pd.DataFrame:
    """读取实验流域映射到固定ERA5网格的面积近似权重。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    required = {
        "symbol",
        "asset_id",
        "weather_area_id",
        "grid_point_id",
        "latitude",
        "longitude",
        "area_weight",
        "weight_method",
        "model",
        "source_url",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"流域天气网格权重缺少字段: {missing}")
    if frame["grid_point_id"].duplicated().any():
        raise ValueError("流域天气网格标识不能重复")
    if not frame["model"].eq("era5").all():
        raise ValueError("流域长期天气网格必须固定ERA5模型")
    if (frame["area_weight"] <= 0).any() or abs(frame["area_weight"].sum() - 1) > 1e-9:
        raise ValueError("流域天气网格面积权重必须为正且合计为1")
    return frame.sort_values("grid_point_id").reset_index(drop=True)


def _point_in_polygon(
    longitude: float, latitude: float, polygon: list[list[float]]
) -> bool:
    """用射线法判断经纬度点是否落入简单多边形。"""

    inside = False
    previous = len(polygon) - 1
    for current, (x_current, y_current) in enumerate(polygon):
        x_previous, y_previous = polygon[previous]
        crosses = (y_current > latitude) != (y_previous > latitude)
        if crosses:
            boundary_x = (x_previous - x_current) * (
                latitude - y_current
            ) / (y_previous - y_current) + x_current
            if longitude < boundary_x:
                inside = not inside
        previous = current
    return inside


def derive_catchment_grid_weights(
    geojson_path: str | Path = DEFAULT_WATERSHED_GEOJSON_PATH,
    *,
    lattice_step_degrees: float = 0.01,
    weather_grid_degrees: float = 0.25,
) -> pd.DataFrame:
    """从候选流域以规则点阵近似重建ERA5网格面积权重。"""

    if lattice_step_degrees <= 0 or weather_grid_degrees <= 0:
        raise ValueError("格点步长必须为正")
    payload = json.loads(Path(geojson_path).read_text(encoding="utf-8"))
    polygon = payload["features"][0]["geometry"]["coordinates"][0]
    min_longitude = min(point[0] for point in polygon)
    max_longitude = max(point[0] for point in polygon)
    min_latitude = min(point[1] for point in polygon)
    max_latitude = max(point[1] for point in polygon)
    scale = round(1 / lattice_step_degrees)
    longitude_start = math.ceil(min_longitude * scale)
    longitude_stop = math.floor(max_longitude * scale)
    latitude_start = math.ceil(min_latitude * scale)
    latitude_stop = math.floor(max_latitude * scale)
    counts: dict[tuple[float, float], int] = {}
    for latitude_index in range(latitude_start, latitude_stop + 1):
        latitude = latitude_index / scale
        for longitude_index in range(longitude_start, longitude_stop + 1):
            longitude = longitude_index / scale
            if not _point_in_polygon(longitude, latitude, polygon):
                continue
            grid_latitude = round(latitude / weather_grid_degrees) * weather_grid_degrees
            grid_longitude = round(longitude / weather_grid_degrees) * weather_grid_degrees
            key = (grid_latitude, grid_longitude)
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        raise ValueError("候选流域内没有规则格点")
    total = sum(counts.values())
    rows = [
        {
            "latitude": latitude,
            "longitude": longitude,
            "area_weight": round(count / total, 4),
            "lattice_points": count,
        }
        for (latitude, longitude), count in counts.items()
    ]
    frame = pd.DataFrame(rows).sort_values(
        ["area_weight", "latitude", "longitude"], ascending=[False, True, True]
    )
    frame.insert(
        0,
        "grid_point_id",
        [f"era5_grid_{index:02d}" for index in range(1, len(frame) + 1)],
    )
    return frame.reset_index(drop=True)


def load_catchment_weather_features(
    path: str | Path = DEFAULT_CATCHMENT_WEATHER_PATH,
) -> pd.DataFrame:
    """读取MERIT候选流域的面积加权季度ERA5再分析特征。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    required = {
        "symbol",
        "asset_id",
        "weather_area_id",
        "period_end",
        "data_kind",
        "precipitation_sum_mm",
        "temperature_2m_mean_c",
        "weather_days",
        "grid_points",
        "area_weight_coverage",
        "modeled_basin_area_km2",
        "official_basin_area_km2",
        "source_url",
        "source_note",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"流域再分析天气缺少字段: {missing}")
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="raise")
    if frame.duplicated(["weather_area_id", "period_end", "data_kind"]).any():
        raise ValueError("流域再分析天气自然键存在重复")
    if not frame["data_kind"].eq(
        "ex_post_reanalysis_era5_area_weighted_candidate"
    ).all():
        raise ValueError("流域再分析快照数据类型错误")
    if not frame["area_weight_coverage"].eq(1.0).all():
        raise ValueError("流域天气网格权重覆盖不完整")
    _validate_complete_quarters(frame, "流域再分析天气")
    return frame.sort_values("period_end").reset_index(drop=True)


def aggregate_catchment_daily_weather(
    daily_weather: pd.DataFrame, weights: pd.DataFrame
) -> pd.DataFrame:
    """用固定网格权重把多点日频ERA5聚合为自然季度流域特征。"""

    weather_columns = {
        "precipitation_sum": "precipitation_sum_mm",
        "rain_sum": "rain_sum_mm",
        "snowfall_sum": "snowfall_sum_cm",
        "temperature_2m_mean": "temperature_2m_mean_c",
        "et0_fao_evapotranspiration": "et0_fao_evapotranspiration_sum_mm",
    }
    required = {"grid_point_id", "time", *weather_columns}
    missing = sorted(required.difference(daily_weather.columns))
    if missing:
        raise ValueError(f"流域日频天气缺少字段: {missing}")
    if daily_weather[list(required)].isna().any().any():
        raise ValueError("流域日频天气关键字段不得缺失")
    daily = daily_weather.copy()
    daily["time"] = pd.to_datetime(daily["time"], errors="raise")
    if daily.duplicated(["grid_point_id", "time"]).any():
        raise ValueError("流域日频天气网格和日期存在重复")
    if set(daily["grid_point_id"]) != set(weights["grid_point_id"]):
        raise ValueError("流域日频天气网格与权重表不一致")
    if (
        weights["grid_point_id"].duplicated().any()
        or (weights["area_weight"] <= 0).any()
        or not math.isclose(float(weights["area_weight"].sum()), 1.0, abs_tol=1e-9)
    ):
        raise ValueError("流域日频聚合权重必须唯一、为正且合计为1")
    calendars = daily.groupby("grid_point_id")["time"].agg(frozenset)
    if calendars.nunique() != 1:
        raise ValueError("流域日频天气各网格日历覆盖不一致")
    daily = daily.merge(
        weights[["grid_point_id", "area_weight"]],
        on="grid_point_id",
        validate="many_to_one",
    )
    daily["period_end"] = daily["time"].dt.to_period("Q").dt.end_time.dt.normalize()
    for source, target in weather_columns.items():
        daily[target] = daily[source] * daily["area_weight"]
    result = daily.groupby("period_end").agg(
        precipitation_sum_mm=("precipitation_sum_mm", "sum"),
        rain_sum_mm=("rain_sum_mm", "sum"),
        snowfall_sum_cm=("snowfall_sum_cm", "sum"),
        temperature_weighted_sum=("temperature_2m_mean_c", "sum"),
        et0_fao_evapotranspiration_sum_mm=(
            "et0_fao_evapotranspiration_sum_mm",
            "sum",
        ),
        weather_days=("time", "nunique"),
    ).reset_index()
    result["temperature_2m_mean_c"] = result.pop(
        "temperature_weighted_sum"
    ) / result["weather_days"]
    _validate_complete_quarters(result, "聚合后的流域天气")
    return result


def load_fixed_lead_weather_forecast(
    path: str | Path = DEFAULT_FIXED_LEAD_FORECAST_PATH,
) -> pd.DataFrame:
    """读取GFS固定提前24小时的季度点位降水预报快照。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    required = {
        "symbol",
        "asset_id",
        "weather_point_id",
        "period_end",
        "precipitation_forecast_sum_mm",
        "forecast_hours",
        "data_kind",
        "model",
        "lead_offset_hours",
        "source_url",
        "source_note",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"固定提前期天气预报缺少字段: {missing}")
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="raise")
    if frame.duplicated(["weather_point_id", "period_end", "data_kind"]).any():
        raise ValueError("固定提前期天气预报自然键存在重复")
    if not frame["data_kind"].eq("historical_forecast_fixed_lead").all():
        raise ValueError("固定提前期天气预报数据类型错误")
    if not frame["model"].eq("gfs_global").all() or not frame[
        "lead_offset_hours"
    ].eq(24).all():
        raise ValueError("历史预报必须固定GFS global和24小时时距")
    expected_hours = frame["period_end"].dt.to_period("Q").map(
        lambda period: (
            period.end_time.normalize() - period.start_time.normalize()
        ).days
        * 24
        + 24
    )
    if not frame["forecast_hours"].eq(expected_hours).all():
        raise ValueError("固定提前期天气预报季度小时覆盖不完整")
    _validate_complete_quarters(frame, "固定提前期天气预报", check_days=False)
    return frame.sort_values("period_end").reset_index(drop=True)


def audit_watershed_weather_proxy(
    watershed: pd.DataFrame,
    weights: pd.DataFrame,
    weather: pd.DataFrame,
) -> dict[str, object]:
    """审计候选流域、ERA5网格权重和季度聚合之间的关系。"""

    watershed_ids = set(watershed["watershed_id"])
    if set(weights["weather_area_id"]) != watershed_ids:
        raise ValueError("流域网格权重未连接到唯一候选流域")
    if set(weather["weather_area_id"]) != watershed_ids:
        raise ValueError("流域天气未连接到唯一候选流域")
    if not weather["grid_points"].eq(len(weights)).all():
        raise ValueError("流域天气记录的网格数与权重表不一致")
    metadata = watershed.iloc[0]
    if not weather["modeled_basin_area_km2"].eq(
        metadata["modeled_area_km2"]
    ).all():
        raise ValueError("流域天气自动面积与元数据不一致")
    if not weather["official_basin_area_km2"].eq(
        metadata["official_area_km2"]
    ).all():
        raise ValueError("流域天气官方面积与元数据不一致")
    derived = derive_catchment_grid_weights()
    comparison = weights.merge(
        derived,
        on=["grid_point_id", "latitude", "longitude"],
        suffixes=("_stored", "_derived"),
        how="outer",
        indicator=True,
    )
    if not comparison["_merge"].eq("both").all() or not (
        comparison["area_weight_stored"] - comparison["area_weight_derived"]
    ).abs().lt(1e-9).all():
        raise ValueError("流域天气网格权重无法从候选边界复现")
    return {
        "watersheds": len(watershed),
        "grid_points": len(weights),
        "weather_quarters": len(weather),
        "area_weight_coverage": float(weights["area_weight"].sum()),
        "status": metadata["status"],
    }


def aggregate_hourly_fixed_lead_forecast(
    weather: pd.DataFrame,
    *,
    value_column: str = "precipitation_previous_day1",
) -> pd.DataFrame:
    """把固定提前期小时预报聚合为完整自然季度。"""

    if not {"time", value_column}.issubset(weather.columns):
        raise ValueError("固定提前期小时预报缺少时间或目标字段")
    hourly = weather[["time", value_column]].copy()
    hourly["time"] = pd.to_datetime(hourly["time"], errors="raise")
    if hourly[value_column].isna().any() or hourly["time"].duplicated().any():
        raise ValueError("固定提前期小时预报存在缺失或重复时间")
    hourly["period_end"] = hourly["time"].dt.to_period("Q").dt.end_time.dt.normalize()
    result = hourly.groupby("period_end")[value_column].agg(
        precipitation_forecast_sum_mm="sum", forecast_hours="count"
    ).reset_index()
    expected_hours = result["period_end"].dt.to_period("Q").map(
        lambda period: (
            period.end_time.normalize() - period.start_time.normalize()
        ).days
        * 24
        + 24
    )
    if not result["forecast_hours"].eq(expected_hours).all():
        raise ValueError("固定提前期小时预报不能形成完整自然季度")
    return result


def build_fixed_lead_forecast_snapshot(
    weather: pd.DataFrame,
    *,
    symbol: str,
    asset_id: str,
    weather_point_id: str,
    model: str,
    lead_days: int,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """把Open-Meteo小时预报整理为带时点语义的标准季度快照。"""

    value_column = f"precipitation_previous_day{lead_days}"
    result = aggregate_hourly_fixed_lead_forecast(
        weather, value_column=value_column
    )
    if not {"latitude", "longitude"}.issubset(weather.columns):
        raise ValueError("固定提前期小时预报缺少返回网格坐标")
    result.insert(0, "weather_point_id", weather_point_id)
    result.insert(0, "asset_id", asset_id)
    result.insert(0, "symbol", symbol)
    result["data_kind"] = "historical_forecast_fixed_lead"
    result["model"] = model
    result["lead_offset_hours"] = lead_days * 24
    result["latitude"] = float(weather["latitude"].iloc[0])
    result["longitude"] = float(weather["longitude"].iloc[0])
    result["source_url"] = (
        "https://previous-runs-api.open-meteo.com/v1/forecast?models=" + model
    )
    result["retrieved_at"] = pd.Timestamp(retrieved_at).date().isoformat()
    result["source_note"] = (
        f"每个有效小时取_previous_day{lead_days}固定提前{lead_days * 24}小时预报；"
        "模型运行仍有计算发布延迟；季度总量仅在季度结束后完整可知；"
        "点位代理非流域面雨量"
    )
    return result


def _validate_complete_quarters(
    frame: pd.DataFrame, name: str, *, check_days: bool = True
) -> None:
    """校验季度序列连续，并可选校验完整日历天数。"""

    periods = pd.PeriodIndex(frame["period_end"], freq="Q")
    expected = pd.period_range(periods.min(), periods.max(), freq="Q")
    if len(periods) != len(expected) or set(periods) != set(expected):
        raise ValueError(f"{name}季度序列不连续")
    if check_days:
        expected_days = frame["period_end"].dt.to_period("Q").map(
            lambda period: (
                period.end_time.normalize() - period.start_time.normalize()
            ).days
            + 1
        )
        if not frame["weather_days"].eq(expected_days).all():
            raise ValueError(f"{name}存在非完整日历覆盖")


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
