"""增量冻结全市场C-REIT不复权日线，供历史估值使用。"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from pandas.errors import EmptyDataError

from creit_quant.market import (
    MarketDataError,
    fetch_reit_adjusted_history_direct,
    fetch_reit_history_sina,
)
from creit_quant.master_data import load_universe_history

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRICE_PATH = ROOT / "data" / "snapshots" / "full_market_unadjusted_prices.csv"
DEFAULT_COVERAGE_PATH = (
    ROOT / "data" / "snapshots" / "full_market_unadjusted_price_coverage.csv"
)
COVERAGE_COLUMNS = [
    "symbol",
    "status",
    "rows",
    "first_date",
    "last_date",
    "attempts",
    "error",
    "retrieved_at",
    "universe_snapshot_date",
    "start_date",
    "end_date",
]


def fetch_unadjusted_symbols(
    symbols: list[str],
    start_date: str,
    end_date: str,
    universe_snapshot_date: str | pd.Timestamp,
    *,
    maximum_attempts: int = 3,
    timeout: float = 30,
    fetcher: Callable[..., pd.DataFrame] = fetch_reit_adjusted_history_direct,
    source_label: str = "东方财富push2his直接接口",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """逐证券拉取不复权行情，失败保留在覆盖表而不生成价格。"""

    if maximum_attempts <= 0:
        raise ValueError("maximum_attempts必须为正整数")
    retrieved_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    histories: list[pd.DataFrame] = []
    coverage_rows = []
    for number, symbol in enumerate(symbols, 1):
        history = None
        error: Exception | None = None
        attempts = 0
        for attempts in range(1, maximum_attempts + 1):
            try:
                history = fetcher(
                    symbol,
                    start_date,
                    end_date,
                    adjust="",
                    timeout=timeout,
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
                    "start_date": start_date,
                    "end_date": end_date,
                }
            )
            print(
                f"[{number}/{len(symbols)}] {symbol}: {'无历史' if no_history else '网络失败'}"
            )
            continue
        history = history.copy()
        history["adjustment"] = "none"
        history["source"] = source_label
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
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        print(f"[{number}/{len(symbols)}] {symbol}: {len(history)}行")
    prices = pd.concat(histories, ignore_index=True) if histories else pd.DataFrame()
    return prices, pd.DataFrame(coverage_rows, columns=COVERAGE_COLUMNS)


def merge_unadjusted_snapshot(
    existing_prices: pd.DataFrame | None,
    existing_coverage: pd.DataFrame | None,
    fetched_prices: pd.DataFrame,
    fetched_coverage: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """用本次逐证券结果替换同证券旧结果，其他检查点保留。"""

    # 网络失败是一次抓取状态，不能用它删除已经冻结的有效历史。
    replacement_symbols = set(
        fetched_coverage.loc[
            fetched_coverage["status"].isin({"available", "no_history"}), "symbol"
        ].astype(str)
    )
    old_prices = (
        existing_prices.loc[~existing_prices["symbol"].isin(replacement_symbols)].copy()
        if existing_prices is not None and not existing_prices.empty
        else pd.DataFrame()
    )
    old_available_symbols = (
        set(existing_prices["symbol"].astype(str))
        if existing_prices is not None and not existing_prices.empty
        else set()
    )
    failed_with_frozen_history = set(
        fetched_coverage.loc[
            fetched_coverage["status"].eq("network_failed"), "symbol"
        ].astype(str)
    ).intersection(old_available_symbols)
    coverage_replacement_symbols = replacement_symbols.union(
        set(fetched_coverage["symbol"].astype(str)).difference(
            failed_with_frozen_history
        )
    )
    old_coverage = (
        existing_coverage.loc[
            ~existing_coverage["symbol"].isin(coverage_replacement_symbols)
        ].copy()
        if existing_coverage is not None and not existing_coverage.empty
        else pd.DataFrame()
    )
    fetched_coverage = fetched_coverage.loc[
        ~fetched_coverage["symbol"].isin(failed_with_frozen_history)
    ].copy()
    price_parts = [part for part in [old_prices, fetched_prices] if not part.empty]
    coverage_parts = [
        part for part in [old_coverage, fetched_coverage] if not part.empty
    ]
    prices = (
        pd.concat(price_parts, ignore_index=True) if price_parts else pd.DataFrame()
    )
    coverage = (
        pd.concat(coverage_parts, ignore_index=True)
        if coverage_parts
        else pd.DataFrame(columns=["symbol", "status"])
    )
    if not prices.empty:
        prices = prices.sort_values(["symbol", "date"]).reset_index(drop=True)
        if prices.duplicated(["symbol", "date"]).any():
            raise ValueError("不复权行情symbol/date重复")
        if not prices["adjustment"].eq("none").all():
            raise ValueError("全市场估值行情必须为不复权")
    if coverage["symbol"].duplicated().any():
        raise ValueError("不复权行情覆盖表symbol重复")
    return prices, coverage.sort_values("symbol").reset_index(drop=True)


def _read_csv_if_available(path: Path) -> pd.DataFrame | None:
    """读取已有快照；空文件视为尚无快照。"""

    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        return pd.read_csv(path, dtype={"symbol": str})
    except EmptyDataError:
        return None


def _fetch_sina_unadjusted(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    adjust: str,
    timeout: float,
) -> pd.DataFrame:
    """适配新浪不复权接口到批量抓取器的统一签名。"""

    if adjust != "":
        raise ValueError("新浪备用源仅用于不复权行情")
    del timeout  # AKShare该接口暂不暴露timeout参数。
    return fetch_reit_history_sina(symbol, start_date, end_date)


def _completed_symbols_for_window(
    coverage: pd.DataFrame | None, start_date: str, end_date: str
) -> set[str]:
    """仅复用抓取窗口完全相同的最终覆盖状态。"""

    if coverage is None or coverage.empty:
        return set()
    required = {"symbol", "status", "start_date", "end_date"}
    if not required.issubset(coverage.columns):
        return set()
    complete = coverage["status"].isin({"available", "no_history"})
    same_window = coverage["start_date"].astype(str).eq(start_date) & coverage[
        "end_date"
    ].astype(str).eq(end_date)
    return set(coverage.loc[complete & same_window, "symbol"].astype(str))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="20210621")
    parser.add_argument("--end-date", default="20260902")
    parser.add_argument("--price-out", type=Path, default=DEFAULT_PRICE_PATH)
    parser.add_argument("--coverage-out", type=Path, default=DEFAULT_COVERAGE_PATH)
    parser.add_argument("--maximum-attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument(
        "--source",
        choices=["eastmoney", "sina"],
        default="eastmoney",
        help="行情上游；东方财富受限时可显式切换新浪备用源",
    )
    parser.add_argument("--refresh-all", action="store_true")
    args = parser.parse_args()

    universe = load_universe_history(
        ROOT / "data" / "snapshots" / "reit_universe_history.csv"
    )
    snapshot_date = universe["snapshot_date"].max()
    symbols = sorted(
        universe.loc[universe["snapshot_date"].eq(snapshot_date), "symbol"].unique()
    )
    existing_prices = (
        _read_csv_if_available(args.price_out) if not args.refresh_all else None
    )
    existing_coverage = (
        _read_csv_if_available(args.coverage_out) if not args.refresh_all else None
    )
    completed = _completed_symbols_for_window(
        existing_coverage, args.start_date, args.end_date
    )
    pending = (
        symbols if args.refresh_all else sorted(set(symbols).difference(completed))
    )
    fetcher = (
        fetch_reit_adjusted_history_direct
        if args.source == "eastmoney"
        else _fetch_sina_unadjusted
    )
    source_label = (
        "东方财富push2his直接接口" if args.source == "eastmoney" else "AKShare/新浪基金历史"
    )
    fetched_prices, fetched_coverage = fetch_unadjusted_symbols(
        pending,
        args.start_date,
        args.end_date,
        snapshot_date,
        maximum_attempts=args.maximum_attempts,
        timeout=args.timeout,
        fetcher=fetcher,
        source_label=source_label,
    )
    prices, coverage = merge_unadjusted_snapshot(
        existing_prices, existing_coverage, fetched_prices, fetched_coverage
    )
    args.price_out.parent.mkdir(parents=True, exist_ok=True)
    args.coverage_out.parent.mkdir(parents=True, exist_ok=True)
    prices.to_csv(args.price_out, index=False)
    coverage.to_csv(args.coverage_out, index=False)
    print(
        f"不复权行情 {len(prices)}行 / {prices['symbol'].nunique() if not prices.empty else 0}只；"
        f"覆盖状态 {coverage['status'].value_counts().to_dict()}"
    )


if __name__ == "__main__":
    main()
