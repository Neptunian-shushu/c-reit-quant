import pandas as pd
import pytest

from creit_quant.energy_research import load_market_snapshot
from creit_quant.database import (
    DEFAULT_CROSS_DOCUMENTS_PATH,
    audit_asset_events,
    load_asset_events,
    load_assets,
    load_source_documents,
)
from creit_quant.operating_research import (
    DEFAULT_BENCHMARK_PRICE_PATH,
    DEFAULT_FULL_MARKET_PRICE_PATH,
    DEFAULT_PHASE3_EVENTS_PATH,
    DEFAULT_PHASE3_ASSETS_PATH,
    audit_phase3_non_energy_database,
    build_announcement_event_study,
    build_operating_cross_section_signals,
    build_operating_point_in_time_features,
    load_default_operating_research_inputs,
    load_operating_feature_definitions,
    run_operating_surprise_backtest,
    summarize_phase3_gates,
)


def _default_research_inputs():
    metrics, documents = load_default_operating_research_inputs()
    definitions = load_operating_feature_definitions()
    features = build_operating_point_in_time_features(metrics, documents, definitions)
    prices = load_market_snapshot(DEFAULT_FULL_MARKET_PRICE_PATH, kind="security")
    prices = prices.loc[prices["symbol"].isin(definitions["symbol"])]
    benchmark = load_market_snapshot(DEFAULT_BENCHMARK_PRICE_PATH, kind="benchmark")
    return definitions, features, prices, benchmark


def test_phase3_database_uses_explicit_stable_asset_scopes():
    definitions, features, _, _ = _default_research_inputs()

    assert len(definitions) == 8
    assert features["symbol"].nunique() == 8
    assert len(features) == 73
    salt_field = definitions.set_index("symbol").loc["180301", "asset_ids"]
    glp = definitions.set_index("symbol").loc["508056", "asset_ids"]
    assert salt_field == "modern_logistics_center"
    assert glp == "post_expansion_portfolio"
    assert features.loc[features["symbol"].eq("508056"), "period_end"].min() == pd.Timestamp(
        "2024-06-30"
    )

    audit = audit_phase3_non_energy_database()
    assert audit == {
        "securities": 4,
        "assets": 4,
        "observations": 110,
        "quarter_start": "2023Q1",
        "quarter_end": "2026Q2",
        "used_documents": 54,
        "human_verified_observations": 110,
    }


def test_phase3_asset_expansions_preserve_known_date_precision():
    events = load_asset_events(DEFAULT_PHASE3_EVENTS_PATH)
    audit = audit_asset_events(
        events,
        load_assets(DEFAULT_PHASE3_ASSETS_PATH),
        load_source_documents(DEFAULT_CROSS_DOCUMENTS_PATH),
    )

    assert audit == {"events": 2, "asset_level_events": 0, "symbol_level_events": 2}
    dates = events.set_index("symbol")["date_precision"].to_dict()
    assert dates == {"508056": "day", "180301": "quarter"}


def test_phase3_cross_section_is_long_only_and_waits_for_all_reports():
    _, features, _, _ = _default_research_inputs()
    signals = build_operating_cross_section_signals(features)

    assert signals["period_end"].nunique() == 8
    assert signals.groupby("period_end")["selected"].sum().eq(2).all()
    assert signals.groupby("period_end")["universe_count"].min().ge(6).all()
    assert (signals["decision_date"] >= signals["publication_date"]).all()


def test_announcement_event_study_enters_after_publication():
    _, features, prices, benchmark = _default_research_inputs()
    events = build_announcement_event_study(features, prices, benchmark)

    assert set(events["horizon_trading_days"]) == {20, 60}
    assert (events["entry_date"] > events["publication_date"]).all()
    assert (events["exit_date"] > events["entry_date"]).all()
    assert events[["return_pct", "benchmark_return_pct", "excess_return_pct"]].notna().all().all()


def test_phase3_snapshot_reproduces_research_baseline_and_blocks_deployment():
    _, features, prices, benchmark = _default_research_inputs()
    signals = build_operating_cross_section_signals(features)
    event_study = build_announcement_event_study(features, prices, benchmark)
    summary, events, daily = run_operating_surprise_backtest(
        signals, prices, benchmark
    )
    result = summary.set_index("portfolio")
    gates = summarize_phase3_gates(
        features, signals, event_study, historical_universe_snapshots=63
    )

    assert result.loc[
        "cross_asset_top_surprise_net", "total_return_pct"
    ] == pytest.approx(11.382873, abs=1e-6)
    assert result.loc[
        "eligible_reit_equal_weight_net", "total_return_pct"
    ] == pytest.approx(2.105948, abs=1e-6)
    assert result.loc[
        "reit_total_return_index_benchmark", "total_return_pct"
    ] == pytest.approx(0.681553, abs=1e-6)
    assert summary["cash_annual_yield_pct"].eq(1.5).all()
    assert summary["commission_rate_pct"].eq(0.01).all()
    assert not gates["deployable"].any()
    assert gates.set_index("gate").loc["historical_universe_snapshots", "passed"]
    assert events["selected"].sum() == 16
    assert daily["strategy_value"].gt(0).all()
