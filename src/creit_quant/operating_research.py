"""跨资产REIT经营预期、公告事件与纯多头组合研究。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from creit_quant.database import (
    DEFAULT_CROSS_DOCUMENTS_PATH,
    DEFAULT_DOCUMENTS_PATH,
    DEFAULT_ENERGY_DOCUMENTS_PATH,
    load_assets,
    load_metric_definitions,
    load_operating_metrics,
    load_source_documents,
)
from creit_quant.energy_research import (
    build_energy_cross_section_signals,
    build_energy_point_in_time_features,
    run_energy_surprise_backtest,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FEATURE_DEFINITIONS_PATH = (
    ROOT / "data" / "reference" / "operating_feature_definitions.csv"
)
DEFAULT_FULL_MARKET_PRICE_PATH = (
    ROOT / "data" / "snapshots" / "phase2_full_market_adjusted_history.csv"
)
DEFAULT_BENCHMARK_PRICE_PATH = (
    ROOT / "data" / "snapshots" / "phase2_932047_total_return.csv"
)
DEFAULT_NON_ENERGY_METRIC_PATHS = (
    ROOT / "data" / "samples" / "180201_quarterly_operating_metrics.csv",
    ROOT / "data" / "samples" / "180301_quarterly_operating_metrics.csv",
    ROOT / "data" / "samples" / "508018_quarterly_operating_metrics.csv",
    ROOT / "data" / "samples" / "508056_quarterly_operating_metrics.csv",
)
DEFAULT_PHASE3_EVENTS_PATH = ROOT / "data" / "samples" / "phase3_asset_events.csv"
DEFAULT_PHASE3_ASSETS_PATH = ROOT / "data" / "samples" / "phase3_asset_master.csv"


def load_operating_feature_definitions(
    path: str | Path = DEFAULT_FEATURE_DEFINITIONS_PATH,
) -> pd.DataFrame:
    """读取跨资产主经营特征定义并校验稳定资产范围。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    required = {
        "symbol",
        "asset_type",
        "feature_id",
        "metric",
        "aggregation",
        "asset_ids",
        "comparison_lag_quarters",
        "source_note",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"跨资产特征定义缺少字段: {missing}")
    if frame["symbol"].duplicated().any() or frame["feature_id"].duplicated().any():
        raise ValueError("跨资产特征定义的symbol和feature_id必须唯一")
    if not frame["symbol"].str.fullmatch(r"\d{6}").all():
        raise ValueError("证券代码必须为六位数字")
    if not frame["aggregation"].eq("sum").all():
        raise ValueError("当前主特征只允许sum聚合；比率指标必须使用单一稳定资产范围")
    frame["comparison_lag_quarters"] = pd.to_numeric(
        frame["comparison_lag_quarters"], errors="raise"
    ).astype(int)
    if frame["comparison_lag_quarters"].le(0).any():
        raise ValueError("同比滞后季度数必须为正")
    if frame["asset_ids"].isna().any() or frame["asset_ids"].str.strip().eq("").any():
        raise ValueError("每个特征必须显式登记稳定资产范围")
    return frame


def load_default_operating_research_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    """合并能源、高速与物流经营观测及其正式公告登记。"""

    from creit_quant.energy_research import load_default_energy_research_inputs

    energy_metrics, _ = load_default_energy_research_inputs()
    metrics = pd.concat(
        [energy_metrics]
        + [load_operating_metrics(path) for path in DEFAULT_NON_ENERGY_METRIC_PATHS],
        ignore_index=True,
    )
    documents = pd.concat(
        [
            load_source_documents(DEFAULT_DOCUMENTS_PATH),
            load_source_documents(DEFAULT_ENERGY_DOCUMENTS_PATH),
            load_source_documents(DEFAULT_CROSS_DOCUMENTS_PATH),
        ],
        ignore_index=True,
    )
    identity = documents.groupby("source_url").agg(
        symbols=("symbol", "nunique"),
        periods=("period_end", "nunique"),
        document_types=("document_type", "nunique"),
    )
    if identity.gt(1).any(axis=1).any():
        raise ValueError("合并来源登记表中同一URL对应冲突的证券、期间或文档类型")
    documents["_verified_order"] = documents["verification_status"].eq(
        "human_verified"
    ).astype(int)
    documents = (
        documents.sort_values(["source_url", "_verified_order"])
        .drop_duplicates("source_url", keep="last")
        .drop(columns="_verified_order")
    )
    return metrics, documents


