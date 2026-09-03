"""生成全市场 C-REIT 数据库公告覆盖与质量缺口报告。"""

from __future__ import annotations

import argparse
from pathlib import Path

from creit_quant.database import (
    DEFAULT_CROSS_DOCUMENTS_PATH,
    DEFAULT_ENERGY_DOCUMENTS_PATH,
    load_source_documents,
)
from creit_quant.documents import merge_document_registries
from creit_quant.announcements import load_announcement_catalog
from creit_quant.master_data import (
    apply_security_overrides,
    build_security_master,
    classify_asset_type_candidates,
    load_security_overrides,
    load_universe_history,
)
from creit_quant.phase1_universe import DEFAULT_HISTORY_PATH
from creit_quant.phase1_announcements import DEFAULT_CATALOG_PATH
from creit_quant.quality import (
    build_announcement_catalog_coverage,
    build_document_coverage,
    build_quality_issues,
    summarise_quality_issues,
)


def main() -> None:
    """离线输出公告覆盖和待办质量队列。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe-history", default=str(DEFAULT_HISTORY_PATH))
    parser.add_argument("--announcement-catalog", default=str(DEFAULT_CATALOG_PATH))
    parser.add_argument("--out-dir", help="可选质量报告输出目录")
    args = parser.parse_args()

    master = apply_security_overrides(
        classify_asset_type_candidates(
            build_security_master(load_universe_history(args.universe_history))
        ),
        load_security_overrides(),
    )
    documents = merge_document_registries(
        load_source_documents(), load_source_documents(DEFAULT_CROSS_DOCUMENTS_PATH)
    )
    documents = merge_document_registries(
        documents, load_source_documents(DEFAULT_ENERGY_DOCUMENTS_PATH)
    )
    coverage = build_document_coverage(master, documents)
    catalog = load_announcement_catalog(args.announcement_catalog)
    catalog_coverage = build_announcement_catalog_coverage(master, catalog)
    issues = build_quality_issues(master, documents, coverage, catalog_coverage)
    summary = summarise_quality_issues(issues)

    print(f"全市场证券观察数: {len(master)}")
    print(f"已登记定期报告的证券: {coverage['periodic_reports'].gt(0).sum()}")
    print(f"尚未登记定期报告的证券: {coverage['periodic_reports'].eq(0).sum()}")
    statuses = catalog_coverage["catalog_coverage_status"].value_counts()
    print(f"交易所目录发现定期报告候选的证券: {statuses.get('periodic_candidates_found', 0)}")
    print(f"目录已有公告但暂未发现定期报告的证券: {statuses.get('catalog_no_periodic_candidate', 0)}")
    print(f"尚未接入公告目录的证券: {statuses.get('announcement_catalog_missing', 0)}")
    print("质量问题汇总:")
    print(summary.to_string(index=False))
    if args.out_dir:
        output = Path(args.out_dir)
        output.mkdir(parents=True, exist_ok=True)
        master.to_csv(output / "security_master_review.csv", index=False)
        coverage.to_csv(output / "document_coverage.csv", index=False)
        catalog_coverage.to_csv(output / "announcement_catalog_coverage.csv", index=False)
        issues.to_csv(output / "quality_issues.csv", index=False)
        summary.to_csv(output / "quality_summary.csv", index=False)
        print(f"报告已保存至: {output}")


if __name__ == "__main__":
    main()
