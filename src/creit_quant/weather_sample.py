from __future__ import annotations

import argparse

from creit_quant.weather import fetch_historical_weather


def fetch_weather(lat: float, lon: float, start: str, end: str):
    """Backward-compatible wrapper around the Phase 0 weather client."""

    return fetch_historical_weather(lat, lon, start, end)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()
    print(fetch_weather(args.lat, args.lon, args.start, args.end).to_string(index=False))


if __name__ == "__main__":
    main()
