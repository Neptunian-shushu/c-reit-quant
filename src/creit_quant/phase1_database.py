"""运行 508026 研究数据库关系审计并可导出 point-in-time 数据产品。"""

import argparse

from creit_quant.database import (
    DEFAULT_CROSS_DOCUMENTS_PATH,
    audit_periodic_document_sequences,
    audit_cross_asset_seed_database,
    audit_default_pilot_database,
    export_default_pilot_database,
    load_source_documents,
)


def main() -> None:
    """输出数据库覆盖和来源完整性摘要。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", help="可选规范数据库导出目录")
    parser.add_argument("--as-of", help="可选历史快照日期，格式 YYYY-MM-DD")
    args = parser.parse_args()

    audit = audit_default_pilot_database()
    print("508026 研究数据库审计通过")
    print(f"证券 / 资产: {audit['securities']} / {audit['assets']}")
    print(f"经营观测: {audit['operating_observations']} 条")
    print(
        f"时点版本: {audit['observation_versions']} 条，"
        f"其中修订版本 {audit['revised_observations']} 条"
    )
    print(
        f"试点指标覆盖: {audit['available_cells']} / {audit['coverage_cells']} "
        f"({audit['coverage_pct']:.1f}%)"
    )
    print(f"季度覆盖: {audit['quarter_start']} 至 {audit['quarter_end']}")
    print(f"指标定义: {audit['metric_definitions']} 项")
    print(
        f"公告来源: {audit['source_documents']} 份，"
        f"人工核验 {audit['verified_documents']} 份"
    )
    print(f"现金分派: {audit['distributions']} 条")
    cross = audit_cross_asset_seed_database()
    print("\n跨资产数据库种子审计通过")
    print(f"证券 / 资产: {cross['securities']} / {cross['assets']}")
    print(
        f"经营观测 / 已使用来源: {cross['operating_observations']} / "
        f"{cross['source_documents_used']}"
    )
    print(
        f"定期报告登记: {cross['source_documents']} 份，"
        f"其中元数据已核验 {cross['metadata_verified_documents']} 份"
    )
    print(
        f"核心指标覆盖: {cross['available_cells']} / {cross['coverage_cells']} "
        f"({cross['coverage_pct']:.1f}%)"
    )
    sequences = audit_periodic_document_sequences(
        load_source_documents(DEFAULT_CROSS_DOCUMENTS_PATH), ["508018", "508056"]
    )
    print("扩面标的定期报告序列:")
    for row in sequences.itertuples(index=False):
        print(
            f"  - {row.symbol}: {row.quarter_start} 至 {row.quarter_end}，"
            f"{row.covered_quarters}/{row.expected_quarters} 个季度，"
            f"登记 {row.registered_documents} 份，哈希 {row.hashed_documents} 份"
        )
    if args.as_of and not args.out_dir:
        parser.error("--as-of 必须与 --out-dir 一起使用")
    if args.out_dir:
        paths = export_default_pilot_database(args.out_dir, as_of=args.as_of)
        print("数据库产品已导出:")
        for name, path in paths.items():
            print(f"  - {name}: {path}")


if __name__ == "__main__":
    main()
