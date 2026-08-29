"""运行研究数据库关系审计并可导出 point-in-time 数据产品。"""

import argparse

import pandas as pd

from creit_quant.database import (
    DEFAULT_CROSS_DOCUMENTS_PATH,
    DEFAULT_ENERGY_DOCUMENTS_PATH,
    audit_periodic_document_sequences,
    audit_cross_asset_seed_database,
    audit_default_pilot_database,
    audit_energy_seed_database,
    audit_gas_panel_database,
    audit_asset_events,
    audit_panel_reviews,
    audit_annual_reconciliations,
    audit_solar_hydro_panel_database,
    audit_wind_panel_database,
    export_default_pilot_database,
    export_energy_seed_database,
    load_asset_events,
    load_assets,
    load_source_documents,
    load_operating_metrics,
    load_panel_reviews,
    load_annual_reconciliations,
    DEFAULT_GAS_METRICS_PATH,
    DEFAULT_SOLAR_HYDRO_METRICS_PATH,
    DEFAULT_WIND_METRICS_PATH,
    DEFAULT_ENERGY_ASSETS_PATH,
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
    energy = audit_energy_seed_database()
    print("\n能源扩面数据库种子审计通过")
    print(f"证券 / 资产: {energy['securities']} / {energy['assets']}")
    print(
        f"经营观测 / 人工核验来源: {energy['operating_observations']} / "
        f"{energy['verified_documents']}"
    )
    print(
        f"核心指标覆盖: {energy['available_cells']} / {energy['coverage_cells']} "
        f"({energy['coverage_pct']:.1f}%)"
    )
    wind = audit_wind_panel_database()
    print("\n508028 海上风电连续季度面板审计通过")
    print(
        f"季度: {wind['quarter_start']} 至 {wind['quarter_end']}，"
        f"经营观测 {wind['operating_observations']} 条"
    )
    print(
        f"核心指标覆盖: {wind['available_cells']} / {wind['coverage_cells']} "
        f"({wind['coverage_pct']:.1f}%)"
    )
    for label, panel_name, metrics_path, panel_audit in [
        (
            "508096 光伏／扩募水电",
            "508096_quarterly",
            DEFAULT_SOLAR_HYDRO_METRICS_PATH,
            audit_solar_hydro_panel_database(),
        ),
        (
            "180401 燃气发电",
            "180401_quarterly",
            DEFAULT_GAS_METRICS_PATH,
            audit_gas_panel_database(),
        ),
    ]:
        print(f"\n{label}连续季度面板审计通过")
        print(
            f"季度: {panel_audit['quarter_start']} 至 {panel_audit['quarter_end']}，"
            f"经营观测 {panel_audit['operating_observations']} 条"
        )
        print(
            f"核心指标覆盖: {panel_audit['available_cells']} / "
            f"{panel_audit['coverage_cells']} ({panel_audit['coverage_pct']:.1f}%)"
        )
        print(
            f"时点版本: {panel_audit['observation_versions']} 条，"
            f"其中修订版本 {panel_audit['revised_observations']} 条"
        )
        review = audit_panel_reviews(
            load_operating_metrics(metrics_path),
            load_panel_reviews(),
            panel_name=panel_name,
        )
        print(
            f"来源复核: {review['reviewed_documents']} 份，"
            f"交叉核对 {review['double_checked_documents']} 份"
        )
    wind_review = audit_panel_reviews(
        load_operating_metrics(DEFAULT_WIND_METRICS_PATH),
        load_panel_reviews(),
        panel_name="508028_quarterly",
    )
    print(
        f"508028 来源复核: {wind_review['reviewed_documents']} 份，"
        f"交叉核对 {wind_review['double_checked_documents']} 份"
    )
    annual_reconciliation = audit_annual_reconciliations(
        load_annual_reconciliations(),
        pd.concat(
            [
                load_operating_metrics(DEFAULT_SOLAR_HYDRO_METRICS_PATH),
                load_operating_metrics(DEFAULT_GAS_METRICS_PATH),
            ],
            ignore_index=True,
        ),
        load_source_documents(DEFAULT_ENERGY_DOCUMENTS_PATH),
    )
    print(
        f"2025年季度—年报勾稽: {annual_reconciliation['reconciliations']} 项，"
        f"完全一致 {annual_reconciliation['exact']} 项，"
        f"披露精度内差异 {annual_reconciliation['within_rounding']} 项，"
        f"年报调整 {annual_reconciliation['annual_true_up']} 项"
    )
    event_audit = audit_asset_events(
        load_asset_events(),
        load_assets(DEFAULT_ENERGY_ASSETS_PATH),
        load_source_documents(DEFAULT_ENERGY_DOCUMENTS_PATH),
    )
    print(
        f"能源资产事件: {event_audit['events']} 条，"
        f"其中资产级 {event_audit['asset_level_events']} 条"
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
    energy_sequences = audit_periodic_document_sequences(
        load_source_documents(DEFAULT_ENERGY_DOCUMENTS_PATH),
        ["180401", "508028", "508096"],
    )
    print("能源标的定期报告序列:")
    for row in energy_sequences.itertuples(index=False):
        print(
            f"  - {row.symbol}: {row.quarter_start} 至 {row.quarter_end}，"
            f"{row.covered_quarters}/{row.expected_quarters} 个季度，"
            f"登记 {row.registered_documents} 份，哈希 {row.hashed_documents} 份"
        )
    if args.as_of and not args.out_dir:
        parser.error("--as-of 必须与 --out-dir 一起使用")
    if args.out_dir:
        paths = export_default_pilot_database(args.out_dir, as_of=args.as_of)
        paths.update(export_energy_seed_database(args.out_dir))
        print("数据库产品已导出:")
        for name, path in paths.items():
            print(f"  - {name}: {path}")


if __name__ == "__main__":
    main()
