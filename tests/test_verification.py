import pandas as pd
import pytest
from pathlib import Path

from creit_quant.verification import (
    build_distribution_verification_queue,
    build_phase4_source_registry,
    build_phase4_verification_queue,
    merge_registered_source_metadata,
    summarize_verification_queue,
    validate_phase4_verification_queue,
)

ROOT = Path(__file__).resolve().parents[1]


def _inputs():
    fundamentals = pd.DataFrame(
        {
            "symbol": ["508026"],
            "period_end": [pd.Timestamp("2026-06-30")],
            "publication_date": [pd.Timestamp("2026-07-21")],
            "metric": ["fund_shares"],
            "value": [400_000_000.0],
            "unit": ["shares"],
            "source_url": ["https://sse/report.pdf"],
            "verification_status": ["machine_extracted_official_pdf"],
        }
    )
    distributions = pd.DataFrame(
        {
            "symbol": ["508026"],
            "publication_date": [pd.Timestamp("2026-08-01")],
            "dpu_per_unit": [0.1],
            "source_url": ["https://sse/distribution.pdf"],
            "verification_status": ["visual_verified_official_pdf"],
        }
    )
    return fundamentals, distributions


def test_verification_queue_has_stable_ids_and_preserves_completed_review():
    fundamentals, distributions = _inputs()
    first = build_phase4_verification_queue(fundamentals, distributions)
    first.loc[0, ["review_status", "reviewed_by", "reviewed_at"]] = [
        "confirmed",
        "reviewer_b",
        "2026-09-06T10:00:00+08:00",
    ]

    second = build_phase4_verification_queue(
        fundamentals, distributions, existing=first
    )
    summary = summarize_verification_queue(second)

    assert first["observation_id"].tolist() == second["observation_id"].tolist()
    assert summary == {
        "observations": 2,
        "confirmed": 1,
        "rejected": 0,
        "pending": 1,
        "source_hash_present": 0,
    }


def test_completed_review_requires_reviewer_and_timestamp():
    fundamentals, distributions = _inputs()
    queue = build_phase4_verification_queue(fundamentals, distributions)
    queue.loc[0, "review_status"] = "confirmed"

    with pytest.raises(ValueError, match="必须填写"):
        validate_phase4_verification_queue(queue)


def test_source_registry_deduplicates_urls_and_preserves_hash_metadata():
    fundamentals, distributions = _inputs()
    queue = build_phase4_verification_queue(fundamentals, distributions)
    first = build_phase4_source_registry(queue)
    first.loc[0, ["content_sha256", "retrieval_status"]] = ["a" * 64, "success"]

    second = build_phase4_source_registry(queue, first)

    assert len(second) == 2
    assert second["observation_count"].sum() == 2
    assert second["content_sha256"].eq("a" * 64).sum() == 1


def test_existing_registry_does_not_drop_new_url_hash():
    fundamentals, distributions = _inputs()
    queue = build_phase4_verification_queue(fundamentals, distributions)
    queue.loc[queue["dataset"].eq("phase4_distributions"), "source_sha256"] = "b" * 64
    full = build_phase4_source_registry(queue)
    existing = full.loc[full["source_url"].eq("https://sse/report.pdf")].copy()

    rebuilt = build_phase4_source_registry(queue, existing).set_index("source_url")

    assert rebuilt.loc["https://sse/distribution.pdf", "content_sha256"] == "b" * 64
    assert rebuilt.loc["https://sse/distribution.pdf", "retrieval_status"] == "success"


def test_distribution_review_queue_preserves_review_by_stable_observation_id():
    distributions = pd.DataFrame(
        {
            "symbol": ["508026"],
            "publication_date": ["2026-08-01"],
            "dpu_per_unit": [0.1],
            "source_url": ["https://sse/distribution.pdf"],
            "source_sha256": ["a" * 64],
            "verification_status": ["machine_extracted_official_pdf"],
        }
    )
    first = build_distribution_verification_queue(distributions)
    first.loc[0, "review_status"] = "confirmed"
    first.loc[0, "reviewed_by"] = "reviewer"
    first.loc[0, "reviewed_at"] = "2026-09-05T12:00:00+08:00"

    rebuilt = build_distribution_verification_queue(distributions, existing=first)

    assert rebuilt.loc[0, "review_status"] == "confirmed"
    assert rebuilt.loc[0, "reviewed_by"] == "reviewer"


def test_registered_source_metadata_fills_empty_fields(tmp_path):
    fundamentals, distributions = _inputs()
    queue = build_phase4_verification_queue(fundamentals, distributions)
    sources = build_phase4_source_registry(queue)
    metadata = pd.DataFrame(
        {
            "source_url": ["https://sse/report.pdf"],
            "retrieved_at": ["2026-09-06T02:00:00Z"],
            "content_sha256": ["a" * 64],
            "content_type": ["application/pdf"],
            "content_length_bytes": ["123"],
            "retrieval_status": ["success"],
            "retrieval_error": [""],
        }
    )
    path = tmp_path / "documents.csv"
    metadata.to_csv(path, index=False)

    merged = merge_registered_source_metadata(sources, [path]).set_index("source_url")

    assert merged.loc["https://sse/report.pdf", "content_sha256"] == "a" * 64
    assert merged.loc["https://sse/report.pdf", "content_length_bytes"] == "123"


def test_repository_phase4_sources_are_all_hashed_without_pdf_storage():
    sources = pd.read_csv(
        ROOT / "data" / "samples" / "phase4_source_registry.csv", dtype=str
    )
    queue = pd.read_csv(
        ROOT / "data" / "samples" / "phase4_verification_queue.csv",
        dtype=str,
        keep_default_na=False,
    )

    assert len(sources) == 209
    assert sources["source_url"].is_unique
    assert sources["retrieval_status"].eq("success").all()
    assert sources["content_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert queue["source_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert len(queue) == 419
    assert not list(ROOT.rglob("*.pdf"))
