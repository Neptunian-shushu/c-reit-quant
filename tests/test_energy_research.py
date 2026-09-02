import pandas as pd
import pytest

from creit_quant.energy_research import (
    DEFAULT_BENCHMARK_PRICE_PATH,
    DEFAULT_ENERGY_PRICE_PATH,
    build_energy_cross_section_signals,
    build_energy_point_in_time_features,
    load_default_energy_research_inputs,
    load_energy_feature_definitions,
    load_market_snapshot,
    run_energy_surprise_backtest,
)


def test_default_energy_features_have_stable_scopes_and_pit_lineage():
    metrics, documents = load_default_energy_research_inputs()
    features = build_energy_point_in_time_features(
        metrics, documents, load_energy_feature_definitions()
    )

    assert len(features) == 35
    assert features.groupby("symbol").size().to_dict() == {
        "180401": 12,
        "508026": 5,
        "508028": 9,
        "508096": 9,
    }
    solar = features.loc[features["symbol"].eq("508096")]
    assert solar["asset_ids"].eq("hubei_jingtai_pv|yulin_pv").all()
    assert solar["asset_count"].eq(2).all()
    assert features["current_observation_ids"].str.len().gt(0).all()
    assert features["lag_observation_ids"].str.len().gt(0).all()
    assert features["lineage_quality_status"].value_counts().to_dict() == {
        "contains_unverified_source_registry": 30,
        "verified": 5,
    }


def test_point_in_time_feature_does_not_use_later_revision():
    metrics = pd.DataFrame(
        [
            ["123456", "asset", "2023-03-31", "power_generation", 100, "u", "2023-04-20", "u1"],
            ["123456", "asset", "2023-03-31", "power_generation", 110, "u", "2024-03-01", "u2"],
            ["123456", "asset", "2023-03-31", "power_generation", 120, "u", "2024-05-01", "u3"],
            ["123456", "asset", "2024-03-31", "power_generation", 220, "u", "2024-04-20", "u4"],
        ],
        columns=[
            "symbol",
            "asset_id",
            "period_end",
            "metric",
            "value",
            "unit",
            "publication_date",
            "source_url",
        ],
    )
    metrics[["period_end", "publication_date"]] = metrics[
        ["period_end", "publication_date"]
    ].apply(pd.to_datetime)
    documents = pd.DataFrame(
        {
            "document_id": ["d1", "d2", "d3", "d4"],
            "source_url": ["u1", "u2", "u3", "u4"],
            "verification_status": ["human_verified"] * 4,
        }
    )
    definitions = pd.DataFrame(
        {
            "symbol": ["123456"],
            "feature_id": ["feature"],
            "metric": ["power_generation"],
            "aggregation": ["sum"],
            "asset_ids": ["asset"],
            "comparison_lag_quarters": [4],
            "source_note": ["test"],
        }
    )

    result = build_energy_point_in_time_features(metrics, documents, definitions)

    assert len(result) == 1
    assert result.loc[0, "lag_value_as_of_publication"] == 110
    assert result.loc[0, "operating_yoy_pct"] == pytest.approx(100.0)
    assert "d2" in result.loc[0, "lag_observation_ids"]
    assert "d3" not in result.loc[0, "lag_observation_ids"]


def test_default_cross_section_waits_for_all_reports_and_is_long_only():
    metrics, documents = load_default_energy_research_inputs()
    features = build_energy_point_in_time_features(
        metrics, documents, load_energy_feature_definitions()
    )
    signals = build_energy_cross_section_signals(features)

    assert signals["period_end"].nunique() == 8
    assert len(signals) == 28
    assert signals.groupby("period_end")["selected"].sum().eq(1).all()
    assert (signals["decision_date"] >= signals["publication_date"]).all()
    assert signals["signal_rank"].ge(1).all()


def test_energy_backtest_charges_each_buy_and_sell_order():
    signal_rows = []
    for period, decision, selected in [
        ("2023-12-31", "2024-01-01", "a"),
        ("2024-03-31", "2024-01-03", "b"),
    ]:
        for rank, symbol in enumerate([selected, "c", "b" if selected == "a" else "a"], 1):
            signal_rows.append(
                {
                    "period_end": pd.Timestamp(period),
                    "decision_date": pd.Timestamp(decision),
                    "symbol": symbol,
                    "selected": rank == 1,
                    "operating_surprise_pct": 4 - rank,
                }
            )
    signals = pd.DataFrame(signal_rows)
    dates = pd.date_range("2024-01-02", "2024-01-05", freq="D")
    closes = {
        "a": [100, 110, 110, 110],
        "b": [100, 100, 100, 110],
        "c": [100, 100, 100, 100],
    }
    prices = pd.DataFrame(
        [
            {"symbol": symbol, "date": day, "close": values[index]}
            for symbol, values in closes.items()
            for index, day in enumerate(dates)
        ]
    )
    benchmark = pd.DataFrame({"date": dates, "close": [100, 100, 100, 100]})

    summary, events, daily = run_energy_surprise_backtest(
        signals, prices, benchmark, cash_annual_yield=0, forward_horizon_days=1
    )

    strategy = summary.set_index("portfolio").loc["top_operating_surprise_net"]
    assert strategy["commission_paid_rmb"] == pytest.approx(31.9978)
    assert strategy["total_return_pct"] > 20
    assert events["entry_date"].min() == pd.Timestamp("2024-01-02")
    assert daily["strategy_value"].gt(0).all()


def test_default_phase2_snapshot_reproduces_baseline_result():
    metrics, documents = load_default_energy_research_inputs()
    features = build_energy_point_in_time_features(
        metrics, documents, load_energy_feature_definitions()
    )
    signals = build_energy_cross_section_signals(features)
    prices = load_market_snapshot(DEFAULT_ENERGY_PRICE_PATH, kind="security")
    benchmark = load_market_snapshot(DEFAULT_BENCHMARK_PRICE_PATH, kind="benchmark")

    summary, events, daily = run_energy_surprise_backtest(
        signals, prices, benchmark
    )
    result = summary.set_index("portfolio")

    assert len(prices) == 2381
    assert len(benchmark) == 597
    assert result.loc["top_operating_surprise_net", "total_return_pct"] == pytest.approx(
        -5.014157
    )
    assert result.loc["energy_equal_weight_net", "total_return_pct"] == pytest.approx(
        4.531357
    )
    assert result.loc[
        "reit_total_return_index_benchmark", "total_return_pct"
    ] == pytest.approx(0.681553)
    assert result["mean_rank_ic"].tolist() == pytest.approx([-0.4875] * 3)
    assert events["forward_return_pct"].notna().all()
    assert daily["date"].min() == pd.Timestamp("2024-10-28")
