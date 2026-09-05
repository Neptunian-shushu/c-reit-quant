"""全市场公告与基础字段覆盖统计。"""

from __future__ import annotations

import pandas as pd


REPORT_TYPES = {
    "quarterly_report": "quarterly_report_count",
    "semiannual_report": "semiannual_report_count",
    "annual_report": "annual_report_count",
    "distribution_announcement": "distribution_announcement_count",
}

EXTRACTION_QUEUE_COLUMNS = [
    "announcement_id",
    "symbol",
    "publication_date",
    "period_end_candidate",
    "document_type",
    "is_corrected",
    "asset_type",
    "classification_status",
    "source_url",
    "extraction_status",
]


def _base_document_type(values: pd.Series) -> pd.Series:
    return values.astype(str).str.removesuffix("_corrected")


def build_security_data_coverage(
    catalog: pd.DataFrame,
    asset_type_evidence: pd.DataFrame,
    listings: pd.DataFrame,
    *,
    as_of_date: str | pd.Timestamp,
) -> pd.DataFrame:
    """按证券汇总正式公告候选数、日期范围、上市状态和分类证据。"""

    required = {"symbol", "publication_date", "document_type_candidate", "source_url"}
    missing = sorted(required.difference(catalog.columns))
    if missing:
        raise ValueError(f"公告目录缺少覆盖统计字段: {missing}")
    frame = catalog.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.zfill(6)
    frame["publication_date"] = pd.to_datetime(
        frame["publication_date"], errors="raise"
    )
    if asset_type_evidence["symbol"].duplicated().any():
        raise ValueError("资产类型证据每个 symbol 只能有一行")
    if listings["symbol"].duplicated().any():
        raise ValueError("上市记录每个 symbol 只能有一行")

    symbols = pd.DataFrame({"symbol": sorted(frame["symbol"].unique())})
    dates = frame.groupby("symbol")["publication_date"].agg(
        first_announcement_date="min", latest_announcement_date="max"
    )
    frame["base_document_type"] = _base_document_type(frame["document_type_candidate"])
    counts = pd.crosstab(frame["symbol"], frame["base_document_type"])
    for document_type, column in REPORT_TYPES.items():
        symbols[column] = (
            symbols["symbol"]
            .map(counts[document_type] if document_type in counts else {})
            .fillna(0)
            .astype(int)
        )
    symbols = symbols.merge(dates, on="symbol", how="left", validate="one_to_one")
    evidence_columns = ["symbol", "asset_type", "classification_status", "source_url"]
    evidence = asset_type_evidence[evidence_columns].rename(
        columns={"source_url": "asset_type_source_url"}
    )
    symbols = symbols.merge(evidence, on="symbol", how="left", validate="one_to_one")
    listing = (
        listings[["symbol", "listing_date", "source_url"]]
        .copy()
        .rename(columns={"source_url": "listing_source_url"})
    )
    listing["listing_date"] = pd.to_datetime(listing["listing_date"], errors="raise")
    symbols = symbols.merge(listing, on="symbol", how="left", validate="one_to_one")
    end = pd.Timestamp(as_of_date).normalize()
    symbols["listing_status"] = "pre_listing_observed"
    symbols.loc[symbols["listing_date"].le(end), "listing_status"] = "listed"
    symbols["has_periodic_report"] = (
        symbols[
            ["quarterly_report_count", "semiannual_report_count", "annual_report_count"]
        ]
        .sum(axis=1)
        .gt(0)
    )
    symbols["has_distribution_announcement"] = symbols[
        "distribution_announcement_count"
    ].gt(0)
    return symbols.sort_values("symbol").reset_index(drop=True)


def build_document_extraction_queue(
    catalog: pd.DataFrame,
    asset_type_evidence: pd.DataFrame,
    registered_sources: pd.DataFrame | None = None,
    document_audit: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """生成全市场报告/分派解析队列，并标出已有观测使用过的来源。"""

    required = {
        "announcement_id",
        "symbol",
        "publication_date",
        "period_end_candidate",
        "document_type_candidate",
        "source_url",
    }
    missing = sorted(required.difference(catalog.columns))
    if missing:
        raise ValueError(f"公告目录缺少解析队列字段: {missing}")
    if asset_type_evidence["symbol"].duplicated().any():
        raise ValueError("资产类型证据每个 symbol 只能有一行")
    frame = catalog.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.zfill(6)
    frame["publication_date"] = pd.to_datetime(
        frame["publication_date"], errors="raise"
    )
    frame["document_type"] = _base_document_type(frame["document_type_candidate"])
    frame["is_corrected"] = (
        frame["document_type_candidate"].astype(str).str.endswith("_corrected")
    )
    frame = frame.loc[frame["document_type"].isin(REPORT_TYPES)].copy()
    evidence = asset_type_evidence[["symbol", "asset_type", "classification_status"]]
    frame = frame.merge(evidence, on="symbol", how="left", validate="many_to_one")
    registered_urls: set[str] = set()
    if registered_sources is not None and not registered_sources.empty:
        if "source_url" not in registered_sources:
            raise ValueError("来源登记表缺少 source_url")
        registered_urls = set(registered_sources["source_url"].dropna().astype(str))
    frame["extraction_status"] = (
        frame["source_url"]
        .isin(registered_urls)
        .map({True: "observation_source_registered", False: "pending_extraction"})
    )
    if document_audit is not None and not document_audit.empty:
        audit_required = {"announcement_id", "retrieval_status", "failure_reason"}
        audit_missing = sorted(audit_required.difference(document_audit.columns))
        if audit_missing:
            raise ValueError(f"文档抽取审计缺少字段: {audit_missing}")
        if document_audit["announcement_id"].duplicated().any():
            raise ValueError("文档抽取审计 announcement_id 重复")
        audit_status = document_audit.set_index("announcement_id")
        success_ids = set(
            audit_status.loc[audit_status["retrieval_status"].eq("success")].index
        )
        no_text_ids = set(
            audit_status.loc[audit_status["failure_reason"].eq("PDF没有可用文字层")].index
        )
        failed_ids = set(audit_status.index).difference(success_ids | no_text_ids)
        not_registered = frame["extraction_status"].ne("observation_source_registered")
        frame.loc[
            not_registered & frame["announcement_id"].isin(success_ids),
            "extraction_status",
        ] = "machine_extracted_document"
        frame.loc[
            not_registered & frame["announcement_id"].isin(no_text_ids),
            "extraction_status",
        ] = "needs_ocr_or_visual_review"
        frame.loc[
            not_registered & frame["announcement_id"].isin(failed_ids),
            "extraction_status",
        ] = "fetch_or_parse_failed"
    if frame["announcement_id"].duplicated().any():
        raise ValueError("解析队列 announcement_id 重复")
    return (
        frame[EXTRACTION_QUEUE_COLUMNS]
        .sort_values(["symbol", "publication_date", "announcement_id"])
        .reset_index(drop=True)
    )
