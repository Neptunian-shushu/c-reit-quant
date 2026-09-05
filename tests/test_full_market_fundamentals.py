from pathlib import Path

import pandas as pd
import pytest

from creit_quant.full_market_fundamentals import (
    AUDIT_COLUMNS,
    build_annual_observations,
    fetch_annual_documents,
)

ROOT = Path(__file__).resolve().parents[1]


def test_build_annual_observations_is_long_format_and_hashed():
    audit = pd.DataFrame(
        {
            "announcement_id": ["a"],
            "symbol": ["508001"],
            "publication_date": ["2026-03-31"],
            "period_end_candidate": ["2025-12-31"],
            "source_url": ["https://sse/a"],
            "content_sha256": ["a" * 64],
            "retrieval_status": ["success"],
            "fund_shares": [500_000_000],
            "nav_per_unit": [4.2],
            "raw_text": ["evidence"],
        }
    )

    result = build_annual_observations(audit)

    assert result["metric"].tolist() == ["fund_shares", "nav_per_unit"]
    assert result["source_sha256"].str.fullmatch(r"a{64}").all()


def test_build_annual_observations_rejects_conflicting_duplicate_reports():
    audit = pd.DataFrame(
        {
            "announcement_id": ["a", "b"],
            "symbol": ["508001"] * 2,
            "publication_date": ["2026-03-31", "2026-04-01"],
            "period_end_candidate": ["2025-12-31"] * 2,
            "source_url": ["https://sse/a", "https://sse/b"],
            "content_sha256": ["a" * 64, "b" * 64],
            "retrieval_status": ["success"] * 2,
            "fund_shares": [500_000_000] * 2,
            "nav_per_unit": [4.2, 4.3],
            "raw_text": ["a", "b"],
        }
    )

    with pytest.raises(ValueError, match="冲突"):
        build_annual_observations(audit)


def test_fetch_annual_documents_empty_result_has_stable_schema():
    catalog = pd.DataFrame(
        columns=[
            "announcement_id",
            "symbol",
            "publication_date",
            "period_end_candidate",
            "document_type_candidate",
            "title",
            "source_url",
        ]
    )

    result = fetch_annual_documents(catalog)

    assert result.columns.tolist() == AUDIT_COLUMNS


def test_repository_annual_fundamentals_are_hashed_and_well_formed():
    path = ROOT / "data" / "samples" / "full_market_annual_fundamentals.csv"
    if not path.exists():
        pytest.skip("全市场年报面板尚未生成")
    frame = pd.read_csv(path, dtype={"symbol": str})

    assert set(frame["metric"]) == {"fund_shares", "nav_per_unit"}
    assert frame["source_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert not frame.duplicated(["symbol", "period_end", "metric"]).any()
    assert (
        pd.to_datetime(frame["publication_date"]) >= pd.to_datetime(frame["period_end"])
    ).all()
    assert frame.groupby(["symbol", "period_end"])["metric"].nunique().eq(2).all()

    phase4 = pd.read_csv(
        ROOT / "data" / "samples" / "phase4_fund_fundamentals.csv",
        dtype={"symbol": str},
    )
    overlap = frame.merge(
        phase4.loc[phase4["metric"].isin(["fund_shares", "nav_per_unit"])],
        on=["symbol", "period_end", "metric"],
        suffixes=("_annual", "_phase4"),
    )
    assert len(overlap) == 30
    assert (overlap["value_annual"] - overlap["value_phase4"]).abs().lt(1e-9).all()

    review = pd.read_csv(
        ROOT
        / "data"
        / "samples"
        / "full_market_annual_fundamentals_verification_queue.csv",
        dtype=str,
        keep_default_na=False,
    )
    assert len(review) == len(frame)
    assert review["review_status"].eq("pending_independent_review").all()
