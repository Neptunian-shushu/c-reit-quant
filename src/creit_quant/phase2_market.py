"""运行Phase 2B全市场价格与流动性因子研究。"""

from __future__ import annotations

import argparse
import time
from datetime import date
from pathlib import Path

import pandas as pd

from creit_quant.energy_research import DEFAULT_BENCHMARK_PRICE_PATH, load_market_snapshot
from creit_quant.market import MarketDataError, fetch_reit_adjusted_history_direct
from creit_quant.market_factor_research import (
    DEFAULT_FULL_MARKET_PRICE_PATH,
    DEFAULT_FULL_MARKET_COVERAGE_PATH,
    DEFAULT_UNIVERSE_HISTORY_PATH,
    build_market_factor_panel,
    build_market_signals,
    build_phase2_data_gates,
    load_full_market_prices,
    load_full_market_coverage,
    run_market_factor_backtest,
    validate_full_market_snapshot,
)
from creit_quant.master_data import load_security_overrides, load_universe_history
from creit_quant.strategy import load_distributions

ROOT = Path(__file__).resolve().parents[2]


def _fetch_full_market_snapshot(
    symbols: list[str],
    start_date: str,
    end_date: str,
    universe_snapshot_date: pd.Timestamp,
    *,
    maximum_attempts: int = 4,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    retrieved_at = pd.Timestamp.now(tz="Asia/Shanghai").isoformat()
    histories = []
    failures = []
    coverage_rows = []
    for number, symbol in enumerate(symbols, 1):
        history = None
        error = None
        attempts = 0
        for attempts in range(1, maximum_attempts + 1):
            try:
                history = fetch_reit_adjusted_history_direct(
                    symbol, start_date, end_date, adjust="hfq"
                )
                break
            except MarketDataError as exc:
                error = exc
                if "returned no history" in str(exc):
                    break
                if attempts < maximum_attempts:
                    time.sleep(min(2 ** (attempts - 1), 4))
        if history is None:
            no_history = error is not None and "returned no history" in str(error)
            coverage_rows.append(
                {
                    "symbol": symbol,
                    "status": "no_history" if no_history else "network_failed",
                    "rows": 0,
                    "first_date": pd.NaT,
                    "last_date": pd.NaT,
                    "attempts": attempts,
                    "error": str(error),
                    "retrieved_at": retrieved_at,
                    "universe_snapshot_date": universe_snapshot_date,
                }
            )
            if not no_history:
                failures.append(f"{symbol}: {error}")
            print(f"[{number}/{len(symbols)}] {symbol}: {'无历史' if no_history else '网络失败'}")
            continue
        history["adjustment"] = "hfq"
        history["source"] = "东方财富push2his直接接口"
        history["retrieved_at"] = retrieved_at
        history["universe_snapshot_date"] = universe_snapshot_date
        histories.append(history)
        coverage_rows.append(
            {
                "symbol": symbol,
                "status": "available",
                "rows": len(history),
                "first_date": history["date"].min(),
                "last_date": history["date"].max(),
                "attempts": attempts,
                "error": "",
                "retrieved_at": retrieved_at,
                "universe_snapshot_date": universe_snapshot_date,
            }
        )
        print(f"[{number}/{len(symbols)}] {symbol}: {len(history)}行")
    if failures:
        raise MarketDataError("全市场抓取不完整，拒绝写入：" + " | ".join(failures))
    return pd.concat(histories, ignore_index=True), pd.DataFrame(coverage_rows)


def main() -> None:
    """按需冻结全市场行情，并离线生成因子、回测与数据闸门。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-market", action="store_true", help="联网重建全市场行情")
    parser.add_argument("--replace-market-snapshot", action="store_true", help="允许覆盖已有快照")
    parser.add_argument("--start-date", default="20210621")
    parser.add_argument("--end-date", default=date.today().strftime("%Y%m%d"))
    parser.add_argument("--price-out", default=str(DEFAULT_FULL_MARKET_PRICE_PATH))
    parser.add_argument(
        "--coverage-out",
        default=str(DEFAULT_FULL_MARKET_COVERAGE_PATH),
    )
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()

    universe_history = load_universe_history(DEFAULT_UNIVERSE_HISTORY_PATH)
    latest_date = universe_history["snapshot_date"].max()
    symbols = sorted(
        universe_history.loc[universe_history["snapshot_date"].eq(latest_date), "symbol"].unique()
    )
    price_path = Path(args.price_out)
    coverage_path = Path(args.coverage_out)
    if args.fetch_market:
        existing = [path for path in [price_path, coverage_path] if path.exists()]
        if existing and not args.replace_market_snapshot:
            names = ", ".join(str(path) for path in existing)
            raise SystemExit(
                f"全市场行情文件已存在：{names}；请改输出路径或显式允许覆盖"
            )
        try:
            prices, coverage = _fetch_full_market_snapshot(
                symbols, args.start_date, args.end_date, latest_date
            )
        except MarketDataError as exc:
            raise SystemExit(f"更新失败，原文件未被覆盖：{exc}") from exc
        price_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = price_path.with_suffix(price_path.suffix + ".tmp")
        coverage_path.parent.mkdir(parents=True, exist_ok=True)
        coverage_temporary = coverage_path.with_suffix(coverage_path.suffix + ".tmp")
        prices.to_csv(temporary, index=False)
        coverage.to_csv(coverage_temporary, index=False)
        temporary.replace(price_path)
        coverage_temporary.replace(coverage_path)
        print(
            f"已保存全市场行情：{price_path}，{len(prices)}行；"
            f"覆盖状态：{coverage_path}"
        )
    if not price_path.exists():
        raise SystemExit("尚无全市场行情快照；先使用--fetch-market")

    prices = load_full_market_prices(price_path)
    coverage = load_full_market_coverage(args.coverage_out)
    validate_full_market_snapshot(prices, coverage, universe_history)
    benchmark = load_market_snapshot(DEFAULT_BENCHMARK_PRICE_PATH, kind="benchmark")
    panel = build_market_factor_panel(prices)
    signal_frames = []
    summary_frames = []
    selection_frames = []
    robustness_frames = []
    for frequency in ["monthly", "weekly"]:
        frequency_signals = build_market_signals(panel, frequency=frequency)
        frequency_summary, frequency_selections = run_market_factor_backtest(
            frequency_signals, prices, benchmark
        )
        frequency_summary.insert(0, "rebalance_frequency", frequency)
        frequency_selections.insert(0, "rebalance_frequency", frequency)
        signal_frames.append(frequency_signals)
        summary_frames.append(frequency_summary)
        selection_frames.append(frequency_selections)
        for top_fraction in [0.1, 0.2, 0.3]:
            for minimum_commission in [0.0, 5.0]:
                robustness, _ = run_market_factor_backtest(
                    frequency_signals,
                    prices,
                    benchmark,
                    top_fraction=top_fraction,
                    minimum_commission=minimum_commission,
                )
                robustness = robustness.loc[
                    robustness["factor"].eq("momentum_20d")
                ].copy()
                robustness.insert(0, "minimum_commission_rmb", minimum_commission)
                robustness.insert(0, "top_fraction", top_fraction)
                robustness.insert(0, "rebalance_frequency", frequency)
                robustness_frames.append(robustness)
    signals = pd.concat(signal_frames, ignore_index=True)
    summary = pd.concat(summary_frames, ignore_index=True)
    selections = pd.concat(selection_frames, ignore_index=True)
    robustness = pd.concat(robustness_frames, ignore_index=True)
    distributions = load_distributions()
    membership_path = ROOT / "data" / "samples" / "reit_tradable_universe_monthly.csv"
    reconstructed_membership = (
        pd.read_csv(membership_path, dtype={"symbol": str})
        if membership_path.exists()
        else None
    )
    gates = build_phase2_data_gates(
        universe_history,
        prices,
        verified_asset_type_count=len(load_security_overrides()),
        verified_distribution_security_count=distributions["symbol"].nunique(),
        reconstructed_membership=reconstructed_membership,
    )
    print("\nPhase 2B纯多头市场因子（收益率单位：%）")
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print("\n数据闸门")
    print(gates.to_string(index=False))
    print("\n20日动量参数／最低佣金稳健性")
    print(
        robustness[
            [
                "rebalance_frequency",
                "top_fraction",
                "minimum_commission_rmb",
                "total_return_pct",
                "excess_vs_equal_weight_pct",
                "excess_vs_932047_pct",
                "commission_paid_rmb",
            ]
        ].to_string(index=False, float_format=lambda value: f"{value:.4f}")
    )
    if args.out_dir:
        output = Path(args.out_dir)
        output.mkdir(parents=True, exist_ok=True)
        signals.to_csv(output / "phase2_market_factor_signals.csv", index=False)
        summary.to_csv(output / "phase2_market_factor_summary.csv", index=False)
        selections.to_csv(output / "phase2_market_factor_selections.csv", index=False)
        robustness.to_csv(output / "phase2_market_factor_robustness.csv", index=False)
        gates.to_csv(output / "phase2_data_gates.csv", index=False)
        print(f"研究结果已保存：{output}")


if __name__ == "__main__":
    main()
