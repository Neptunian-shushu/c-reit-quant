import pandas as pd

from creit_quant.quality import (
    build_announcement_catalog_coverage,
    build_document_coverage,
    build_quality_issues,
    summarise_quality_issues,
)


def test_document_coverage_keeps_securities_without_documents():
    master = pd.DataFrame(
        {
            "symbol": ["508026", "180202"],
            "name": ["水电REIT", "高速REIT"],
            "exchange": ["SSE", "SZSE"],
        }
    )
    documents = pd.DataFrame(
        {
            "document_id": ["doc"],
            "symbol": ["508026"],
            "document_type": ["quarterly_report"],
            "publication_date": pd.to_datetime(["2025-07-20"]),
            "verification_status": ["human_verified"],
        }
    )

    coverage = build_document_coverage(master, documents).set_index("symbol")

    assert coverage.loc["508026", "periodic_reports"] == 1
    assert coverage.loc["180202", "coverage_status"] == "no_periodic_report_registered"


def test_quality_issues_are_explicit_and_summarised():
    master = pd.DataFrame(
        {
            "symbol": ["508026"],
            "name": ["截断..."],
            "exchange": ["SSE"],
            "record_status": ["needs_name_review"],
            "candidate_asset_type": ["unknown"],
            "classification_status": ["needs_human_review"],
        }
    )
    documents = pd.DataFrame(
        {
            "document_id": ["doc"],
            "symbol": ["508026"],
            "document_type": ["distribution_announcement"],
            "publication_date": pd.to_datetime(["2025-07-20"]),
            "verification_status": ["human_verified"],
            "content_sha256": [pd.NA],
        }
    )
    coverage = build_document_coverage(master, documents)
    issues = build_quality_issues(master, documents, coverage)
    summary = summarise_quality_issues(issues)

    assert set(issues["issue_type"]) == {
        "security_name_needs_review",
        "asset_type_needs_review",
        "periodic_report_not_registered",
        "document_hash_missing",
    }
    assert summary["count"].sum() == 4


def test_catalog_coverage_distinguishes_discovery_from_registration():
    master = pd.DataFrame(
        {
            "symbol": ["508026", "508099", "180202"],
            "name": ["水电", "新上市", "深市"],
            "exchange": ["SSE", "SSE", "SZSE"],
        }
    )
    catalog = pd.DataFrame(
        {
            "announcement_id": ["a", "b"],
            "symbol": ["508026", "508099"],
            "publication_date": pd.to_datetime(["2026-07-20", "2026-08-20"]),
            "document_type_candidate": ["quarterly_report", "other"],
        }
    )

    coverage = build_announcement_catalog_coverage(master, catalog).set_index("symbol")

    assert coverage.loc["508026", "catalog_coverage_status"] == "periodic_candidates_found"
    assert coverage.loc["508099", "catalog_coverage_status"] == "catalog_no_periodic_candidate"
    assert coverage.loc["180202", "catalog_coverage_status"] == "announcement_catalog_missing"


def test_quality_issues_use_catalog_stage_for_missing_registered_reports():
    master = pd.DataFrame(
        {
            "symbol": ["508026"],
            "name": ["水电"],
            "exchange": ["SSE"],
            "record_status": ["source_observed"],
            "candidate_asset_type": ["hydropower"],
            "classification_status": ["human_verified"],
        }
    )
    documents = pd.DataFrame(
        columns=[
            "document_id",
            "symbol",
            "document_type",
            "publication_date",
            "verification_status",
            "content_sha256",
        ]
    )
    document_coverage = build_document_coverage(master, documents)
    catalog_coverage = pd.DataFrame(
        {
            "symbol": ["508026"],
            "catalog_coverage_status": ["periodic_candidates_found"],
        }
    )

    issues = build_quality_issues(
        master, documents, document_coverage, catalog_coverage
    )

    assert issues["issue_type"].tolist() == ["periodic_report_review_pending"]
