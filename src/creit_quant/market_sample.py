from __future__ import annotations

import argparse
from pathlib import Path

import akshare as ak


def fetch_reit_history(symbol: str):
    """Fetch daily C-REIT history using AKShare's documented Eastmoney endpoint."""
    df = ak.reits_hist_em(symbol=symbol)
    if df.empty:
        raise RuntimeError(f"No data returned for {symbol}")
    return df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="508097")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    df = fetch_reit_history(args.symbol)
    print(df.tail(10).to_string(index=False))

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        print(f"saved: {out}")


if __name__ == "__main__":
    main()
