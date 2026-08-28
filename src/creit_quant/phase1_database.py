"""运行 508026 研究数据库关系与覆盖审计。"""

from creit_quant.database import audit_default_pilot_database


def main() -> None:
    """输出数据库覆盖和来源完整性摘要。"""

    audit = audit_default_pilot_database()
    print("508026 研究数据库审计通过")
    print(f"证券 / 资产: {audit['securities']} / {audit['assets']}")
    print(f"经营观测: {audit['operating_observations']} 条")
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


if __name__ == "__main__":
    main()
