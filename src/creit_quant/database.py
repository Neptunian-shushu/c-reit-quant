"""研究数据库的轻量读取、关系校验和覆盖审计。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from creit_quant.hydropower import (
    DEFAULT_ASSET_PATH,
    DEFAULT_METRICS_PATH,
    load_hydropower_asset,
    load_hydropower_metrics,
)
from creit_quant.strategy import DEFAULT_DISTRIBUTIONS_PATH, load_distributions

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MASTER_PATH = ROOT / "data" / "samples" / "reit_master.csv"
DEFAULT_DOCUMENTS_PATH = ROOT / "data" / "samples" / "508026_source_documents.csv"
DEFAULT_DEFINITIONS_PATH = ROOT / "data" / "reference" / "metric_definitions.csv"
DEFAULT_REQUIREMENTS_PATH = ROOT / "data" / "reference" / "asset_type_metric_requirements.csv"

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
    versions["raw_value"] = versions["value"]
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
    return {
        "securities": len(master),
        "assets": len(assets),
        "metric_definitions": len(definitions),
        "source_documents": len(documents),
        "operating_observations": len(metrics),
        "distributions": len(distributions),
        "quarter_start": str(periods.min()),
        "quarter_end": str(periods.max()),
        "verified_documents": int(documents["verification_status"].eq("human_verified").sum()),
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
    """构建并导出 508026 规范观测版本、时点快照和核心覆盖矩阵。"""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    assets = load_hydropower_asset(DEFAULT_ASSET_PATH)
    metrics = load_hydropower_metrics(DEFAULT_METRICS_PATH)
    documents = load_source_documents(DEFAULT_DOCUMENTS_PATH)
    requirements = load_asset_metric_requirements(DEFAULT_REQUIREMENTS_PATH)
    versions = build_observation_versions(metrics, documents)
    coverage = build_asset_type_coverage(assets, metrics, requirements)

    paths = {
        "observation_versions": output / "operating_observation_versions.csv",
        "core_metric_coverage": output / "core_metric_coverage.csv",
    }
    versions.to_csv(paths["observation_versions"], index=False)
    coverage.to_csv(paths["core_metric_coverage"], index=False)
    if as_of is not None:
        snapshot = select_observations_as_of(versions, as_of)
        snapshot.insert(0, "snapshot_as_of", pd.Timestamp(as_of))
        paths["point_in_time_snapshot"] = output / "operating_observations_as_of.csv"
        snapshot.to_csv(paths["point_in_time_snapshot"], index=False)
    return paths
