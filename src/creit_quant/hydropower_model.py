"""508026年度水文解释模型与Phase 1完成度审计。"""

from __future__ import annotations

import math

import pandas as pd

from creit_quant.hydropower import build_prelisting_weather_panel


def build_annual_model_panel(
    prelisting_metrics: pd.DataFrame,
    point_weather: pd.DataFrame,
    catchment_weather: pd.DataFrame,
) -> pd.DataFrame:
    """连接年度经营指标、点位天气和实验流域面积加权天气。"""

    panel = build_prelisting_weather_panel(prelisting_metrics, point_weather)
    catchment = catchment_weather.copy()
    catchment["year"] = catchment["period_end"].dt.year
    annual = catchment.groupby("year").agg(
        catchment_precipitation_sum_mm=("precipitation_sum_mm", "sum"),
        catchment_et0_sum_mm=("et0_fao_evapotranspiration_sum_mm", "sum"),
        catchment_weather_days=("weather_days", "sum"),
    )
    annual["period_end"] = pd.to_datetime(annual.index.astype(str) + "-12-31")
    return panel.merge(
        annual.reset_index(drop=True),
        on="period_end",
        how="left",
        validate="one_to_one",
    ).sort_values("period_end").reset_index(drop=True)


def _univariate_prediction(
    train_x: pd.Series, train_y: pd.Series, test_x: float
) -> float:
    centered = train_x - train_x.mean()
    denominator = float(centered.pow(2).sum())
    if denominator == 0:
        return float(train_y.mean())
    slope = float((centered * (train_y - train_y.mean())).sum() / denominator)
    return float(train_y.mean() + slope * (test_x - train_x.mean()))


def expanding_annual_backtest(
    panel: pd.DataFrame,
    *,
    target: str = "hydrological_generation_potential",
    minimum_train_years: int = 5,
) -> pd.DataFrame:
    """用扩展窗口比较均值、持续性和两个单变量天气模型。

    天气模型使用当年完整ERA5再分析，只属于解释性样本外检验，
    不是可交易回测。每次预测只用更早年度拟合参数，避免随机切分带来的时间泄漏。
    """

    features = {
        "point_precipitation_ols": "precipitation_sum_mm",
        "catchment_precipitation_ols": "catchment_precipitation_sum_mm",
    }
    required = {"period_end", target, *features.values()}
    missing = sorted(required.difference(panel.columns))
    if missing:
        raise ValueError(f"年度模型面板缺少字段: {missing}")
    if minimum_train_years < 3 or len(panel) <= minimum_train_years:
        raise ValueError("年度模型至少需要3个训练年度和1个测试年度")
    if panel[list(required)].isna().any().any():
        raise ValueError("年度模型输入不得缺失")

    ordered = panel.sort_values("period_end").reset_index(drop=True)
    rows: list[dict[str, object]] = []
    for index in range(minimum_train_years, len(ordered)):
        train = ordered.iloc[:index]
        test = ordered.iloc[index]
        actual = float(test[target])
        predictions = {
            "historical_mean": float(train[target].mean()),
            "previous_year": float(train[target].iloc[-1]),
        }
        predictions.update(
            {
                model: _univariate_prediction(
                    train[feature], train[target], float(test[feature])
                )
                for model, feature in features.items()
            }
        )
        for model, prediction in predictions.items():
            rows.append(
                {
                    "target": target,
                    "test_year": int(test["period_end"].year),
                    "train_start_year": int(train["period_end"].dt.year.min()),
                    "train_end_year": int(train["period_end"].dt.year.max()),
                    "train_years": len(train),
                    "model": model,
                    "actual": actual,
                    "prediction": prediction,
                    "error": prediction - actual,
                }
            )
    return pd.DataFrame(rows)


def summarize_annual_backtest(predictions: pd.DataFrame) -> pd.DataFrame:
    """汇总年度扩展窗口预测误差及相对历史均值的MAE技能分数。"""

    required = {"model", "actual", "prediction", "error", "test_year"}
    missing = sorted(required.difference(predictions.columns))
    if missing:
        raise ValueError(f"年度预测结果缺少字段: {missing}")
    rows = []
    for model, group in predictions.groupby("model", sort=False):
        absolute = group["error"].abs()
        rows.append(
            {
                "model": model,
                "oos_years": len(group),
                "test_start_year": int(group["test_year"].min()),
                "test_end_year": int(group["test_year"].max()),
                "mae_10k_kwh": float(absolute.mean()),
                "rmse_10k_kwh": float(math.sqrt(group["error"].pow(2).mean())),
                "mape_pct": float((absolute / group["actual"]).mean() * 100),
            }
        )
    result = pd.DataFrame(rows)
    baseline = result.loc[result["model"].eq("historical_mean"), "mae_10k_kwh"]
    if len(baseline) != 1:
        raise ValueError("年度预测结果必须包含唯一历史均值基线")
    result["mae_skill_vs_mean_pct"] = (
        1 - result["mae_10k_kwh"] / float(baseline.iloc[0])
    ) * 100
    return result.sort_values("mae_10k_kwh").reset_index(drop=True)


