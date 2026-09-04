import pandas as pd
import pytest

from creit_quant.market_factor_research import (
    DEFAULT_FULL_MARKET_COVERAGE_PATH,
    DEFAULT_FULL_MARKET_PRICE_PATH,
    build_market_factor_panel,
    build_market_signals,
    build_monthly_market_signals,
    build_phase2_data_gates,
    load_full_market_coverage,
    load_full_market_prices,
    run_market_factor_backtest,
    validate_full_market_snapshot,
)
from creit_quant.energy_research import DEFAULT_BENCHMARK_PRICE_PATH, load_market_snapshot
from creit_quant.master_data import load_universe_history


def _prices(symbols=("a", "b", "c", "d", "e"), periods=130):
    dates = pd.bdate_range("2024-01-02", periods=periods)
    rows = []
    for offset, symbol in enumerate(symbols):
        for number, day in enumerate(dates):
            rows.append(
                {
                    "symbol": symbol,
                    "date": day,
                    "close": 100 + number * (offset + 1) / 10,
                    "turnover": 2_000_000 + offset * 100_000,
                }
            )
    return pd.DataFrame(rows), dates


def test_market_factor_panel_is_lagged_and_tidy():
    prices, _ = _prices()
    panel = build_market_factor_panel(prices)
    sample = panel.loc[panel["symbol"].eq("a")].reset_index(drop=True)

    assert sample.loc[19, "average_turnover_20d"] == 2_000_000
    assert pd.isna(sample.loc[59, "momentum_60d"])
    assert sample.loc[60, "momentum_60d"] == pytest.approx(0.06)
    assert sample.loc[0, "listing_observation_days"] == 1
    assert sample.loc[0, "forward_return_20d"] == pytest.approx(0.02)


def test_monthly_signals_apply_listing_and_liquidity_rules():
    prices, _ = _prices()
    panel = build_market_factor_panel(prices)
    signals = build_monthly_market_signals(panel, minimum_history_days=80)

    assert signals["date"].dt.is_month_end.any() or len(signals) > 0
    assert signals["listing_observation_days"].ge(80).all()
    assert signals["average_turnover_20d"].ge(1_000_000).all()
    assert signals["market_composite"].between(0, 1).all()


def test_weekly_signals_have_more_rebalance_periods_than_monthly():
    prices, _ = _prices(periods=180)
    panel = build_market_factor_panel(prices)

    weekly = build_market_signals(panel, frequency="weekly")
    monthly = build_market_signals(panel, frequency="monthly")

    assert weekly["date"].nunique() > monthly["date"].nunique()
    assert weekly["rebalance_frequency"].eq("weekly").all()


def test_market_backtest_is_long_only_and_charges_commission():
    prices, dates = _prices(periods=180)
    panel = build_market_factor_panel(prices)
    signals = build_monthly_market_signals(panel, minimum_history_days=80)
    benchmark = pd.DataFrame({"date": dates, "close": range(1000, 1000 + len(dates))})

    summary, selections = run_market_factor_backtest(
        signals, prices, benchmark, cash_annual_yield=0
    )

    assert set(summary["factor"]) == {
        "momentum_20d",
        "momentum_60d",
        "short_term_reversal_5d",
        "liquidity_20d",
        "low_illiquidity_20d",
        "low_volatility_20d",
        "market_composite",
    }
    assert selections["selected_count"].eq(1).all()
    assert summary["commission_paid_rmb"].gt(0).all()
    assert selections["capacity_at_5pct_adv_rmb"].gt(0).all()


def test_signals_before_benchmark_start_are_not_collapsed_into_first_day():
    prices, dates = _prices(periods=180)
    signals = build_monthly_market_signals(
        build_market_factor_panel(prices), minimum_history_days=80
    )
    benchmark_dates = dates[130:]
    benchmark = pd.DataFrame(
        {"date": benchmark_dates, "close": range(1000, 1000 + len(benchmark_dates))}
    )

    summary, selections = run_market_factor_backtest(signals, prices, benchmark)

    assert selections["signal_date"].min() >= benchmark_dates.min()
    assert summary["rebalance_events"].max() == selections["signal_date"].nunique()


def test_data_gates_expose_current_universe_bias_and_valuation_gaps():
    history = pd.DataFrame(
        {"snapshot_date": ["2026-08-28"] * 2, "symbol": ["a", "b"]}
    )
    prices, _ = _prices(symbols=("a", "b"), periods=2)
    gates = build_phase2_data_gates(
        history,
        prices,
        verified_asset_type_count=1,
        verified_distribution_security_count=1,
    ).set_index("gate")

    assert gates.loc["current_universe_price_coverage", "status"] == "pass"
    assert gates.loc["historical_universe_snapshots", "status"] == "fail"
    assert gates.loc["point_in_time_nav_history", "observed"] == 0


def test_data_gates_accept_official_listing_date_membership_history():
    history = pd.DataFrame(
        {"snapshot_date": ["2026-08-28"] * 2, "symbol": ["a", "b"]}
    )
    membership = pd.DataFrame(
        {
            "snapshot_date": pd.date_range("2025-08-31", periods=12, freq="ME"),
            "symbol": ["a"] * 12,
        }
    )
    prices, _ = _prices(symbols=("a", "b"), periods=2)

    gates = build_phase2_data_gates(
        history,
        prices,
        verified_asset_type_count=1,
        verified_distribution_security_count=1,
        reconstructed_membership=membership,
    ).set_index("gate")

    assert gates.loc["historical_universe_snapshots", "status"] == "pass"


def test_unchanged_weekly_holdings_do_not_generate_rebalance_fees():
    prices, dates = _prices(periods=180)
    panel = build_market_factor_panel(prices)
    signals = build_market_signals(panel, frequency="weekly")
    benchmark = pd.DataFrame({"date": dates, "close": 1000})

    summary, _ = run_market_factor_backtest(
        signals, prices, benchmark, cash_annual_yield=0
    )

    liquidity = summary.set_index("factor").loc["liquidity_20d"]
    assert liquidity["commission_paid_rmb"] < 200


def test_frozen_full_market_snapshot_is_internally_consistent():
    prices = load_full_market_prices(DEFAULT_FULL_MARKET_PRICE_PATH)
    coverage = load_full_market_coverage(DEFAULT_FULL_MARKET_COVERAGE_PATH)
    universe = load_universe_history("data/snapshots/reit_universe_history.csv")

    validate_full_market_snapshot(prices, coverage, universe)

    assert len(prices) == 50_863
    assert prices["symbol"].nunique() == 88
    assert coverage["status"].value_counts().to_dict() == {
        "available": 88,
        "no_history": 6,
    }


def test_frozen_snapshot_reproduces_monthly_momentum_result():
    prices = load_full_market_prices(DEFAULT_FULL_MARKET_PRICE_PATH)
    benchmark = load_market_snapshot(DEFAULT_BENCHMARK_PRICE_PATH, kind="benchmark")
    signals = build_monthly_market_signals(build_market_factor_panel(prices))

    summary, _ = run_market_factor_backtest(signals, prices, benchmark)
    momentum = summary.set_index("factor").loc["momentum_20d"]

    assert momentum["total_return_pct"] == pytest.approx(16.3929, abs=1e-4)
    assert momentum["mean_rank_ic_20d"] == pytest.approx(0.0496, abs=1e-4)
    assert momentum["rank_ic_naive_t_stat"] == pytest.approx(1.0750, abs=1e-4)
    assert momentum["benchmark_932047_total_return_pct"] == pytest.approx(
        3.4532, abs=1e-4
    )