def audit_phase3_non_energy_database() -> dict[str, object]:
    """审计四条新增面板的资产键、单位、来源及报告期关系。"""

    metrics = pd.concat(
        [load_operating_metrics(path) for path in DEFAULT_NON_ENERGY_METRIC_PATHS],
        ignore_index=True,
    )
    assets = load_assets(DEFAULT_PHASE3_ASSETS_PATH)
    documents = load_source_documents(DEFAULT_CROSS_DOCUMENTS_PATH)
    definitions = load_metric_definitions()
    asset_keys = set(zip(assets["symbol"], assets["asset_id"], strict=False))
    metric_keys = set(zip(metrics["symbol"], metrics["asset_id"], strict=False))
    if not metric_keys.issubset(asset_keys):
        raise ValueError("Phase 3经营观测存在未登记资产键")
    canonical_units = definitions.set_index("metric")["canonical_unit"]
    linked_units = metrics["metric"].map(canonical_units)
    if linked_units.isna().any() or not metrics["unit"].eq(linked_units).all():
        raise ValueError("Phase 3经营观测含未登记指标或非规范单位")
    document_keys = documents.set_index("source_url")
    if not set(metrics["source_url"]).issubset(document_keys.index):
        raise ValueError("Phase 3经营观测存在未登记来源")
    linked = metrics.join(
        document_keys[["symbol", "period_end", "publication_date", "verification_status"]],
        on="source_url",
        rsuffix="_document",
        validate="many_to_one",
    )
    mismatch = (
        linked["symbol"].ne(linked["symbol_document"])
        | linked["period_end"].ne(linked["period_end_document"])
        | linked["publication_date"].ne(linked["publication_date_document"])
    )
    if mismatch.any():
        raise ValueError("Phase 3经营观测与来源证券、报告期或发布日期不一致")
    return {
        "securities": metrics["symbol"].nunique(),
        "assets": len(assets),
        "observations": len(metrics),
        "quarter_start": str(metrics["period_end"].min().to_period("Q")),
        "quarter_end": str(metrics["period_end"].max().to_period("Q")),
        "used_documents": metrics["source_url"].nunique(),
        "human_verified_observations": int(
            linked["verification_status"].eq("human_verified").sum()
        ),
    }


def build_operating_point_in_time_features(
    metrics: pd.DataFrame,
    documents: pd.DataFrame,
    definitions: pd.DataFrame,
) -> pd.DataFrame:
    """按真实公告日生成同比减历史均值的经营surprise。"""

    features = build_energy_point_in_time_features(metrics, documents, definitions)
    return features.merge(
        definitions[["symbol", "asset_type"]],
        on="symbol",
        how="left",
        validate="many_to_one",
    )


def build_operating_cross_section_signals(
    features: pd.DataFrame,
    *,
    minimum_securities: int = 6,
    top_n: int = 2,
) -> pd.DataFrame:
    """等待同季度报告到齐后，选经营surprise最高的纯多头组合。"""

    return build_energy_cross_section_signals(
        features, minimum_securities=minimum_securities, top_n=top_n
    )


