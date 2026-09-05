"""定期报告基金份额与账面NAV抽取。"""

from __future__ import annotations

import re

import pandas as pd


def _number(value: str) -> float:
    return float(value.replace(",", ""))


def _extract_shares(compact: str) -> re.Match[str]:
    share_patterns = [
        r"报告期末基金份额总额\s*([\d,]+(?:\.\d+)?)\s*份",
        r"报告期末基金份额总额\s*[（(]单位[：:]份[）)]\s*([\d,]+(?:\.\d+)?)",
        r"报告期期末基金份额总额\s*([\d,]+(?:\.\d+)?)",
        r"本报告期期末基金份额总额\s*([\d,]+(?:\.\d+)?)\s*份",
        r"报告截止日.{0,140}?基金份额总额(?:为)?\s*([\d,]+(?:\.\d+)?)\s*份",
    ]
    shares = next(
        (match for pattern in share_patterns if (match := re.search(pattern, compact))),
        None,
    )
    if shares is None:
        raise ValueError("未找到报告期末基金份额总额")
    return shares


def _extract_book_nav(compact: str, period: pd.Timestamp) -> re.Match[str]:
    nav_patterns = [
        rf"报告截止日[\s：:]*{period.year}\s*年\s*0?{period.month}\s*月\s*0?{period.day}\s*日.{{0,80}}?基金份额净\s*值(?:为)?(?:人民币)?\s*([\d.]+)\s*元",
        r"期末不动产基金份额净\s*值\s*([\d.]+)",
        r"期末基金份额净\s*值\s*([\d.]+)",
        r"期末(?:不动产)?基金份额净\s+([\d.]+)(?:\s+[\d.]+){0,4}\s+值",
    ]
    nav = next(
        (match for pattern in nav_patterns if (match := re.search(pattern, compact))),
        None,
    )
    if nav is None:
        raise ValueError("未找到期末账面基金份额净值")
    return nav


def parse_annual_fundamentals_text(
    text: str, period_end: str | pd.Timestamp
) -> list[dict[str, object]]:
    """从年报文字层提取期末份额和账面每份NAV，不抽公允价值参考净值。"""

    compact = " ".join(text.split())
    if not compact:
        raise ValueError("PDF没有可用文字层")
    period = pd.Timestamp(period_end).normalize()
    shares = _extract_shares(compact)
    nav = _extract_book_nav(compact, period)
    share_value = _number(shares.group(1))
    nav_value = _number(nav.group(1))
    if not 1_000_000 <= share_value <= 100_000_000_000:
        raise ValueError("基金份额总额超出合理校验范围")
    if not 0 < nav_value < 100:
        raise ValueError("账面每份NAV超出合理校验范围")
    evidence = f"报告期末基金份额总额 {shares.group(1)} 份；" f"期末账面基金份额净值 {nav_value:g} 元"
    return [
        {
            "metric": "fund_shares",
            "value": share_value,
            "unit": "shares",
            "raw_text": evidence,
        },
        {
            "metric": "nav_per_unit",
            "value": nav_value,
            "unit": "RMB_per_unit",
            "raw_text": evidence,
        },
    ]


def parse_periodic_fundamentals_text(
    text: str,
    period_end: str | pd.Timestamp,
    document_type: str,
) -> list[dict[str, object]]:
    """抽取季报／中报期末份额和本期可供分配金额。

    中报若直接披露报告截止日账面NAV，同时返回NAV；季报不推算NAV。
    """

    if document_type not in {"quarterly_report", "semiannual_report"}:
        raise ValueError("只支持季度报告和中期报告")
    compact = " ".join(text.split())
    if not compact:
        raise ValueError("PDF没有可用文字层")
    period = pd.Timestamp(period_end).normalize()
    shares = _extract_shares(compact)
    values = None
    sections = re.finditer(
        r"3\s*\.\s*[23]\s*\.\s*1(?:\s*\.\s*1)?\s*"
        r"本报告期(?:及近三年)?(?:的)?可供分配金额(.{0,1500})",
        compact,
    )
    for section in sections:
        values = re.search(
            r"本期\s+(-?[\d,]+(?:\.\d+)?)\s+(-?[\d.]+)\b",
            section.group(1),
        )
        if values is None:
            values = re.search(
                r"本期\s+(-?[\d,]+(?:\.\d+)?)\s+-\s+(-?[\d.]+)\b",
                section.group(1),
            )
        if values is not None:
            break
    if values is None:
        raise ValueError("未找到本期可供分配金额及单位金额")
    share_value = _number(shares.group(1))
    amount_value = _number(values.group(1))
    per_unit_value = _number(values.group(2))
    if not 1_000_000 <= share_value <= 100_000_000_000:
        raise ValueError("基金份额总额超出合理校验范围")
    if abs(amount_value) >= 1_000_000_000_000 or abs(per_unit_value) >= 100:
        raise ValueError("可供分配金额超出合理校验范围")
    evidence = (
        f"报告期末基金份额总额 {shares.group(1)} 份；"
        f"本期可供分配金额 {values.group(1)} 元；"
        f"单位可供分配金额 {values.group(2)} 元/份"
    )
    rows = [
        {
            "metric": "fund_shares",
            "value": share_value,
            "unit": "shares",
            "raw_text": evidence,
        },
        {
            "metric": "distributable_amount_period",
            "value": amount_value,
            "unit": "RMB",
            "raw_text": evidence,
        },
        {
            "metric": "distributable_amount_per_unit_period",
            "value": per_unit_value,
            "unit": "RMB_per_unit",
            "raw_text": evidence,
        },
    ]
    if document_type == "semiannual_report":
        nav = _extract_book_nav(compact, period)
        nav_value = _number(nav.group(1))
        if not 0 < nav_value < 100:
            raise ValueError("账面每份NAV超出合理校验范围")
        rows.append(
            {
                "metric": "nav_per_unit",
                "value": nav_value,
                "unit": "RMB_per_unit",
                "raw_text": evidence + f"；期末账面基金份净值 {nav_value:g} 元",
            }
        )
    return rows
