import pandas as pd

from creit_quant.hydropower import (
    aggregate_daily_weather,
    assess_model_readiness,
    audit_hydropower_extension,
    build_prelisting_weather_panel,
    load_hydrology_mapping,
    load_hydropower_metrics,
    load_hydropower_weather_features,
    load_prelisting_hydropower_metrics,
    pivot_quarterly_metrics,
)
from creit_quant.database import load_source_documents


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


def test_prelisting_hydropower_panel_preserves_annual_and_ytd_scopes():
    metrics = load_prelisting_hydropower_metrics()
    annual = metrics.loc[metrics["period_type"].eq("annual")]

    assert len(metrics) == 55
    assert annual["period_end"].nunique() == 10
    assert metrics["period_type"].eq("year_to_date").sum() == 6
    wide = annual.pivot(index="period_end", columns="metric", values="value")
    assert wide.loc[pd.Timestamp("2016-12-31"), "hydrological_generation_potential"] == 58202.16
    assert wide.loc[pd.Timestamp("2022-12-31"), "power_generation"] == 58504.21


def test_hydrology_mapping_does_not_invent_missing_coordinates():
    mapping = load_hydrology_mapping().set_index("mapping_id")

    assert len(mapping) == 4
    assert mapping.loc["wuyiqiao_upstream_catchment", "basin_area_km2"] == 1642
    assert pd.isna(mapping.loc["xigu_reservoir", "latitude"])
    assert mapping.loc["xigu_reservoir", "regulating_capacity_10k_m3"] == 8634.4


def test_reanalysis_weather_is_continuous_and_joinable_to_prelisting_years():
    weather = load_hydropower_weather_features()
    panel = build_prelisting_weather_panel(load_prelisting_hydropower_metrics(), weather)

    assert len(weather) == 54
    assert weather["period_end"].iloc[0] == pd.Timestamp("2013-03-31")
    assert weather["period_end"].iloc[-1] == pd.Timestamp("2026-06-30")
    assert weather["data_kind"].eq("ex_post_reanalysis_era5").all()
    assert len(panel) == 10
    assert panel["precipitation_sum_mm"].notna().all()


def test_hydropower_extension_relations_and_sources_are_audited():
    result = audit_hydropower_extension(
        load_prelisting_hydropower_metrics(),
        load_hydrology_mapping(),
        load_hydropower_weather_features(),
        load_source_documents(),
    )

    assert result == {
        "prelisting_observations": 55,
        "complete_annual_years": 10,
        "year_to_date_observations": 6,
        "hydrology_mappings": 4,
        "weather_quarters": 54,
        "annual_weather_join_rows": 10,
        "annual_weather_complete_rows": 10,
    }
