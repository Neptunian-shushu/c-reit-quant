from pathlib import Path

import pandas as pd
import pytest

from creit_quant.full_market_periodic_fundamentals import (
    AUDIT_COLUMNS,
    build_full_market_fundamental_panel,
    build_periodic_observations,
    build_periodic_reconciliation,
    fetch_periodic_documents,
)

ROOT = Path(__file__).resolve().parents[1]


def _audit() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "announcement_id": ["q", "h"],
            "symbol": ["508000", "508000"],
            "publication_date": ["2025-04-21", "2025-08-30"],
            "period_end_candidate": ["2025-03-31", "2025-06-30"],
            "document_type": ["quarterly_report", "semiannual_report"],
            "is_corrected": [False, False],
            "source_url": ["https://sse/q", "https://sse/h"],
            "content_sha256": ["a" * 64, "b" * 64],
            "retrieval_status": ["success", "success"],
            "fund_shares": [500_000_000, 500_000_000],
            "distributable_amount_period": [10_000_000, 22_000_000],
            "distributable_amount_per_unit_period": [0.02, 0.044],
            "nav_per_unit": [pd.NA, 2.8],
            "raw_text": ["q", "h"],
        }
    )


def test_build_periodic_observations_has_three_quarterly_and_four_semiannual_rows():
    result = build_periodic_observations(_audit())

    assert len(result) == 7
    counts = result.groupby("document_type")["metric"].nunique().to_dict()
    assert counts == {"quarterly_report": 3, "semiannual_report": 4}
    assert result["source_sha256"].str.fullmatch(r"[ab]{64}").all()


def test_build_periodic_observations_rejects_missing_success_metric():
    audit = _audit()
    audit.loc[audit["document_type"].eq("semiannual_report"), "nav_per_unit"] = pd.NA

    with pytest.raises(ValueError, match="缺少"):
        build_periodic_observations(audit)


def test_fetch_periodic_documents_empty_result_has_stable_schema():
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

    assert fetch_periodic_documents(catalog).columns.tolist() == AUDIT_COLUMNS


def test_build_periodic_observations_prefers_corrected_document():
    audit = pd.concat([_audit().iloc[[1]], _audit().iloc[[1]]], ignore_index=True)
    audit["announcement_id"] = ["original", "corrected"]
    audit["is_corrected"] = [False, True]
    audit["source_url"] = ["https://sse/original", "https://sse/corrected"]
    audit["content_sha256"] = ["a" * 64, "b" * 64]

    result = build_periodic_observations(audit)

    assert result["source_url"].eq("https://sse/corrected").all()
    assert len(result) == 4


def test_periodic_reconciliation_flags_only_large_difference():
    observations = build_periodic_observations(_audit())
    result = build_periodic_reconciliation(observations)

    assert result["reconciliation_status"].eq("within_disclosure_precision").all()
    observations.loc[
        observations["metric"].eq("distributable_amount_per_unit_period"), "value"
    ] += 0.01

    flagged = build_periodic_reconciliation(observations)

    assert flagged["reconciliation_status"].eq("needs_review").all()


def test_combined_fundamental_panel_adds_annual_document_type():
    periodic = build_periodic_observations(_audit())
    annual = periodic.iloc[[0]].drop(columns=["document_type", "is_corrected"])
    annual["publication_date"] = "2026-03-31"
    annual["period_end"] = "2025-12-31"

    result = build_full_market_fundamental_panel(periodic, annual)

    assert len(result) == len(periodic) + 1
    assert (
        result.loc[result["document_type"].eq("annual_report"), "is_corrected"]
        .eq(False)
        .all()
    )


def test_repository_periodic_panel_is_hashed_reconciled_and_matches_phase4():
    periodic = pd.read_csv(
        ROOT / "data" / "samples" / "full_market_periodic_fundamentals.csv",
        dtype={"symbol": str},
    )
    reconciliation = pd.read_csv(
        ROOT / "data" / "samples" / "full_market_periodic_reconciliation.csv",
        dtype={"symbol": str},
    )
    review = pd.read_csv(
        ROOT
        / "data"
        / "samples"
        / "full_market_periodic_fundamentals_verification_queue.csv",
        dtype=str,
        keep_default_na=False,
    )
    assert len(periodic) == 2_972
    assert periodic["symbol"].nunique() == 81
    assert periodic["source_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert (
        reconciliation["reconciliation_status"].eq("within_disclosure_precision").all()
    )
    assert len(review) == len(periodic)
    assert review["review_status"].eq("pending_independent_review").all()

    phase4 = pd.read_csv(
        ROOT / "data" / "samples" / "phase4_fund_fundamentals.csv",
        dtype={"symbol": str},
    )
    phase4 = phase4.loc[phase4["document_type"].eq("quarterly_report")].copy()
    metric_map = {
        "fund_shares": "fund_shares",
        "distributable_amount_period": "distributable_amount_quarter",
        "distributable_amount_per_unit_period": "distributable_amount_per_unit_quarter",
    }
    quarterly = periodic.loc[periodic["document_type"].eq("quarterly_report")].copy()
    quarterly["phase4_metric"] = quarterly["metric"].map(metric_map)
    overlap = quarterly.merge(
        phase4,
        left_on=["symbol", "period_end", "publication_date", "phase4_metric"],
        right_on=["symbol", "period_end", "publication_date", "metric"],
        suffixes=("_full", "_phase4"),
    )
    assert len(overlap) == 315
    assert (overlap["value_full"] - overlap["value_phase4"]).abs().lt(1e-9).all()
