import pandas as pd
import pytest

from creit_quant.strategy import (
    build_generation_signals,
    load_distributions,
    run_generation_long_only_backtest,
)


def _metrics() -> pd.DataFrame:
    rows = []
    generations = [100.0, 120.0, 90.0, 80.0, 110.0, 100.0]
    periods = pd.date_range("2024-03-31", periods=6, freq="QE")
    for period, generation in zip(periods, generations, strict=True):
        rows.extend(
            {
                "symbol": "508026",
                "asset_id": "asset",
                "period_end": period,
                "metric": metric,
                "value": value,
                "publication_date": period + pd.Timedelta(days=20),
            }
            for metric, value in {
                "power_generation": generation,
                "utilization_hours": 1.0,
                "settled_electricity": 1.0,
                "settlement_tariff_excl_tax": 1.0,
            }.items()
        )
    return pd.DataFrame(rows)


def test_generation_signal_uses_four_quarter_yoy():
    signals = build_generation_signals(_metrics())

    assert len(signals) == 2
    assert signals["hold_reit"].tolist() == [True, False]
    assert signals["signal"].tolist() == ["reit", "cash"]
    assert signals["generation_yoy_pct"].round(2).tolist() == [10.0, -16.67]


def test_backtest_enters_after_publication_and_charges_switch_cost():
    dates = pd.to_datetime(["2025-04-21", "2025-04-22", "2025-04-23", "2025-07-21", "2025-07-22", "2025-07-23"])
    reit = pd.DataFrame({"date": dates, "close": [100, 100, 100, 110, 110, 99]})
    benchmark = pd.DataFrame({"date": dates, "close": [100, 100, 100, 100, 100, 110]})

    summary, events, daily = run_generation_long_only_backtest(
        _metrics(),
        reit,
        benchmark,
        initial_capital=1_000,
        commission_rate=0.001,
        minimum_commission=5,
        cash_annual_yield=0.0,
    )

    assert events["entry_date"].tolist() == [pd.Timestamp("2025-04-21"), pd.Timestamp("2025-07-21")]
    assert daily.loc[daily["date"].eq(pd.Timestamp("2025-07-21")), "trade_orders"].item() == 1
    assert summary.loc[0, "signal_events"] == 2
    assert daily.iloc[0]["strategy_return"] == pytest.approx(-0.005)
    assert daily.loc[daily["date"].eq(pd.Timestamp("2025-07-22")), "gross_return"].item() == 0.0


def test_cash_distribution_is_included_in_reit_total_return(tmp_path):
    path = tmp_path / "distributions.csv"
    path.write_text(
        "symbol,ex_date,cash_per_unit,source_url\n"
        "508026,2025-04-22,5.0,https://example.test/report.pdf\n",
        encoding="utf-8",
    )
    distributions = load_distributions(path)
    dates = pd.to_datetime(["2025-04-21", "2025-04-22", "2025-04-23", "2025-07-21"])
    reit = pd.DataFrame({"date": dates, "close": [100.0, 95.0, 95.0, 95.0]})
    benchmark = pd.DataFrame({"date": dates, "close": [100.0, 100.0, 100.0, 100.0]})

    _, _, daily = run_generation_long_only_backtest(
        _metrics(), reit, benchmark, distributions=distributions
    )

    ex_date_return = daily.loc[daily["date"].eq(pd.Timestamp("2025-04-22")), "reit_return"].item()
    assert ex_date_return == pytest.approx(0.0)


def test_cash_position_earns_configured_annual_yield():
    dates = pd.to_datetime(["2025-04-21", "2025-07-21", "2025-07-22", "2025-07-23"])
    reit = pd.DataFrame({"date": dates, "close": [100.0, 100.0, 100.0, 100.0]})
    benchmark = pd.DataFrame({"date": dates, "close": [100.0, 100.0, 100.0, 100.0]})

    _, events, daily = run_generation_long_only_backtest(
        _metrics(),
        reit,
        benchmark,
        commission_rate=0.0,
        minimum_commission=0.0,
        cash_annual_yield=0.015,
    )

    expected_daily = (1.015 ** (1 / 252)) - 1
    cash_day = daily.loc[daily["date"].eq(pd.Timestamp("2025-07-22"))]
    assert cash_day["gross_return"].item() == pytest.approx(expected_daily)
    assert events.iloc[1]["selected_return_pct"] > 0
