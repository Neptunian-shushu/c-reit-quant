from __future__ import annotations

import argparse
from pathlib import Path

from creit_quant.market import fetch_reit_history


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
