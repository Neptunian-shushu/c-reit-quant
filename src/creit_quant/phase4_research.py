"""Phase 4基金时点数据库、联合纯多头信号与数据闸门。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from creit_quant.operating_research import run_operating_surprise_backtest


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FUNDAMENTALS_PATH = ROOT / "data" / "samples" / "phase4_fund_fundamentals.csv"
DEFAULT_DISTRIBUTIONS_PATH = ROOT / "data" / "samples" / "phase4_distributions.csv"
DEFAULT_DISTRIBUTION_EXCLUSIONS_PATH = (
    ROOT / "data" / "samples" / "phase4_distribution_exclusions.csv"
)
DEFAULT_UNADJUSTED_PRICES_PATH = (
    ROOT / "data" / "snapshots" / "phase4_unadjusted_prices.csv"
)


def load_fund_fundamentals(
    path: str | Path = DEFAULT_FUNDAMENTALS_PATH,
) -> pd.DataFrame:
    """读取季度基金指标和年末NAV的long-format时点快照。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    required = {
        "symbol",
        "period_end",
        "publication_date",
        "metric",
        "value",
        "unit",
        "source_url",
        "document_type",
        "verification_status",
        "raw_text",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"基金指标表缺少字段: {missing}")
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="raise")
    frame["publication_date"] = pd.to_datetime(
        frame["publication_date"], errors="raise"
    )
    frame["value"] = pd.to_numeric(frame["value"], errors="raise")
    if frame.duplicated(["symbol", "period_end", "publication_date", "metric"]).any():
        raise ValueError("基金指标时点键重复")
    if (frame["publication_date"] < frame["period_end"]).any():
        raise ValueError("基金指标发布日期不能早于报告期末")
    allowed = {
        "fund_shares": "shares",
        "distributable_amount_quarter": "RMB",
        "distributable_amount_per_unit_quarter": "RMB_per_unit",
        "nav_per_unit": "RMB_per_unit",
    }
    if not set(frame["metric"]).issubset(allowed):
        raise ValueError("基金指标表含未知metric")
    if not frame.apply(lambda row: row["unit"] == allowed[row["metric"]], axis=1).all():
        raise ValueError("基金指标单位与metric不一致")
    positive = frame["metric"].isin({"fund_shares", "nav_per_unit"})
    if frame.loc[positive, "value"].le(0).any():
        raise ValueError("基金份额和NAV必须为正")
    return frame.sort_values(
        ["symbol", "period_end", "publication_date", "metric"]
    ).reset_index(drop=True)


def load_phase4_distributions(
    path: str | Path = DEFAULT_DISTRIBUTIONS_PATH,
) -> pd.DataFrame:
    """读取实际分派公告；DPU按每份标准化并保留公告日与场内除息日。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    required = {
        "symbol",
        "publication_date",
        "ex_date",
        "dpu_per_unit",
        "disclosed_rmb_per_10_units",
        "source_url",
        "verification_status",
        "raw_text",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"分派表缺少字段: {missing}")
    frame["publication_date"] = pd.to_datetime(
        frame["publication_date"], errors="raise"
    )
    frame["ex_date"] = pd.to_datetime(frame["ex_date"], errors="raise")
    for column in ["dpu_per_unit", "disclosed_rmb_per_10_units"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    if frame.duplicated(["symbol", "publication_date"]).any():
        raise ValueError("同一证券公告日存在重复分派")
    if (
        frame["dpu_per_unit"].le(0).any()
        or (frame["ex_date"] < frame["publication_date"]).any()
    ):
        raise ValueError("DPU必须为正且除息日不能早于公告日")
    ratio_error = (
        frame["dpu_per_unit"] * 10 - frame["disclosed_rmb_per_10_units"]
    ).abs()
    if ratio_error.gt(1e-10).any():
        raise ValueError("每10份披露值与标准化DPU不一致")
    return frame.sort_values(["publication_date", "symbol"]).reset_index(drop=True)


def load_unadjusted_prices(
    path: str | Path = DEFAULT_UNADJUSTED_PRICES_PATH,
) -> pd.DataFrame:
    """读取冻结的不复权价格；该价格只用于估值与时点动量，不用于总收益基准。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    required = {"symbol", "date", "close", "adjustment", "source", "retrieved_at"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"不复权价格缺少字段: {missing}")
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    frame["close"] = pd.to_numeric(frame["close"], errors="raise")
    if not frame["adjustment"].eq("none").all() or frame["close"].le(0).any():
        raise ValueError("估值价格必须是正值不复权价格")
    if frame.duplicated(["symbol", "date"]).any():
        raise ValueError("不复权价格symbol/date重复")
    return frame.sort_values(["symbol", "date"]).reset_index(drop=True)


