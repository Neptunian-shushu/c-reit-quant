import pandas as pd
import pytest

from creit_quant.hydropower import (
    load_catchment_weather_features,
    load_fixed_lead_weather_forecast,
    load_hydropower_metrics,
    load_hydropower_weather_features,
    load_prelisting_hydropower_metrics,
    load_watershed_proxy,
)
from creit_quant.hydropower_model import (
    assess_phase1_completion,
    audit_fixed_lead_forecast_skill,
    build_annual_model_panel,
    expanding_annual_backtest,
    summarize_annual_backtest,
)


def _annual_panel() -> pd.DataFrame:
    return build_annual_model_panel(
        load_prelisting_hydropower_metrics(),
        load_hydropower_weather_features(),
        load_catchment_weather_features(),
    )


def test_annual_model_backtest_uses_only_earlier_years():
    predictions = expanding_annual_backtest(_annual_panel())

    assert len(predictions) == 20
    assert predictions["test_year"].unique().tolist() == [2018, 2019, 2020, 2021, 2022]
    assert (predictions["train_end_year"] < predictions["test_year"]).all()
    assert predictions.groupby("test_year")["model"].nunique().eq(4).all()


def test_weather_models_do_not_beat_historical_mean_out_of_sample():
    summary = summarize_annual_backtest(expanding_annual_backtest(_annual_panel())).set_index(
        "model"
    )

    assert summary.loc["historical_mean", "mae_10k_kwh"] == pytest.approx(3783.3649)
    assert summary.loc["catchment_precipitation_ols", "mae_10k_kwh"] == pytest.approx(
        4578.5619
    )
    assert summary.loc["point_precipitation_ols", "mae_10k_kwh"] == pytest.approx(
        6049.8869
    )
    assert summary.loc["catchment_precipitation_ols", "mae_skill_vs_mean_pct"] < 0
    assert summary.loc["point_precipitation_ols", "mae_skill_vs_mean_pct"] < 0


def test_phase1_research_complete_but_nowcast_not_deployable():
    panel = _annual_panel()
    predictions = expanding_annual_backtest(panel)
    completion = assess_phase1_completion(
        panel,
        load_hydropower_metrics(),
        load_fixed_lead_weather_forecast(),
        predictions,
        load_watershed_proxy(),
    )

    assert completion["phase1_research_complete"] is True
    assert completion["deployable_nowcast_ready"] is False
    assert completion["annual_years"] == 10
    assert completion["oos_years"] == 5
    assert completion["quarterly_periods"] == 9
    assert completion["fixed_lead_forecast_quarters"] == 9
    assert completion["forecast_periods_aligned"] is True
    assert completion["entities_aligned"] is True
    assert completion["boundary_verified"] is False
    assert completion["weather_model_beats_mean"] is False
    assert completion["forecast_is_area_weighted"] is False
    assert len(completion["reasons"]) == 4


def test_phase1_completion_reasons_only_report_failed_gates():
    panel = _annual_panel()
    completion = assess_phase1_completion(
        panel,
        load_hydropower_metrics(),
        load_fixed_lead_weather_forecast(),
        expanding_annual_backtest(panel),
        load_watershed_proxy(),
        minimum_quarters_for_nowcast=9,
    )

    assert not any("季度训练闸门" in reason for reason in completion["reasons"])
    assert any("流域级历史预报" in reason for reason in completion["reasons"])


def test_fixed_lead_forecast_is_checked_against_reanalysis():
    result = audit_fixed_lead_forecast_skill(
        load_fixed_lead_weather_forecast(), load_hydropower_weather_features()
    )

    assert result["quarters"] == 9
    assert result["correlation"] == pytest.approx(0.980358)
    assert result["mean_bias_mm"] == pytest.approx(-27.266667)
    assert result["mae_mm"] == pytest.approx(38.288889)
    assert result["forecast_to_reanalysis_ratio"] == pytest.approx(0.943556)
