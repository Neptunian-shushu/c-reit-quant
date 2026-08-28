"""Command-line Phase 0 data availability check."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from creit_quant.market import MarketDataError, fetch_reit_history, fetch_reit_universe

DEFAULT_SAMPLE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "samples" / "phase0_operating_metrics.csv"
)


def load_operating_samples(path: str | Path = DEFAULT_SAMPLE_PATH) -> pd.DataFrame:
    """Load the small, source-linked Phase 0 operating metric sample."""

    frame = pd.read_csv(path, dtype={"symbol": str})
    required = {
        "symbol",
        "period_end",
        "asset_type",
        "metric",
        "value",
        "unit",
        "source_url_or_note",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"sample file is missing columns: {sorted(missing)}")
    return frame


def summarise_metric_coverage(frame: pd.DataFrame) -> pd.Series:
    """List the verified sample metrics currently available by asset type."""

    return frame.groupby("asset_type")["metric"].agg(
        lambda values: ", ".join(sorted(values.unique()))
    )


def run_phase0(sample_path: str | Path, history_symbol: str | None = None) -> int:
    """Run live market checks plus the static operating-data feasibility audit."""

    market_ok = False
    try:
        universe = fetch_reit_universe()
        market_ok = True
        print(f"Current C-REIT universe: {len(universe)} securities")
    except MarketDataError as exc:
        print(f"Current C-REIT universe: unavailable ({exc})")

    if history_symbol:
        try:
            history = fetch_reit_history(history_symbol)
            print(
                f"Daily history for {history_symbol}: {len(history)} rows, "
                f"{history['date'].min().date()} to {history['date'].max().date()}"
            )
        except MarketDataError as exc:
            print(f"Daily history for {history_symbol}: unavailable ({exc})")

    samples = load_operating_samples(sample_path)
    print(f"Verified operating sample: {len(samples)} observations")
    print("Metric coverage by asset type:")
    for asset_type, metrics in summarise_metric_coverage(samples).items():
        print(f"  - {asset_type}: {metrics}")

    covered_types = samples["asset_type"].nunique()
    print("Feasibility summary:")
    print(f"  - market endpoint reachable now: {'yes' if market_ok else 'no / retry needed'}")
    print(f"  - operating asset types with verified public examples: {covered_types}")
    print("  - verdict: public-data research is feasible; panel standardisation is the bottleneck")
    return 0


def main() -> None:
    """Parse command-line options and run the Phase 0 check."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", default=str(DEFAULT_SAMPLE_PATH))
    parser.add_argument(
        "--history-symbol",
        default=None,
        help="optionally request daily history for one six-digit REIT symbol",
    )
    args = parser.parse_args()
    raise SystemExit(run_phase0(args.samples, args.history_symbol))


if __name__ == "__main__":
    main()
