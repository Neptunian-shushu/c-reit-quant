import pandas as pd

from creit_quant.hydropower import (
    aggregate_daily_weather,
    assess_model_readiness,
    load_hydropower_metrics,
    pivot_quarterly_metrics,
)


def test_verified_hydropower_sample_is_continuous_and_complete():
    metrics = load_hydropower_metrics()
    panel = pivot_quarterly_metrics(metrics)

    assert len(metrics) == 36
    assert len(panel) == 9
    assert panel["quarter"].tolist() == [
        "2024Q2",
        "2024Q3",
        "2024Q4",
        "2025Q1",
        "2025Q2",
        "2025Q3",
        "2025Q4",
        "2026Q1",
        "2026Q2",
    ]
    assert panel.loc[panel["quarter"] == "2025Q3", "power_generation"].item() == 22043.064


def test_daily_weather_aggregation_preserves_quarter_boundaries():
    weather = pd.DataFrame(
        {
            "time": ["2025-03-30", "2025-03-31", "2025-04-01", "2025-04-02"],
            "precipitation_sum": [0.0, 1.0, 2.0, 4.0],
            "temperature_2m_mean": [10.0, 12.0, 14.0, 16.0],
        }
    )

    result = aggregate_daily_weather(weather)

    assert result["period_end"].dt.strftime("%Y-%m-%d").tolist() == ["2025-03-31", "2025-06-30"]
    assert result["precipitation_sum_mm"].tolist() == [1.0, 6.0]
    assert result["wet_days"].tolist() == [1, 2]
    assert result["temperature_2m_mean_c"].tolist() == [11.0, 15.0]


def test_model_readiness_blocks_too_short_panel():
    panel = pivot_quarterly_metrics(load_hydropower_metrics())

    readiness = assess_model_readiness(panel, minimum_quarters=12)

    assert readiness["ready"] is False
    assert readiness["quarters"] == 9
    assert readiness["consecutive"] is True
    assert readiness["complete_core_metrics"] is True
    assert "低于 12 个季度门槛" in readiness["reasons"][0]
