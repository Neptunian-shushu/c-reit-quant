"""构建全市场基金数据可用性与资产边界事件候选表。"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def _date_range(frame: pd.DataFrame, column: str) -> tuple[object, object]:
    if frame.empty:
        return pd.NaT, pd.NaT
    values = pd.to_datetime(frame[column], errors="raise")
    return values.min(), values.max()


def build_fundamental_readiness(
    securities: pd.DataFrame,
    fundamentals: pd.DataFrame,
    distributions: pd.DataFrame,
    unadjusted_prices: pd.DataFrame,
) -> pd.DataFrame:
    """按证券汇总基金事实、DPU和不复权价格的研究就绪度。"""

    base_columns = [
        "symbol",
        "asset_type",
        "classification_status",
        "listing_status",
        "listing_date",
    ]
    missing = sorted(set(base_columns).difference(securities.columns))
    if missing:
        raise ValueError(f"证券覆盖表缺少字段: {missing}")
    result = securities[base_columns].copy()
    result["symbol"] = result["symbol"].astype(str).str.zfill(6)

    fact_rows = []
    for symbol, group in fundamentals.groupby("symbol"):
        first_period, last_period = _date_range(group, "period_end")
        metric_counts = group["metric"].value_counts()
        fact_rows.append(
            {
                "symbol": symbol,
                "fundamental_observations": len(group),
                "fundamental_first_period": first_period,
                "fundamental_last_period": last_period,
                "fund_share_observations": int(metric_counts.get("fund_shares", 0)),
                "nav_observations": int(metric_counts.get("nav_per_unit", 0)),
                "distributable_amount_observations": int(
                    metric_counts.get("distributable_amount_period", 0)
                ),
                "fundamental_hash_complete": bool(
                    group["source_sha256"]
                    .astype(str)
                    .str.fullmatch(r"[0-9a-f]{64}")
                    .all()
                ),
            }
        )
    result = result.merge(
        pd.DataFrame(
            fact_rows,
            columns=[
                "symbol",
                "fundamental_observations",
                "fundamental_first_period",
                "fundamental_last_period",
                "fund_share_observations",
                "nav_observations",
                "distributable_amount_observations",
                "fundamental_hash_complete",
            ],
        ),
        on="symbol",
        how="left",
    )

    distribution_rows = []
    for symbol, group in distributions.groupby("symbol"):
        first_ex_date, last_ex_date = _date_range(group, "ex_date")
        distribution_rows.append(
            {
                "symbol": symbol,
                "distribution_events": len(group),
                "first_ex_date": first_ex_date,
                "last_ex_date": last_ex_date,
                "distribution_hash_complete": bool(
                    group["source_sha256"]
                    .astype(str)
                    .str.fullmatch(r"[0-9a-f]{64}")
                    .all()
                ),
            }
        )
    result = result.merge(
        pd.DataFrame(
            distribution_rows,
            columns=[
                "symbol",
                "distribution_events",
                "first_ex_date",
                "last_ex_date",
                "distribution_hash_complete",
            ],
        ),
        on="symbol",
        how="left",
    )

    price_rows = []
    for symbol, group in unadjusted_prices.groupby("symbol"):
        first_price_date, last_price_date = _date_range(group, "date")
        price_rows.append(
            {
                "symbol": symbol,
                "unadjusted_price_rows": len(group),
                "first_unadjusted_price_date": first_price_date,
                "last_unadjusted_price_date": last_price_date,
            }
        )
    result = result.merge(
        pd.DataFrame(
            price_rows,
            columns=[
                "symbol",
                "unadjusted_price_rows",
                "first_unadjusted_price_date",
                "last_unadjusted_price_date",
            ],
        ),
        on="symbol",
        how="left",
    )

    count_columns = [
        "fundamental_observations",
        "fund_share_observations",
        "nav_observations",
        "distributable_amount_observations",
        "distribution_events",
        "unadjusted_price_rows",
    ]
    result[count_columns] = (
        result[count_columns]
        .apply(pd.to_numeric, errors="coerce")
        .fillna(0)
        .astype(int)
    )
    for column in ["fundamental_hash_complete", "distribution_hash_complete"]:
        result[column] = result[column].eq(True)
    result["fundamental_panel_status"] = "missing_fundamentals"
    has_facts = result["fund_share_observations"].gt(0) & result[
        "distributable_amount_observations"
    ].gt(0)
    result.loc[has_facts, "fundamental_panel_status"] = "cashflow_panel_available"
    result.loc[
        has_facts & result["nav_observations"].gt(0), "fundamental_panel_status"
    ] = "cashflow_and_nav_available"

    has_price = result["unadjusted_price_rows"].gt(0)
    result["p_nav_status"] = "missing_nav"
    result.loc[
        result["nav_observations"].gt(0), "p_nav_status"
    ] = "missing_full_market_unadjusted_price"
    result.loc[
        result["nav_observations"].gt(0) & has_price, "p_nav_status"
    ] = "data_available_pending_independent_review"
    result["dpu_yield_status"] = "missing_distribution_history"
    result.loc[
        result["distribution_events"].gt(0), "dpu_yield_status"
    ] = "missing_full_market_unadjusted_price"
    result.loc[
        result["distribution_events"].gt(0) & has_price, "dpu_yield_status"
    ] = "data_available_pending_independent_review"
    return result.sort_values("symbol").reset_index(drop=True)


def extract_fund_event_candidates(catalog: pd.DataFrame) -> pd.DataFrame:
    """从交易所标题提取扩募、更名和终止候选，不猜测生效日。"""

    required = {
        "announcement_id",
        "symbol",
        "publication_date",
        "title",
        "source_url",
    }
    missing = sorted(required.difference(catalog.columns))
    if missing:
        raise ValueError(f"公告目录缺少事件候选字段: {missing}")
    frame = catalog.copy()
    title = frame["title"].fillna("").astype(str)
    event_type = pd.Series("", index=frame.index)
    event_type.loc[title.str.contains("扩募")] = "expansion"
    event_type.loc[title.str.contains("变更名称|更名", regex=True)] = "fund_rename"
    event_type.loc[title.str.contains("终止上市|终止基金合同|退市|摘牌", regex=True)] = "termination"
    frame["event_type"] = event_type
    frame = frame.loc[frame["event_type"].ne("")].copy()
    frame["event_stage"] = "other_official_disclosure"
    expansion = frame["event_type"].eq("expansion")
    frame.loc[
        expansion & title.str.contains("拟扩募|决定.*扩募", regex=True), "event_stage"
    ] = "proposal"
    frame.loc[
        expansion & title.str.contains("提交.*申请", regex=True), "event_stage"
    ] = "application_submitted"
    frame.loc[
        expansion & title.str.contains("获得受理|申请受理", regex=True), "event_stage"
    ] = "application_accepted"
    frame.loc[
        expansion & title.str.contains("反馈意见"), "event_stage"
    ] = "exchange_feedback"
    frame.loc[
        expansion & title.str.contains("准予注册|审核通过|获得.*批复", regex=True),
        "event_stage",
    ] = "approval_or_registration"
    frame.loc[
        expansion & title.str.contains("询价|发售|认购|定价", regex=True), "event_stage"
    ] = "offering"
    frame.loc[
        expansion & title.str.contains("扩募份额上市交易", regex=True),
        "event_stage",
    ] = "expansion_units_listing_notice"
    frame.loc[
        expansion & title.str.contains("交割审计|完成交割", regex=True),
        "event_stage",
    ] = "asset_closing_disclosure"
    frame.loc[
        frame["event_type"].eq("fund_rename"), "event_stage"
    ] = "name_change_notice"
    frame.loc[
        frame["event_type"].eq("termination"), "event_stage"
    ] = "termination_notice"
    frame["event_date_candidate"] = frame["publication_date"]
    frame["event_date_semantics"] = "announcement_publication_only"
    frame["effective_date"] = ""
    frame["candidate_status"] = "official_title_candidate"
    columns = [
        "announcement_id",
        "symbol",
        "event_type",
        "event_stage",
        "event_date_candidate",
        "event_date_semantics",
        "effective_date",
        "candidate_status",
        "title",
        "source_url",
    ]
    return (
        frame[columns]
        .sort_values(["symbol", "event_date_candidate", "announcement_id"])
        .reset_index(drop=True)
    )


def build_share_change_events(
    fundamentals: pd.DataFrame, event_candidates: pd.DataFrame
) -> pd.DataFrame:
    """识别定期报告中首次出现的份额跳变，不倒推精确生效日。"""

    shares = fundamentals.loc[fundamentals["metric"].eq("fund_shares")].copy()
    same_period = shares.groupby(["symbol", "period_end"])["value"].nunique()
    if same_period.gt(1).any():
        raise ValueError("同一证券期末存在冲突份额")
    shares = (
        shares.sort_values(["symbol", "period_end", "publication_date"])
        .groupby(["symbol", "period_end"], as_index=False)
        .tail(1)
        .sort_values(["symbol", "period_end"])
    )
    shares["previous_shares"] = shares.groupby("symbol")["value"].shift()
    changes = shares.loc[
        shares["previous_shares"].notna()
        & shares["value"].ne(shares["previous_shares"])
    ].copy()
    expansion_symbols = set(
        event_candidates.loc[event_candidates["event_type"].eq("expansion"), "symbol"]
    )
    result = pd.DataFrame(
        {
            "symbol": changes["symbol"],
            "first_reported_period_end": changes["period_end"],
            "first_reported_publication_date": changes["publication_date"],
            "previous_reported_shares": changes["previous_shares"],
            "new_reported_shares": changes["value"],
            "share_change_ratio": changes["value"] / changes["previous_shares"] - 1,
            "has_expansion_announcement_candidate": changes["symbol"].isin(
                expansion_symbols
            ),
            "effective_date": "",
            "effective_date_status": "unknown_between_reports",
            "source_url": changes["source_url"],
            "source_sha256": changes["source_sha256"],
        }
    )
    return result.sort_values(["first_reported_period_end", "symbol"]).reset_index(
        drop=True
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data" / "samples")
    args = parser.parse_args()
    samples = ROOT / "data" / "samples"
    snapshots = ROOT / "data" / "snapshots"
    securities = pd.read_csv(
        samples / "reit_security_data_coverage.csv", dtype={"symbol": str}
    )
    fundamentals = pd.read_csv(
        samples / "full_market_fundamentals.csv", dtype={"symbol": str}
    )
    distributions = pd.read_csv(
        samples / "full_market_distributions.csv", dtype={"symbol": str}
    )
    full_market_price_path = snapshots / "full_market_unadjusted_prices.csv"
    price_path = (
        full_market_price_path
        if full_market_price_path.exists() and full_market_price_path.stat().st_size > 0
        else snapshots / "phase4_unadjusted_prices.csv"
    )
    prices = pd.read_csv(price_path, dtype={"symbol": str})
    catalog = pd.read_csv(
        snapshots / "reit_announcement_catalog.csv", dtype={"symbol": str}
    )
    readiness = build_fundamental_readiness(
        securities, fundamentals, distributions, prices
    )
    candidates = extract_fund_event_candidates(catalog)
    share_changes = build_share_change_events(fundamentals, candidates)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    readiness.to_csv(args.out_dir / "reit_fundamental_readiness.csv", index=False)
    candidates.to_csv(args.out_dir / "reit_fund_event_candidates.csv", index=False)
    share_changes.to_csv(args.out_dir / "reit_share_change_events.csv", index=False)
    print(
        f"基金数据覆盖 {readiness['fundamental_observations'].gt(0).sum()} / "
        f"{len(readiness)}只；P/NAV数据齐备 "
        f"{readiness['p_nav_status'].eq('data_available_pending_independent_review').sum()}只"
    )
    print(f"估值行情来源 {price_path.relative_to(ROOT)}")
    print(
        f"事件候选 {len(candidates)}份公告 / {candidates['symbol'].nunique()}只；"
        f"报表份额跳变 {len(share_changes)}次 / {share_changes['symbol'].nunique()}只"
    )


if __name__ == "__main__":
    main()
