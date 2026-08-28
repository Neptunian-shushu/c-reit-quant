from unittest.mock import Mock

import pandas as pd

from creit_quant.documents import (
    build_periodic_document_registry,
    enrich_document_metadata,
    merge_document_registries,
)


def test_document_enrichment_hashes_bytes_without_writing_files():
    documents = pd.DataFrame(
        {"document_id": ["doc"], "source_url": ["https://example.test/report.pdf"]}
    )
    response = Mock()
    response.content = b"official report bytes"
    response.headers = {"Content-Type": "application/pdf"}
    response.raise_for_status.return_value = None
    session = Mock()
    session.get.return_value = response

    enriched = enrich_document_metadata(
        documents,
        retrieved_at="2026-08-28T08:00:00Z",
        session=session,
    )

    assert enriched.loc[0, "retrieval_status"] == "success"
    assert enriched.loc[0, "content_length_bytes"] == 21
    assert len(enriched.loc[0, "content_sha256"]) == 64
    assert enriched.loc[0, "content_type"] == "application/pdf"


def test_document_enrichment_keeps_failure_for_retry():
    documents = pd.DataFrame(
        {"document_id": ["doc"], "source_url": ["https://example.test/report.pdf"]}
    )
    session = Mock()
    session.get.side_effect = ValueError("empty response body")

    enriched = enrich_document_metadata(documents, session=session)

    assert enriched.loc[0, "retrieval_status"] == "failed"
    assert "empty response" in enriched.loc[0, "retrieval_error"]


def test_periodic_catalog_promotion_is_explicit_and_idempotent():
    catalog = pd.DataFrame(
        {
            "announcement_id": ["SSE_report", "SSE_distribution"],
            "symbol": ["508018", "508018"],
            "publication_date": pd.to_datetime(["2026-07-21", "2026-08-14"]),
            "document_type_candidate": ["quarterly_report", "distribution_announcement"],
            "period_end_candidate": ["2026-06-30", pd.NA],
            "title": ["2026年第2季度报告", "收益分配公告"],
            "source_url": ["https://example.test/q2.pdf", "https://example.test/dist.pdf"],
        }
    )

    discovered = build_periodic_document_registry(catalog, ["508018"])
    merged = merge_document_registries(discovered, discovered)

    assert len(discovered) == 1
    assert discovered.loc[0, "verification_status"] == "metadata_verified"
    assert discovered.loc[0, "retrieval_status"] == "pending"
    assert len(merged) == 1
