"""508026 水电经营披露事件策略的轻量回测工具。"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from creit_quant.hydropower import pivot_quarterly_metrics

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DISTRIBUTIONS_PATH = ROOT / "data" / "samples" / "508026_distributions.csv"


def load_distributions(path: str | Path = DEFAULT_DISTRIBUTIONS_PATH) -> pd.DataFrame:
    """读取经正式收益分配公告核验的场内现金分派。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    required = {"symbol", "ex_date", "cash_per_unit", "source_url"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"分派文件缺少字段: {missing}")
    frame["ex_date"] = pd.to_datetime(frame["ex_date"], errors="raise")
    frame["cash_per_unit"] = pd.to_numeric(frame["cash_per_unit"], errors="raise")
    if (frame["cash_per_unit"] <= 0).any() or frame.duplicated(["symbol", "ex_date"]).any():
        raise ValueError("分派金额必须为正且同一标的除息日不能重复")
    return frame.sort_values("ex_date").reset_index(drop=True)


def build_generation_signals(metrics: pd.DataFrame) -> pd.DataFrame:
    """构造仅使用报告发布时已知信息的发电量同比信号。"""

    panel = pivot_quarterly_metrics(metrics)
    publications = metrics.groupby("period_end", as_index=False)["publication_date"].max()
    signals = panel.merge(publications, on="period_end", validate="one_to_one")
    signals = signals.dropna(subset=["generation_yoy_pct"]).copy()
    signals["hold_reit"] = signals["generation_yoy_pct"] > 0
    signals["signal"] = signals["hold_reit"].map({True: "reit", False: "cash"})
    return signals[
        [
            "period_end",
            "publication_date",
            "power_generation",
            "generation_yoy_pct",
            "hold_reit",
            "signal",
        ]
    ].reset_index(drop=True)


def prepare_price_panel(reit_history: pd.DataFrame, benchmark_history: pd.DataFrame) -> pd.DataFrame:
    """按共同交易日对齐 REIT 复权价格和全收益基准。"""

    for name, frame in {"reit": reit_history, "benchmark": benchmark_history}.items():
        if not {"date", "close"}.issubset(frame.columns):
            raise ValueError(f"{name} history must contain date and close")
    reit = reit_history[["date", "close"]].rename(columns={"close": "reit_close"}).copy()
    benchmark = benchmark_history[["date", "close"]].rename(
        columns={"close": "benchmark_close"}
    ).copy()
    for frame in (reit, benchmark):
        frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    prices = reit.merge(benchmark, on="date", how="inner", validate="one_to_one")
    prices = prices.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    if prices.empty or (prices[["reit_close", "benchmark_close"]] <= 0).any().any():
        raise ValueError("aligned price history is empty or contains non-positive closes")
    return prices


def _align_entries(signals: pd.DataFrame, dates: pd.Series) -> pd.DataFrame:
    aligned: list[dict[str, object]] = []
    trading_dates = pd.DatetimeIndex(dates)
    for row in signals.itertuples(index=False):
        candidates = trading_dates[trading_dates > pd.Timestamp(row.publication_date)]
        if len(candidates) == 0:
            continue
        record = row._asdict()
        record["entry_date"] = candidates[0]
        aligned.append(record)
    if not aligned:
        raise ValueError("no signal has a subsequent trading date in the price history")
    return pd.DataFrame(aligned).drop_duplicates("entry_date", keep="last")


def _performance_statistics(returns: pd.Series) -> dict[str, float]:
    equity = (1 + returns).cumprod()
    total_return = equity.iloc[-1] - 1
    observations = max(len(returns) - 1, 1)
    annualised_return = (1 + total_return) ** (252 / observations) - 1
    volatility = returns.std(ddof=0) * math.sqrt(252)
    drawdown = equity / equity.cummax() - 1
    return {
        "total_return_pct": float(total_return * 100),
        "annualised_return_pct": float(annualised_return * 100),
        "annualised_volatility_pct": float(volatility * 100),
        "max_drawdown_pct": float(drawdown.min() * 100),
    }


