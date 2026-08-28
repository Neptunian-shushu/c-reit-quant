# Data availability audit

## 1. Market data — GREEN

### AKShare / Eastmoney

AKShare documents dedicated C-REIT endpoints:

- `reits_realtime_em()` — all REIT real-time quotes
- `reits_hist_em(symbol=...)` — daily history for one REIT
- `reits_hist_min_em(...)` — minute history

Daily output includes open/high/low/latest, volume, turnover value, amplitude and turnover rate.

**Assessment:** enough to build a first market-factor panel without paid Wind/Choice access.

**Risk:** this is an unofficial wrapper around a public web data source. Endpoint stability, rate limits and field definitions should be monitored. For production-grade research, cache raw responses and consider a licensed vendor later.

## 2. REIT universe and exchange metadata — GREEN

Both SSE and SZSE maintain dedicated C-REIT portals. The exchanges expose product/project pages, market information, project status, issuance/expansion and disclosures.

**Assessment:** master security table can be built from exchange sources and cross-checked with AKShare.

## 3. Periodic reports and announcements — GREEN / AMBER

SSE has dedicated REIT announcement and periodic-report pages. Its rules explicitly govern quarterly, semiannual and annual REIT disclosures. SZSE also has a dedicated REIT information platform with disclosure sections.

The data exist, but the bottleneck is extraction:

- PDFs / HTML tables are not a normalized research database.
- Fields vary by asset class.
- Historical naming can change after expansion/new asset injection.

**Assessment:** highly feasible, but this becomes a document-parsing/data-engineering project.

Recommended normalized long-format table:

| symbol | period_end | metric | value | unit | publication_date | source |
|---|---|---|---:|---|---|---|
| 508xxx | 2026-06-30 | occupancy | 0.942 | ratio | 2026-07-xx | PDF |
| 508xxx | 2026-06-30 | distributable_amount | ... | RMB | ... | PDF |

## 4. Operating fundamentals — AMBER, but probably the moat

Likely useful categories:

### Industrial parks / logistics
- occupancy
- average rent
- newly signed / renewed area
- tenant concentration
- lease expiry structure
- property NOI

### Toll roads
- traffic volume
- toll revenue
- passenger vs freight split when disclosed

### Renewable energy
- generation (MWh/GWh)
- utilization hours
- curtailment / availability if disclosed
- tariff / settlement information

### Retail / commercial property
- occupancy
- rental income
- tenant sales / footfall if disclosed
- WALE / tenant concentration

**Assessment:** existence is relatively good, consistency is the hard problem. The repo should measure field coverage before assuming a universal factor exists.

## 5. Weather — GREEN

Open-Meteo provides location-based historical weather through an HTTP API, with variables including precipitation, wind speed, temperature, cloud cover and others. Its historical service uses ERA5 / ERA5-Land and other models.

Copernicus CDS also offers ERA5 hourly global reanalysis from 1940 onward, with API access.

**Critical research note:** reanalysis is reconstructed using information unavailable in real time. For a tradable nowcast backtest, use archived historical forecasts/model runs available at the decision timestamp. Reanalysis is fine for explanatory operating regressions.

## 6. Macro / retail / logistics aggregates — GREEN / AMBER

NBS exposes monthly macro series such as retail sales, PMI and related statistics through the National Data portal.

Sector ministries publish additional aggregates, but frequency/geographic granularity varies.

**Assessment:** useful for controls and regional/sector state variables; unlikely to be the strongest source of asset-level alpha by itself.

## 7. Road traffic — AMBER

Baidu Maps documents a Traffic API for current road/area congestion. This confirms programmatic road-state data exist, but it is not automatically a clean historical database of traffic volume on each toll-road asset.

Best MVP sources for toll-road operations are therefore:
1. REIT periodic disclosures (actual traffic), and
2. weather + holidays + regional macro as external predictors.

Only after this works should we invest in historical road-traffic acquisition.

## 8. Footfall / mobility / POI — AMBER / RED for free historical data

Current POI and routing/map APIs are accessible, but **historical** footfall/mobile-location data are often proprietary. Scraping consumer platforms also creates stability/licensing/ToS issues.

**Recommendation:** do not make proprietary footfall necessary for MVP. Treat it as an optional later upgrade.

## Bottom line

The project is feasible with public data.

The strongest immediately obtainable stack is:

1. **full-universe price/volume**
2. **exchange disclosure PDFs / announcements**
3. **weather history / archived forecasts**
4. **NBS and sector aggregate data**

The likely proprietary moat is not access to prices. It is the normalized historical panel extracted from REIT operating disclosures and correctly joined to asset locations and external state variables.