def audit_phase4_database(
    fundamentals: pd.DataFrame, distributions: pd.DataFrame
) -> dict[str, object]:
    """核对金额/份额勾稽并报告真实覆盖，不把机器抽取冒充人工核验。"""

    quarterly = fundamentals.loc[fundamentals["document_type"].eq("quarterly_report")]
    wide = quarterly.pivot_table(
        index=["symbol", "period_end", "publication_date", "source_url"],
        columns="metric",
        values="value",
        aggfunc="first",
    )
    required = {
        "fund_shares",
        "distributable_amount_quarter",
        "distributable_amount_per_unit_quarter",
    }
    if not required.issubset(wide.columns) or wide[list(required)].isna().any().any():
        raise ValueError("季度基金指标三项不完整")
    calculated = wide["distributable_amount_quarter"] / wide["fund_shares"]
    # 个别报告只把单位金额披露到小数点后两位，其余通常为四位。
    if (
        (calculated - wide["distributable_amount_per_unit_quarter"])
        .abs()
        .gt(0.0051)
        .any()
    ):
        raise ValueError("可供分配金额、份额与每份金额无法在披露精度内勾稽")
    nav = fundamentals.loc[fundamentals["metric"].eq("nav_per_unit")]
    return {
        "securities": fundamentals["symbol"].nunique(),
        "quarterly_reports": len(wide),
        "fundamental_observations": len(fundamentals),
        "nav_observations": len(nav),
        "nav_securities": nav["symbol"].nunique(),
        "distribution_events": len(distributions),
        "distribution_securities": distributions["symbol"].nunique(),
        "machine_extracted_observations": len(fundamentals) + len(distributions),
        "human_verified_observations": 0,
    }


def _latest_value(
    frame: pd.DataFrame, symbol: str, date: pd.Timestamp, metric: str
) -> float | None:
    rows = frame.loc[
        frame["symbol"].eq(symbol)
        & frame["metric"].eq(metric)
        & frame["publication_date"].le(date)
    ].sort_values("publication_date")
    return None if rows.empty else float(rows.iloc[-1]["value"])


