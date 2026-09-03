"""C-REIT全市场价格与流动性因子的point-in-time研究工具。"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FULL_MARKET_PRICE_PATH = (
    ROOT / "data" / "snapshots" / "phase2_full_market_adjusted_history.csv"
)
DEFAULT_FULL_MARKET_COVERAGE_PATH = (
    ROOT / "data" / "snapshots" / "phase2_full_market_price_coverage.csv"
)
DEFAULT_UNIVERSE_HISTORY_PATH = (
    ROOT / "data" / "snapshots" / "reit_universe_history.csv"
)

FACTOR_DIRECTIONS = {
    "momentum_20d": 1.0,
    "momentum_60d": 1.0,
    "short_term_reversal_5d": 1.0,
    "liquidity_20d": 1.0,
    "low_illiquidity_20d": 1.0,
    "low_volatility_20d": 1.0,
    "market_composite": 1.0,
}


def load_full_market_prices(path: str | Path = DEFAULT_FULL_MARKET_PRICE_PATH) -> pd.DataFrame:
    """读取冻结的全市场后复权行情，并校验研究所需字段。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    required = {
        "symbol",
        "date",
        "close",
        "turnover",
        "adjustment",
        "source",
        "retrieved_at",
        "universe_snapshot_date",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"全市场行情快照缺少字段: {missing}")
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    frame["retrieved_at"] = pd.to_datetime(frame["retrieved_at"], errors="raise")
    frame["universe_snapshot_date"] = pd.to_datetime(
        frame["universe_snapshot_date"], errors="raise"
    )
    for column in ["close", "turnover"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    if frame.duplicated(["symbol", "date"]).any():
        raise ValueError("全市场行情快照的symbol/date不能重复")
    if frame["close"].le(0).any() or frame["turnover"].lt(0).any():
        raise ValueError("收盘价必须为正，成交额不能为负")
    if not frame["adjustment"].eq("hfq").all():
        raise ValueError("Phase 2市场研究只接受冻结的后复权行情")
    return frame.sort_values(["symbol", "date"]).reset_index(drop=True)


def load_full_market_coverage(
    path: str | Path = DEFAULT_FULL_MARKET_COVERAGE_PATH,
) -> pd.DataFrame:
    """读取每只当前universe证券的行情抓取覆盖状态。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    required = {
        "symbol",
        "status",
        "rows",
        "first_date",
        "last_date",
        "retrieved_at",
        "universe_snapshot_date",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"全市场行情覆盖表缺少字段: {missing}")
    if frame["symbol"].duplicated().any():
        raise ValueError("行情覆盖表symbol不能重复")
    allowed = {"available", "no_history", "network_failed"}
    if not set(frame["status"]).issubset(allowed):
        raise ValueError("行情覆盖表包含未知状态")
    frame["rows"] = pd.to_numeric(frame["rows"], errors="raise").astype(int)
    if frame["rows"].lt(0).any():
        raise ValueError("行情覆盖行数不能为负")
    frame["first_date"] = pd.to_datetime(frame["first_date"], errors="coerce")
    frame["last_date"] = pd.to_datetime(frame["last_date"], errors="coerce")
    frame["retrieved_at"] = pd.to_datetime(frame["retrieved_at"], errors="raise")
    frame["universe_snapshot_date"] = pd.to_datetime(
        frame["universe_snapshot_date"], errors="raise"
    )
    available = frame["status"].eq("available")
    invalid_available = available & (
        frame["rows"].le(0)
        | frame["first_date"].isna()
        | frame["last_date"].isna()
    )
    invalid_missing = ~available & frame["rows"].ne(0)
    if invalid_available.any() or invalid_missing.any():
        raise ValueError("行情覆盖状态、行数或日期不一致")
    return frame.sort_values("symbol").reset_index(drop=True)


def validate_full_market_snapshot(
    prices: pd.DataFrame,
    coverage: pd.DataFrame,
    universe_history: pd.DataFrame,
) -> None:
    """交叉核对行情、覆盖清单与最新universe，不返回静默修复值。"""

    latest_date = pd.to_datetime(universe_history["snapshot_date"], errors="raise").max()
    latest_symbols = set(
        universe_history.loc[
            pd.to_datetime(universe_history["snapshot_date"]).eq(latest_date), "symbol"
        ].astype(str)
    )
    if set(coverage["symbol"]) != latest_symbols:
        raise ValueError("行情覆盖表没有逐只覆盖最新universe")
    available = coverage.loc[coverage["status"].eq("available")].set_index("symbol")
    if set(prices["symbol"].astype(str)) != set(available.index):
        raise ValueError("行情证券集合与available覆盖状态不一致")
    grouped = prices.groupby("symbol").agg(
        rows=("date", "size"), first_date=("date", "min"), last_date=("date", "max")
    )
    comparison = available[["rows", "first_date", "last_date"]].copy()
    comparison["rows"] = comparison["rows"].astype(int)
    if not grouped.sort_index().equals(comparison.sort_index()):
        raise ValueError("行情逐证券行数或起止日与覆盖清单不一致")


def build_market_factor_panel(prices: pd.DataFrame) -> pd.DataFrame:
    """仅用每个交易日及此前数据构造价格、流动性和波动率因子。"""

    required = {"symbol", "date", "close", "turnover"}
    missing = sorted(required.difference(prices.columns))
    if missing:
        raise ValueError(f"行情缺少因子字段: {missing}")
    frame = prices[["symbol", "date", "close", "turnover"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    frame = frame.sort_values(["symbol", "date"]).reset_index(drop=True)
    if frame.duplicated(["symbol", "date"]).any():
        raise ValueError("行情symbol/date不能重复")
    grouped = frame.groupby("symbol", sort=False)
    frame["listing_observation_days"] = grouped.cumcount() + 1
    frame["daily_return"] = grouped["close"].pct_change(fill_method=None)
    frame["momentum_20d"] = grouped["close"].pct_change(20, fill_method=None)
    frame["momentum_60d"] = grouped["close"].pct_change(60, fill_method=None)
    frame["short_term_reversal_5d"] = -grouped["close"].pct_change(
        5, fill_method=None
    )
    frame["average_turnover_20d"] = grouped["turnover"].transform(
        lambda values: values.rolling(20, min_periods=20).mean()
    )
    frame["liquidity_20d"] = frame["average_turnover_20d"].where(
        frame["average_turnover_20d"].gt(0)
    ).map(math.log)
    daily_illiquidity = (
        frame["daily_return"].abs()
        / frame["turnover"].where(frame["turnover"].gt(0))
        * 100_000_000
    )
    frame["amihud_illiquidity_20d"] = daily_illiquidity.groupby(
        frame["symbol"], sort=False
    ).transform(lambda values: values.rolling(20, min_periods=20).mean())
    frame["low_illiquidity_20d"] = -frame["amihud_illiquidity_20d"]
    frame["realized_volatility_20d"] = frame["daily_return"].groupby(
        frame["symbol"], sort=False
    ).transform(lambda values: values.rolling(20, min_periods=20).std(ddof=0)) * math.sqrt(252)
    frame["low_volatility_20d"] = -frame["realized_volatility_20d"]
    frame["forward_return_20d"] = grouped["close"].shift(-20) / frame["close"] - 1
    return frame


def build_market_signals(
    factor_panel: pd.DataFrame,
    *,
    frequency: str = "monthly",
    minimum_history_days: int = 80,
    minimum_average_turnover_rmb: float = 1_000_000,
) -> pd.DataFrame:
    """在每周或每月最后一个市场交易日生成可交易横截面。

    信号只使用当日收盘后已知字段；实际回测在下一个市场交易日收盘建仓。
    上市观察天数与20日平均成交额是明确的可交易性筛选条件。
    """

    if frequency not in {"weekly", "monthly"}:
        raise ValueError("frequency必须为weekly或monthly")
    if minimum_history_days < 60 or minimum_average_turnover_rmb < 0:
        raise ValueError("最短历史不能少于60日，最低成交额不能为负")
    frame = factor_panel.copy()
    frame["rebalance_period"] = frame["date"].dt.to_period(
        "W-FRI" if frequency == "weekly" else "M"
    )
    market_period_ends = frame.groupby("rebalance_period")["date"].max()
    frame = frame.loc[
        frame["date"].eq(frame["rebalance_period"].map(market_period_ends))
    ].copy()
    required_factors = [name for name in FACTOR_DIRECTIONS if name != "market_composite"]
    frame = frame.loc[
        frame["listing_observation_days"].ge(minimum_history_days)
        & frame["average_turnover_20d"].ge(minimum_average_turnover_rmb)
    ].dropna(subset=required_factors)
    if frame.empty:
        raise ValueError("没有证券满足月末因子与流动性条件")
    for factor in required_factors:
        frame[f"{factor}_rank_pct"] = frame.groupby("date")[factor].rank(
            method="average", pct=True
        )
    frame["trend_rank_pct"] = frame[
        ["momentum_20d_rank_pct", "momentum_60d_rank_pct"]
    ].mean(axis=1)
    frame["liquidity_quality_rank_pct"] = frame[
        ["liquidity_20d_rank_pct", "low_illiquidity_20d_rank_pct"]
    ].mean(axis=1)
    frame["market_composite"] = frame[
        [
            "trend_rank_pct",
            "short_term_reversal_5d_rank_pct",
            "liquidity_quality_rank_pct",
            "low_volatility_20d_rank_pct",
        ]
    ].mean(axis=1)
    frame["rebalance_frequency"] = frequency
    frame["eligible_universe_count"] = frame.groupby("date")["symbol"].transform(
        "nunique"
    )
    return frame.sort_values(["date", "symbol"]).reset_index(drop=True)


def build_monthly_market_signals(
    factor_panel: pd.DataFrame,
    *,
    minimum_history_days: int = 80,
    minimum_average_turnover_rmb: float = 1_000_000,
) -> pd.DataFrame:
    """兼容接口：构造月频市场因子横截面。"""

    return build_market_signals(
        factor_panel,
        frequency="monthly",
        minimum_history_days=minimum_history_days,
        minimum_average_turnover_rmb=minimum_average_turnover_rmb,
    )


def _portfolio_statistics(returns: pd.Series) -> dict[str, float]:
    equity = (1 + returns).cumprod()
    periods = max(len(returns) - 1, 1)
    total = float(equity.iloc[-1] - 1)
    drawdown = equity / equity.cummax() - 1
    return {
        "total_return_pct": total * 100,
        "annualised_return_pct": ((1 + total) ** (252 / periods) - 1) * 100,
        "annualised_volatility_pct": float(returns.std(ddof=0) * math.sqrt(252) * 100),
        "max_drawdown_pct": float(drawdown.min() * 100),
    }


def _simulate_targets(
    returns: pd.DataFrame,
    targets: dict[pd.Timestamp, dict[str, float]],
    *,
    initial_capital: float,
    commission_rate: float,
    minimum_commission: float,
    cash_annual_yield: float,
) -> tuple[pd.Series, float, float]:
    holdings = {symbol: 0.0 for symbol in returns.columns}
    cash = initial_capital
    previous_equity = initial_capital
    net_returns: list[float] = []
    total_fee = 0.0
    total_one_way_turnover = 0.0
    active_symbols: frozenset[str] = frozenset()
    cash_return = (1 + cash_annual_yield) ** (1 / 252) - 1
    for row_number, (date, daily_returns) in enumerate(returns.iterrows()):
        holdings = {
            symbol: value * (1 + float(daily_returns[symbol]))
            for symbol, value in holdings.items()
        }
        if row_number:
            cash *= 1 + cash_return
        before_fee = cash + sum(holdings.values())
        if date in targets:
            desired = targets[date]
            desired_symbols = frozenset(
                symbol for symbol, weight in desired.items() if weight > 0
            )
            if desired_symbols == active_symbols:
                equity = before_fee
                net_returns.append(equity / previous_equity - 1)
                previous_equity = equity
                continue
            orders = {
                symbol: before_fee * desired.get(symbol, 0.0) - holdings[symbol]
                for symbol in holdings
            }
            fee = sum(
                max(abs(order) * commission_rate, minimum_commission)
                for order in orders.values()
                if abs(order) > 1e-8
            )
            if fee >= before_fee:
                raise ValueError("交易费用耗尽组合资产")
            total_fee += fee
            total_one_way_turnover += sum(abs(order) for order in orders.values()) / (
                2 * before_fee
            )
            after_fee = before_fee - fee
            holdings = {
                symbol: after_fee * desired.get(symbol, 0.0) for symbol in holdings
            }
            cash = after_fee * (1 - sum(desired.values()))
            active_symbols = desired_symbols
        equity = cash + sum(holdings.values())
        net_returns.append(equity / previous_equity - 1)
        previous_equity = equity
    return pd.Series(net_returns, index=returns.index), total_fee, total_one_way_turnover


def run_market_factor_backtest(
    signals: pd.DataFrame,
    prices: pd.DataFrame,
    benchmark_prices: pd.DataFrame,
    *,
    top_fraction: float = 0.2,
    initial_capital: float = 100_000,
    commission_rate: float = 0.0001,
    minimum_commission: float = 5,
    cash_annual_yield: float = 0.015,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """测试月频纯多头top组，并与同期可交易等权及932047比较。"""

    if not 0 < top_fraction < 1:
        raise ValueError("top_fraction必须在0与1之间")
    if initial_capital <= 0 or min(commission_rate, minimum_commission) < 0:
        raise ValueError("资金必须为正，佣金参数不能为负")
    benchmark = benchmark_prices[["date", "close"]].copy()
    benchmark["date"] = pd.to_datetime(benchmark["date"], errors="raise")
    benchmark = benchmark.drop_duplicates("date").set_index("date")["close"].sort_index()
    calendar = benchmark.index
    signal_dates = sorted(signals["date"].unique())
    entry_map: dict[pd.Timestamp, pd.Timestamp] = {}
    for signal_date in signal_dates:
        if pd.Timestamp(signal_date) < calendar.min():
            continue
        future = calendar[calendar > pd.Timestamp(signal_date)]
        if len(future):
            entry_map[pd.Timestamp(signal_date)] = future[0]
    if not entry_map:
        raise ValueError("信号日后没有基准交易日")
    first_entry = min(entry_map.values())
    last_date = calendar.max()
    close = prices.pivot(index="date", columns="symbol", values="close").sort_index()
    close = close.reindex(calendar).ffill()
    close = close.loc[first_entry:last_date]
    returns = close.pct_change(fill_method=None).fillna(0.0)
    benchmark_returns = benchmark.loc[first_entry:last_date].pct_change(fill_method=None).fillna(0.0)

    common_targets: dict[pd.Timestamp, dict[str, float]] = {}
    factor_targets: dict[str, dict[pd.Timestamp, dict[str, float]]] = {
        factor: {} for factor in FACTOR_DIRECTIONS
    }
    selection_rows: list[dict[str, object]] = []
    for signal_date, entry_date in entry_map.items():
        group = signals.loc[signals["date"].eq(signal_date)].copy()
        tradable = [symbol for symbol in group["symbol"] if symbol in returns.columns and pd.notna(close.loc[entry_date, symbol])]
        group = group.loc[group["symbol"].isin(tradable)]
        if len(group) < 5:
            continue
        common_targets[entry_date] = {symbol: 1 / len(group) for symbol in group["symbol"]}
        selected_count = max(1, math.ceil(len(group) * top_fraction))
        for factor in FACTOR_DIRECTIONS:
            selected = group.nlargest(selected_count, factor)
            factor_targets[factor][entry_date] = {
                symbol: 1 / selected_count for symbol in selected["symbol"]
            }
            capacity = float(selected["average_turnover_20d"].min() * 0.05 * selected_count)
            for row in selected.itertuples(index=False):
                selection_rows.append(
                    {
                        "signal_date": signal_date,
                        "entry_date": entry_date,
                        "factor": factor,
                        "symbol": row.symbol,
                        "factor_value": getattr(row, factor),
                        "selected_count": selected_count,
                        "eligible_universe_count": len(group),
                        "capacity_at_5pct_adv_rmb": capacity,
                    }
                )
    if not common_targets:
        raise ValueError("没有至少5只可交易证券的月度事件")
    equal_returns, equal_fee, equal_turnover = _simulate_targets(
        returns,
        common_targets,
        initial_capital=initial_capital,
        commission_rate=commission_rate,
        minimum_commission=minimum_commission,
        cash_annual_yield=cash_annual_yield,
    )
    equal_stats = _portfolio_statistics(equal_returns)
    benchmark_stats = _portfolio_statistics(benchmark_returns)

    rows: list[dict[str, object]] = []
    for factor, targets in factor_targets.items():
        factor_returns, fee, turnover = _simulate_targets(
            returns,
            targets,
            initial_capital=initial_capital,
            commission_rate=commission_rate,
            minimum_commission=minimum_commission,
            cash_annual_yield=cash_annual_yield,
        )
        complete = signals.loc[signals["date"].isin(entry_map)].dropna(
            subset=[factor, "forward_return_20d"]
        )
        rank_ics = complete.groupby("date")[[factor, "forward_return_20d"]].apply(
            lambda group: group[factor].rank().corr(group["forward_return_20d"].rank()),
        ).dropna()
        rank_ic_std = float(rank_ics.std(ddof=1)) if len(rank_ics) > 1 else float("nan")
        rank_ic_t_stat = (
            float(rank_ics.mean() / (rank_ic_std / math.sqrt(len(rank_ics))))
            if rank_ic_std > 0
            else float("nan")
        )
        selections = pd.DataFrame(selection_rows)
        selected_factor = selections.loc[selections["factor"].eq(factor)]
        stats = _portfolio_statistics(factor_returns)
        rows.append(
            {
                "factor": factor,
                **stats,
                "excess_vs_equal_weight_pct": stats["total_return_pct"] - equal_stats["total_return_pct"],
                "excess_vs_932047_pct": stats["total_return_pct"] - benchmark_stats["total_return_pct"],
                "mean_rank_ic_20d": float(rank_ics.mean()),
                "rank_ic_naive_t_stat": rank_ic_t_stat,
                "positive_rank_ic_share": float(rank_ics.gt(0).mean()),
                "complete_rank_ic_periods": len(rank_ics),
                "rebalance_events": len(targets),
                "average_selected_count": selected_factor["selected_count"].mean(),
                "minimum_capacity_at_5pct_adv_rmb": selected_factor["capacity_at_5pct_adv_rmb"].min(),
                "commission_paid_rmb": fee,
                "cumulative_one_way_turnover": turnover,
                "equal_weight_total_return_pct": equal_stats["total_return_pct"],
                "benchmark_932047_total_return_pct": benchmark_stats["total_return_pct"],
                "start_date": returns.index.min(),
                "end_date": returns.index.max(),
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(selection_rows)


def build_phase2_data_gates(
    universe_history: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    verified_asset_type_count: int,
    verified_distribution_security_count: int,
) -> pd.DataFrame:
    """把Phase 2能否研究与能否部署所需的数据条件显式化。"""

    snapshots = pd.to_datetime(universe_history["snapshot_date"], errors="raise")
    current_symbols = universe_history.loc[
        snapshots.eq(snapshots.max()), "symbol"
    ].astype(str)
    priced_symbols = set(prices["symbol"].astype(str))
    rows = [
        ("current_universe_price_coverage", len(set(current_symbols) & priced_symbols), len(set(current_symbols)), "pass" if set(current_symbols).issubset(priced_symbols) else "fail", "当前快照证券均需有真实历史行情"),
        ("historical_universe_snapshots", snapshots.nunique(), 12, "pass" if snapshots.nunique() >= 12 else "fail", "至少12个月末快照，避免用当前名单回填历史"),
        ("verified_asset_types", verified_asset_type_count, len(set(current_symbols)), "pass" if verified_asset_type_count == len(set(current_symbols)) else "fail", "资产类型中性研究要求全部人工核验"),
        ("point_in_time_distribution_history", verified_distribution_security_count, len(set(current_symbols)), "pass" if verified_distribution_security_count == len(set(current_symbols)) else "fail", "分派收益率要求公告日和除息日历史"),
        ("point_in_time_nav_history", 0, len(set(current_symbols)), "fail", "P/NAV要求报告期、发布日期和基金份额版本"),
        ("government_bond_vintage", 0, 1, "fail", "利差因子需要当时可得的同期限国债收益率版本"),
    ]
    return pd.DataFrame(rows, columns=["gate", "observed", "required", "status", "reason"])
