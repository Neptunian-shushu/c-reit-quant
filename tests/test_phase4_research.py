import pandas as pd
import pytest

from creit_quant.energy_research import load_market_snapshot
from creit_quant.operating_research import (
    DEFAULT_BENCHMARK_PRICE_PATH,
    DEFAULT_FULL_MARKET_PRICE_PATH,
    build_operating_cross_section_signals,
    build_operating_point_in_time_features,
    load_default_operating_research_inputs,
    load_operating_feature_definitions,
)
from creit_quant.phase4_research import (
    DEFAULT_DISTRIBUTION_EXCLUSIONS_PATH,
    audit_phase4_database,
    build_phase4_gates,
    build_phase4_joint_signals,
    load_fund_fundamentals,
    load_phase4_distributions,
    load_unadjusted_prices,
    run_phase4_backtest,
    summarize_phase4_capacity,
)


def _inputs():
    metrics, documents = load_default_operating_research_inputs()
    definitions = load_operating_feature_definitions()
    features = build_operating_point_in_time_features(metrics, documents, definitions)
    operating = build_operating_cross_section_signals(features)
    fundamentals = load_fund_fundamentals()
    distributions = load_phase4_distributions()
    raw_prices = load_unadjusted_prices()
    prices = load_market_snapshot(DEFAULT_FULL_MARKET_PRICE_PATH, kind="security")
    prices = prices.loc[prices["symbol"].isin(definitions["symbol"])]
    benchmark = load_market_snapshot(DEFAULT_BENCHMARK_PRICE_PATH, kind="benchmark")
    signals = build_phase4_joint_signals(
        operating, fundamentals, distributions, raw_prices
    )
    return fundamentals, distributions, prices, benchmark, signals


def test_phase4_database_has_real_pit_nav_shares_and_distributions():
    fundamentals, distributions, _, _, _ = _inputs()

    assert audit_phase4_database(fundamentals, distributions) == {
        "securities": 8,
        "quarterly_reports": 105,
        "fundamental_observations": 343,
        "nav_observations": 28,
        "nav_securities": 8,
        "distribution_events": 76,
        "distribution_securities": 8,
        "machine_extracted_observations": 413,
        "visual_verified_observations": 6,
        "human_verified_observations": 0,
    }
    assert (distributions["ex_date"] >= distributions["publication_date"]).all()
    assert (
        distributions["dpu_per_unit"] * 10 - distributions["disclosed_rmb_per_10_units"]
    ).abs().max() < 1e-12
    visual = distributions.loc[
        distributions["verification_status"].eq("visual_verified_official_pdf")
    ]
    assert len(visual) == 6
    assert visual["symbol"].eq("508028").all()
    assert pd.read_csv(DEFAULT_DISTRIBUTION_EXCLUSIONS_PATH).empty


def test_joint_signal_uses_only_information_known_by_decision_date():
    fundamentals, distributions, _, _, signals = _inputs()

    assert len(signals) == 60
    assert signals["period_end"].nunique() == 8
    assert signals.groupby("period_end")["selected"].sum().eq(2).all()
    assert signals.groupby("period_end")["phase4_universe_count"].min().ge(6).all()
    assert (signals["signal_price_date"] <= signals["decision_date"]).all()
    for row in signals.itertuples(index=False):
        known_nav = fundamentals.loc[
            fundamentals["symbol"].eq(row.symbol)
            & fundamentals["metric"].eq("nav_per_unit")
            & fundamentals["publication_date"].le(row.decision_date)
        ]
        known_dpu = distributions.loc[
            distributions["symbol"].eq(row.symbol)
            & distributions["publication_date"].le(row.decision_date)
            & distributions["ex_date"].le(row.decision_date)
        ]
        assert not known_nav.empty
        assert not known_dpu.empty


def test_phase4_backtest_reproduces_fixed_cost_baseline():
    _, _, prices, benchmark, signals = _inputs()
    summary, events, daily = run_phase4_backtest(signals, prices, benchmark)
    result = summary.set_index("portfolio")

    assert result.loc["phase4_joint_top2_net", "total_return_pct"] == pytest.approx(
        11.188920, abs=1e-6
    )
    assert result.loc[
        "phase4_eligible_equal_weight_net", "total_return_pct"
    ] == pytest.approx(2.105948, abs=1e-6)
    assert result.loc[
        "reit_total_return_index_benchmark", "total_return_pct"
    ] == pytest.approx(0.681553, abs=1e-6)
    assert summary["commission_rate_pct"].eq(0.01).all()
    assert summary["minimum_commission_rmb"].eq(5).all()
    assert summary["cash_annual_yield_pct"].eq(1.5).all()
    assert events["selected"].sum() == 16
    assert daily["strategy_value"].gt(0).all()


def test_phase4_capacity_and_gates_block_deployment():
    fundamentals, distributions, prices, _, signals = _inputs()
    capacity = summarize_phase4_capacity(signals, prices)
    gates = build_phase4_gates(
        signals,
        fundamentals,
        distributions,
        universe_snapshots=1,
        distribution_exclusions=0,
    )

    assert len(capacity) == 8
    assert capacity["capacity_at_5pct_adv_rmb"].min() == pytest.approx(416093.386455)
    assert gates.set_index("gate").loc["point_in_time_nav_securities", "passed"]
    assert gates.set_index("gate").loc["distribution_extraction_exclusions", "passed"]
    assert not gates.set_index("gate").loc["historical_universe_snapshots", "passed"]
    assert not gates.set_index("gate").loc[
        "prospective_out_of_sample_quarters", "passed"
    ]
    assert not gates["deployable"].any()


def test_fundamental_loader_rejects_bad_units(tmp_path):
    frame = load_fund_fundamentals().head(1).copy()
    frame.loc[:, "unit"] = "percent"
    path = tmp_path / "bad.csv"
    frame.to_csv(path, index=False)

    with pytest.raises(ValueError, match="单位"):
        load_fund_fundamentals(path)
