"""能源REIT point-in-time经营特征和纯多头横截面研究。"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from creit_quant.database import (
    DEFAULT_DOCUMENTS_PATH,
    DEFAULT_ENERGY_DOCUMENTS_PATH,
    DEFAULT_GAS_METRICS_PATH,
    DEFAULT_SOLAR_HYDRO_METRICS_PATH,
    DEFAULT_WIND_METRICS_PATH,
    build_observation_versions,
    load_operating_metrics,
    load_source_documents,
    select_observations_as_of,
)
from creit_quant.hydropower import DEFAULT_METRICS_PATH

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FEATURE_DEFINITIONS_PATH = (
    ROOT / "data" / "reference" / "energy_feature_definitions.csv"
)
DEFAULT_ENERGY_PRICE_PATH = (
    ROOT / "data" / "snapshots" / "phase2_energy_adjusted_prices.csv"
)
DEFAULT_BENCHMARK_PRICE_PATH = (
    ROOT / "data" / "snapshots" / "phase2_932047_total_return.csv"
)


def load_energy_feature_definitions(
    path: str | Path = DEFAULT_FEATURE_DEFINITIONS_PATH,
) -> pd.DataFrame:
    """读取每只能源REIT的稳定资产范围和主经营指标定义。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    required = {
        "symbol",
        "feature_id",
        "metric",
        "aggregation",
        "asset_ids",
        "comparison_lag_quarters",
        "source_note",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"能源特征定义缺少字段: {missing}")
    if frame["symbol"].duplicated().any() or frame["feature_id"].duplicated().any():
        raise ValueError("能源特征定义的symbol和feature_id必须唯一")
    if not frame["symbol"].str.fullmatch(r"\d{6}").all():
        raise ValueError("能源特征定义的证券代码必须为六位数字")
    if not frame["aggregation"].eq("sum").all():
        raise ValueError("当前能源主指标只允许可加总的sum聚合")
    frame["comparison_lag_quarters"] = pd.to_numeric(
        frame["comparison_lag_quarters"], errors="raise"
    ).astype(int)
    if frame["comparison_lag_quarters"].le(0).any():
        raise ValueError("同比滞后季度数必须为正")
    if frame["asset_ids"].isna().any() or frame["asset_ids"].str.strip().eq("").any():
        raise ValueError("能源特征必须显式登记稳定资产范围")
    return frame


def load_default_energy_research_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    """合并四只能源REIT的经营观测和来源公告。"""

    metric_paths = [
        DEFAULT_METRICS_PATH,
        DEFAULT_WIND_METRICS_PATH,
        DEFAULT_SOLAR_HYDRO_METRICS_PATH,
        DEFAULT_GAS_METRICS_PATH,
    ]
    metrics = pd.concat(
        [load_operating_metrics(path) for path in metric_paths], ignore_index=True
    )
    documents = pd.concat(
        [
            load_source_documents(DEFAULT_DOCUMENTS_PATH),
            load_source_documents(DEFAULT_ENERGY_DOCUMENTS_PATH),
        ],
        ignore_index=True,
    )
    if documents["source_url"].duplicated().any():
        raise ValueError("合并后的能源来源公告URL不能重复")
    return metrics, documents


def _period_end_offset(period_end: pd.Timestamp, quarters: int) -> pd.Timestamp:
    return (period_end.to_period("Q") - quarters).end_time.normalize()


