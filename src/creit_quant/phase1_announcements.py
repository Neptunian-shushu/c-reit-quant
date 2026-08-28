"""批量更新上交所 C-REIT 官方公告候选目录。"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from creit_quant.announcements import (
    fetch_sse_reit_announcements,
    fetch_szse_reit_announcements,
    load_announcement_catalog,
    merge_announcement_catalogs,
)
from creit_quant.master_data import load_universe_history
from creit_quant.phase1_universe import DEFAULT_HISTORY_PATH

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_PATH = ROOT / "data" / "snapshots" / "reit_announcement_catalog.csv"


def main() -> None:
    """逐只抓取上交所公告；失败证券保留在失败报告中供重试。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe-history", default=str(DEFAULT_HISTORY_PATH))
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG_PATH))
    parser.add_argument("--start-date", default="2021-01-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--symbols", nargs="*", help="可选 REIT 代码；默认最新快照全部 REIT")
    parser.add_argument("--exchange", choices=["all", "SSE", "SZSE"], default="all")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--offline", action="store_true", help="不联网，仅按当前规则重分类已有目录")
    args = parser.parse_args()

    history = load_universe_history(args.universe_history)
    latest = history.loc[history["snapshot_date"].eq(history["snapshot_date"].max())]
    if args.symbols:
        symbols = args.symbols
    elif args.exchange == "all":
        symbols = latest["symbol"].tolist()
    else:
        symbols = latest.loc[latest["exchange"].eq(args.exchange), "symbol"].tolist()
    catalog_path = Path(args.catalog)
    existing = load_announcement_catalog(catalog_path) if catalog_path.exists() else None
    if args.offline:
        if existing is None:
            parser.error("--offline 需要已有 --catalog 文件")
        serialised = existing.copy()
        serialised["publication_date"] = serialised["publication_date"].dt.strftime("%Y-%m-%d")
        serialised.to_csv(catalog_path, index=False)
        print(f"公告目录已离线重分类: {len(existing)} 条")
        return
    frames: list[pd.DataFrame] = []
    failures: list[tuple[str, str]] = []
    for symbol in symbols:
        try:
            fetcher = (
                fetch_sse_reit_announcements
                if str(symbol).startswith("508")
                else fetch_szse_reit_announcements
            )
            frame = fetcher(
                symbol,
                args.start_date,
                args.end_date,
                timeout=args.timeout,
            )
        except (RuntimeError, ValueError) as exc:
            failures.append((symbol, str(exc)))
            continue
        frames.append(frame)
        print(f"{symbol}: {len(frame)} 份公告")
    if frames:
        new = pd.concat(frames, ignore_index=True)
        catalog = merge_announcement_catalogs(existing, new)
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        serialised = catalog.copy()
        serialised["publication_date"] = serialised["publication_date"].dt.strftime("%Y-%m-%d")
        serialised.to_csv(catalog_path, index=False)
        print(f"公告目录累计: {len(catalog)} 条，已保存至 {catalog_path}")
    if failures:
        print(f"失败证券: {len(failures)}")
        for symbol, error in failures:
            print(f"  - {symbol}: {error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
