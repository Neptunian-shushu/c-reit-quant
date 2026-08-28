"""Extensible candidate extraction for C-REIT operating disclosures.

This module deliberately stops at candidate extraction. PDF layout recovery,
table reconstruction, OCR, and human verification remain separate future
steps; regex matches alone are not a production-quality report parser.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Pattern

import pandas as pd

OPERATING_METRIC_COLUMNS = [
    "symbol",
    "period_end",
    "asset_type",
    "metric",
    "value",
    "unit",
    "publication_date",
    "source",
    "raw_text",
]


@dataclass(frozen=True)
class OperatingMetric:
    """One standardised long-format observation from a public disclosure."""

    symbol: str
    period_end: str
    asset_type: str
    metric: str
    value: float
    unit: str
    publication_date: str | None
    source: str
    raw_text: str

    def as_record(self) -> dict[str, object]:
        """Return a dictionary in the canonical column order."""

        record = asdict(self)
        return {column: record[column] for column in OPERATING_METRIC_COLUMNS}


@dataclass(frozen=True)
class MetricPattern:
    metric: str
    pattern: Pattern[str]


NUMBER = r"(?P<value>-?\d[\d,]*(?:\.\d+)?)"


def _pattern(metric: str, keywords: str, units: str) -> MetricPattern:
    expression = rf"(?P<raw>(?:{keywords})[^。；;\n]{{0,28}}?{NUMBER}\s*(?P<unit>{units}))"
    return MetricPattern(metric, re.compile(expression, re.IGNORECASE))


METRIC_PATTERNS = (
    _pattern("occupancy", r"出租率|occupancy", r"%|％"),
    _pattern("rentable_area", r"可供出租(?:建筑)?面积|可出租面积|rentable area", r"平方米|㎡|sq\.?\s*m"),
    _pattern("leased_area", r"实际出租(?:建筑)?面积|已出租面积|leased area", r"平方米|㎡|sq\.?\s*m"),
    _pattern("average_rent", r"平均租金|租金单价(?:水平)?|average rent", r"元/平方米/(?:天|月)|元/㎡/(?:天|月)"),
    _pattern("rent_collection_rate", r"租金收缴率|rent collection rate", r"%|％"),
    _pattern("tenant_concentration", r"租户集中度|前五大租户[^。；;\n]{0,12}(?:占比|比例)|tenant concentration", r"%|％"),
    _pattern(
        "traffic_volume",
        r"(?<!客车)(?<!货车)日均自然车流量|总收费车流量|(?<!客车)(?<!货车)车流量|traffic volume",
        r"万辆|辆次|辆/日|辆",
    ),
    _pattern("passenger_vehicle_traffic", r"客车(?:日均自然)?车流量|客车流量|passenger vehicle traffic", r"万辆|辆次|辆/日|辆"),
    _pattern("freight_vehicle_traffic", r"货车(?:日均自然)?车流量|货车流量|freight vehicle traffic", r"万辆|辆次|辆/日|辆"),
    _pattern("toll_revenue", r"通行费收入|toll revenue", r"亿元|万元|元|RMB"),
    _pattern("power_generation", r"发电量|power generation", r"亿千瓦时|万千瓦时|千瓦时|GWh|MWh"),
    _pattern("utilization_hours", r"有效发电小时|等效利用小时(?:数)?|利用小时(?:数)?|utili[sz]ation hours", r"小时|hours?"),
    _pattern("settled_electricity", r"结算电量|settled electricity", r"亿千瓦时|万千瓦时|千瓦时|GWh|MWh"),
    _pattern("settlement_tariff", r"结算(?:均价|电价)|settlement tariff", r"元/千瓦时|RMB/kWh"),
    _pattern("revenue", r"营业收入|revenue", r"亿元|万元|元|RMB"),
    _pattern("noi", r"运营净收益|\bNOI\b", r"亿元|万元|元|RMB"),
    _pattern("distributable_amount", r"可供分配金额|distributable amount", r"亿元|万元|元|RMB"),
    _pattern("distribution_per_unit", r"每份分派|每基金份额分派|distribution per unit|\bDPU\b", r"元/份|元|RMB"),
)


def extract_metric_candidates(
    text: str,
    *,
    symbol: str,
    period_end: str,
    asset_type: str,
    publication_date: str | None = None,
    source: str = "",
) -> list[OperatingMetric]:
    """Extract regex-based metric candidates from already recovered text.

    Values retain their reported units and scale. Percentage values therefore
    remain percentage points (for example, ``96.4`` with unit ``%``), avoiding
    silent transformations before human verification.
    """

    candidates: list[OperatingMetric] = []
    for specification in METRIC_PATTERNS:
        for match in specification.pattern.finditer(text):
            value = float(match.group("value").replace(",", ""))
            candidates.append(
                OperatingMetric(
                    symbol=str(symbol),
                    period_end=period_end,
                    asset_type=asset_type,
                    metric=specification.metric,
                    value=value,
                    unit=match.group("unit"),
                    publication_date=publication_date,
                    source=source,
                    raw_text=match.group("raw").strip(),
                )
            )
    return candidates


def metrics_to_frame(metrics: list[OperatingMetric]) -> pd.DataFrame:
    """Convert operating observations to the canonical long-format frame."""

    return pd.DataFrame(
        [metric.as_record() for metric in metrics], columns=OPERATING_METRIC_COLUMNS
    )


def validate_metric_frame(frame: pd.DataFrame) -> None:
    """Validate required columns and basic non-null/value constraints."""

    missing = [column for column in OPERATING_METRIC_COLUMNS if column not in frame]
    if missing:
        raise ValueError(f"missing operating metric columns: {missing}")
    required = ["symbol", "period_end", "asset_type", "metric", "value", "unit", "source"]
    if frame[required].isna().any().any():
        raise ValueError("required operating metric fields cannot be null")
    if not frame["symbol"].astype(str).str.fullmatch(r"\d{6}").all():
        raise ValueError("symbol values must be six digits")
    pd.to_numeric(frame["value"], errors="raise")
    pd.to_datetime(frame["period_end"], errors="raise")
