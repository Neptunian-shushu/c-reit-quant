"""研究数据库的轻量读取、关系校验和覆盖审计。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from creit_quant.hydropower import (
    DEFAULT_ASSET_PATH,
    DEFAULT_METRICS_PATH,
    DEFAULT_WATERSHED_GEOJSON_PATH,
    build_prelisting_weather_panel,
    load_catchment_grid_weights,
    load_catchment_weather_features,
    load_fixed_lead_weather_forecast,
    load_hydrology_mapping,
    load_hydropower_asset,
    load_hydropower_metrics,
    load_hydropower_weather_features,
    load_prelisting_hydropower_metrics,
    load_watershed_proxy,
)
from creit_quant.hydropower_model import (
    build_annual_model_panel,
    expanding_annual_backtest,
    summarize_annual_backtest,
)
from creit_quant.documents import PERIODIC_DOCUMENT_TYPES
from creit_quant.strategy import DEFAULT_DISTRIBUTIONS_PATH, load_distributions

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MASTER_PATH = ROOT / "data" / "samples" / "reit_master.csv"
DEFAULT_DOCUMENTS_PATH = ROOT / "data" / "samples" / "508026_source_documents.csv"
DEFAULT_DEFINITIONS_PATH = ROOT / "data" / "reference" / "metric_definitions.csv"
DEFAULT_REQUIREMENTS_PATH = ROOT / "data" / "reference" / "asset_type_metric_requirements.csv"
DEFAULT_CROSS_ASSETS_PATH = ROOT / "data" / "samples" / "cross_asset_asset_master.csv"
DEFAULT_CROSS_METRICS_PATH = ROOT / "data" / "samples" / "cross_asset_operating_metrics.csv"
DEFAULT_CROSS_DOCUMENTS_PATH = ROOT / "data" / "samples" / "cross_asset_source_documents.csv"
DEFAULT_ENERGY_ASSETS_PATH = ROOT / "data" / "samples" / "energy_asset_master.csv"
DEFAULT_ENERGY_METRICS_PATH = ROOT / "data" / "samples" / "energy_operating_metrics.csv"
DEFAULT_ENERGY_DOCUMENTS_PATH = ROOT / "data" / "samples" / "energy_source_documents.csv"
DEFAULT_WIND_METRICS_PATH = ROOT / "data" / "samples" / "508028_quarterly_operating_metrics.csv"
DEFAULT_SOLAR_HYDRO_METRICS_PATH = (
    ROOT / "data" / "samples" / "508096_quarterly_operating_metrics.csv"
)
DEFAULT_GAS_METRICS_PATH = ROOT / "data" / "samples" / "180401_quarterly_operating_metrics.csv"
DEFAULT_ENERGY_EVENTS_PATH = ROOT / "data" / "samples" / "energy_asset_events.csv"
DEFAULT_PANEL_REVIEWS_PATH = ROOT / "data" / "samples" / "panel_quality_reviews.csv"
DEFAULT_ANNUAL_RECONCILIATIONS_PATH = (
    ROOT / "data" / "samples" / "panel_annual_reconciliations.csv"
)

OBSERVATION_KEY = ["symbol", "asset_id", "period_end", "metric"]


def _read_table(path: str | Path, required: set[str], *, name: str) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"symbol": str})
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{name} 缺少字段: {missing}")
    return frame


def load_reit_master(path: str | Path = DEFAULT_MASTER_PATH) -> pd.DataFrame:
    """读取证券主表并校验证券代码和唯一性。"""

    frame = _read_table(
        path,
        {"symbol", "name", "exchange", "listing_date", "asset_type", "status", "source_url"},
        name="证券主表",
    )
    if not frame["symbol"].str.fullmatch(r"\d{6}").all() or frame["symbol"].duplicated().any():
        raise ValueError("证券主表代码必须为唯一六位数字")
    frame["listing_date"] = pd.to_datetime(frame["listing_date"], errors="raise")
    return frame


def load_source_documents(path: str | Path = DEFAULT_DOCUMENTS_PATH) -> pd.DataFrame:
    """读取公告登记表；URL 是经营观测与原始证据之间的外键。"""

    frame = _read_table(
        path,
        {
            "document_id",
            "symbol",
            "document_type",
            "period_end",
            "publication_date",
            "source_url",
            "verification_status",
        },
        name="公告登记表",
    )
    if frame["document_id"].duplicated().any() or frame["source_url"].duplicated().any():
        raise ValueError("公告 document_id 和 source_url 必须唯一")
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="raise")
    frame["publication_date"] = pd.to_datetime(frame["publication_date"], errors="raise")
    if (frame["publication_date"] < frame["period_end"]).any():
        raise ValueError("公告发布日期不能早于对应报告期末")
    if "retrieved_at" in frame:
        frame["retrieved_at"] = pd.to_datetime(frame["retrieved_at"], errors="raise")
    if "content_sha256" in frame:
        hashes = frame["content_sha256"].dropna().astype(str)
        hashes = hashes.loc[hashes.ne("")]
        if not hashes.str.fullmatch(r"[0-9a-f]{64}").all():
            raise ValueError("content_sha256 必须是 64 位小写十六进制")
    if "supersedes_document_id" in frame:
        parents = frame["supersedes_document_id"].dropna().astype(str)
        parents = parents.loc[parents.ne("")]
        if not set(parents).issubset(set(frame["document_id"])):
            raise ValueError("公告更正关系指向未登记 document_id")
        lookup = frame.set_index("document_id")
        linked = frame.loc[frame["supersedes_document_id"].notna()]
        for row in linked.itertuples(index=False):
            parent_id = str(row.supersedes_document_id)
            if not parent_id:
                continue
            parent = lookup.loc[parent_id]
            if row.document_id == parent_id or row.symbol != parent["symbol"]:
                raise ValueError("公告不能替代自身或其他证券的公告")
            if row.publication_date <= parent["publication_date"]:
                raise ValueError("更正公告发布日期必须晚于被替代公告")
    return frame


def load_metric_definitions(path: str | Path = DEFAULT_DEFINITIONS_PATH) -> pd.DataFrame:
    """读取规范指标字典。"""

    frame = _read_table(
        path,
        {"metric", "metric_cn", "asset_scope", "canonical_unit", "expected_frequency"},
        name="指标字典",
    )
    if frame["metric"].duplicated().any():
        raise ValueError("指标字典 metric 必须唯一")
    return frame


def load_asset_metric_requirements(
    path: str | Path = DEFAULT_REQUIREMENTS_PATH,
) -> pd.DataFrame:
    """读取各类底层资产的核心与可选指标要求。"""

    frame = _read_table(
        path,
        {"asset_type", "metric", "requirement_level", "expected_frequency"},
        name="资产类型指标要求表",
    )
    if frame.duplicated(["asset_type", "metric"]).any():
        raise ValueError("资产类型指标要求不能重复")
    allowed_levels = {"core", "optional"}
    if not set(frame["requirement_level"]).issubset(allowed_levels):
        raise ValueError("requirement_level 只能是 core 或 optional")
    return frame


def load_assets(path: str | Path) -> pd.DataFrame:
    """读取通用底层资产表并校验证券内资产标识唯一。"""

    frame = _read_table(
        path,
        {"symbol", "asset_id", "asset_name", "asset_type", "source_url"},
        name="底层资产表",
    )
    if frame.duplicated(["symbol", "asset_id"]).any():
        raise ValueError("底层资产表 symbol/asset_id 必须唯一")
    if "asset_effective_from" in frame:
        frame["asset_effective_from"] = pd.to_datetime(
            frame["asset_effective_from"], errors="raise"
        )
    if "installed_capacity_mw" in frame:
        frame["installed_capacity_mw"] = pd.to_numeric(
            frame["installed_capacity_mw"], errors="coerce"
        )
        if frame["installed_capacity_mw"].dropna().le(0).any():
            raise ValueError("已披露装机容量必须大于 0")
    return frame


def load_operating_metrics(path: str | Path) -> pd.DataFrame:
    """读取不限定资产类型的规范 long-format 经营观测。"""

    frame = _read_table(
        path,
        {
            "symbol",
            "asset_id",
            "period_end",
            "metric",
            "value",
            "unit",
            "publication_date",
            "source_url",
        },
        name="经营观测表",
    )
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="raise")
    frame["publication_date"] = pd.to_datetime(frame["publication_date"], errors="raise")
    frame["value"] = pd.to_numeric(frame["value"], errors="raise")
    if frame.duplicated(OBSERVATION_KEY + ["publication_date"]).any():
        raise ValueError("同一经营指标版本重复")
    if frame[["symbol", "asset_id", "metric", "unit", "source_url"]].isna().any().any():
        raise ValueError("经营观测关键字段不能为空")
    return frame.sort_values(OBSERVATION_KEY + ["publication_date"]).reset_index(drop=True)


def load_asset_events(path: str | Path = DEFAULT_ENERGY_EVENTS_PATH) -> pd.DataFrame:
    """读取扩募、停机和电价机制等会改变可比性的资产事件。"""

    frame = _read_table(
        path,
        {
            "event_id",
            "symbol",
            "event_type",
            "event_start",
            "date_precision",
            "publication_date",
            "source_url",
            "verification_status",
        },
        name="资产事件表",
    )
    if frame["event_id"].duplicated().any():
        raise ValueError("资产事件 event_id 必须唯一")
    frame["event_start"] = pd.to_datetime(frame["event_start"], errors="raise")
    frame["event_end"] = pd.to_datetime(frame.get("event_end"), errors="coerce")
    frame["publication_date"] = pd.to_datetime(frame["publication_date"], errors="raise")
    if (frame["event_end"].notna() & frame["event_end"].lt(frame["event_start"])).any():
        raise ValueError("资产事件结束日期不能早于开始日期")
    if not set(frame["date_precision"]).issubset({"day", "month", "quarter"}):
        raise ValueError("资产事件日期精度只能是 day、month 或 quarter")
    if (frame["publication_date"] < frame["event_start"]).any():
        raise ValueError("资产事件发布日期不能早于事件开始日期")
    return frame.sort_values(["event_start", "event_id"]).reset_index(drop=True)


def load_panel_reviews(path: str | Path = DEFAULT_PANEL_REVIEWS_PATH) -> pd.DataFrame:
    """读取季度面板的人工复核台账。"""

    frame = _read_table(
        path,
        {
            "symbol",
            "period_end",
            "panel_name",
            "source_url",
            "review_status",
            "reviewed_at",
        },
        name="面板复核台账",
    )
    if frame.duplicated(["panel_name", "source_url"]).any():
        raise ValueError("同一面板的来源文档复核记录不能重复")
    allowed = {"single_pass", "double_checked"}
    if not set(frame["review_status"]).issubset(allowed):
        raise ValueError("review_status 只能是 single_pass 或 double_checked")
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="raise")
    frame["reviewed_at"] = pd.to_datetime(frame["reviewed_at"], errors="raise")
    return frame.sort_values(["symbol", "period_end", "panel_name"]).reset_index(drop=True)


def audit_panel_reviews(
    metrics: pd.DataFrame, reviews: pd.DataFrame, *, panel_name: str
) -> dict[str, int]:
    """确认面板使用的每份来源均有复核记录，且证券和报告期一致。"""

    used = metrics[["symbol", "period_end", "source_url"]].drop_duplicates()
    ledger = reviews.loc[reviews["panel_name"].eq(panel_name)]
    joined = used.merge(
        ledger,
        on=["symbol", "period_end", "source_url"],
        how="left",
        validate="one_to_one",
    )
    if joined["review_status"].isna().any():
        raise ValueError(f"{panel_name} 存在未登记人工复核的来源文档")
    return {
        "reviewed_documents": len(joined),
        "single_pass_documents": int(joined["review_status"].eq("single_pass").sum()),
        "double_checked_documents": int(joined["review_status"].eq("double_checked").sum()),
    }


def load_annual_reconciliations(
    path: str | Path = DEFAULT_ANNUAL_RECONCILIATIONS_PATH,
) -> pd.DataFrame:
    """读取季度面板与正式年报之间的年度勾稽记录。"""

    frame = _read_table(
        path,
        {
            "symbol",
            "asset_id",
            "fiscal_year",
            "metric",
            "aggregation_method",
            "quarterly_value",
            "annual_value",
            "unit",
            "absolute_difference",
            "relative_difference_pct",
            "status",
            "annual_publication_date",
            "annual_source_url",
            "reviewed_at",
        },
        name="年度勾稽表",
    )
    key = ["symbol", "asset_id", "fiscal_year", "metric"]
    if frame.duplicated(key).any():
        raise ValueError("年度勾稽记录自然键不能重复")
    methods = {
        "sum",
        "settled_electricity_weighted_average",
        "fuel_consumption_weighted_average",
    }
    statuses = {"exact", "within_rounding", "annual_true_up", "basis_difference"}
    if not set(frame["aggregation_method"]).issubset(methods):
        raise ValueError("年度勾稽表包含未知聚合方法")
    if not set(frame["status"]).issubset(statuses):
        raise ValueError("年度勾稽表包含未知状态")
    numeric = [
        "fiscal_year",
        "quarterly_value",
        "annual_value",
        "absolute_difference",
        "relative_difference_pct",
    ]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    if frame[["absolute_difference", "relative_difference_pct"]].lt(0).any().any():
        raise ValueError("年度勾稽差异必须使用非负绝对值")
    calculated_difference = (frame["annual_value"] - frame["quarterly_value"]).abs()
    if (calculated_difference - frame["absolute_difference"]).abs().gt(1e-6).any():
        raise ValueError("年度勾稽绝对差异与季度值、年报值不一致")
    nonzero_annual = frame["annual_value"].ne(0)
    calculated_relative = (
        calculated_difference.loc[nonzero_annual]
        / frame.loc[nonzero_annual, "annual_value"].abs()
        * 100
    )
    if (
        calculated_relative - frame.loc[nonzero_annual, "relative_difference_pct"]
    ).abs().gt(1e-7).any():
        raise ValueError("年度勾稽相对差异与季度值、年报值不一致")
    if frame.loc[~nonzero_annual, "relative_difference_pct"].ne(0).any():
        raise ValueError("年报值为零时年度勾稽相对差异必须为零")
    exact = frame["status"].eq("exact")
    if frame.loc[exact, "absolute_difference"].gt(1e-8).any():
        raise ValueError("标记 exact 的年度勾稽记录存在非零差异")
    frame["annual_publication_date"] = pd.to_datetime(
        frame["annual_publication_date"], errors="raise"
    )
    frame["reviewed_at"] = pd.to_datetime(frame["reviewed_at"], errors="raise")
    return frame.sort_values(key).reset_index(drop=True)


def audit_annual_reconciliations(
    reconciliations: pd.DataFrame,
    metrics: pd.DataFrame,
    documents: pd.DataFrame,
) -> dict[str, int]:
    """重算季度聚合并检查年报来源、单位和勾稽状态。"""

    document_lookup = documents.set_index("source_url")
    if not set(reconciliations["annual_source_url"]).issubset(document_lookup.index):
        raise ValueError("年度勾稽表存在未登记的年报来源")
    linked = reconciliations.join(
        document_lookup[
            [
                "symbol",
                "period_end",
                "publication_date",
                "document_type",
                "verification_status",
            ]
        ],
        on="annual_source_url",
        rsuffix="_document",
        validate="many_to_one",
    )
    mismatch = (
        linked["symbol"] != linked["symbol_document"]
    ) | (
        linked["annual_publication_date"] != linked["publication_date"]
    ) | (~linked["document_type"].eq("annual_report")) | (
        linked["period_end"].dt.year != linked["fiscal_year"]
    ) | (
        ~linked["verification_status"].eq("human_verified")
    )
    if mismatch.any():
        raise ValueError("年度勾稽记录与人工核验年报的证券、年度或发布日期不一致")

    rows: list[dict[str, object]] = []
    for row in reconciliations.itertuples(index=False):
        group = metrics.loc[
            metrics["symbol"].eq(row.symbol)
            & metrics["asset_id"].eq(row.asset_id)
            & metrics["period_end"].dt.year.eq(row.fiscal_year)
            & metrics["publication_date"].le(row.annual_publication_date)
        ].copy()
        group = group.sort_values("publication_date").drop_duplicates(
            OBSERVATION_KEY, keep="last"
        )
        if row.aggregation_method == "sum":
            values = group.loc[group["metric"].eq(row.metric), "value"]
            calculated = float(values.sum())
        else:
            weight_metric = (
                "settled_electricity"
                if row.aggregation_method == "settled_electricity_weighted_average"
                else "fuel_consumption"
            )
            wide = group.pivot(index="period_end", columns="metric", values="value")
            if row.metric not in wide or weight_metric not in wide:
                raise ValueError("年度勾稽缺少加权平均所需季度指标")
            valid = wide.dropna(subset=[row.metric, weight_metric])
            calculated = float(
                (valid[row.metric] * valid[weight_metric]).sum()
                / valid[weight_metric].sum()
            )
        tolerance = 1e-6
        if abs(calculated - float(row.quarterly_value)) > tolerance:
            raise ValueError(
                "年度勾稽表的季度聚合值无法由经营面板重算: "
                f"{row.symbol}/{row.asset_id}/{row.metric} "
                f"calculated={calculated}, recorded={row.quarterly_value}"
            )
        rows.append({"status": row.status})
    status = pd.DataFrame(rows)["status"]
    return {
        "reconciliations": len(reconciliations),
        "exact": int(status.eq("exact").sum()),
        "within_rounding": int(status.eq("within_rounding").sum()),
        "annual_true_up": int(status.eq("annual_true_up").sum()),
        "basis_difference": int(status.eq("basis_difference").sum()),
    }


def audit_asset_events(
    events: pd.DataFrame, assets: pd.DataFrame, documents: pd.DataFrame
) -> dict[str, int]:
    """检查事件的证券、可选资产键和正式来源关系。"""

    if not set(events["symbol"]).issubset(set(documents["symbol"])):
        raise ValueError("资产事件存在来源登记表中没有的证券")
    if not set(events["source_url"]).issubset(set(documents["source_url"])):
        raise ValueError("资产事件存在未登记的来源 URL")
    with_asset = events.loc[events["asset_id"].notna() & events["asset_id"].ne("")]
    asset_keys = set(zip(assets["symbol"], assets["asset_id"], strict=False))
    event_asset_keys = set(zip(with_asset["symbol"], with_asset["asset_id"], strict=False))
    if not event_asset_keys.issubset(asset_keys):
        raise ValueError("资产事件存在未登记的 symbol/asset_id")
    return {
        "events": len(events),
        "asset_level_events": len(with_asset),
        "symbol_level_events": len(events) - len(with_asset),
    }


def audit_periodic_document_sequences(
    documents: pd.DataFrame, symbols: list[str] | None = None
) -> pd.DataFrame:
    """按证券检查已登记定期报告是否形成连续季度覆盖。"""

    periodic = documents.loc[
        documents["document_type"].isin(PERIODIC_DOCUMENT_TYPES)
    ].copy()
    if symbols is not None:
        periodic = periodic.loc[periodic["symbol"].isin(symbols)]
    rows: list[dict[str, object]] = []
    for symbol, group in periodic.groupby("symbol"):
        periods = pd.PeriodIndex(group["period_end"], freq="Q").unique().sort_values()
        expected = pd.period_range(periods.min(), periods.max(), freq="Q")
        rows.append(
            {
                "symbol": symbol,
                "quarter_start": str(periods.min()),
                "quarter_end": str(periods.max()),
                "covered_quarters": len(periods),
                "expected_quarters": len(expected),
                "consecutive": len(periods) == len(expected) and set(periods) == set(expected),
                "registered_documents": len(group),
                "hashed_documents": int(group["content_sha256"].notna().sum()),
                "human_verified_documents": int(
                    group["verification_status"].eq("human_verified").sum()
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("symbol").reset_index(drop=True)


def build_metric_coverage(
    metrics: pd.DataFrame, expected_metrics: set[str]
) -> pd.DataFrame:
    """生成“资产×季度×预期指标”的显式覆盖矩阵。"""

    keys = metrics[["symbol", "asset_id", "period_end"]].drop_duplicates()
    expected = pd.DataFrame({"metric": sorted(expected_metrics)})
    coverage = keys.merge(expected, how="cross")
    observed = metrics[["symbol", "asset_id", "period_end", "metric"]].drop_duplicates()
    coverage = coverage.merge(
        observed,
        on=["symbol", "asset_id", "period_end", "metric"],
        how="left",
        indicator=True,
        validate="one_to_one",
    )
    coverage["status"] = coverage.pop("_merge").map(
        {"both": "available", "left_only": "missing", "right_only": "unexpected"}
    ).astype("string")
    return coverage.sort_values(
        ["symbol", "asset_id", "period_end", "metric"]
    ).reset_index(drop=True)


def build_asset_type_coverage(
    assets: pd.DataFrame,
    metrics: pd.DataFrame,
    requirements: pd.DataFrame,
    *,
    requirement_level: str = "core",
) -> pd.DataFrame:
    """按资产类型要求生成可跨 REIT 比较的季度指标覆盖矩阵。"""

    asset_periods = metrics[["symbol", "asset_id", "period_end"]].drop_duplicates()
    asset_types = assets[["symbol", "asset_id", "asset_type"]].drop_duplicates()
    expected = asset_periods.merge(
        asset_types,
        on=["symbol", "asset_id"],
        how="left",
        validate="many_to_one",
    ).merge(
        requirements.loc[
            requirements["requirement_level"].eq(requirement_level),
            ["asset_type", "metric", "requirement_level"],
        ],
        on="asset_type",
        how="left",
        validate="many_to_many",
    )
    if expected["asset_type"].isna().any() or expected["metric"].isna().any():
        raise ValueError("存在未登记资产类型或没有指标要求的资产")
    observed = metrics[OBSERVATION_KEY].drop_duplicates()
    coverage = expected.merge(
        observed,
        on=OBSERVATION_KEY,
        how="left",
        indicator=True,
        validate="one_to_one",
    )
    coverage["status"] = coverage.pop("_merge").map(
        {"both": "available", "left_only": "missing", "right_only": "unexpected"}
    ).astype("string")
    return coverage.sort_values(OBSERVATION_KEY).reset_index(drop=True)


def build_observation_versions(
    metrics: pd.DataFrame, documents: pd.DataFrame
) -> pd.DataFrame:
    """把来源可追溯的观测转换成带生效区间的 point-in-time 版本表。

    同一自然键若被后续公告修订，旧版本的 ``valid_to`` 会落在新公告
    发布日，新版本通过 ``supersedes_observation_id`` 指向旧版本。
    """

    required = set(OBSERVATION_KEY) | {
        "value",
        "unit",
        "publication_date",
        "source_url",
    }
    missing = sorted(required.difference(metrics.columns))
    if missing:
        raise ValueError(f"经营观测缺少版本化字段: {missing}")
    document_lookup = documents[
        ["document_id", "source_url", "verification_status"]
    ].drop_duplicates()
    versions = metrics.merge(
        document_lookup,
        on="source_url",
        how="left",
        validate="many_to_one",
    )
    if versions["document_id"].isna().any():
        raise ValueError("经营观测存在无法连接的 document_id")
    versions = versions.sort_values(OBSERVATION_KEY + ["publication_date", "document_id"])
    if versions.duplicated(OBSERVATION_KEY + ["publication_date"]).any():
        raise ValueError("同一指标版本不能共享相同发布日期")

    period_labels = pd.to_datetime(versions["period_end"]).dt.strftime("%Y%m%d")
    versions["observation_id"] = (
        versions["symbol"].astype(str)
        + ":"
        + versions["asset_id"].astype(str)
        + ":"
        + period_labels
        + ":"
        + versions["metric"].astype(str)
        + ":"
        + versions["document_id"].astype(str)
    )
    if versions["observation_id"].duplicated().any():
        raise ValueError("生成的 observation_id 不唯一")
    grouped = versions.groupby(OBSERVATION_KEY, sort=False)
    versions["valid_from"] = pd.to_datetime(versions["publication_date"], errors="raise")
    versions["valid_to"] = grouped["valid_from"].shift(-1)
    versions["supersedes_observation_id"] = grouped["observation_id"].shift(1)
    if "raw_value" not in versions:
        versions["raw_value"] = versions["value"]
    if "raw_unit" not in versions:
        versions["raw_unit"] = versions["unit"]
    versions["quality_status"] = versions["verification_status"].map(
        {"human_verified": "verified"}
    ).fillna("unverified")
    return versions[
        [
            "observation_id",
            *OBSERVATION_KEY,
            "value",
            "unit",
            "raw_value",
            "raw_unit",
            "document_id",
            "valid_from",
            "valid_to",
            "supersedes_observation_id",
            "quality_status",
            "source_url",
        ]
    ].reset_index(drop=True)


def select_observations_as_of(
    versions: pd.DataFrame, as_of: str | pd.Timestamp
) -> pd.DataFrame:
    """返回指定历史日期收盘前已经生效、尚未被替代的观测版本。"""

    timestamp = pd.Timestamp(as_of)
    active = versions.loc[
        versions["valid_from"].le(timestamp)
        & (versions["valid_to"].isna() | versions["valid_to"].gt(timestamp))
    ].copy()
    if active.duplicated(OBSERVATION_KEY).any():
        raise ValueError("指定时点存在多个同时生效的指标版本")
    return active.sort_values(OBSERVATION_KEY).reset_index(drop=True)


def audit_research_database(
    master: pd.DataFrame,
    assets: pd.DataFrame,
    metrics: pd.DataFrame,
    distributions: pd.DataFrame,
    documents: pd.DataFrame,
    definitions: pd.DataFrame,
    requirements: pd.DataFrame | None = None,
) -> dict[str, object]:
    """检查主外键、来源、单位及 point-in-time 日期关系。"""

    master_symbols = set(master["symbol"])
    if not set(assets["symbol"]).issubset(master_symbols):
        raise ValueError("资产表存在证券主表中没有的 symbol")
    if not set(documents["symbol"]).issubset(master_symbols):
        raise ValueError("公告表存在证券主表中没有的 symbol")
    if not set(metrics["symbol"]).issubset(master_symbols):
        raise ValueError("经营指标存在证券主表中没有的 symbol")
    if not set(distributions["symbol"]).issubset(master_symbols):
        raise ValueError("分派表存在证券主表中没有的 symbol")

    asset_keys = set(zip(assets["symbol"], assets["asset_id"], strict=False))
    metric_asset_keys = set(zip(metrics["symbol"], metrics["asset_id"], strict=False))
    if not metric_asset_keys.issubset(asset_keys):
        raise ValueError("经营指标存在资产表中没有的 symbol/asset_id")

    definition_units = definitions.set_index("metric")["canonical_unit"].to_dict()
    unknown_metrics = sorted(set(metrics["metric"]).difference(definition_units))
    if unknown_metrics:
        raise ValueError(f"经营指标未登记到指标字典: {unknown_metrics}")
    bad_units = metrics.loc[
        metrics.apply(lambda row: definition_units[row["metric"]] != row["unit"], axis=1),
        ["metric", "unit"],
    ].drop_duplicates()
    if not bad_units.empty:
        raise ValueError(f"经营指标单位与指标字典不一致: {bad_units.to_dict('records')}")

    metric_scopes = definitions.set_index("metric")["asset_scope"].to_dict()
    asset_columns = ["symbol", "asset_id", "asset_type"]
    if "asset_effective_from" in assets:
        asset_columns.append("asset_effective_from")
    typed_metrics = metrics.merge(
        assets[asset_columns],
        on=["symbol", "asset_id"],
        how="left",
        validate="many_to_one",
    )
    invalid_scopes = typed_metrics.loc[
        typed_metrics.apply(
            lambda row: "all" not in str(metric_scopes[row["metric"]]).split("|")
            and row["asset_type"]
            not in str(metric_scopes[row["metric"]]).split("|"),
            axis=1,
        ),
        ["asset_type", "metric"],
    ].drop_duplicates()
    if not invalid_scopes.empty:
        raise ValueError(
            f"经营指标不适用于对应资产类型: {invalid_scopes.to_dict('records')}"
        )
    if "asset_effective_from" in typed_metrics:
        predates_asset = typed_metrics["period_end"].lt(
            typed_metrics["asset_effective_from"]
        )
        if predates_asset.any():
            raise ValueError("经营指标报告期末不能早于资产纳入日期")

    document_urls = set(documents["source_url"])
    if not set(metrics["source_url"]).issubset(document_urls):
        raise ValueError("经营指标存在未登记的来源 URL")
    if not set(distributions["source_url"]).issubset(document_urls):
        raise ValueError("分派记录存在未登记的来源 URL")

    document_keys = documents.set_index("source_url")
    metric_documents = metrics.join(
        document_keys[["symbol", "period_end", "publication_date"]],
        on="source_url",
        rsuffix="_document",
        validate="many_to_one",
    )
    metric_link_mismatch = (
        metric_documents["symbol"] != metric_documents["symbol_document"]
    ) | (
        metric_documents["period_end"] != metric_documents["period_end_document"]
    ) | (
        metric_documents["publication_date"]
        != metric_documents["publication_date_document"]
    )
    if metric_link_mismatch.any():
        raise ValueError("经营指标与来源公告的证券、报告期或发布日期不一致")

    distribution_documents = distributions.join(
        document_keys[["symbol", "publication_date"]],
        on="source_url",
        rsuffix="_document",
        validate="many_to_one",
    )
    announcement_dates = pd.to_datetime(
        distribution_documents["announcement_date"], errors="raise"
    )
    distribution_link_mismatch = (
        distribution_documents["symbol"] != distribution_documents["symbol_document"]
    ) | (
        announcement_dates != distribution_documents["publication_date"]
    )
    if distribution_link_mismatch.any():
        raise ValueError("分派记录与来源公告的证券或公告日期不一致")

    if (metrics["publication_date"] < metrics["period_end"]).any():
        raise ValueError("经营指标发布日期不能早于报告期末")
    if "announcement_date" in distributions:
        if (announcement_dates > distributions["ex_date"]).any():
            raise ValueError("分派公告日期不能晚于除息日")

    periods = metrics["period_end"].dt.to_period("Q")
    if requirements is None:
        coverage = build_metric_coverage(metrics, set(metrics["metric"]))
    else:
        requirement_metrics = set(requirements["metric"])
        unknown_requirements = sorted(requirement_metrics.difference(definition_units))
        if unknown_requirements:
            raise ValueError(f"资产类型要求包含未登记指标: {unknown_requirements}")
        coverage = build_asset_type_coverage(assets, metrics, requirements)
    versions = build_observation_versions(metrics, documents)
    used_document_urls = set(metrics["source_url"]) | set(distributions["source_url"])
    return {
        "securities": len(master),
        "assets": len(assets),
        "metric_definitions": len(definitions),
        "source_documents": len(documents),
        "source_documents_used": len(used_document_urls),
        "operating_observations": len(metrics),
        "distributions": len(distributions),
        "quarter_start": str(periods.min()),
        "quarter_end": str(periods.max()),
        "verified_documents": int(documents["verification_status"].eq("human_verified").sum()),
        "metadata_verified_documents": int(
            documents["verification_status"].eq("metadata_verified").sum()
        ),
        "coverage_cells": len(coverage),
        "available_cells": int(coverage["status"].eq("available").sum()),
        "coverage_pct": float(coverage["status"].eq("available").mean() * 100),
        "observation_versions": len(versions),
        "revised_observations": int(versions["supersedes_observation_id"].notna().sum()),
    }


def audit_default_pilot_database() -> dict[str, object]:
    """加载并审计仓库内 508026 试点的全部关系表。"""

    return audit_research_database(
        load_reit_master(DEFAULT_MASTER_PATH),
        load_hydropower_asset(DEFAULT_ASSET_PATH),
        load_hydropower_metrics(DEFAULT_METRICS_PATH),
        load_distributions(DEFAULT_DISTRIBUTIONS_PATH),
        load_source_documents(DEFAULT_DOCUMENTS_PATH),
        load_metric_definitions(DEFAULT_DEFINITIONS_PATH),
        load_asset_metric_requirements(DEFAULT_REQUIREMENTS_PATH),
    )


def export_default_pilot_database(
    output_dir: str | Path,
    *,
    as_of: str | pd.Timestamp | None = None,
) -> dict[str, Path]:
    """导出508026季度版本、上市前年度数据、水文映射和再分析天气。"""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    assets = load_hydropower_asset(DEFAULT_ASSET_PATH)
    metrics = load_hydropower_metrics(DEFAULT_METRICS_PATH)
    documents = load_source_documents(DEFAULT_DOCUMENTS_PATH)
    requirements = load_asset_metric_requirements(DEFAULT_REQUIREMENTS_PATH)
    versions = build_observation_versions(metrics, documents)
    coverage = build_asset_type_coverage(assets, metrics, requirements)
    prelisting = load_prelisting_hydropower_metrics()
    hydrology = load_hydrology_mapping()
    weather = load_hydropower_weather_features()
    annual_weather = build_prelisting_weather_panel(prelisting, weather)
    watershed = load_watershed_proxy()
    catchment_weights = load_catchment_grid_weights()
    catchment_weather = load_catchment_weather_features()
    fixed_lead_forecast = load_fixed_lead_weather_forecast()
    annual_model_panel = build_annual_model_panel(
        prelisting, weather, catchment_weather
    )
    annual_predictions = expanding_annual_backtest(annual_model_panel)
    annual_model_summary = summarize_annual_backtest(annual_predictions)

    paths = {
        "observation_versions": output / "operating_observation_versions.csv",
        "core_metric_coverage": output / "core_metric_coverage.csv",
        "prelisting_operating_metrics": output
        / "508026_prelisting_operating_metrics.csv",
        "hydrology_mapping": output / "508026_hydrology_mapping.csv",
        "quarterly_weather_reanalysis": output
        / "508026_quarterly_weather_reanalysis.csv",
        "prelisting_annual_weather_panel": output
        / "508026_prelisting_annual_weather_panel.csv",
        "watershed_candidate_geojson": output
        / "508026_watershed_candidate.geojson",
        "watershed_proxy_metadata": output
        / "508026_watershed_proxy_metadata.csv",
        "catchment_grid_weights": output / "508026_catchment_grid_weights.csv",
        "quarterly_catchment_weather_reanalysis": output
        / "508026_quarterly_catchment_weather_reanalysis.csv",
        "quarterly_weather_forecast_lead24": output
        / "508026_quarterly_weather_forecast_lead24.csv",
        "annual_model_panel": output / "508026_annual_model_panel.csv",
        "annual_model_predictions": output / "508026_annual_model_predictions.csv",
        "annual_model_summary": output / "508026_annual_model_summary.csv",
    }
    versions.to_csv(paths["observation_versions"], index=False)
    coverage.to_csv(paths["core_metric_coverage"], index=False)
    prelisting.to_csv(paths["prelisting_operating_metrics"], index=False)
    hydrology.to_csv(paths["hydrology_mapping"], index=False)
    weather.to_csv(paths["quarterly_weather_reanalysis"], index=False)
    annual_weather.to_csv(paths["prelisting_annual_weather_panel"], index=False)
    shutil.copyfile(
        DEFAULT_WATERSHED_GEOJSON_PATH, paths["watershed_candidate_geojson"]
    )
    watershed.to_csv(paths["watershed_proxy_metadata"], index=False)
    catchment_weights.to_csv(paths["catchment_grid_weights"], index=False)
    catchment_weather.to_csv(
        paths["quarterly_catchment_weather_reanalysis"], index=False
    )
    fixed_lead_forecast.to_csv(
        paths["quarterly_weather_forecast_lead24"], index=False
    )
    annual_model_panel.to_csv(paths["annual_model_panel"], index=False)
    annual_predictions.to_csv(paths["annual_model_predictions"], index=False)
    annual_model_summary.to_csv(paths["annual_model_summary"], index=False)
    if as_of is not None:
        snapshot = select_observations_as_of(versions, as_of)
        snapshot.insert(0, "snapshot_as_of", pd.Timestamp(as_of))
        paths["point_in_time_snapshot"] = output / "operating_observations_as_of.csv"
        snapshot.to_csv(paths["point_in_time_snapshot"], index=False)
    return paths


def audit_cross_asset_seed_database() -> dict[str, object]:
    """审计 Phase 0 三类资产已核验样本迁移后的规范数据库种子。"""

    empty_distributions = pd.DataFrame(
        columns=["symbol", "ex_date", "cash_per_unit", "announcement_date", "source_url"]
    )
    empty_distributions["ex_date"] = pd.to_datetime(empty_distributions["ex_date"])
    return audit_research_database(
        load_reit_master(DEFAULT_MASTER_PATH),
        load_assets(DEFAULT_CROSS_ASSETS_PATH),
        load_operating_metrics(DEFAULT_CROSS_METRICS_PATH),
        empty_distributions,
        load_source_documents(DEFAULT_CROSS_DOCUMENTS_PATH),
        load_metric_definitions(DEFAULT_DEFINITIONS_PATH),
        load_asset_metric_requirements(DEFAULT_REQUIREMENTS_PATH),
    )


def audit_energy_seed_database() -> dict[str, object]:
    """审计首批风电、光伏、水电和燃气发电资产级经营样本。"""

    empty_distributions = pd.DataFrame(
        columns=["symbol", "ex_date", "cash_per_unit", "announcement_date", "source_url"]
    )
    empty_distributions["ex_date"] = pd.to_datetime(empty_distributions["ex_date"])
    return audit_research_database(
        load_reit_master(DEFAULT_MASTER_PATH),
        load_assets(DEFAULT_ENERGY_ASSETS_PATH),
        load_operating_metrics(DEFAULT_ENERGY_METRICS_PATH),
        empty_distributions,
        load_source_documents(DEFAULT_ENERGY_DOCUMENTS_PATH),
        load_metric_definitions(DEFAULT_DEFINITIONS_PATH),
        load_asset_metric_requirements(DEFAULT_REQUIREMENTS_PATH),
    )


def audit_wind_panel_database() -> dict[str, object]:
    """审计 508028 海上风电连续季度经营面板。"""

    empty_distributions = pd.DataFrame(
        columns=["symbol", "ex_date", "cash_per_unit", "announcement_date", "source_url"]
    )
    empty_distributions["ex_date"] = pd.to_datetime(empty_distributions["ex_date"])
    assets = load_assets(DEFAULT_ENERGY_ASSETS_PATH)
    assets = assets.loc[assets["symbol"].eq("508028")].reset_index(drop=True)
    documents = load_source_documents(DEFAULT_ENERGY_DOCUMENTS_PATH)
    documents = documents.loc[documents["symbol"].eq("508028")].reset_index(drop=True)
    return audit_research_database(
        load_reit_master(DEFAULT_MASTER_PATH),
        assets,
        load_operating_metrics(DEFAULT_WIND_METRICS_PATH),
        empty_distributions,
        documents,
        load_metric_definitions(DEFAULT_DEFINITIONS_PATH),
        load_asset_metric_requirements(DEFAULT_REQUIREMENTS_PATH),
    )


def _audit_energy_panel_database(symbol: str, metrics_path: str | Path) -> dict[str, object]:
    """按单只能源 REIT 审计连续季度经营面板。"""

    empty_distributions = pd.DataFrame(
        columns=["symbol", "ex_date", "cash_per_unit", "announcement_date", "source_url"]
    )
    empty_distributions["ex_date"] = pd.to_datetime(empty_distributions["ex_date"])
    assets = load_assets(DEFAULT_ENERGY_ASSETS_PATH)
    assets = assets.loc[assets["symbol"].eq(symbol)].reset_index(drop=True)
    documents = load_source_documents(DEFAULT_ENERGY_DOCUMENTS_PATH)
    documents = documents.loc[documents["symbol"].eq(symbol)].reset_index(drop=True)
    return audit_research_database(
        load_reit_master(DEFAULT_MASTER_PATH),
        assets,
        load_operating_metrics(metrics_path),
        empty_distributions,
        documents,
        load_metric_definitions(DEFAULT_DEFINITIONS_PATH),
        load_asset_metric_requirements(DEFAULT_REQUIREMENTS_PATH),
    )


def audit_solar_hydro_panel_database() -> dict[str, object]:
    """审计 508096 光伏及扩募水电季度经营面板。"""

    return _audit_energy_panel_database("508096", DEFAULT_SOLAR_HYDRO_METRICS_PATH)


def audit_gas_panel_database() -> dict[str, object]:
    """审计 180401 燃气发电季度经营面板。"""

    return _audit_energy_panel_database("180401", DEFAULT_GAS_METRICS_PATH)


def export_energy_seed_database(output_dir: str | Path) -> dict[str, Path]:
    """导出能源横截面及三只能源 REIT 的纵向版本与覆盖矩阵。"""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    assets = load_assets(DEFAULT_ENERGY_ASSETS_PATH)
    metrics = load_operating_metrics(DEFAULT_ENERGY_METRICS_PATH)
    documents = load_source_documents(DEFAULT_ENERGY_DOCUMENTS_PATH)
    requirements = load_asset_metric_requirements(DEFAULT_REQUIREMENTS_PATH)
    versions = build_observation_versions(metrics, documents)
    coverage = build_asset_type_coverage(assets, metrics, requirements)
    wind_metrics = load_operating_metrics(DEFAULT_WIND_METRICS_PATH)
    wind_documents = documents.loc[documents["symbol"].eq("508028")]
    wind_assets = assets.loc[assets["symbol"].eq("508028")]
    wind_versions = build_observation_versions(wind_metrics, wind_documents)
    wind_coverage = build_asset_type_coverage(wind_assets, wind_metrics, requirements)
    paths = {
        "energy_observation_versions": output / "energy_observation_versions.csv",
        "energy_core_metric_coverage": output / "energy_core_metric_coverage.csv",
        "wind_observation_versions": output / "508028_observation_versions.csv",
        "wind_core_metric_coverage": output / "508028_core_metric_coverage.csv",
        "energy_annual_reconciliations": output
        / "energy_annual_reconciliations.csv",
    }
    versions.to_csv(paths["energy_observation_versions"], index=False)
    coverage.to_csv(paths["energy_core_metric_coverage"], index=False)
    wind_versions.to_csv(paths["wind_observation_versions"], index=False)
    wind_coverage.to_csv(paths["wind_core_metric_coverage"], index=False)
    load_annual_reconciliations().to_csv(
        paths["energy_annual_reconciliations"], index=False
    )
    for symbol, metrics_path, label in [
        ("508096", DEFAULT_SOLAR_HYDRO_METRICS_PATH, "solar_hydro"),
        ("180401", DEFAULT_GAS_METRICS_PATH, "gas"),
    ]:
        panel_metrics = load_operating_metrics(metrics_path)
        panel_documents = documents.loc[documents["symbol"].eq(symbol)]
        panel_assets = assets.loc[assets["symbol"].eq(symbol)]
        panel_versions = build_observation_versions(panel_metrics, panel_documents)
        panel_coverage = build_asset_type_coverage(
            panel_assets, panel_metrics, requirements
        )
        version_key = f"{label}_observation_versions"
        coverage_key = f"{label}_core_metric_coverage"
        paths[version_key] = output / f"{symbol}_observation_versions.csv"
        paths[coverage_key] = output / f"{symbol}_core_metric_coverage.csv"
        panel_versions.to_csv(paths[version_key], index=False)
        panel_coverage.to_csv(paths[coverage_key], index=False)
    return paths
