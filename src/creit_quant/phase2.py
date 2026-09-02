"""运行能源REIT point-in-time经营surprise横截面研究。"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

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
from creit_quant.market import (
    MarketDataError,
    fetch_csindex_history,
    fetch_reit_adjusted_history,
)


def _fetch_market_snapshots(
    symbols: list[str], start_date: str, end_date: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    retrieved_at = pd.Timestamp.now(tz="Asia/Shanghai").isoformat()
    histories = []
    for symbol in symbols:
        history = fetch_reit_adjusted_history(
            symbol, start_date, end_date, adjust="hfq"
        )[["symbol", "date", "close"]]
        history["adjustment"] = "hfq"
        history["source"] = "东方财富push2his（AKShare包装或直接fallback）"
        history["retrieved_at"] = retrieved_at
        histories.append(history)
    securities = pd.concat(histories, ignore_index=True)
    benchmark = fetch_csindex_history("932047", start_date, end_date)[
        ["date", "close"]
    ]
    benchmark.insert(0, "symbol", "932047")
    benchmark["index_kind"] = "total_return"
    benchmark["source"] = "中证指数官网"
    benchmark["retrieved_at"] = retrieved_at
    return securities, benchmark


def main() -> None:
    """构建特征；按需更新市场快照后运行纯多头事件回测。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-market", action="store_true", help="联网重建行情快照")
    parser.add_argument(
        "--replace-market-snapshot",
        action="store_true",
        help="显式允许覆盖已经存在的行情研究快照",
    )
    parser.add_argument("--start-date", default="20240320", help="行情起始日YYYYMMDD")
    parser.add_argument("--end-date", default=date.today().strftime("%Y%m%d"))
    parser.add_argument(
        "--price-out", default=str(DEFAULT_ENERGY_PRICE_PATH), help="能源REIT行情快照"
    )
    parser.add_argument(
        "--benchmark-out",
        default=str(DEFAULT_BENCHMARK_PRICE_PATH),
        help="932047全收益基准快照",
    )
    parser.add_argument("--out-dir", default=None, help="可选研究结果输出目录")
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--commission-rate", type=float, default=0.0001)
    parser.add_argument("--minimum-commission", type=float, default=5.0)
    parser.add_argument("--cash-yield", type=float, default=0.015)
    args = parser.parse_args()

    metrics, documents = load_default_energy_research_inputs()
    definitions = load_energy_feature_definitions()
    features = build_energy_point_in_time_features(metrics, documents, definitions)
    signals = build_energy_cross_section_signals(features)
    print(
        f"能源PIT特征: {len(features)}条，{features['symbol'].nunique()}只证券；"
        f"可用横截面: {signals['period_end'].nunique()}个季度"
    )

    price_path = Path(args.price_out)
    benchmark_path = Path(args.benchmark_out)
    if args.fetch_market:
        existing = [path for path in [price_path, benchmark_path] if path.exists()]
        if existing and not args.replace_market_snapshot:
            names = ", ".join(str(path) for path in existing)
            raise SystemExit(
                f"市场快照已存在且不会静默覆盖：{names}；"
                "请改用其他输出路径或显式指定--replace-market-snapshot"
            )
        try:
            securities, benchmark = _fetch_market_snapshots(
                definitions["symbol"].tolist(), args.start_date, args.end_date
            )
        except MarketDataError as exc:
            raise SystemExit(f"市场快照更新失败；没有覆盖原文件：{exc}") from exc
        price_path.parent.mkdir(parents=True, exist_ok=True)
        benchmark_path.parent.mkdir(parents=True, exist_ok=True)
        price_temporary = price_path.with_suffix(price_path.suffix + ".tmp")
        benchmark_temporary = benchmark_path.with_suffix(
            benchmark_path.suffix + ".tmp"
        )
        securities.to_csv(price_temporary, index=False)
        benchmark.to_csv(benchmark_temporary, index=False)
        price_temporary.replace(price_path)
        benchmark_temporary.replace(benchmark_path)
        print(f"市场快照已保存: {price_path} / {benchmark_path}")

    if not price_path.exists() or not benchmark_path.exists():
        print("尚无本地价格快照；使用--fetch-market联网构建后才能运行收益检验。")
        return
    securities = load_market_snapshot(price_path, kind="security")
    benchmark = load_market_snapshot(benchmark_path, kind="benchmark")
    summary, events, daily = run_energy_surprise_backtest(
        signals,
        securities,
        benchmark,
        initial_capital=args.capital,
        commission_rate=args.commission_rate,
        minimum_commission=args.minimum_commission,
        cash_annual_yield=args.cash_yield,
    )
    print("\nPhase 2能源横截面基线（收益率单位：%）")
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.2f}"))
    print("\n每期最高surprise证券")
    selected = events.loc[events["selected"]]
    print(
        selected[
            [
                "period_end",
                "decision_date",
                "entry_date",
                "symbol",
                "operating_surprise_pct",
                "forward_return_pct",
                "forward_excess_return_pct",
            ]
        ].to_string(index=False, float_format=lambda value: f"{value:.2f}")
    )
    print(
        f"\n警告：仅{summary['rebalance_events'].iloc[0]}个季度横截面；"
        "rank IC使用固定20交易日前瞻收益，"
        "结果只用于验证研究链路，不构成稳健alpha证据。"
    )
    if args.out_dir:
        output = Path(args.out_dir)
        output.mkdir(parents=True, exist_ok=True)
        features.to_csv(output / "energy_point_in_time_features.csv", index=False)
        signals.to_csv(output / "energy_cross_section_signals.csv", index=False)
        summary.to_csv(output / "summary.csv", index=False)
        events.to_csv(output / "events.csv", index=False)
        daily.to_csv(output / "daily.csv", index=False)
        print(f"研究结果已保存: {output}")


if __name__ == "__main__":
    main()
