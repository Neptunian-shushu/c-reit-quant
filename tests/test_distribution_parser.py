import pandas as pd
import pytest

from creit_quant.distribution_parser import (
    parse_distribution_text,
    resolve_distribution_documents,
)


def test_parse_distribution_text_handles_both_exchange_date_layouts():
    first = parse_distribution_text(
        "本次公募 REITs 分红方案（单位：元/10 份基金份额）0.3470 "
        "有关年度分红次数的说明 除息日 2026年4月14日（场内） "
        "2026年4月13日（场外） 现金红利发放日"
    )
    second = parse_distribution_text(
        "本次分红方案（单位：元 0.4000 /10 份基金份额）有关年度说明 " "除息日 场外：2026年5月7日 场内：2026年5月8日 现金红利发放日"
    )

    assert first["dpu_per_unit"] == pytest.approx(0.0347)
    assert first["ex_date"] == pd.Timestamp("2026-04-14")
    assert second["dpu_per_unit"] == pytest.approx(0.04)
    assert second["ex_date"] == pd.Timestamp("2026-05-08")


def test_parse_distribution_text_skips_narrative_scheme_reference():
    result = parse_distribution_text(
        "董事会复核本次分红方案并同意实施。若干说明。"
        "本次公募REITs分红方案（单位：元/10 0.2000 份基金份额）"
        "有关年度分红次数的说明 除息日 2025年12月9日（场内）"
        "2025年12月8日（场外）现金红利发放日"
    )

    assert result["dpu_per_unit"] == pytest.approx(0.02)


def test_parse_distribution_text_recovers_interleaved_pdf_table_columns():
    result = parse_distribution_text(
        "本次公募REITs分红方案（单位:元/1 4.278 0份基金份额）"
        "有关年度说明 权益登记日 2024年11月29日 "
        "2024年12月02日(场 除息日 2024年11月29日(场外) 内) "
        "现金红利发放日"
    )

    assert result["dpu_per_unit"] == pytest.approx(0.4278)
    assert result["ex_date"] == pd.Timestamp("2024-12-02")


def test_parse_distribution_text_ignores_registration_date_in_interleaved_table():
    result = parse_distribution_text(
        "本次分红方案（单位：0.6722 元/10份基金份额）有关年度说明 "
        "权益登记日 2023年4月17日 2023年4月18日（场 "
        "2023年4月17日（场 除息日 内）外）现金红利发放日"
    )

    assert result["ex_date"] == pd.Timestamp("2023-04-18")


def test_parse_distribution_text_ignores_interleaved_cash_payment_dates():
    result = parse_distribution_text(
        "本次分红方案（单位：0.6722 元/10份基金份额）有关年度说明 "
        "权益登记日 2023年4月17日 2023年4月18日（场 2023年4月17日（场 "
        "除息日 内）外）2023年4月21日（场 2023年4月19日（场 "
        "现金红利发放日 内）外）"
    )

    assert result["ex_date"] == pd.Timestamp("2023-04-18")


def test_parse_distribution_text_rejects_missing_unit_or_venue():
    with pytest.raises(ValueError, match="分红方案"):
        parse_distribution_text("本次分红方案（单位：元/份）0.1 有关年度说明 " "除息日 2026年5月8日（场内） 现金红利发放日")
    with pytest.raises(ValueError, match="场内"):
        parse_distribution_text("本次分红方案（单位：元/10份）0.1 有关年度说明 " "除息日 2026年5月8日 现金红利发放日")


def test_resolve_distribution_documents_prefers_explicit_correction():
    documents = pd.DataFrame(
        {
            "announcement_id": ["old", "new"],
            "symbol": ["508006", "508006"],
            "publication_date": ["2022-01-20", "2022-01-20"],
            "title": ["收益分配公告", "收益分配公告（以此为准）"],
            "source_url": ["https://sse/old", "https://sse/new"],
            "ex_date": ["2022-01-25", "2022-01-26"],
            "dpu_per_unit": [0.1, 0.2],
            "disclosed_rmb_per_10_units": [1.0, 2.0],
            "raw_text": ["old", "new"],
        }
    )

    result = resolve_distribution_documents(documents).iloc[0]

    assert result["source_url"] == "https://sse/new"
    assert result["dpu_per_unit"] == pytest.approx(0.2)


def test_resolve_distribution_documents_accepts_incremental_mixed_date_formats():
    documents = pd.DataFrame(
        {
            "announcement_id": ["old", "new"],
            "symbol": ["508001", "508002"],
            "publication_date": ["2024-01-01", "2024-02-01 00:00:00"],
            "title": ["分红公告", "分红公告"],
            "source_url": ["https://sse/old", "https://sse/new"],
            "ex_date": ["2024-01-03", pd.Timestamp("2024-02-05")],
            "dpu_per_unit": [0.1, 0.2],
            "disclosed_rmb_per_10_units": [1.0, 2.0],
            "raw_text": ["old", "new"],
        }
    )

    result = resolve_distribution_documents(documents)

    assert len(result) == 2
    assert pd.api.types.is_datetime64_any_dtype(result["ex_date"])


def test_resolve_distribution_documents_rejects_ex_date_before_publication():
    documents = pd.DataFrame(
        {
            "announcement_id": ["bad"],
            "symbol": ["508001"],
            "publication_date": ["2024-02-02"],
            "title": ["分红公告"],
            "source_url": ["https://sse/bad"],
            "ex_date": ["2024-02-01"],
            "dpu_per_unit": [0.1],
            "disclosed_rmb_per_10_units": [1.0],
            "raw_text": ["bad"],
        }
    )

    with pytest.raises(ValueError, match="不能早于"):
        resolve_distribution_documents(documents)
