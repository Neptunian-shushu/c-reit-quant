import pandas as pd
import pytest

from creit_quant.fundamentals_parser import (
    parse_annual_fundamentals_text,
    parse_periodic_fundamentals_text,
)


def test_parse_annual_fundamentals_prefers_book_nav_over_fair_value_reference():
    rows = parse_annual_fundamentals_text(
        "报告期末基金份额总额 500,000,000.00 份。"
        "数据和指标 2025年 2024年 期末不动产基金份额净值 3.1143 3.2320 "
        "期末不动产基金份额公允价值参考净值 3.2295 3.2688",
        "2025-12-31",
    )
    result = pd.DataFrame(rows).set_index("metric")

    assert result.loc["fund_shares", "value"] == 500_000_000
    assert result.loc["nav_per_unit", "value"] == pytest.approx(3.1143)


def test_parse_annual_fundamentals_handles_explicit_report_date_note():
    rows = parse_annual_fundamentals_text(
        "报告期末基金份额总额 960,326,121.00 份。"
        "报告截止日 2025 年 12 月 31 日，基金份额净值人民币 2.6374 元，"
        "基金份额公允价值参考净值人民币2.6607元。",
        "2025-12-31",
    )

    assert rows[1]["value"] == pytest.approx(2.6374)


def test_parse_annual_fundamentals_handles_note_with_wei_and_share_fallback():
    rows = parse_annual_fundamentals_text(
        "报告截止日 2025 年 12 月 31 日，基金份额净值为人民币 4.8642 元，" "基金份额总额为 1,000,000,000.00 份。",
        "2025-12-31",
    )

    assert rows[0]["value"] == 1_000_000_000
    assert rows[1]["value"] == pytest.approx(4.8642)


def test_parse_annual_fundamentals_handles_wrapped_table_label():
    rows = parse_annual_fundamentals_text(
        "本报告期期末基金份额总额 500,000,000.00 份 "
        "期末不动产基金份额净 3.0206 3.0667 3.0513 值 "
        "期末不动产基金份额公允价值参考净值 3.2",
        "2025-12-31",
    )

    assert rows[1]["value"] == pytest.approx(3.0206)


def test_parse_annual_fundamentals_rejects_missing_or_implausible_values():
    with pytest.raises(ValueError, match="份额总额"):
        parse_annual_fundamentals_text("期末不动产基金份额净值 3.1", "2025-12-31")
    with pytest.raises(ValueError, match="净值"):
        parse_annual_fundamentals_text("报告期末基金份额总额 500,000,000份", "2025-12-31")


def test_parse_quarterly_fundamentals_uses_current_period_not_year_to_date():
    rows = parse_periodic_fundamentals_text(
        "报告期末基金份额总额 500,000,000.00 份 "
        "3.3.1本报告期及近三年的可供分配金额 "
        "期间 可供分配金额 单位可供分配金额 备注 "
        "本期 15,535,458.56 0.0311 - 本年累计 22,184,464.72 0.0444 - "
        "3.3.2 本报告期实际分配金额",
        "2021-09-30",
        "quarterly_report",
    )
    result = pd.DataFrame(rows).set_index("metric")

    assert result.loc["fund_shares", "value"] == 500_000_000
    assert result.loc["distributable_amount_period", "value"] == pytest.approx(
        15_535_458.56
    )
    assert result.loc["distributable_amount_per_unit_period", "value"] == pytest.approx(
        0.0311
    )
    assert "nav_per_unit" not in result.index


def test_parse_semiannual_fundamentals_includes_direct_book_nav():
    rows = parse_periodic_fundamentals_text(
        "报告期末基金份额总额 500,000,000.00 份 "
        "3.3.1.1 本报告期及近三年的可供分配金额 "
        "本期 33,571,575.53 0.0671 - "
        "报告截止日 2022 年 06 月 30 日，基金份额净值 2.8590 元，"
        "基金份额总额 500,000,000.00 份。",
        "2022-06-30",
        "semiannual_report",
    )
    result = pd.DataFrame(rows).set_index("metric")

    assert result.loc["distributable_amount_period", "value"] == pytest.approx(
        33_571_575.53
    )
    assert result.loc["nav_per_unit", "value"] == pytest.approx(2.8590)


def test_parse_periodic_fundamentals_rejects_unknown_document_type():
    with pytest.raises(ValueError, match="只支持"):
        parse_periodic_fundamentals_text("text", "2025-12-31", "annual_report")


@pytest.mark.parametrize(
    "shares_text",
    [
        "报告期末基金份额总额（单位：份） 500,000,000.00",
        "报告期期末基金份额总额 500,000,000.00",
    ],
)
def test_parse_periodic_fundamentals_handles_alternate_share_labels(shares_text):
    rows = parse_periodic_fundamentals_text(
        f"{shares_text} 3.2.1 本报告期的可供分配金额 " "本期 55,277,306.09 0.1106 -",
        "2026-06-30",
        "quarterly_report",
    )

    assert rows[0]["value"] == 500_000_000


def test_parse_periodic_fundamentals_handles_intervening_remark_column():
    rows = parse_periodic_fundamentals_text(
        "报告期末基金份额总额 400,000,000.00 份 " "3.3.1 本报告期的可供分配金额 " "本期 15,833,410.73 - 0.0396",
        "2025-12-31",
        "quarterly_report",
    )

    assert rows[2]["value"] == pytest.approx(0.0396)


def test_parse_periodic_fundamentals_skips_early_section_reference():
    rows = parse_periodic_fundamentals_text(
        "3.3.1 本报告期及近三年的可供分配金额 详见第三章 " + "说明 " * 800 + "报告期末基金份额总额 900,000,000.00 份 "
        "3.3.1 本报告期及近三年的可供分配金额 "
        "本期 7,136,531.89 0.0079 -",
        "2024-12-31",
        "quarterly_report",
    )

    assert rows[1]["value"] == pytest.approx(7_136_531.89)
