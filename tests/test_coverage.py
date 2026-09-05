import pandas as pd
import pytest

from creit_quant.coverage import (
    build_document_extraction_queue,
    build_security_data_coverage,
)


def test_security_data_coverage_counts_reports_and_listing_state():
    catalog = pd.DataFrame(
        {
            "symbol": ["508001", "508001", "508002"],
            "publication_date": ["2025-03-31", "2025-04-10", "2026-09-04"],
            "document_type_candidate": [
                "annual_report",
                "distribution_announcement",
                "other",
            ],
            "source_url": ["https://sse/a", "https://sse/b", "https://sse/c"],
        }
    )
    evidence = pd.DataFrame(
        {
            "symbol": ["508001", "508002"],
            "asset_type": ["toll_road", "rental_housing"],
            "classification_status": ["official_title_evidence"] * 2,
            "source_url": ["https://sse/a", "https://sse/c"],
        }
    )
    listings = pd.DataFrame(
        {
            "symbol": ["508001"],
            "listing_date": ["2021-06-21"],
            "source_url": ["https://sse/list"],
        }
    )

    result = build_security_data_coverage(
        catalog, evidence, listings, as_of_date="2026-09-05"
    ).set_index("symbol")

    assert result.loc["508001", "annual_report_count"] == 1
    assert result.loc["508001", "distribution_announcement_count"] == 1
    assert bool(result.loc["508001", "has_periodic_report"])
    assert result.loc["508001", "listing_status"] == "listed"
    assert result.loc["508002", "listing_status"] == "pre_listing_observed"


def test_security_data_coverage_rejects_duplicate_evidence():
    catalog = pd.DataFrame(
        {
            "symbol": ["508001"],
            "publication_date": ["2025-03-31"],
            "document_type_candidate": ["annual_report"],
            "source_url": ["https://sse/a"],
        }
    )
    evidence = pd.DataFrame(
        {
            "symbol": ["508001", "508001"],
            "asset_type": ["toll_road", "toll_road"],
            "classification_status": ["official_title_evidence"] * 2,
            "source_url": ["https://sse/a", "https://sse/a"],
        }
    )
    listings = pd.DataFrame(columns=["symbol", "listing_date", "source_url"])

    with pytest.raises(ValueError, match="资产类型证据"):
        build_security_data_coverage(
            catalog, evidence, listings, as_of_date="2026-09-05"
        )


def test_document_extraction_queue_normalizes_corrections_and_marks_sources():
    catalog = pd.DataFrame(
        {
            "announcement_id": ["a", "b", "c"],
            "symbol": ["508001"] * 3,
            "publication_date": ["2025-03-31", "2025-04-01", "2025-04-02"],
            "period_end_candidate": ["2024-12-31", "2024-12-31", None],
            "document_type_candidate": [
                "annual_report",
                "annual_report_corrected",
                "other",
            ],
            "source_url": ["https://sse/a", "https://sse/b", "https://sse/c"],
        }
    )
    evidence = pd.DataFrame(
        {
            "symbol": ["508001"],
            "asset_type": ["toll_road"],
            "classification_status": ["official_title_evidence"],
        }
    )
    registry = pd.DataFrame({"source_url": ["https://sse/a"]})

    audit = pd.DataFrame(
        {
            "announcement_id": ["b"],
            "retrieval_status": ["failed"],
            "failure_reason": ["PDF没有可用文字层"],
        }
    )
    queue = build_document_extraction_queue(catalog, evidence, registry, audit)

    assert queue["document_type"].tolist() == ["annual_report", "annual_report"]
    assert queue["is_corrected"].tolist() == [False, True]
    assert queue["extraction_status"].tolist() == [
        "observation_source_registered",
        "needs_ocr_or_visual_review",
    ]
