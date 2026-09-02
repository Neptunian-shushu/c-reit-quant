import pandas as pd
import pytest

from creit_quant.hydropower import (
    aggregate_catchment_daily_weather,
    aggregate_hourly_fixed_lead_forecast,
    aggregate_daily_weather,
    assess_model_readiness,
    audit_hydropower_extension,
    audit_watershed_weather_proxy,
    build_fixed_lead_forecast_snapshot,
    build_prelisting_weather_panel,
    derive_catchment_grid_weights,
    load_catchment_grid_weights,
    load_catchment_weather_features,
    load_fixed_lead_weather_forecast,
    load_hydrology_mapping,
    load_hydropower_metrics,
    load_hydropower_weather_features,
    load_prelisting_hydropower_metrics,
    load_watershed_proxy,
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


def test_experimental_watershed_is_fingerprinted_and_not_official():
    watershed = load_watershed_proxy().iloc[0]
    weights = load_catchment_grid_weights()

    assert watershed["status"] == "experimental_area_mismatch"
    assert watershed["modeled_area_km2"] == 1930
    assert watershed["official_area_km2"] == 1642
    assert watershed["relative_area_error_pct"] == pytest.approx(17.5396, rel=1e-5)
    assert len(weights) == 8
    assert weights["area_weight"].sum() == pytest.approx(1.0)


def test_catchment_weather_and_fixed_lead_forecast_have_complete_periods():
    catchment = load_catchment_weather_features()
    forecast = load_fixed_lead_weather_forecast()

    assert len(catchment) == 40
    assert catchment["period_end"].iloc[0] == pd.Timestamp("2013-03-31")
    assert catchment["period_end"].iloc[-1] == pd.Timestamp("2022-12-31")
    assert catchment["grid_points"].eq(8).all()
    assert len(forecast) == 9
    assert forecast["period_end"].iloc[0] == pd.Timestamp("2024-06-30")
    assert forecast["period_end"].iloc[-1] == pd.Timestamp("2026-06-30")
    assert forecast["forecast_hours"].sum() == 19704


def test_watershed_weather_relations_are_audited():
    result = audit_watershed_weather_proxy(
        load_watershed_proxy(),
        load_catchment_grid_weights(),
        load_catchment_weather_features(),
    )

    assert result == {
        "watersheds": 1,
        "grid_points": 8,
        "weather_quarters": 40,
        "area_weight_coverage": pytest.approx(1.0),
        "status": "experimental_area_mismatch",
    }


def test_catchment_weights_are_reproducible_from_geojson():
    derived = derive_catchment_grid_weights()
    stored = load_catchment_grid_weights()

    assert derived["lattice_points"].sum() == 1783
    assert derived["grid_point_id"].tolist() == stored["grid_point_id"].tolist()
    assert derived["area_weight"].tolist() == stored["area_weight"].tolist()


def test_fixed_lead_hourly_aggregation_requires_full_quarters():
    time = pd.date_range("2024-01-01", "2024-03-31 23:00", freq="h")
    hourly = pd.DataFrame(
        {"time": time, "precipitation_previous_day1": [0.1] * len(time)}
    )

    result = aggregate_hourly_fixed_lead_forecast(hourly)

    assert result["forecast_hours"].item() == 2184
    assert result["precipitation_forecast_sum_mm"].item() == pytest.approx(218.4)


def test_fixed_lead_snapshot_preserves_model_and_lead_semantics():
    time = pd.date_range("2024-01-01", "2024-03-31 23:00", freq="h")
    hourly = pd.DataFrame(
        {
            "latitude": [28.64] * len(time),
            "longitude": [101.72] * len(time),
            "time": time,
            "precipitation_previous_day1": [0.1] * len(time),
        }
    )

    result = build_fixed_lead_forecast_snapshot(
        hourly,
        symbol="508026",
        asset_id="asset",
        weather_point_id="point",
        model="gfs_global",
        lead_days=1,
        retrieved_at="2026-09-02",
    )

    assert result["data_kind"].item() == "historical_forecast_fixed_lead"
    assert result["model"].item() == "gfs_global"
    assert result["lead_offset_hours"].item() == 24
    assert result["retrieved_at"].item() == "2026-09-02"


def test_catchment_daily_weather_uses_registered_area_weights():
    dates = pd.date_range("2024-01-01", "2024-03-31", freq="D")
    daily = pd.concat(
        [
            pd.DataFrame(
                {
                    "grid_point_id": point,
                    "time": dates,
                    "precipitation_sum": value,
                    "rain_sum": value,
                    "snowfall_sum": 0.0,
                    "temperature_2m_mean": value * 10,
                    "et0_fao_evapotranspiration": value / 2,
                }
            )
            for point, value in [("a", 1.0), ("b", 3.0)]
        ],
        ignore_index=True,
    )
    weights = pd.DataFrame(
        {"grid_point_id": ["a", "b"], "area_weight": [0.25, 0.75]}
    )

    result = aggregate_catchment_daily_weather(daily, weights)

    assert result["weather_days"].item() == 91
    assert result["precipitation_sum_mm"].item() == pytest.approx(227.5)
    assert result["temperature_2m_mean_c"].item() == pytest.approx(25.0)


def test_catchment_daily_weather_rejects_misaligned_grid_calendars():
    days = pd.date_range("2024-01-01", "2024-03-31", freq="D")
    weather = pd.concat(
        [
            pd.DataFrame({"grid_point_id": "a", "time": days}),
            pd.DataFrame(
                {
                    "grid_point_id": "b",
                    "time": days.where(
                        days != pd.Timestamp("2024-01-01"),
                        pd.Timestamp("2024-04-01"),
                    ),
                }
            ),
        ],
        ignore_index=True,
    )
    for column in [
        "precipitation_sum",
        "rain_sum",
        "snowfall_sum",
        "temperature_2m_mean",
        "et0_fao_evapotranspiration",
    ]:
        weather[column] = 1.0
    weights = pd.DataFrame(
        {"grid_point_id": ["a", "b"], "area_weight": [0.5, 0.5]}
    )

    with pytest.raises(ValueError, match="日历覆盖不一致"):
        aggregate_catchment_daily_weather(weather, weights)