def build_energy_point_in_time_features(
    metrics: pd.DataFrame,
    documents: pd.DataFrame,
    definitions: pd.DataFrame,
) -> pd.DataFrame:
    """按首次披露日构造稳定资产范围的同比和扩展历史surprise。

    当前值与四季度前值都从当次公告日有效的版本表读取。后续年报修订
    不会回填到更早事件；同比本身控制季度季节性，预期值只使用该证券
    此前已经公布的同比，不使用同日或未来横截面信息。
    """

    versions = build_observation_versions(metrics, documents)
    rows: list[dict[str, object]] = []
    for definition in definitions.itertuples(index=False):
        asset_ids = tuple(str(definition.asset_ids).split("|"))
        selected = metrics.loc[
            metrics["symbol"].eq(definition.symbol)
            & metrics["metric"].eq(definition.metric)
            & metrics["asset_id"].isin(asset_ids)
        ].copy()
        if set(selected["asset_id"]) != set(asset_ids):
            raise ValueError(f"{definition.symbol}特征定义包含没有观测的资产")
        first_versions = selected.sort_values("publication_date").drop_duplicates(
            ["asset_id", "period_end"], keep="first"
        )
        schedule = first_versions.groupby("period_end", as_index=False).agg(
            publication_date=("publication_date", "max"),
            available_assets=("asset_id", "nunique"),
        )
        schedule = schedule.loc[schedule["available_assets"].eq(len(asset_ids))]
        for event in schedule.itertuples(index=False):
            period_end = pd.Timestamp(event.period_end)
            lag_end = _period_end_offset(
                period_end, int(definition.comparison_lag_quarters)
            )
            active = select_observations_as_of(versions, event.publication_date)
            active = active.loc[
                active["symbol"].eq(definition.symbol)
                & active["metric"].eq(definition.metric)
                & active["asset_id"].isin(asset_ids)
                & active["period_end"].isin([period_end, lag_end])
            ]
            current = active.loc[active["period_end"].eq(period_end)]
            lagged = active.loc[active["period_end"].eq(lag_end)]
            if current["asset_id"].nunique() != len(asset_ids):
                continue
            if lagged["asset_id"].nunique() != len(asset_ids):
                continue
            current_value = float(current["value"].sum())
            lagged_value = float(lagged["value"].sum())
            if lagged_value == 0:
                raise ValueError(f"{definition.symbol}/{lag_end.date()}同比基数为零")
            rows.append(
                {
                    "symbol": definition.symbol,
                    "feature_id": definition.feature_id,
                    "period_end": period_end,
                    "publication_date": pd.Timestamp(event.publication_date),
                    "metric": definition.metric,
                    "aggregation": definition.aggregation,
                    "asset_ids": definition.asset_ids,
                    "asset_count": len(asset_ids),
                    "current_value": current_value,
                    "lag_period_end": lag_end,
                    "lag_value_as_of_publication": lagged_value,
                    "operating_yoy_pct": (current_value / lagged_value - 1) * 100,
                    "current_observation_ids": "|".join(
                        sorted(current["observation_id"].astype(str))
                    ),
                    "lag_observation_ids": "|".join(
                        sorted(lagged["observation_id"].astype(str))
                    ),
                    "current_quality_status": "|".join(
                        sorted(current["quality_status"].astype(str).unique())
                    ),
                    "lag_quality_status": "|".join(
                        sorted(lagged["quality_status"].astype(str).unique())
                    ),
                    "lineage_quality_status": (
                        "verified"
                        if current["quality_status"].eq("verified").all()
                        and lagged["quality_status"].eq("verified").all()
                        else "contains_unverified_source_registry"
                    ),
                }
            )
    if not rows:
        raise ValueError("没有能源主指标能形成point-in-time同比")
    features = pd.DataFrame(rows).sort_values(
        ["symbol", "publication_date", "period_end"]
    ).reset_index(drop=True)
    grouped = features.groupby("symbol", sort=False)["operating_yoy_pct"]
    features["prior_yoy_observations"] = grouped.cumcount()
    features["expected_yoy_pct"] = grouped.transform(
        lambda values: values.shift(1).expanding(min_periods=1).mean()
    )
    features["operating_surprise_pct"] = (
        features["operating_yoy_pct"] - features["expected_yoy_pct"]
    )
    return features.sort_values(["period_end", "symbol"]).reset_index(drop=True)