def run_generation_long_only_backtest(
    metrics: pd.DataFrame,
    reit_history: pd.DataFrame,
    benchmark_history: pd.DataFrame,
    *,
    initial_capital: float = 100_000.0,
    commission_rate: float = 0.0001,
    minimum_commission: float = 5.0,
    cash_annual_yield: float = 0.015,
    distributions: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """运行“发电量同比正增长持有 REIT，否则持有现金”的纯多头回测。

    信号在正式发布日期后首个共同交易日收盘生效。因此该入场日自身的
    收益仍属于旧仓位。佣金按成交金额双向收取，并支持每笔最低佣金。
    全收益指数只用于业绩比较，不作为可交易持仓。
    """

    if initial_capital <= 0:
        raise ValueError("initial_capital must be positive")
    if commission_rate < 0 or minimum_commission < 0:
        raise ValueError("commission inputs cannot be negative")
    if cash_annual_yield <= -1:
        raise ValueError("cash_annual_yield must be greater than -100%")
    prices = prepare_price_panel(reit_history, benchmark_history)
    signals = _align_entries(build_generation_signals(metrics), prices["date"])
    first_entry = signals["entry_date"].min()

    daily = prices.copy()
    daily["cash_distribution"] = 0.0
    if distributions is not None:
        cash = distributions[["ex_date", "cash_per_unit"]].rename(columns={"ex_date": "date"})
        daily = daily.merge(cash, on="date", how="left", validate="one_to_one")
        daily["cash_distribution"] = daily.pop("cash_per_unit").fillna(0.0)
    previous_close = daily["reit_close"].shift(1)
    daily["reit_return"] = (
        (daily["reit_close"] + daily["cash_distribution"]) / previous_close - 1
    ).fillna(0.0)
    daily["benchmark_return"] = daily["benchmark_close"].pct_change().fillna(0.0)
    daily["reit_weight"] = float("nan")
    for row in signals.itertuples(index=False):
        mask = daily["date"].eq(row.entry_date)
        daily.loc[mask, "reit_weight"] = 1.0 if row.hold_reit else 0.0
    daily["reit_weight"] = daily["reit_weight"].ffill().fillna(0.0)

    previous_reit = daily["reit_weight"].shift(1).fillna(0.0)
    daily_cash_return = (1 + cash_annual_yield) ** (1 / 252) - 1
    daily["cash_return"] = daily_cash_return
    daily["gross_return"] = (
        previous_reit * daily["reit_return"]
        + (1 - previous_reit) * daily["cash_return"]
    )
    daily.loc[daily["date"].le(first_entry), "gross_return"] = 0.0
    daily["trade_orders"] = (daily["reit_weight"] != previous_reit).astype(int)

    strategy_returns: list[float] = []
    strategy_values: list[float] = []
    commissions: list[float] = []
    equity = initial_capital
    for row in daily.itertuples(index=False):
        equity_before_fee = equity * (1 + row.gross_return)
        fee = (
            max(equity_before_fee * commission_rate, minimum_commission)
            if row.trade_orders
            else 0.0
        )
        equity_after_fee = equity_before_fee - fee
        strategy_returns.append(equity_after_fee / equity - 1)
        strategy_values.append(equity_after_fee)
        commissions.append(fee)
        equity = equity_after_fee
    daily["commission_rmb"] = commissions
    daily["strategy_return"] = strategy_returns
    daily["strategy_value"] = strategy_values

    daily = daily.loc[daily["date"] >= first_entry].copy().reset_index(drop=True)
    daily["buy_hold_reit_return"] = daily["reit_return"]
    daily["buy_hold_benchmark_return"] = daily["benchmark_return"]
    buy_hold_fee = max(initial_capital * commission_rate, minimum_commission)
    daily.loc[0, "buy_hold_reit_return"] = -buy_hold_fee / initial_capital
    daily.loc[0, "buy_hold_benchmark_return"] = 0.0
    daily["strategy_equity"] = daily["strategy_value"] / initial_capital
    daily["buy_hold_reit_equity"] = (1 + daily["buy_hold_reit_return"]).cumprod()
    daily["buy_hold_benchmark_equity"] = (
        1 + daily["buy_hold_benchmark_return"]
    ).cumprod()

    event_rows: list[dict[str, object]] = []
    for index, row in signals.reset_index(drop=True).iterrows():
        end_date = (
            signals.iloc[index + 1]["entry_date"]
            if index + 1 < len(signals)
            else daily["date"].max()
        )
        event_daily = daily.loc[
            daily["date"].gt(row["entry_date"]) & daily["date"].le(end_date)
        ]
        reit_event_return = (1 + event_daily["reit_return"]).prod() - 1
        benchmark_event_return = (1 + event_daily["benchmark_return"]).prod() - 1
        cash_event_return = (1 + event_daily["cash_return"]).prod() - 1
        event_rows.append(
            {
                **row.to_dict(),
                "holding_end": end_date,
                "reit_return_pct": reit_event_return * 100,
                "benchmark_return_pct": benchmark_event_return * 100,
                "selected_return_pct": (
                    reit_event_return * 100 if row["hold_reit"] else cash_event_return * 100
                ),
            }
        )
    events = pd.DataFrame(event_rows)
    events["reit_excess_return_pct"] = (
        events["reit_return_pct"] - events["benchmark_return_pct"]
    )

    summary_rows = []
    for name, column in [
        ("generation_long_cash_net", "strategy_return"),
        ("buy_hold_508026_net", "buy_hold_reit_return"),
        ("reit_total_return_index_benchmark", "buy_hold_benchmark_return"),
    ]:
        summary_rows.append({"portfolio": name, **_performance_statistics(daily[column])})
    summary = pd.DataFrame(summary_rows)
    summary["commission_paid_rmb"] = [daily["commission_rmb"].sum(), buy_hold_fee, 0.0]
    summary["start_date"] = daily["date"].min()
    summary["end_date"] = daily["date"].max()
    summary["signal_events"] = len(signals)
    summary["initial_capital_rmb"] = initial_capital
    summary["commission_rate_pct"] = commission_rate * 100
    summary["minimum_commission_rmb"] = minimum_commission
    summary["cash_annual_yield_pct"] = cash_annual_yield * 100
    return summary, events, daily
