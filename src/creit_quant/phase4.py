"""运行Phase 4基金时点数据库和固定联合纯多头模型。"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

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
    run_phase4_robustness,
    summarize_phase4_capacity,
)


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    """重建联合信号、净成本回测、容量结果及部署闸门。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--commission-rate", type=float, default=0.0001)
    parser.add_argument("--minimum-commission", type=float, default=5.0)
    parser.add_argument("--cash-yield", type=float, default=0.015)
    args = parser.parse_args()

    metrics, documents = load_default_operating_research_inputs()
    definitions = load_operating_feature_definitions()
    features = build_operating_point_in_time_features(metrics, documents, definitions)
    operating_signals = build_operating_cross_section_signals(features)
    fundamentals = load_fund_fundamentals()
    distributions = load_phase4_distributions()
    raw_prices = load_unadjusted_prices()
    prices = load_market_snapshot(DEFAULT_FULL_MARKET_PRICE_PATH, kind="security")
    prices = prices.loc[prices["symbol"].isin(definitions["symbol"])]
    benchmark = load_market_snapshot(DEFAULT_BENCHMARK_PRICE_PATH, kind="benchmark")
    signals = build_phase4_joint_signals(
        operating_signals, fundamentals, distributions, raw_prices
    )
    summary, events, daily = run_phase4_backtest(
        signals,
        prices,
        benchmark,
        initial_capital=args.capital,
        commission_rate=args.commission_rate,
        minimum_commission=args.minimum_commission,
        cash_annual_yield=args.cash_yield,
    )
    robustness = run_phase4_robustness(signals, prices, benchmark)
    capacity = summarize_phase4_capacity(signals, prices)
    exclusions = pd.read_csv(
        DEFAULT_DISTRIBUTION_EXCLUSIONS_PATH, dtype={"symbol": str}
    )
    universe = pd.read_csv(
        ROOT / "data" / "snapshots" / "reit_universe_history.csv", dtype={"symbol": str}
    )
    gates = build_phase4_gates(
        signals,
        fundamentals,
        distributions,
        universe_snapshots=pd.to_datetime(universe["snapshot_date"]).nunique(),
        distribution_exclusions=len(exclusions),
    )
    audit = audit_phase4_database(fundamentals, distributions)

    print(f"Phase 4数据库审计: {audit}")
    print(
        f"联合信号: {len(signals)}条，{signals['symbol'].nunique()}只证券，{signals['period_end'].nunique()}个横截面"
    )
    print("\n固定联合模型（收益率单位：%）")
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.3f}"))
    print("\n稳健性与单因子对照")
    print(robustness.to_string(index=False, float_format=lambda value: f"{value:.3f}"))
    print("\n数据与部署闸门")
    print(gates.to_string(index=False))
    print(
        "\n结论：Phase 4数据库和研究代码闭环完成，但不部署。"
        "扫描PDF缺口已完成视觉复核；历史universe、12期横截面及"
        "前瞻样本外季度仍未过闸门。"
    )

    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        signals.to_csv(args.out_dir / "phase4_joint_signals.csv", index=False)
        summary.to_csv(args.out_dir / "phase4_strategy_summary.csv", index=False)
        events.to_csv(args.out_dir / "phase4_strategy_events.csv", index=False)
        daily.to_csv(args.out_dir / "phase4_strategy_daily.csv", index=False)
        robustness.to_csv(args.out_dir / "phase4_strategy_robustness.csv", index=False)
        capacity.to_csv(args.out_dir / "phase4_capacity.csv", index=False)
        gates.to_csv(args.out_dir / "phase4_data_gates.csv", index=False)
        pd.DataFrame([audit]).to_csv(
            args.out_dir / "phase4_database_audit.csv", index=False
        )
        print(f"\n结果已保存: {args.out_dir}")


if __name__ == "__main__":
    main()
