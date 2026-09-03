"""运行Phase 3跨资产经营预期与公告事件研究。"""

from __future__ import annotations

import argparse
from pathlib import Path

from creit_quant.energy_research import load_market_snapshot
from creit_quant.operating_research import (
    DEFAULT_BENCHMARK_PRICE_PATH,
    DEFAULT_FULL_MARKET_PRICE_PATH,
    audit_phase3_non_energy_database,
    build_announcement_event_study,
    build_operating_cross_section_signals,
    build_operating_point_in_time_features,
    load_default_operating_research_inputs,
    load_operating_feature_definitions,
    run_phase3_robustness,
    run_operating_surprise_backtest,
    summarize_announcement_event_study,
    summarize_phase3_gates,
)


def main() -> None:
    """构建PIT特征，执行事件研究与纯多头回测并保存可复现结果。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=None, help="可选结果输出目录")
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--commission-rate", type=float, default=0.0001)
    parser.add_argument("--minimum-commission", type=float, default=5.0)
    parser.add_argument("--cash-yield", type=float, default=0.015)
    args = parser.parse_args()

    database_audit = audit_phase3_non_energy_database()
    metrics, documents = load_default_operating_research_inputs()
    definitions = load_operating_feature_definitions()
    features = build_operating_point_in_time_features(metrics, documents, definitions)
    signals = build_operating_cross_section_signals(features)
    prices = load_market_snapshot(DEFAULT_FULL_MARKET_PRICE_PATH, kind="security")
    benchmark = load_market_snapshot(DEFAULT_BENCHMARK_PRICE_PATH, kind="benchmark")
    selected_prices = prices.loc[prices["symbol"].isin(definitions["symbol"])]
    event_study = build_announcement_event_study(features, selected_prices, benchmark)
    event_summary = summarize_announcement_event_study(event_study)
    summary, events, daily = run_operating_surprise_backtest(
        signals,
        selected_prices,
        benchmark,
        initial_capital=args.capital,
        commission_rate=args.commission_rate,
        minimum_commission=args.minimum_commission,
        cash_annual_yield=args.cash_yield,
    )
    gates = summarize_phase3_gates(features, signals, event_study)
    robustness = run_phase3_robustness(features, selected_prices, benchmark)

    print(
        f"Phase 3 PIT特征: {len(features)}条，{features['symbol'].nunique()}只证券，"
        f"{features['asset_type'].nunique()}类资产；横截面{signals['period_end'].nunique()}期"
    )
    print(f"新增非能源数据库审计: {database_audit}")
    print("\n纯多头组合（收益率单位：%）")
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.2f}"))
    print("\n数据与部署闸门")
    print(gates.to_string(index=False))
    print("\n公告事件研究")
    print(event_summary.to_string(index=False, float_format=lambda value: f"{value:.3f}"))
    print("\n稳健性检验")
    print(robustness.to_string(index=False, float_format=lambda value: f"{value:.2f}"))
    print(
        "\n结论：该结果是研究样本，不是可部署策略。历史universe、横截面期数和"
        "分派/NAV覆盖仍未通过部署闸门。"
    )

    if args.out_dir:
        output = Path(args.out_dir)
        output.mkdir(parents=True, exist_ok=True)
        features.to_csv(output / "phase3_operating_point_in_time_features.csv", index=False)
        signals.to_csv(output / "phase3_operating_cross_section_signals.csv", index=False)
        event_study.to_csv(output / "phase3_announcement_event_study.csv", index=False)
        event_summary.to_csv(output / "phase3_announcement_event_summary.csv", index=False)
        summary.to_csv(output / "phase3_strategy_summary.csv", index=False)
        events.to_csv(output / "phase3_strategy_events.csv", index=False)
        daily.to_csv(output / "phase3_strategy_daily.csv", index=False)
        gates.to_csv(output / "phase3_data_gates.csv", index=False)
        robustness.to_csv(output / "phase3_strategy_robustness.csv", index=False)
        print(f"研究结果已保存: {output}")


if __name__ == "__main__":
    main()
