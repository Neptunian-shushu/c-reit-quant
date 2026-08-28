import pandas as pd
import pytest

from creit_quant.report_parser import (
    OPERATING_METRIC_COLUMNS,
    extract_metric_candidates,
    metrics_to_frame,
    validate_metric_frame,
)


def test_extracts_chinese_operating_metric_candidates():
    text = (
        "报告期末可供出租面积为 77,894.28 平方米，出租率为 96.43%，"
        "租金收缴率为 97.10%。2024年发电量 50,312.1216 万千瓦时，"
        "有效发电小时数 3,672 小时。"
    )

    candidates = extract_metric_candidates(
        text,
        symbol="508026",
        period_end="2024-12-31",
        asset_type="hydropower",
        publication_date="2025-03-28",
        source="annual-report.pdf",
    )
    by_metric = {candidate.metric: candidate for candidate in candidates}

    assert by_metric["rentable_area"].value == 77894.28
    assert by_metric["occupancy"].value == 96.43
    assert by_metric["rent_collection_rate"].value == 97.10
    assert by_metric["power_generation"].value == 50312.1216
    assert by_metric["utilization_hours"].value == 3672
    assert "发电量" in by_metric["power_generation"].raw_text


def test_standardised_frame_has_canonical_long_schema():
    candidates = extract_metric_candidates(
        "日均自然车流量 24,331 辆次，通行费收入 43,214.0 万元。",
        symbol="508018",
        period_end="2024-12-31",
        asset_type="toll_road",
        source="annual-report.pdf",
    )

    frame = metrics_to_frame(candidates)

    assert list(frame.columns) == OPERATING_METRIC_COLUMNS
    assert set(frame["metric"]) == {"traffic_volume", "toll_revenue"}
    validate_metric_frame(frame)


def test_schema_validation_rejects_missing_and_bad_symbols():
    with pytest.raises(ValueError, match="missing operating metric columns"):
        validate_metric_frame(pd.DataFrame({"symbol": ["508018"]}))

    row = {column: "sample" for column in OPERATING_METRIC_COLUMNS}
    row.update(period_end="2024-12-31", value=1.0, symbol="bad")
    with pytest.raises(ValueError, match="six digits"):
        validate_metric_frame(pd.DataFrame([row]))
