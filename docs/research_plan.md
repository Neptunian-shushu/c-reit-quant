# Research plan

## Phase 0 — feasibility audit

Deliverables:
- master universe table
- daily market panel
- report archive for a small representative sample
- field-coverage report by REIT asset class

Success criterion: >= 80% of the chosen pilot asset class has enough repeated operating observations for a panel test.

## Phase 1 — baseline cross-sectional factors

Test monthly/weekly signals:
- 1m / 3m / 6m momentum
- short-horizon reversal
- turnover / illiquidity
- realized volatility
- distribution yield
- P/NAV
- yield spread vs. government bonds

Controls:
- asset type
- exchange
- listing age
- liquidity

Evaluation:
- rank IC
- top-minus-bottom portfolio return
- long-only top-quintile return
- turnover and capacity
- asset-type-neutral portfolios

## Phase 2 — operating surprise model

Build expected operating metric from trailing history and seasonality.

Examples:
- toll road: traffic surprise
- renewable: generation surprise
- park/logistics: occupancy/rent surprise

Then test:

`operating surprise -> report-date abnormal return -> 1m/3m subsequent return`

## Phase 3 — alternative-data nowcasting

### Toll road pilot
Features:
- rainfall / snow / temperature extremes
- holiday indicators
- regional activity controls

Target:
- next-quarter traffic growth

### Renewable pilot
Features:
- wind speed / solar radiation / precipitation
- asset geolocation

Target:
- next-quarter generation growth

## Phase 4 — tradable model

Only after forecast timestamp integrity is solved:

`public info at t -> predicted DPU / operating surprise -> expected return ranking`

Key safeguards:
- point-in-time report publication dates
- no future-revised macro series without vintage control
- historical forecasts rather than realized weather for true trading backtests
- delisted/expanded-asset history retained
