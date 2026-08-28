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


def audit_research_database(
    master: pd.DataFrame,
    assets: pd.DataFrame,
    metrics: pd.DataFrame,
    distributions: pd.DataFrame,
    documents: pd.DataFrame,
    definitions: pd.DataFrame,
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
    pilot_metrics = set(metrics["metric"])
    coverage = build_metric_coverage(metrics, pilot_metrics)
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
    )
