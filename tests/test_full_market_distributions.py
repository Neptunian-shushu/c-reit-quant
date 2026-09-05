from pathlib import Path

import pandas as pd

from creit_quant.full_market_distributions import fetch_distribution_documents


ROOT = Path(__file__).resolve().parents[1]


def test_empty_incremental_distribution_fetch_is_idempotent():
    catalog = pd.DataFrame(
        columns=[
            "announcement_id",
            "symbol",
            "publication_date",
            "title",
            "source_url",
            "document_type_candidate",
        ]
    )

    result = fetch_distribution_documents(catalog)

    assert result.empty
    assert {"content_sha256", "failure_reason", "dpu_per_unit"}.issubset(result.columns)


def test_repository_full_market_distribution_panel_is_auditable():
    events = pd.read_csv(
        ROOT / "data" / "samples" / "full_market_distributions.csv",
        dtype={"symbol": str},
    )
    audit = pd.read_csv(
        ROOT / "data" / "samples" / "full_market_distribution_document_audit.csv",
        dtype={"symbol": str},
    )
    reviews = pd.read_csv(
        ROOT / "data" / "samples" / "full_market_distribution_verification_queue.csv",
        dtype=str,
    )

    assert len(audit) == 495
    assert audit["announcement_id"].is_unique
    assert len(events) >= 369
    assert events["symbol"].nunique() >= 67
    assert not events.duplicated(["symbol", "publication_date"]).any()
    assert (events["dpu_per_unit"] > 0).all()
    assert events["source_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert (
        (events["dpu_per_unit"] * 10 - events["disclosed_rmb_per_10_units"])
        .abs()
        .lt(1e-10)
        .all()
    )
    successful = audit["retrieval_status"].eq("success")
    assert audit.loc[successful, "content_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert audit.loc[successful, "content_length_bytes"].gt(0).all()
    assert len(reviews) == len(events)
    assert reviews["observation_id"].is_unique
    assert reviews["review_status"].eq("pending_independent_review").all()
    assert reviews["source_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
