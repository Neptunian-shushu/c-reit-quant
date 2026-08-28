from unittest.mock import Mock

import pandas as pd

from creit_quant.documents import enrich_document_metadata


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
