"""冻结Phase 4八只研究证券的不复权日线，供DPU yield与P/NAV计算。"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pandas as pd

from creit_quant.market import (
    EASTMONEY_HISTORY_URL,
    MarketDataError,
    fetch_reit_adjusted_history,
    fetch_reit_history_sina,
)


SYMBOLS = (
    "180201",
    "180301",
    "180401",
    "508018",
    "508026",
    "508028",
    "508056",
    "508096",
)


def _fetch_via_curl(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """在requests受本机代理影响时，重试同一东方财富公开接口。"""

    params = {
        "secid": f"{'1' if symbol.startswith('5') else '0'}.{symbol}",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "0",
        "beg": start_date,
        "end": end_date,
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
    }
    result = subprocess.run(
        [
            "curl",
            "-fsSL",
            "--retry",
            "4",
            "--connect-timeout",
            "15",
            "--max-time",
            "90",
            f"{EASTMONEY_HISTORY_URL}?{urlencode(params)}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise MarketDataError(f"curl历史行情失败 {symbol}: {result.stderr.strip()}")
    try:
        klines = json.loads(result.stdout)["data"]["klines"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise MarketDataError(f"curl历史行情响应格式异常 {symbol}") from exc
    frame = pd.DataFrame(
        [row.split(",") for row in klines],
        columns=[
            "date",
            "open",
            "close",
            "high",
            "low",
            "volume",
            "turnover",
            "amplitude_pct",
            "change_pct",
            "change",
            "turnover_rate_pct",
        ],
    )
    frame.insert(0, "symbol", symbol)
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    numeric = [column for column in frame if column not in {"symbol", "date"}]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="raise")
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="20210101")
    parser.add_argument("--end-date", default="20260902")
    parser.add_argument(
        "--out", type=Path, default=Path("data/snapshots/phase4_unadjusted_prices.csv")
    )
    args = parser.parse_args()
    retrieved_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    rows = []
    for symbol in SYMBOLS:
        try:
            frame = fetch_reit_history_sina(symbol, args.start_date, args.end_date)
            source = "AKShare/新浪基金历史"
        except MarketDataError:
            try:
                frame = fetch_reit_adjusted_history(
                    symbol, args.start_date, args.end_date, adjust=""
                )
                source = "AKShare/东方财富"
            except MarketDataError:
                frame = _fetch_via_curl(symbol, args.start_date, args.end_date)
                source = "东方财富push2his直接接口（curl重试）"
        frame["adjustment"] = "none"
        frame["source"] = source
        frame["retrieved_at"] = retrieved_at
        rows.append(frame)
        print(
            symbol, len(frame), frame["date"].min().date(), frame["date"].max().date()
        )
    result = pd.concat(rows, ignore_index=True).sort_values(["symbol", "date"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.out, index=False)
    print(f"saved={args.out}, rows={len(result)}")


if __name__ == "__main__":
    main()
