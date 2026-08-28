"""运行 508026 发电量披露事件策略的探索性回测。"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from creit_quant.hydropower import load_hydropower_metrics
from creit_quant.market import (
    MarketDataError,
    fetch_csindex_history,
    fetch_reit_adjusted_history,
    fetch_reit_history_sina,
)
from creit_quant.strategy import load_distributions, run_generation_long_only_backtest


def main() -> None:
    """联网获取真实行情并输出策略、事件及日频结果。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end-date", default=date.today().strftime("%Y%m%d"))
    parser.add_argument("--capital", type=float, default=100_000.0, help="初始资金，单位元")
    parser.add_argument(
        "--commission-rate", type=float, default=0.0001, help="单边券商佣金率，0.0001 表示万一"
    )
    parser.add_argument("--minimum-commission", type=float, default=5.0, help="每笔最低佣金，单位元")
    parser.add_argument(
        "--cash-yield",
        type=float,
        default=0.015,
        help="现金年化收益率，0.015 表示 1.5%%",
    )
    parser.add_argument("--out-dir", default=None, help="可选结果目录")
    args = parser.parse_args()

    metrics = load_hydropower_metrics()
    distributions = None
    try:
        reit = fetch_reit_adjusted_history("508026", "20240328", args.end_date, adjust="hfq")
        reit_source = "AKShare/东方财富后复权"
    except MarketDataError as exc:
        print("东方财富复权行情不可用，切换 AKShare/新浪并显式加入现金分派。")
        reit = fetch_reit_history_sina("508026", "20240328", args.end_date)
        distributions = load_distributions()
        reit_source = "AKShare/新浪不复权 + 正式现金分派"
    benchmark = fetch_csindex_history("932047", "20240328", args.end_date)
    summary, events, daily = run_generation_long_only_backtest(
        metrics,
        reit,
        benchmark,
        initial_capital=args.capital,
        commission_rate=args.commission_rate,
        minimum_commission=args.minimum_commission,
        cash_annual_yield=args.cash_yield,
        distributions=distributions,
    )
    summary["reit_price_source"] = reit_source
    summary["benchmark_source"] = "中证指数官网 932047"

    print("\n探索性策略汇总（收益率单位：%）")
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.2f}"))
    print("\n信号事件")
    columns = [
        "period_end",
        "publication_date",
        "entry_date",
        "generation_yoy_pct",
        "signal",
        "selected_return_pct",
        "reit_return_pct",
        "benchmark_return_pct",
        "reit_excess_return_pct",
    ]
    print(events[columns].to_string(index=False, float_format=lambda value: f"{value:.2f}"))
    event_count = int(summary["signal_events"].iloc[0])
    print(f"\n警告：仅 {event_count} 个同比信号事件，结果不构成稳健 alpha 证据。")

    if args.out_dir:
        output = Path(args.out_dir)
        output.mkdir(parents=True, exist_ok=True)
        summary.to_csv(output / "summary.csv", index=False)
        events.to_csv(output / "events.csv", index=False)
        daily.to_csv(output / "daily.csv", index=False)
        print(f"结果已保存至: {output}")


if __name__ == "__main__":
    main()
