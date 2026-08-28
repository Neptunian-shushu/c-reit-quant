# C-REIT Quant Research

A feasibility-first research project for testing whether China public REITs (C-REITs) support systematic research built from market data, disclosed asset operations, and alternative data.

## Phase 0 status

**Phase 0 — data availability validation is implemented.** The current conclusion is that a public-data project is feasible, but the valuable and difficult component is a standardised historical operating-fundamental panel rather than price collection.

Phase 0 now provides:

- AKShare current universe/quote and daily-history access with normalised fields and explicit failure handling;
- separate Open-Meteo clients for ex-post historical/reanalysis weather and archived historical forecasts;
- a long-format operating-metric schema and regex/keyword candidate extractor;
- a small source-linked sample verified from official annual reports across toll road, hydropower, and logistics assets;
- a command-line feasibility check and offline unit tests.

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

## Data availability verdict

| Dataset | Availability | Automation | Notes |
|---|---|---:|---|
| REIT universe / basic info | Good | High | SSE/SZSE REIT portals; can maintain master security table |
| Daily OHLCV / turnover | Good | High | AKShare exposes Eastmoney-backed REIT real-time and historical endpoints |
| Intraday bars | Good-ish | High | AKShare documents historical minute REIT endpoint; retention may vary |
| Exchange disclosures / periodic reports | Good | Medium-High | SSE/SZSE have dedicated REIT disclosure portals; PDF parsing needed |
| DPU / distributable amount | Good | Medium | In periodic reports and distribution announcements; standardization needed |
| NAV / appraised value | Medium-Good | Medium | Periodic reports / valuation disclosures; not always a clean single API |
| Asset-level occupancy / rent / traffic / generation | Medium-Good | Medium-Low | Often disclosed, but asset-type-specific and PDF/table extraction is needed |
| Historical weather | Excellent | High | Open-Meteo reanalysis; suitable for ex-post explanation |
| Archived forecasts | Good | High | Separate API; issue time and forecast lead must still be controlled |
| National / regional macro | Good | Medium-High | NBS and sector ministries; frequency varies |
| Express / logistics aggregates | Good | Medium | State Post Bureau / MOT, mostly aggregate rather than property-level |
| Real-time road congestion | Medium | Medium | Baidu Traffic API exists; requires API key and is mainly current-state |
| Historical asset-level road traffic | Weak-Medium | Low | Best source may be REIT reports / local transport disclosures |
| Retail footfall / mall traffic | Medium-Weak | Low-Medium | Often property disclosures; external high-frequency data may be commercial |
| POI / map features | Medium | Medium | Mapping APIs available; historical snapshots are the hard part |
| Mobile-location / proprietary footfall | Weak (free) | Low | Likely paid/proprietary; not required for MVP |

See [`docs/phase0_findings.md`](docs/phase0_findings.md) for the completed audit and [`docs/data_availability.md`](docs/data_availability.md) for the broader source inventory.

## Next phase: Phase 1 — Hydropower Pilot

The preferred first pilot is **508026**, provided its repeated public disclosures pass a fuller coverage audit.

Phase 1 will:

1. build a historical quarterly operating dataset for the hydropower REIT;
2. map the underlying asset/catchment to weather locations;
3. join generation and utilisation hours to rainfall/weather features;
4. test a simple generation nowcast model.

This is a data and timestamp-integrity pilot before any trading model.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

python -m creit_quant.phase0
python -m creit_quant.phase0 --history-symbol 508026

# Optional offline tests
pip install -e '.[dev]'
pytest
```

## Repository structure

```text
c-reit-quant/
├── configs/
│   └── data_sources.yaml
├── docs/
│   ├── data_availability.md
│   ├── phase0_findings.md
│   └── research_plan.md
├── src/creit_quant/
│   ├── market.py
│   ├── weather.py
│   ├── report_parser.py
│   ├── phase0.py
│   └── schema.py
├── data/
│   ├── raw/
│   ├── processed/
│   └── samples/
├── scripts/
├── tests/
├── pyproject.toml
└── README.md
```

## Important backtest rule

For alternative-data research, avoid look-ahead bias. Distinguish:

- **reanalysis weather** (best estimate reconstructed after the fact), versus
- **historical weather forecasts available at each trading date**.

Reanalysis is appropriate for explaining realized operations. A tradable nowcast should use information that was actually available at the time.

## Known limitations

- AKShare's REIT endpoints wrap an unofficial Eastmoney source; availability and fields can change, and older AKShare versions may lack the documented daily-history function.
- The report parser produces candidates from recovered text. It does not claim to solve PDF layout, table extraction, OCR, unit harmonisation, or source verification.
- The Phase 0 CSV demonstrates that operating data exist; it is not yet a complete time series.
- Strict tradable tests must distinguish weather reanalysis from forecasts actually available at each historical decision time.