def build_phase4_joint_signals(
    operating_signals: pd.DataFrame,
    fundamentals: pd.DataFrame,
    distributions: pd.DataFrame,
    unadjusted_prices: pd.DataFrame,
    *,
    minimum_securities: int = 6,
    top_n: int = 2,
) -> pd.DataFrame:
    """固定等权合成经营surprise、TTM DPU yield、NAV/price和20日总收益动量。"""

    if top_n < 1 or minimum_securities < top_n:
        raise ValueError("持仓数必须为正且不能超过最低证券数")
    rows: list[dict[str, object]] = []
    price_groups = {
        symbol: group.set_index("date").sort_index()
        for symbol, group in unadjusted_prices.groupby("symbol")
    }
    for signal in operating_signals.itertuples(index=False):
        decision = pd.Timestamp(signal.decision_date)
        history = price_groups.get(signal.symbol)
        if history is None:
            continue
        history = history.loc[history.index <= decision]
        if len(history) < 21:
            continue
        price = float(history.iloc[-1]["close"])
        prior_date = history.index[-21]
        prior_price = float(history.iloc[-21]["close"])
        known_paid = distributions.loc[
            distributions["symbol"].eq(signal.symbol)
            & distributions["publication_date"].le(decision)
            & distributions["ex_date"].le(decision)
        ]
        trailing = known_paid.loc[
            known_paid["ex_date"].gt(decision - pd.Timedelta(days=365)), "dpu_per_unit"
        ].sum()
        window_dpu = known_paid.loc[
            known_paid["ex_date"].gt(prior_date), "dpu_per_unit"
        ].sum()
        nav = _latest_value(fundamentals, signal.symbol, decision, "nav_per_unit")
        if nav is None or trailing <= 0:
            continue
        rows.append(
            {
                **signal._asdict(),
                "raw_operating_surprise_pct": signal.operating_surprise_pct,
                "signal_price_date": history.index[-1],
                "unadjusted_close": price,
                "ttm_dpu_per_unit": float(trailing),
                "ttm_distribution_yield": float(trailing / price),
                "nav_per_unit": nav,
                "nav_to_price": nav / price,
                "total_return_momentum_20d": (price + float(window_dpu)) / prior_price
                - 1,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("没有完整的Phase 4联合信号")
    kept = []
    for (_, _), group in frame.groupby(["period_end", "decision_date"]):
        if len(group) < minimum_securities:
            continue
        group = group.copy()
        factors = [
            "raw_operating_surprise_pct",
            "ttm_distribution_yield",
            "nav_to_price",
            "total_return_momentum_20d",
        ]
        for factor in factors:
            group[f"{factor}_rank_pct"] = group[factor].rank(method="average", pct=True)
        group["model_score"] = group[[f"{factor}_rank_pct" for factor in factors]].mean(
            axis=1
        )
        group["operating_surprise_pct"] = group["model_score"]
        group["phase4_universe_count"] = len(group)
        group["model_rank"] = (
            group["model_score"].rank(method="first", ascending=False).astype(int)
        )
        group["selected"] = group["model_rank"].le(top_n)
        kept.append(group)
    if not kept:
        raise ValueError("没有达到最低证券数的Phase 4横截面")
    return (
        pd.concat(kept, ignore_index=True)
        .sort_values(["period_end", "model_rank"])
        .reset_index(drop=True)
    )


def run_phase4_backtest(
    signals: pd.DataFrame,
    security_prices: pd.DataFrame,
    benchmark_prices: pd.DataFrame,
    **kwargs: object,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """按下一交易日执行联合top组，并与合资格等权和932047总收益比较。"""

    summary, events, daily = run_operating_surprise_backtest(
        signals, security_prices, benchmark_prices, **kwargs
    )
    summary["portfolio"] = summary["portfolio"].replace(
        {
            "cross_asset_top_surprise_net": "phase4_joint_top2_net",
            "eligible_reit_equal_weight_net": "phase4_eligible_equal_weight_net",
        }
    )
    return summary, events, daily


def run_phase4_robustness(
    signals: pd.DataFrame, security_prices: pd.DataFrame, benchmark_prices: pd.DataFrame
) -> pd.DataFrame:
    """固定报告联合/单因子、持仓数和成本敏感性，不按最优结果挑参数。"""

    cases = [
        ("joint_top2", "model_score", 2, 0.0001, 5.0, 0.015),
        (
            "operating_only_top2",
            "raw_operating_surprise_pct_rank_pct",
            2,
            0.0001,
            5.0,
            0.015,
        ),
        (
            "distribution_only_top2",
            "ttm_distribution_yield_rank_pct",
            2,
            0.0001,
            5.0,
            0.015,
        ),
        ("nav_only_top2", "nav_to_price_rank_pct", 2, 0.0001, 5.0, 0.015),
        (
            "momentum_only_top2",
            "total_return_momentum_20d_rank_pct",
            2,
            0.0001,
            5.0,
            0.015,
        ),
        ("joint_top1", "model_score", 1, 0.0001, 5.0, 0.015),
        ("joint_top3", "model_score", 3, 0.0001, 5.0, 0.015),
        ("joint_top2_five_bps", "model_score", 2, 0.0005, 5.0, 0.015),
        ("joint_top2_zero_cash", "model_score", 2, 0.0001, 5.0, 0.0),
    ]
    rows = []
    for case, score, top_n, commission, minimum, cash_yield in cases:
        trial = signals.copy()
        trial["operating_surprise_pct"] = trial[score]
        trial["selected"] = (
            trial.groupby("period_end")[score]
            .rank(method="first", ascending=False)
            .le(top_n)
        )
        summary, _, _ = run_phase4_backtest(
            trial,
            security_prices,
            benchmark_prices,
            commission_rate=commission,
            minimum_commission=minimum,
            cash_annual_yield=cash_yield,
        )
        lookup = summary.set_index("portfolio")
        strategy = lookup.loc["phase4_joint_top2_net"]
        equal_weight = lookup.loc["phase4_eligible_equal_weight_net"]
        benchmark = lookup.loc["reit_total_return_index_benchmark"]
        rows.append(
            {
                "case": case,
                "score": score,
                "top_n": top_n,
                "commission_rate_pct": commission * 100,
                "minimum_commission_rmb": minimum,
                "cash_annual_yield_pct": cash_yield * 100,
                "strategy_return_pct": strategy["total_return_pct"],
                "equal_weight_return_pct": equal_weight["total_return_pct"],
                "benchmark_return_pct": benchmark["total_return_pct"],
                "excess_vs_equal_weight_pct": strategy["total_return_pct"]
                - equal_weight["total_return_pct"],
                "excess_vs_benchmark_pct": strategy["total_return_pct"]
                - benchmark["total_return_pct"],
                "max_drawdown_pct": strategy["max_drawdown_pct"],
                "commission_paid_rmb": strategy["commission_paid_rmb"],
            }
        )
    return pd.DataFrame(rows)


def summarize_phase4_capacity(
    signals: pd.DataFrame, prices: pd.DataFrame, *, participation_rate: float = 0.05
) -> pd.DataFrame:
    """以入选证券过去20日平均成交额的5%估算等权组合容量下限。"""

    if not 0 < participation_rate <= 1:
        raise ValueError("成交额参与率必须在0与1之间")
    rows = []
    for (period_end, decision), group in signals.loc[signals["selected"]].groupby(
        ["period_end", "decision_date"]
    ):
        averages = {}
        for symbol in group["symbol"]:
            history = (
                prices.loc[prices["symbol"].eq(symbol) & prices["date"].le(decision)]
                .sort_values("date")
                .tail(20)
            )
            if len(history) == 20:
                averages[symbol] = float(history["turnover"].mean())
        if len(averages) != len(group):
            continue
        rows.append(
            {
                "period_end": period_end,
                "decision_date": decision,
                "selected_symbols": "|".join(group["symbol"]),
                "selected_count": len(group),
                "minimum_average_turnover_20d_rmb": min(averages.values()),
                "capacity_at_5pct_adv_rmb": min(averages.values())
                * participation_rate
                * len(group),
            }
        )
    return pd.DataFrame(rows)


def build_phase4_gates(
    signals: pd.DataFrame,
    fundamentals: pd.DataFrame,
    distributions: pd.DataFrame,
    *,
    universe_snapshots: int,
    distribution_exclusions: int,
) -> pd.DataFrame:
    """Phase 4完成不等于策略可部署；所有关键数据门槛逐项输出。"""

    nav_securities = fundamentals.loc[
        fundamentals["metric"].eq("nav_per_unit"), "symbol"
    ].nunique()
    share_securities = fundamentals.loc[
        fundamentals["metric"].eq("fund_shares"), "symbol"
    ].nunique()
    values = [
        ("historical_universe_snapshots", universe_snapshots, 12, "真实月末名单，不能用当前名单回填"),
        ("joint_cross_sections", signals["period_end"].nunique(), 12, "至少12个预注册联合横截面"),
        ("point_in_time_nav_securities", nav_securities, 8, "八只样本均有公告日NAV"),
        ("point_in_time_share_securities", share_securities, 8, "八只样本均有公告日份额"),
        (
            "distribution_securities",
            distributions["symbol"].nunique(),
            8,
            "八只样本均有实际DPU事件",
        ),
        (
            "distribution_extraction_exclusions",
            distribution_exclusions,
            0,
            "扫描PDF排除项必须人工或OCR复核清零",
        ),
        ("prospective_out_of_sample_quarters", 0, 4, "Phase 4规则冻结后的新增季度"),
    ]
    rows = [
        {
            "gate": name,
            "observed": observed,
            "required": required,
            "passed": observed >= required
            if name != "distribution_extraction_exclusions"
            else observed == required,
            "reason": reason,
        }
        for name, observed, required, reason in values
    ]
    frame = pd.DataFrame(rows)
    frame["deployable"] = bool(frame["passed"].all())
    return frame
