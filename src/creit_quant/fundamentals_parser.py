"""定期报告基金份额与账面NAV抽取。"""

from __future__ import annotations

import re

import pandas as pd


def _number(value: str) -> float:
    return float(value.replace(",", ""))


def parse_annual_fundamentals_text(
    text: str, period_end: str | pd.Timestamp
) -> list[dict[str, object]]:
    """从年报文字层提取期末份额和账面每份NAV，不抽公允价值参考净值。"""

    compact = " ".join(text.split())
    if not compact:
        raise ValueError("PDF没有可用文字层")
    period = pd.Timestamp(period_end).normalize()
    share_patterns = [
        r"报告期末基金份额总额\s*([\d,]+(?:\.\d+)?)\s*份",
        r"本报告期期末基金份额总额\s*([\d,]+(?:\.\d+)?)\s*份",
        r"报告截止日.{0,140}?基金份额总额(?:为)?\s*([\d,]+(?:\.\d+)?)\s*份",
    ]
    shares = next(
        (match for pattern in share_patterns if (match := re.search(pattern, compact))),
        None,
    )
    if shares is None:
        raise ValueError("未找到报告期末基金份额总额")
    nav_patterns = [
        rf"报告截止日\s*{period.year}\s*年\s*12\s*月\s*31\s*日.{{0,80}}?基金份额净\s*值(?:为)?(?:人民币)?\s*([\d.]+)\s*元",
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
