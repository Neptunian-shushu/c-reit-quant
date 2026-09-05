import pandas as pd
from pathlib import Path

from creit_quant.database_readiness import (
    build_fundamental_readiness,
    build_share_change_events,
    extract_fund_event_candidates,
)

ROOT = Path(__file__).resolve().parents[1]


def test_readiness_requires_unadjusted_prices_for_valuation():
    securities = pd.DataFrame(
        {
            "symbol": ["508001", "508002"],
            "asset_type": ["toll_road", "hydropower"],
            "classification_status": ["human_verified"] * 2,
            "listing_status": ["listed"] * 2,
            "listing_date": ["2021-01-01"] * 2,
        }
    )
    fundamentals = pd.DataFrame(
        {
            "symbol": ["508001"] * 3,
            "period_end": ["2025-12-31"] * 3,
            "metric": ["fund_shares", "nav_per_unit", "distributable_amount_period"],
            "source_sha256": ["a" * 64] * 3,
        }
    )
    distributions = pd.DataFrame(
        {
            "symbol": ["508001"],
            "ex_date": ["2026-01-01"],
            "source_sha256": ["b" * 64],
        }
    )
    prices = pd.DataFrame({"symbol": ["508001"], "date": ["2026-01-01"]})

    result = build_fundamental_readiness(
        securities, fundamentals, distributions, prices
    ).set_index("symbol")

    assert result.loc["508001", "p_nav_status"] == (
        "data_available_pending_independent_review"
    )
    assert result.loc["508001", "dpu_yield_status"] == (
        "data_available_pending_independent_review"
    )
    assert result.loc["508002", "p_nav_status"] == "missing_nav"


def test_readiness_accepts_empty_fact_tables():
    securities = pd.DataFrame(
        {
            "symbol": ["508001"],
            "asset_type": ["toll_road"],
            "classification_status": ["human_verified"],
            "listing_status": ["listed"],
            "listing_date": ["2021-01-01"],
        }
    )
    fundamentals = pd.DataFrame(
        columns=["symbol", "period_end", "metric", "source_sha256"]
    )
    distributions = pd.DataFrame(columns=["symbol", "ex_date", "source_sha256"])
    prices = pd.DataFrame(columns=["symbol", "date"])

    result = build_fundamental_readiness(
        securities, fundamentals, distributions, prices
    )

    assert result.loc[0, "fundamental_panel_status"] == "missing_fundamentals"
    assert result.loc[0, "fundamental_observations"] == 0


def test_event_candidates_do_not_invent_effective_dates():
    catalog = pd.DataFrame(
        {
            "announcement_id": ["a", "b", "c", "d"],
            "symbol": ["508001", "508001", "508002", "508001"],
            "publication_date": [
                "2025-01-01",
                "2025-02-01",
                "2025-03-01",
                "2025-04-01",
            ],
            "title": [
                "关于拟扩募并新购入项目的公告",
                "提交产品变更暨扩募份额上市申请的公告",
                "普通季度报告",
                "扩募份额上市交易提示性公告",
            ],
            "source_url": [
                "https://sse/a",
                "https://sse/b",
                "https://sse/c",
                "https://sse/d",
            ],
        }
    )

    result = extract_fund_event_candidates(catalog)

    assert result["event_stage"].tolist() == [
        "proposal",
        "application_submitted",
        "expansion_units_listing_notice",
    ]
    assert result["effective_date"].eq("").all()
    assert result["event_date_semantics"].eq("announcement_publication_only").all()


def test_share_changes_preserve_first_reported_date_not_effective_date():
    fundamentals = pd.DataFrame(
        {
            "symbol": ["508001"] * 3,
            "period_end": ["2024-12-31", "2025-03-31", "2025-06-30"],
            "publication_date": ["2025-03-31", "2025-04-21", "2025-08-30"],
            "metric": ["fund_shares"] * 3,
            "value": [500_000_000, 500_000_000, 750_000_000],
            "source_url": ["a", "b", "c"],
            "source_sha256": ["a" * 64, "b" * 64, "c" * 64],
        }
    )
    candidates = pd.DataFrame({"symbol": ["508001"], "event_type": ["expansion"]})

    result = build_share_change_events(fundamentals, candidates)

    assert len(result) == 1
    assert result.loc[0, "share_change_ratio"] == 0.5
    assert result.loc[0, "effective_date_status"] == "unknown_between_reports"
    assert result.loc[0, "effective_date"] == ""


def test_frozen_readiness_outputs_preserve_review_boundaries():
    readiness = pd.read_csv(
        ROOT / "data/samples/reit_fundamental_readiness.csv", dtype={"symbol": str}
    )
    candidates = pd.read_csv(
        ROOT / "data/samples/reit_fund_event_candidates.csv", dtype={"symbol": str}
    )
    changes = pd.read_csv(
        ROOT / "data/samples/reit_share_change_events.csv", dtype={"symbol": str}
    )

    assert len(readiness) == readiness["symbol"].nunique() == 95
    assert readiness["fundamental_observations"].gt(0).sum() == 81
    assert (
        readiness["p_nav_status"].eq("data_available_pending_independent_review").sum()
        == 75
    )
    assert (
        readiness["dpu_yield_status"]
        .eq("data_available_pending_independent_review")
        .sum()
        == 67
    )
    assert len(candidates) == 225
    assert candidates["event_date_semantics"].eq("announcement_publication_only").all()
    assert candidates["effective_date"].isna().all()
    assert len(changes) == 10
    assert changes["effective_date_status"].eq("unknown_between_reports").all()