def build_energy_cross_section_signals(
    features: pd.DataFrame,
    *,
    minimum_securities: int = 3,
    top_n: int = 1,
) -> pd.DataFrame:
    """按季度结束日形成公告全部到齐后的纯多头横截面排名。"""

    if minimum_securities < 2 or top_n < 1 or top_n >= minimum_securities:
        raise ValueError("横截面要求minimum_securities>=2且top_n更小")
    required = {
        "symbol",
        "period_end",
        "publication_date",
        "operating_surprise_pct",
    }
    missing = sorted(required.difference(features.columns))
    if missing:
        raise ValueError(f"能源特征缺少横截面字段: {missing}")
    eligible = features.dropna(subset=["operating_surprise_pct"]).copy()
    counts = eligible.groupby("period_end")["symbol"].transform("nunique")
    eligible = eligible.loc[counts.ge(minimum_securities)].copy()
    if eligible.empty:
        raise ValueError("没有满足最小证券数量的能源横截面")
    eligible["decision_date"] = eligible.groupby("period_end")[
        "publication_date"
    ].transform("max")
    eligible["universe_count"] = eligible.groupby("period_end")["symbol"].transform(
        "nunique"
    )
    eligible["signal_rank"] = eligible.groupby("period_end")[
        "operating_surprise_pct"
    ].rank(method="first", ascending=False)
    eligible["signal_rank_pct"] = eligible.groupby("period_end")[
        "operating_surprise_pct"
    ].rank(method="average", ascending=True, pct=True)
    eligible["selected"] = eligible["signal_rank"].le(top_n)
    return eligible.sort_values(["period_end", "signal_rank"]).reset_index(drop=True)


def load_market_snapshot(path: str | Path, *, kind: str) -> pd.DataFrame:
    """读取带来源和抓取时点的本地价格或基准快照。"""

    if kind not in {"security", "benchmark"}:
        raise ValueError("行情快照kind必须为security或benchmark")
    frame = pd.read_csv(path, dtype={"symbol": str})
    required = {"date", "close", "source", "retrieved_at"}
    if kind == "security":
        required.add("symbol")
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{kind}行情快照缺少字段: {missing}")
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    frame["retrieved_at"] = pd.to_datetime(frame["retrieved_at"], errors="raise")
    frame["close"] = pd.to_numeric(frame["close"], errors="raise")
    key = ["symbol", "date"] if kind == "security" else ["date"]
    if frame.duplicated(key).any() or frame["close"].le(0).any():
        raise ValueError(f"{kind}行情快照自然键重复或收盘价非正")
    return frame.sort_values(key).reset_index(drop=True)


def _align_rebalance_dates(signals: pd.DataFrame, dates: pd.Series) -> pd.DataFrame:
    trading_dates = pd.DatetimeIndex(dates)
    decisions = signals[["period_end", "decision_date"]].drop_duplicates()
    rows = []
    for decision in decisions.itertuples(index=False):
        future = trading_dates[trading_dates > pd.Timestamp(decision.decision_date)]
        if len(future):
            rows.append(
                {
                    "period_end": decision.period_end,
                    "decision_date": decision.decision_date,
                    "entry_date": future[0],
                }
            )
    if not rows:
        raise ValueError("横截面事件后没有共同交易日")
    return signals.merge(pd.DataFrame(rows), on=["period_end", "decision_date"])


def _portfolio_statistics(returns: pd.Series) -> dict[str, float]:
    equity = (1 + returns).cumprod()
    observations = max(len(returns) - 1, 1)
    total = float(equity.iloc[-1] - 1)
    drawdown = equity / equity.cummax() - 1
    return {
        "total_return_pct": total * 100,
        "annualised_return_pct": ((1 + total) ** (252 / observations) - 1) * 100,
        "annualised_volatility_pct": float(returns.std(ddof=0) * math.sqrt(252) * 100),
        "max_drawdown_pct": float(drawdown.min() * 100),
    }


