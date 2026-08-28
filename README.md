# C-REIT Quant Research

A research scaffold for testing whether China public REITs (C-REITs) support systematic cross-sectional strategies built from market data, disclosed operating fundamentals, and alternative data.

## Research questions

1. Is the C-REIT universe now large and liquid enough for cross-sectional quant research?
2. Which fundamental variables (DPU, occupancy, traffic, generation, rent, NOI, etc.) are consistently disclosed?
3. Can public alternative data improve forecasts of operating cash flow / DPU?
4. Do fundamental and alternative-data surprises predict future REIT returns?

## First hypotheses

- **Valuation:** forward distribution yield, P/NAV, yield spread vs. CGB.
- **Operating quality:** occupancy, rent growth, traffic growth, generation, NOI margin.
- **Alternative data:** weather, holidays, logistics, retail activity, regional macro.
- **Event studies:** earnings/quarterly reports, expansion (扩募), extreme weather, holidays.

## Data availability: preliminary verdict

| Dataset | Availability | Automation | Notes |
|---|---|---:|---|
| REIT universe / basic info | Good | High | SSE/SZSE REIT portals; can maintain master security table |
| Daily OHLCV / turnover | Good | High | AKShare exposes Eastmoney-backed REIT real-time and historical endpoints |
| Intraday bars | Good-ish | High | AKShare documents historical minute REIT endpoint; retention may vary |
| Exchange disclosures / periodic reports | Good | Medium-High | SSE/SZSE have dedicated REIT disclosure portals; PDF parsing needed |
| DPU / distributable amount | Good | Medium | In periodic reports and distribution announcements; standardization needed |
| NAV / appraised value | Medium-Good | Medium | Periodic reports / valuation disclosures; not always a clean single API |
| Asset-level occupancy / rent / traffic / generation | Medium-Good | Medium-Low | Often disclosed, but asset-type-specific and PDF/table extraction is needed |
| Historical weather | Excellent | High | Open-Meteo / ERA5; location-based hourly history |
| Weather forecasts | Excellent | High | Useful for genuine nowcast tests if timestamps are handled correctly |
| National / regional macro | Good | Medium-High | NBS and sector ministries; frequency varies |
| Express / logistics aggregates | Good | Medium | State Post Bureau / MOT, mostly aggregate rather than property-level |
| Real-time road congestion | Medium | Medium | Baidu Traffic API exists; requires API key and is mainly current-state |
| Historical asset-level road traffic | Weak-Medium | Low | Best source may be REIT reports / local transport disclosures |
| Retail footfall / mall traffic | Medium-Weak | Low-Medium | Often property disclosures; external high-frequency data may be commercial |
| POI / map features | Medium | Medium | Mapping APIs available; historical snapshots are the hard part |
| Mobile-location / proprietary footfall | Weak (free) | Low | Likely paid/proprietary; not required for MVP |

See [`docs/data_availability.md`](docs/data_availability.md) for details and validation plan.

## MVP recommendation

Start with two parallel tracks:

### Track A — cross-sectional market/fundamental baseline

Universe: all listed C-REITs.

Build factors from:
- return / momentum / reversal
- turnover / liquidity
- realized volatility
- distribution yield
- P/NAV where available
- yield spread vs. government bonds
- asset category

Goal: establish whether basic cross-sectional structure is measurable before adding alternative data.

### Track B — asset-type nowcast pilot

Start with **toll-road REITs** or **renewable-energy REITs**.

Toll road example:

`weather + holidays + regional activity -> traffic -> revenue -> DPU -> price reaction`

Renewable example:

`wind / irradiance / rainfall -> generation -> revenue -> DPU -> price reaction`

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

python -m creit_quant.market_sample --symbol 508097
python -m creit_quant.weather_sample --lat 31.23 --lon 121.47 --start 2025-01-01 --end 2025-01-10
```

## Repository structure

```text
c-reit-quant/
├── configs/
│   └── data_sources.yaml
├── docs/
│   ├── data_availability.md
│   └── research_plan.md
├── notebooks/
├── src/creit_quant/
│   ├── market_sample.py
│   ├── weather_sample.py
│   └── schema.py
├── tests/
├── data/
│   ├── raw/
│   └── processed/
├── pyproject.toml
└── README.md
```

## Important backtest rule

For alternative-data research, avoid look-ahead bias. Distinguish:

- **reanalysis weather** (best estimate reconstructed after the fact), versus
- **historical weather forecasts available at each trading date**.

Reanalysis is appropriate for explaining realized operations. A tradable nowcast should use information that was actually available at the time.

## Status

This is a feasibility-first scaffold. The immediate next task is to build a normalized REIT master table and download 2–3 years of daily bars for the full universe, then parse a small sample of quarterly reports to measure field coverage.
