"""重建Phase 4历史成员与独立复核队列。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from creit_quant.announcements import load_announcement_catalog
from creit_quant.documents import enrich_document_metadata
from creit_quant.coverage import (
    build_document_extraction_queue,
    build_security_data_coverage,
)
from creit_quant.master_data import (
    build_month_end_tradable_universe,
    extract_official_asset_type_evidence,
    extract_official_listing_records,
    load_listing_date_overrides,
    load_security_overrides,
    load_universe_history,
)
from creit_quant.phase4_research import (
    load_fund_fundamentals,
    load_phase4_distributions,
)
from creit_quant.verification import (
    build_phase4_source_registry,
    build_phase4_verification_queue,
    merge_registered_source_metadata,
    summarize_verification_queue,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_PATH = ROOT / "data" / "snapshots" / "reit_announcement_catalog.csv"
DEFAULT_UNIVERSE_PATH = ROOT / "data" / "snapshots" / "reit_universe_history.csv"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "samples"
DOCUMENT_REGISTRIES = [
    ROOT / "data" / "samples" / "508026_source_documents.csv",
    ROOT / "data" / "samples" / "energy_source_documents.csv",
    ROOT / "data" / "samples" / "cross_asset_source_documents.csv",
]


def _enrich_sources_in_parallel(
    registry: pd.DataFrame, *, timeout: float, workers: int
) -> pd.DataFrame:
    """并行补齐缺失哈希；每个任务使用独立HTTP会话。"""

    if workers <= 0:
        raise ValueError("hash-workers必须为正整数")
    successful = registry.loc[
        registry["content_sha256"].fillna("").astype(str).ne("")
    ].copy()
    pending = registry.loc[
        registry["content_sha256"].fillna("").astype(str).eq("")
    ].copy()

    def fetch(row: pd.Series) -> pd.Series:
        return enrich_document_metadata(pd.DataFrame([row]), timeout=timeout).iloc[0]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        fetched = list(executor.map(fetch, [row for _, row in pending.iterrows()]))
    combined = pd.concat([successful, pd.DataFrame(fetched)], ignore_index=True)
    return combined.sort_values("source_url").reset_index(drop=True)


def main() -> None:
    """离线、幂等地重建上市记录、月末成员和复核队列。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--as-of-date", help="默认采用最新真实universe快照日")
    parser.add_argument(
        "--fetch-missing-hashes",
        action="store_true",
        help="联网补齐Phase 4来源SHA-256；响应只在内存中处理",
    )
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--hash-workers", type=int, default=8)
    args = parser.parse_args()

    catalog = load_announcement_catalog(args.catalog)
    termination = catalog["title"].fillna("").str.contains("终止上市|退市|摘牌|终止运作|终止基金合同")
    if termination.any():
        raise ValueError("公告目录出现终止交易候选，必须先人工登记终止日期")
    observed = load_universe_history(args.universe)
    latest_date = observed["snapshot_date"].max()
    latest = observed.loc[observed["snapshot_date"].eq(latest_date)].copy()
    listings = extract_official_listing_records(catalog, load_listing_date_overrides())
    asset_types = extract_official_asset_type_evidence(
        catalog, load_security_overrides()
    )
    evidence_as_of = max(latest_date, catalog["publication_date"].max())
    membership = build_month_end_tradable_universe(
        listings,
        latest,
        as_of_date=args.as_of_date or evidence_as_of,
    )
    fundamentals = load_fund_fundamentals()
    distributions = load_phase4_distributions()
    review_path = args.out_dir / "phase4_verification_queue.csv"
    source_path = args.out_dir / "phase4_source_registry.csv"
    existing = pd.read_csv(review_path, dtype=str) if review_path.exists() else None
    queue = build_phase4_verification_queue(
        fundamentals,
        distributions,
        document_registry_paths=DOCUMENT_REGISTRIES,
        existing=existing,
    )
    existing_sources = (
        pd.read_csv(source_path, dtype=str) if source_path.exists() else None
    )
    source_registry = build_phase4_source_registry(queue, existing_sources)
    source_registry = merge_registered_source_metadata(
        source_registry, DOCUMENT_REGISTRIES
    )
    if args.fetch_missing_hashes:
        source_registry = _enrich_sources_in_parallel(
            source_registry,
            timeout=args.timeout,
            workers=args.hash_workers,
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    listings.to_csv(args.out_dir / "reit_official_listing_records.csv", index=False)
    membership.to_csv(args.out_dir / "reit_tradable_universe_monthly.csv", index=False)
    asset_types.to_csv(args.out_dir / "reit_asset_type_evidence.csv", index=False)
    coverage = build_security_data_coverage(
        catalog, asset_types, listings, as_of_date=evidence_as_of
    )
    coverage.to_csv(args.out_dir / "reit_security_data_coverage.csv", index=False)
    audit_paths = [
        args.out_dir / "full_market_distribution_document_audit.csv",
        args.out_dir / "full_market_annual_document_audit.csv",
    ]
    audits = [
        pd.read_csv(path, dtype={"symbol": str})
        for path in audit_paths
        if path.exists()
    ]
    document_audit = pd.concat(audits, ignore_index=True) if audits else None
    extraction_queue = build_document_extraction_queue(
        catalog, asset_types, source_registry, document_audit
    )
    extraction_queue.to_csv(
        args.out_dir / "reit_document_extraction_queue.csv", index=False
    )
    source_registry.to_csv(source_path, index=False)
    queue = build_phase4_verification_queue(
        fundamentals,
        distributions,
        document_registry_paths=[*DOCUMENT_REGISTRIES, source_path],
        existing=queue,
    )
    queue.to_csv(review_path, index=False)
    listed_as_of = listings.loc[
        pd.to_datetime(listings["listing_date"]).le(evidence_as_of), "symbol"
    ]
    unlisted = sorted(set(latest["symbol"]).difference(listed_as_of))
    print(f"正式上市记录: {len(listings)}只；未上市观察对象: {len(unlisted)}只 {unlisted}")
    print(
        f"资产类型证据: {asset_types['asset_type'].ne('unknown').sum()} / "
        f"{len(asset_types)}只；人工核验 "
        f"{asset_types['classification_status'].eq('human_verified').sum()}只"
    )
    print(
        f"月末可交易名单: {membership['snapshot_date'].nunique()}个月 / {len(membership)}行，"
        f"截至{membership['snapshot_date'].max().date()}"
    )
    print(f"独立复核队列: {summarize_verification_queue(queue)}")
    print(
        f"Phase 4来源哈希: {source_registry['retrieval_status'].eq('success').sum()} / "
        f"{len(source_registry)} 个URL"
    )
    print(
        f"全市场解析队列: {len(extraction_queue)}份；"
        f"状态 {extraction_queue['extraction_status'].value_counts().to_dict()}"
    )


if __name__ == "__main__":
    main()
