import pandas as pd
import pytest

from creit_quant.fundamentals_parser import parse_annual_fundamentals_text


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
