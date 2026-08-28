# Phase 0 findings: public-data feasibility

## Main conclusion

The project is broadly feasible with public data. Market quotes, exchange disclosures, weather, and macro series are accessible enough for research. Phase 0 also verified operating observations directly in official 2024 annual reports for a toll-road REIT (508018), a hydropower REIT (508026), and a logistics REIT (508056).

The conclusion is not that a production database already exists. Public disclosures prove that the observations exist; extracting consistent, point-in-time panels remains the main engineering task.

## Data-availability traffic light

### GREEN

- **REIT prices and volume:** AKShare exposes a current universe/quote table and documents a daily-history endpoint. It wraps an unofficial Eastmoney source, so raw caching and monitoring are still necessary.
- **Exchange announcements and periodic reports:** SSE and SZSE maintain public REIT disclosure portals. Official reports contain both financial and asset-level operating measures.
- **Weather data:** Open-Meteo provides long reanalysis histories and a separate historical-forecast archive without an API key for non-commercial use.
- **Macro data:** national and regional series are publicly available, although revisions and release dates must be tracked.

### AMBER

- **Standardised operating fundamentals:** the data exist but labels, units, table layouts, period definitions, and asset boundaries differ across reports.
- **Historical toll-road traffic:** actual traffic is disclosed in REIT reports, but a free, uniform asset-level external history is not readily available.
- **Regional or asset-level alternative data:** joining requires a maintained asset geolocation table and careful geographic aggregation.

### RED / optional

- Free historical shopping-centre footfall.
- High-frequency historical mobile-location data.
- Proprietary consumer-location data.

These are not prerequisites for the first pilot.

## Verified Phase 0 evidence

The checked sample is stored in [`data/samples/phase0_operating_metrics.csv`](../data/samples/phase0_operating_metrics.csv). Every row links to an official SSE report and preserves the reported unit/scale.

| Symbol | Asset type | Period | Verified examples | Primary report |
|---|---|---|---|---|
| 508018 | Toll road | 2024 | daily total/passenger/freight traffic; toll revenue | [2024 annual report](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2025-03-29/508018_20250329_2AXB.pdf) |
| 508026 | Hydropower | 2024 | generation; effective generation hours | [2024 annual report](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2025-03-28/508026_20250328_T61T.pdf) |
| 508056 | Logistics | 2024 | rentable/leased area; occupancy; rent; collection rate | [2024 annual report](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2025-03-28/508056_20250328_6KQ4.pdf) |

This is evidence of existence, not yet a longitudinal coverage audit. Reported values were transcribed only after checking the official report text. No estimated, forecast, or unverified number is included.

## The key insight

The central problem is not “do these operating data exist?” It is:

> How can announcements from different REITs, asset types, periods, and formats be standardised into a durable historical panel?

The parser in Phase 0 is intentionally only a keyword/regex candidate generator. PDF text recovery, OCR, table reconstruction, semantic validation, unit conversion, asset lineage after expansion, and human quality control are unsolved layers.

## Where a research moat can form

The defensible stack is the combination of:

1. a REIT operating-disclosure parser;
2. a standardised asset-level fundamental panel;
3. bottom-asset geolocation and lineage;
4. point-in-time joins to weather, holidays, transport, logistics, consumption, and regional macro data.

Prices alone are not the moat. Consistent historical definitions, source lineage, publication timestamps, and revision handling are.

## Recommended first pilot: hydropower REIT 508026

Subject to repeated public-report coverage, the first pilot should test:

`rainfall -> inflow / hydrology -> generation -> settled electricity -> revenue -> distributable cash flow / DPU`

The 2024 annual report confirms that generation and effective generation hours are disclosed. It also explicitly identifies inflow as an operating risk. The next gate is to build a repeated quarterly history and establish the appropriate upstream catchment/geographic weather mapping; a single annual observation is not sufficient for a model.

## Point-in-time weather warning

Open-Meteo's Historical Weather API is reanalysis: an ex-post reconstruction that is appropriate for explaining realised generation. It is not evidence of what a trader knew at the time.

Open-Meteo separately provides a Historical Forecast API whose continuous series stitches the first hours of successive operational model runs. For a strict trading backtest, lead time and issue timestamp still matter. A robust design should use archived previous/single runs when possible and store the forecast issue time alongside the valid time.

In short:

- **ex-post reanalysis weather:** explanatory regression and realised-weather labels;
- **forecast available at the decision time:** tradable nowcast/backtest features.

Confusing the two creates look-ahead bias.

## Remaining risks and Phase 1 gate

- AKShare endpoints depend on an unofficial upstream website and vary by AKShare version.
- PDFs can be scanned, have broken reading order, or represent tables poorly after text extraction.
- Identical labels can use different scopes (fund-level versus project-level), tax bases, time aggregation, or units.
- Expansion and asset injection can break historical comparability unless asset lineage is explicit.
- Hydropower generation depends on catchment inflow, reservoir dispatch, upstream plants, maintenance, grid curtailment, and tariffs—not rainfall alone.
- Repeated quarterly observations for 508026 and precise catchment/geolocation mapping still need a coverage audit before modelling.

Phase 1 is justified if that audit yields enough consistently defined, publication-dated observations. Phase 0 supports proceeding to that audit; it does not yet prove predictive power.