def build_announcement_event_study(
    features: pd.DataFrame,
    security_prices: pd.DataFrame,
    benchmark_prices: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = (20, 60),
) -> pd.DataFrame:
    """计算每份公告后下一交易日入场的1/3个月绝对及基准超额收益。"""

    if not horizons or min(horizons) < 1:
        raise ValueError("事件窗口必须为正交易日数")
    prices = security_prices.pivot(index="date", columns="symbol", values="close")
    benchmark = benchmark_prices.set_index("date")["close"]
    rows: list[dict[str, object]] = []
    for event in features.dropna(subset=["operating_surprise_pct"]).itertuples(index=False):
        if event.symbol not in prices:
            continue
        panel = pd.concat(
            [prices[event.symbol].rename("security"), benchmark.rename("benchmark")],
            axis=1,
            join="inner",
        ).dropna()
        future = panel.index[panel.index > pd.Timestamp(event.publication_date)]
        if not len(future):
            continue
        entry = future[0]
        entry_position = panel.index.get_loc(entry)
        base = {
            "symbol": event.symbol,
            "asset_type": event.asset_type,
            "period_end": event.period_end,
            "publication_date": event.publication_date,
            "entry_date": entry,
            "operating_surprise_pct": event.operating_surprise_pct,
        }
        for horizon in horizons:
            end_position = entry_position + horizon
            if end_position >= len(panel):
                continue
            end = panel.index[end_position]
            security_return = (
                panel.iloc[end_position].security
                / panel.iloc[entry_position].security
                - 1
            )
            benchmark_return = (
                panel.iloc[end_position].benchmark
                / panel.iloc[entry_position].benchmark
                - 1
            )
            rows.append(
                {
                    **base,
                    "horizon_trading_days": horizon,
                    "exit_date": end,
                    "return_pct": security_return * 100,
                    "benchmark_return_pct": benchmark_return * 100,
                    "excess_return_pct": (security_return - benchmark_return) * 100,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["period_end", "symbol", "horizon_trading_days"]
    ).reset_index(drop=True)


def run_operating_surprise_backtest(
    signals: pd.DataFrame,
    security_prices: pd.DataFrame,
    benchmark_prices: pd.DataFrame,
    **kwargs: object,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """运行跨资产纯多头回测；成本为双向万一、最低5元，现金1.5%。"""

    summary, events, daily = run_energy_surprise_backtest(
        signals, security_prices, benchmark_prices, **kwargs
    )
    summary["portfolio"] = summary["portfolio"].replace(
        {
            "top_operating_surprise_net": "cross_asset_top_surprise_net",
            "energy_equal_weight_net": "eligible_reit_equal_weight_net",
        }
    )
    daily = daily.rename(
        columns={
            "energy_equal_weight_return": "eligible_reit_equal_weight_return",
            "energy_equal_weight_value": "eligible_reit_equal_weight_value",
            "energy_equal_weight_equity": "eligible_reit_equal_weight_equity",
            "energy_equal_weight_commission_rmb": "eligible_reit_equal_weight_commission_rmb",
        }
    )
    return summary, events, daily


def summarize_announcement_event_study(event_study: pd.DataFrame) -> pd.DataFrame:
    """按窗口汇总surprise与公告后收益的秩相关和均值。"""

    required = {
        "horizon_trading_days",
        "operating_surprise_pct",
        "return_pct",
        "excess_return_pct",
    }
    missing = sorted(required.difference(event_study.columns))
    if missing:
        raise ValueError(f"事件研究缺少字段: {missing}")
    rows = []
    for horizon, group in event_study.groupby("horizon_trading_days"):
        rows.append(
            {
                "horizon_trading_days": int(horizon),
                "events": len(group),
                "return_rank_correlation": group["operating_surprise_pct"].rank().corr(
                    group["return_pct"].rank()
                ),
                "excess_return_rank_correlation": group[
                    "operating_surprise_pct"
                ].rank().corr(group["excess_return_pct"].rank()),
                "mean_return_pct": group["return_pct"].mean(),
                "mean_excess_return_pct": group["excess_return_pct"].mean(),
            }
        )
    return pd.DataFrame(rows).sort_values("horizon_trading_days").reset_index(drop=True)


def run_phase3_robustness(
    features: pd.DataFrame,
    security_prices: pd.DataFrame,
    benchmark_prices: pd.DataFrame,
) -> pd.DataFrame:
    """固定检验持仓数和成本假设，避免只展示最优参数。"""

    cases = [
        ("top1_base_cost", 1, 0.0001, 5.0, 0.015),
        ("top2_base_cost", 2, 0.0001, 5.0, 0.015),
        ("top3_base_cost", 3, 0.0001, 5.0, 0.015),
        ("top2_five_bps", 2, 0.0005, 5.0, 0.015),
        ("top2_no_minimum", 2, 0.0001, 0.0, 0.015),
        ("top2_zero_cash_yield", 2, 0.0001, 5.0, 0.0),
    ]
    rows = []
    for case, top_n, commission, minimum, cash_yield in cases:
        signals = build_operating_cross_section_signals(
            features, minimum_securities=6, top_n=top_n
        )
        summary, _, _ = run_operating_surprise_backtest(
            signals,
            security_prices,
            benchmark_prices,
            commission_rate=commission,
            minimum_commission=minimum,
            cash_annual_yield=cash_yield,
        )
        lookup = summary.set_index("portfolio")
        strategy = lookup.loc["cross_asset_top_surprise_net"]
        equal_weight = lookup.loc["eligible_reit_equal_weight_net"]
        benchmark = lookup.loc["reit_total_return_index_benchmark"]
        rows.append(
            {
                "case": case,
                "top_n": top_n,
                "commission_rate_pct": commission * 100,
                "minimum_commission_rmb": minimum,
                "cash_annual_yield_pct": cash_yield * 100,
                "strategy_return_pct": strategy.total_return_pct,
                "equal_weight_return_pct": equal_weight.total_return_pct,
                "benchmark_return_pct": benchmark.total_return_pct,
                "excess_vs_equal_weight_pct": (
                    strategy.total_return_pct - equal_weight.total_return_pct
                ),
                "excess_vs_benchmark_pct": (
                    strategy.total_return_pct - benchmark.total_return_pct
                ),
                "max_drawdown_pct": strategy.max_drawdown_pct,
                "commission_paid_rmb": strategy.commission_paid_rmb,
            }
        )
    return pd.DataFrame(rows)


def summarize_phase3_gates(
    features: pd.DataFrame,
    signals: pd.DataFrame,
    event_study: pd.DataFrame,
    *,
    historical_universe_snapshots: int = 1,
    dpu_pit_securities: int = 1,
    nav_share_pit_securities: int = 0,
) -> pd.DataFrame:
    """输出明确的研究和部署闸门；样本不足时不宣称可部署。"""

    complete_20d = event_study.loc[event_study["horizon_trading_days"].eq(20)]
    values = [
        ("asset_types", features["asset_type"].nunique(), 3),
        ("securities", features["symbol"].nunique(), 8),
        ("cross_sections", signals["period_end"].nunique(), 12),
        ("complete_20d_events", len(complete_20d), 40),
        ("historical_universe_snapshots", historical_universe_snapshots, 12),
        ("dpu_pit_securities", dpu_pit_securities, 8),
        ("nav_share_pit_securities", nav_share_pit_securities, 8),
    ]
    rows = [
        {
            "gate": name,
            "observed": observed,
            "required": required,
            "passed": observed >= required,
        }
        for name, observed, required in values
    ]
    frame = pd.DataFrame(rows)
    frame["deployable"] = bool(frame["passed"].all())
    return frame
