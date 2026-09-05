from pathlib import Path

import pandas as pd

from creit_quant.full_market_unadjusted_prices import (
    _completed_symbols_for_window,
    fetch_unadjusted_symbols,
    merge_unadjusted_snapshot,
)
from creit_quant.market import MarketDataError

ROOT = Path(__file__).resolve().parents[1]


def test_fetch_unadjusted_symbols_keeps_failures_out_of_price_rows():
    def fetcher(symbol, start_date, end_date, *, adjust, timeout):
        assert adjust == ""
        if symbol == "508002":
            raise MarketDataError("returned no history")
        return pd.DataFrame(
            {
                "symbol": [symbol],
                "date": [pd.Timestamp("2025-01-01")],
                "close": [3.0],
            }
        )

    prices, coverage = fetch_unadjusted_symbols(
        ["508001", "508002"],
        "20250101",
        "20250131",
        "2025-01-31",
        fetcher=fetcher,
    )

    assert prices["symbol"].tolist() == ["508001"]
    assert prices["adjustment"].eq("none").all()
    assert coverage.set_index("symbol").loc["508002", "status"] == "no_history"


def test_merge_unadjusted_snapshot_replaces_only_retried_symbols():
    existing_prices = pd.DataFrame(
        {
            "symbol": ["508001", "508002"],
            "date": ["2025-01-01", "2025-01-01"],
            "adjustment": ["none", "none"],
            "close": [3.0, 4.0],
        }
    )
    existing_coverage = pd.DataFrame(
        {"symbol": ["508001", "508002"], "status": ["available", "network_failed"]}
    )
    fetched_prices = pd.DataFrame(
        {
            "symbol": ["508002"],
            "date": ["2025-01-02"],
            "adjustment": ["none"],
            "close": [4.1],
        }
    )
    fetched_coverage = pd.DataFrame({"symbol": ["508002"], "status": ["available"]})

    prices, coverage = merge_unadjusted_snapshot(
        existing_prices, existing_coverage, fetched_prices, fetched_coverage
    )

    assert len(prices) == 2
    assert prices.set_index("symbol").loc["508002", "close"] == 4.1
    assert coverage.set_index("symbol").loc["508001", "status"] == "available"


def test_network_failure_does_not_delete_frozen_history():
    existing_prices = pd.DataFrame(
        {
            "symbol": ["508001"],
            "date": ["2025-01-01"],
            "adjustment": ["none"],
            "close": [3.0],
        }
    )
    existing_coverage = pd.DataFrame({"symbol": ["508001"], "status": ["available"]})
    failed_coverage = pd.DataFrame({"symbol": ["508001"], "status": ["network_failed"]})

    prices, coverage = merge_unadjusted_snapshot(
        existing_prices, existing_coverage, pd.DataFrame(), failed_coverage
    )

    assert prices[["symbol", "close"]].to_dict("records") == [
        {"symbol": "508001", "close": 3.0}
    ]
    assert coverage.to_dict("records") == [{"symbol": "508001", "status": "available"}]


def test_changed_window_retries_available_and_no_history_symbols():
    coverage = pd.DataFrame(
        {
            "symbol": ["508001", "508002", "508003"],
            "status": ["available", "no_history", "network_failed"],
            "start_date": [20210621] * 3,
            "end_date": [20260902] * 3,
        }
    )

    assert _completed_symbols_for_window(coverage, "20210621", "20260902") == {
        "508001",
        "508002",
    }
    assert _completed_symbols_for_window(coverage, "20210621", "20261001") == set()


def test_frozen_full_market_snapshot_is_internally_consistent():
    prices = pd.read_csv(
        ROOT / "data/snapshots/full_market_unadjusted_prices.csv",
        dtype={"symbol": str},
    )
    coverage = pd.read_csv(
        ROOT / "data/snapshots/full_market_unadjusted_price_coverage.csv",
        dtype={"symbol": str},
    )

    assert len(coverage) == 94
    assert coverage["symbol"].nunique() == 94
    assert coverage["status"].value_counts().to_dict() == {
        "available": 88,
        "no_history": 6,
    }
    assert len(prices) == 50_863
    assert prices["symbol"].nunique() == 88
    assert not prices.duplicated(["symbol", "date"]).any()
    assert prices["adjustment"].eq("none").all()
    assert prices["close"].gt(0).all()
    assert int(coverage.loc[coverage["status"].eq("available"), "rows"].sum()) == len(
        prices
    )


def test_full_market_snapshot_matches_existing_phase4_overlap():
    full = pd.read_csv(
        ROOT / "data/snapshots/full_market_unadjusted_prices.csv",
        dtype={"symbol": str},
    )
    phase4 = pd.read_csv(
        ROOT / "data/snapshots/phase4_unadjusted_prices.csv", dtype={"symbol": str}
    )
    columns = ["symbol", "date", "open", "high", "low", "close", "volume"]
    overlap = phase4[columns].merge(
        full[columns], on=["symbol", "date"], suffixes=("_phase4", "_full")
    )

    assert len(overlap) == len(phase4) == 8_098
    assert overlap["symbol"].nunique() == 8
    for column in ["open", "high", "low", "close", "volume"]:
        pd.testing.assert_series_equal(
            overlap[f"{column}_phase4"],
            overlap[f"{column}_full"],
            check_names=False,
        )