def audit_fixed_lead_forecast_skill(
    forecast: pd.DataFrame, reanalysis: pd.DataFrame
) -> dict[str, float | int]:
    """用同季度ERA5核验固定提前期降水预报的覆盖、偏差和相关性。"""

    actual = reanalysis[["period_end", "precipitation_sum_mm"]]
    joined = forecast.merge(actual, on="period_end", how="left", validate="one_to_one")
    if len(joined) != len(forecast) or joined["precipitation_sum_mm"].isna().any():
        raise ValueError("固定提前期预报无法完整连接同季度ERA5")
    error = joined["precipitation_forecast_sum_mm"] - joined["precipitation_sum_mm"]
    return {
        "quarters": len(joined),
        "correlation": float(
            joined["precipitation_forecast_sum_mm"].corr(
                joined["precipitation_sum_mm"]
            )
        ),
        "mean_bias_mm": float(error.mean()),
        "mae_mm": float(error.abs().mean()),
        "forecast_to_reanalysis_ratio": float(
            joined["precipitation_forecast_sum_mm"].sum()
            / joined["precipitation_sum_mm"].sum()
        ),
    }


def assess_phase1_completion(
    annual_panel: pd.DataFrame,
    quarterly_metrics: pd.DataFrame,
    fixed_lead_forecast: pd.DataFrame,
    predictions: pd.DataFrame,
    watershed_proxy: pd.DataFrame,
    *,
    minimum_quarters_for_nowcast: int = 12,
) -> dict[str, object]:
    """区分Phase 1研究闭环完成与可部署季度nowcast就绪状态。"""

    annual_years = annual_panel["period_end"].dt.year.nunique()
    quarterly_periods = quarterly_metrics["period_end"].nunique()
    forecast_quarters = fixed_lead_forecast["period_end"].nunique()
    oos_years = predictions["test_year"].nunique()
    metric_periods = set(quarterly_metrics["period_end"])
    forecast_periods = set(fixed_lead_forecast["period_end"])
    forecast_aligned = metric_periods == forecast_periods
    forecast_is_area_weighted = (
        "weather_area_id" in fixed_lead_forecast.columns
        and "weather_point_id" not in fixed_lead_forecast.columns
    )
    entity_columns = ["symbol", "asset_id"]
    entities_aligned = all(
        set(annual_panel[column])
        == set(quarterly_metrics[column])
        == set(fixed_lead_forecast[column])
        for column in entity_columns
    )
    errors = predictions.assign(absolute_error=predictions["error"].abs())
    model_mae = errors.groupby("model")["absolute_error"].mean()
    weather_models = model_mae.loc[model_mae.index.str.contains("precipitation")]
    weather_beats_mean = bool(
        not weather_models.empty
        and weather_models.min() < model_mae.loc["historical_mean"]
    )
    boundary_verified = bool(
        watershed_proxy["status"].eq("verified_official").all()
    )
    research_complete = all(
        [
            annual_years >= 10,
            oos_years >= 5,
            forecast_aligned,
            entities_aligned,
            len(watershed_proxy) == 1,
        ]
    )
    nowcast_ready = all(
        [
            quarterly_periods >= minimum_quarters_for_nowcast,
            forecast_aligned,
            entities_aligned,
            boundary_verified,
            weather_beats_mean,
            forecast_is_area_weighted,
        ]
    )
    reasons = []
    if quarterly_periods < minimum_quarters_for_nowcast:
        reasons.append(
            f"上市后仅{quarterly_periods}个季度，低于"
            f"{minimum_quarters_for_nowcast}季度训练闸门"
        )
    if not boundary_verified:
        reasons.append("候选流域面积与官方披露相差17.54%，不能视为正式边界")
    if not weather_beats_mean:
        reasons.append("天气模型在时间顺序样本外未战胜历史均值")
    if not forecast_is_area_weighted:
        reasons.append("固定提前期预报仍是点位数据，尚无流域级历史预报")
    return {
        "phase1_research_complete": research_complete,
        "deployable_nowcast_ready": nowcast_ready,
        "annual_years": annual_years,
        "oos_years": oos_years,
        "quarterly_periods": quarterly_periods,
        "fixed_lead_forecast_quarters": forecast_quarters,
        "forecast_periods_aligned": forecast_aligned,
        "entities_aligned": entities_aligned,
        "boundary_verified": boundary_verified,
        "weather_model_beats_mean": weather_beats_mean,
        "forecast_is_area_weighted": forecast_is_area_weighted,
        "reasons": reasons,
    }
