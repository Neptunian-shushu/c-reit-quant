"""研究数据库全市场覆盖与质量缺口报告。"""

from __future__ import annotations

import pandas as pd

PERIODIC_CANDIDATE_TYPES = {
    "quarterly_report",
    "quarterly_report_corrected",
    "semiannual_report",
    "semiannual_report_corrected",
    "annual_report",
    "annual_report_corrected",
}


def build_document_coverage(
    security_master: pd.DataFrame, documents: pd.DataFrame
) -> pd.DataFrame:
    """按证券生成公告登记覆盖；没有公告的证券也必须保留。"""

    securities = security_master[["symbol", "name", "exchange"]].drop_duplicates("symbol")
    docs = documents.copy()
    periodic_types = {"quarterly_report", "quarterly_report_corrected", "annual_report"}
    docs["is_periodic_report"] = docs["document_type"].isin(periodic_types)
    grouped = docs.groupby("symbol", as_index=False).agg(
        registered_documents=("document_id", "count"),
        periodic_reports=("is_periodic_report", "sum"),
        latest_publication_date=("publication_date", "max"),
        verified_documents=(
            "verification_status",
            lambda values: values.eq("human_verified").sum(),
        ),
    )
    coverage = securities.merge(grouped, on="symbol", how="left", validate="one_to_one")
    for column in ["registered_documents", "periodic_reports", "verified_documents"]:
        coverage[column] = pd.to_numeric(coverage[column], errors="coerce").fillna(0).astype(int)
    coverage["coverage_status"] = coverage["periodic_reports"].gt(0).map(
        {True: "periodic_report_registered", False: "no_periodic_report_registered"}
    )
    return coverage.sort_values("symbol").reset_index(drop=True)


def build_announcement_catalog_coverage(
    security_master: pd.DataFrame, catalog: pd.DataFrame
) -> pd.DataFrame:
    """区分交易所目录覆盖、定期报告候选和人工登记三个不同层次。"""

    securities = security_master[["symbol", "name", "exchange"]].drop_duplicates("symbol")
    announcements = catalog.copy()
    announcements["is_periodic_candidate"] = announcements[
        "document_type_candidate"
    ].isin(PERIODIC_CANDIDATE_TYPES)
    grouped = announcements.groupby("symbol", as_index=False).agg(
        catalog_announcements=("announcement_id", "count"),
        periodic_candidates=("is_periodic_candidate", "sum"),
        earliest_catalog_date=("publication_date", "min"),
        latest_catalog_date=("publication_date", "max"),
    )
    coverage = securities.merge(grouped, on="symbol", how="left", validate="one_to_one")
    for column in ["catalog_announcements", "periodic_candidates"]:
        coverage[column] = coverage[column].fillna(0).astype(int)
    coverage["catalog_coverage_status"] = "announcement_catalog_missing"
    has_catalog = coverage["catalog_announcements"].gt(0)
    coverage.loc[has_catalog, "catalog_coverage_status"] = "catalog_no_periodic_candidate"
    coverage.loc[
        coverage["periodic_candidates"].gt(0), "catalog_coverage_status"
    ] = "periodic_candidates_found"
    return coverage.sort_values("symbol").reset_index(drop=True)


def build_quality_issues(
    security_master: pd.DataFrame,
    documents: pd.DataFrame,
    document_coverage: pd.DataFrame,
    catalog_coverage: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """生成可机器跟踪的质量问题队列，不用空值默默代表未知。"""

    issues: list[dict[str, object]] = []
    for row in security_master.itertuples(index=False):
        if getattr(row, "record_status", "source_observed") == "needs_name_review":
            issues.append(
                {
                    "severity": "amber",
                    "issue_type": "security_name_needs_review",
                    "entity_type": "security",
                    "entity_id": row.symbol,
                    "detail": row.name,
                }
            )
        if getattr(row, "classification_status", "") == "needs_human_review":
            issues.append(
                {
                    "severity": "amber",
                    "issue_type": "asset_type_needs_review",
                    "entity_type": "security",
                    "entity_id": row.symbol,
                    "detail": getattr(row, "candidate_asset_type", "unknown"),
                }
            )
    coverage = document_coverage.copy()
    if catalog_coverage is not None:
        coverage = coverage.merge(
            catalog_coverage[["symbol", "catalog_coverage_status"]],
            on="symbol",
            how="left",
            validate="one_to_one",
        )
    missing_reports = coverage["coverage_status"].eq("no_periodic_report_registered")
    for row in coverage.loc[missing_reports].itertuples(index=False):
        catalog_status = getattr(row, "catalog_coverage_status", None)
        if catalog_status == "periodic_candidates_found":
            issue_type = "periodic_report_review_pending"
            detail = "交易所目录已有定期报告候选，尚未人工登记"
        elif catalog_status == "catalog_no_periodic_candidate":
            issue_type = "periodic_report_not_yet_found"
            detail = "交易所目录已覆盖，但尚无定期报告候选"
        elif catalog_status == "announcement_catalog_missing":
            issue_type = "announcement_catalog_missing"
            detail = "尚未接入该证券的交易所公告目录"
        else:
            issue_type = "periodic_report_not_registered"
            detail = "公告登记表尚无定期报告"
        issues.append(
            {
                "severity": "amber",
                "issue_type": issue_type,
                "entity_type": "security",
                "entity_id": row.symbol,
                "detail": detail,
            }
        )
    if "content_sha256" in documents:
        missing_hash = documents["content_sha256"].isna() | documents[
            "content_sha256"
        ].eq("")
        for row in documents.loc[missing_hash].itertuples(index=False):
            issues.append(
                {
                    "severity": "info",
                    "issue_type": "document_hash_missing",
                    "entity_type": "document",
                    "entity_id": row.document_id,
                    "detail": "仓库不保存原 PDF，尚未记录抓取内容哈希",
                }
            )
    return pd.DataFrame(
        issues,
        columns=["severity", "issue_type", "entity_type", "entity_id", "detail"],
    ).sort_values(["severity", "issue_type", "entity_id"]).reset_index(drop=True)


def summarise_quality_issues(issues: pd.DataFrame) -> pd.DataFrame:
    """按严重级别和问题类型汇总质量队列。"""

    if issues.empty:
        return pd.DataFrame(columns=["severity", "issue_type", "count"])
    return (
        issues.groupby(["severity", "issue_type"], as_index=False)
        .size()
        .rename(columns={"size": "count"})
        .sort_values(["severity", "issue_type"])
        .reset_index(drop=True)
    )