def _simulate_portfolio(
    returns: pd.DataFrame,
    targets: dict[pd.Timestamp, dict[str, float]],
    *,
    initial_capital: float,
    commission_rate: float,
    minimum_commission: float,
    cash_annual_yield: float,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    symbols = list(returns.columns)
    holdings = {symbol: 0.0 for symbol in symbols}
    cash = initial_capital
    equity_values: list[float] = []
    net_returns: list[float] = []
    fees: list[float] = []
    previous_equity = initial_capital
    cash_return = (1 + cash_annual_yield) ** (1 / 252) - 1
    for row_number, (date, daily_returns) in enumerate(returns.iterrows()):
        holdings = {
            symbol: value * (1 + float(daily_returns[symbol]))
            for symbol, value in holdings.items()
        }
        if row_number:
            cash *= 1 + cash_return
        equity_before_fee = cash + sum(holdings.values())
        fee = 0.0
        if date in targets:
            target_weights = targets[date]
            for symbol in symbols:
                order = abs(
                    equity_before_fee * target_weights.get(symbol, 0.0)
                    - holdings[symbol]
                )
                if order > 1e-8:
                    fee += max(order * commission_rate, minimum_commission)
            equity_after_fee = equity_before_fee - fee
            if equity_after_fee <= 0:
                raise ValueError("交易费用耗尽组合资产")
            holdings = {
                symbol: equity_after_fee * target_weights.get(symbol, 0.0)
                for symbol in symbols
            }
            cash = equity_after_fee * (1 - sum(target_weights.values()))
        equity = cash + sum(holdings.values())
        net_returns.append(equity / previous_equity - 1)
        equity_values.append(equity)
        fees.append(fee)
        previous_equity = equity
    index = returns.index
    return (
        pd.Series(net_returns, index=index),
        pd.Series(equity_values, index=index),
        pd.Series(fees, index=index),
    )


def run_energy_surprise_backtest(
    signals: pd.DataFrame,
    security_prices: pd.DataFrame,
    benchmark_prices: pd.DataFrame,
    *,
    initial_capital: float = 100_000.0,
    commission_rate: float = 0.0001,
    minimum_commission: float = 5.0,
    cash_annual_yield: float = 0.015,
    forward_horizon_days: int = 20,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """回测最高经营surprise组合，并与能源等权和932047比较。

    组合按下一次季度事件再平衡；横截面rank IC则使用统一的前瞻交易日
    窗口，避免不同公告间隔或最后一期未结束导致标签不可比。
    """

    if initial_capital <= 0 or commission_rate < 0 or minimum_commission < 0:
        raise ValueError("资金必须为正，佣金参数不能为负")
    if cash_annual_yield <= -1:
        raise ValueError("现金年化收益率必须大于-100%")
    if forward_horizon_days < 1:
        raise ValueError("前瞻收益窗口必须至少为1个交易日")
    required_symbols = sorted(signals["symbol"].unique())
    available_symbols = set(security_prices["symbol"])
    if not set(required_symbols).issubset(available_symbols):
        raise ValueError("价格快照没有覆盖全部信号证券")
    prices = security_prices.pivot(index="date", columns="symbol", values="close")
    prices = prices[required_symbols].dropna()
    benchmark = benchmark_prices.set_index("date")["close"].rename("benchmark_close")
    panel = prices.join(benchmark, how="inner").dropna().sort_index()
    if panel.empty:
        raise ValueError("证券和基准没有共同交易日")
    aligned = _align_rebalance_dates(signals, panel.index.to_series())
    first_entry = aligned["entry_date"].min()
    panel = panel.loc[panel.index >= first_entry].copy()
    asset_returns = panel[required_symbols].pct_change().fillna(0.0)
    selected_targets: dict[pd.Timestamp, dict[str, float]] = {}
    equal_targets: dict[pd.Timestamp, dict[str, float]] = {}
    for entry_date, group in aligned.groupby("entry_date"):
        selected = group.loc[group["selected"], "symbol"].tolist()
        selected_targets[pd.Timestamp(entry_date)] = {
            symbol: 1 / len(selected) for symbol in selected
        }
        universe = group["symbol"].tolist()
        equal_targets[pd.Timestamp(entry_date)] = {
            symbol: 1 / len(universe) for symbol in universe
        }
    strategy_return, strategy_value, strategy_fee = _simulate_portfolio(
        asset_returns,
        selected_targets,
        initial_capital=initial_capital,
        commission_rate=commission_rate,
        minimum_commission=minimum_commission,
        cash_annual_yield=cash_annual_yield,
    )
    equal_return, equal_value, equal_fee = _simulate_portfolio(
        asset_returns,
        equal_targets,
        initial_capital=initial_capital,
        commission_rate=commission_rate,
        minimum_commission=minimum_commission,
        cash_annual_yield=cash_annual_yield,
    )
    benchmark_return = panel["benchmark_close"].pct_change().fillna(0.0)
    daily = pd.DataFrame(
        {
            "date": panel.index,
            "strategy_return": strategy_return.values,
            "energy_equal_weight_return": equal_return.values,
            "benchmark_return": benchmark_return.values,
            "strategy_value": strategy_value.values,
            "energy_equal_weight_value": equal_value.values,
            "strategy_commission_rmb": strategy_fee.values,
            "energy_equal_weight_commission_rmb": equal_fee.values,
        }
    )
    daily["strategy_equity"] = daily["strategy_value"] / initial_capital
    daily["energy_equal_weight_equity"] = (
        daily["energy_equal_weight_value"] / initial_capital
    )
    daily["benchmark_equity"] = (1 + daily["benchmark_return"]).cumprod()

    event_rows = []
    entries = sorted(aligned["entry_date"].unique())
    for index, entry_date in enumerate(entries):
        event_signals = aligned.loc[aligned["entry_date"].eq(entry_date)]
        exit_date = entries[index + 1] if index + 1 < len(entries) else panel.index.max()
        entry_position = panel.index.get_loc(entry_date)
        horizon_position = entry_position + forward_horizon_days
        horizon_end = (
            panel.index[horizon_position]
            if horizon_position < len(panel.index)
            else pd.NaT
        )
        for signal in event_signals.itertuples(index=False):
            symbol_prices = panel.loc[[entry_date, exit_date], signal.symbol]
            benchmark_event = panel.loc[[entry_date, exit_date], "benchmark_close"]
            if pd.isna(horizon_end):
                forward_return = float("nan")
                forward_benchmark = float("nan")
            else:
                forward_return = float(
                    panel.loc[horizon_end, signal.symbol]
                    / panel.loc[entry_date, signal.symbol]
                    - 1
                )
                forward_benchmark = float(
                    panel.loc[horizon_end, "benchmark_close"]
                    / panel.loc[entry_date, "benchmark_close"]
                    - 1
                )
            event_rows.append(
                {
                    **signal._asdict(),
                    "holding_end": pd.Timestamp(exit_date),
                    "holding_period_return_pct": float(
                        symbol_prices.iloc[-1] / symbol_prices.iloc[0] - 1
                    )
                    * 100,
                    "holding_period_benchmark_pct": float(
                        benchmark_event.iloc[-1] / benchmark_event.iloc[0] - 1
                    )
                    * 100,
                    "forward_horizon_days": forward_horizon_days,
                    "forward_horizon_end": horizon_end,
                    "forward_return_pct": forward_return * 100,
                    "benchmark_return_pct": forward_benchmark * 100,
                }
            )
    events = pd.DataFrame(event_rows)
    events["forward_excess_return_pct"] = (
        events["forward_return_pct"] - events["benchmark_return_pct"]
    )
    rank_ics = []
    complete_events = events.dropna(subset=["forward_return_pct"])
    for period_end, group in complete_events.groupby("period_end"):
        rank_ics.append(
            {
                "period_end": period_end,
                "rank_ic": float(
                    group["operating_surprise_pct"].rank().corr(
                        group["forward_return_pct"].rank()
                    )
                ),
            }
        )
    rank_ic = pd.DataFrame(rank_ics, columns=["period_end", "rank_ic"])
    summary_rows = []
    for name, values, fees in [
        ("top_operating_surprise_net", strategy_return, strategy_fee),
        ("energy_equal_weight_net", equal_return, equal_fee),
        ("reit_total_return_index_benchmark", benchmark_return, None),
    ]:
        row = {"portfolio": name, **_portfolio_statistics(values)}
        row["commission_paid_rmb"] = 0.0 if fees is None else float(fees.sum())
        summary_rows.append(row)
    summary = pd.DataFrame(summary_rows)
    summary["start_date"] = panel.index.min()
    summary["end_date"] = panel.index.max()
    summary["rebalance_events"] = len(entries)
    summary["rank_ic_horizon_trading_days"] = forward_horizon_days
    summary["complete_rank_ic_events"] = len(rank_ic)
    summary["mean_rank_ic"] = rank_ic["rank_ic"].mean()
    summary["positive_rank_ic_events"] = rank_ic["rank_ic"].gt(0).sum()
    summary["initial_capital_rmb"] = initial_capital
    summary["commission_rate_pct"] = commission_rate * 100
    summary["minimum_commission_rmb"] = minimum_commission
    summary["cash_annual_yield_pct"] = cash_annual_yield * 100
    return summary, events, daily
