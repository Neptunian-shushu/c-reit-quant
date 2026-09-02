"""Phase 1 水电试点覆盖审计与天气面板构建入口。"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from creit_quant.hydropower import (
    assess_model_readiness,
    audit_watershed_weather_proxy,
    build_fixed_lead_forecast_snapshot,
    join_operations_weather,
    load_catchment_weather_features,
    load_catchment_grid_weights,
    load_fixed_lead_weather_forecast,
    load_hydropower_asset,
    load_hydropower_metrics,
    load_hydropower_weather_features,
    load_prelisting_hydropower_metrics,
    load_watershed_proxy,
    pivot_quarterly_metrics,
)
from creit_quant.hydropower_model import (
    assess_phase1_completion,
    audit_fixed_lead_forecast_skill,
    build_annual_model_panel,
    expanding_annual_backtest,
    summarize_annual_backtest,
)
from creit_quant.weather import (
    WeatherAPIError,
    fetch_historical_weather,
    fetch_previous_runs,
)


def main() -> None:
    """运行覆盖审计；按需联网构建天气连接面板。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fetch-weather",
        action="store_true",
        help="从 Open-Meteo 获取点位再分析天气",
    )
    parser.add_argument(
        "--weather-model",
        default="era5",
        help="Open-Meteo固定历史模型；默认era5，避免best-match跨期模型切换",
    )
    parser.add_argument("--out", default=None, help="可选的季度面板 CSV 输出路径")
    parser.add_argument(
        "--model-results-out",
        default=None,
        help="可选的年度扩展窗口预测结果CSV输出路径",
    )
    parser.add_argument(
        "--fetch-fixed-lead",
        action="store_true",
        help="联网验证并构建GFS提前24小时历史预报季度快照",
    )
    parser.add_argument(
        "--fixed-lead-out",
        default=None,
        help="固定提前期历史预报快照的可选CSV输出路径",
    )
    args = parser.parse_args()

    metrics = load_hydropower_metrics()
    asset = load_hydropower_asset().iloc[0]
    panel = pivot_quarterly_metrics(metrics)
    readiness = assess_model_readiness(panel)

    print(f"试点标的: {asset['symbol']} / {asset['asset_name']}")
    print(
        f"季度覆盖: {panel['quarter'].min()} 至 {panel['quarter'].max()}，"
        f"共 {len(panel)} 个季度"
    )
    print(f"核心指标: {', '.join(sorted(set(metrics['metric'])))}")
    print(f"Nowcast 建模就绪: {'是' if readiness['ready'] else '否'}")
    for reason in readiness["reasons"]:
        print(f"  - {reason}")

    watershed = load_watershed_proxy()
    catchment_weights = load_catchment_grid_weights()
    catchment_weather = load_catchment_weather_features()
    audit_watershed_weather_proxy(watershed, catchment_weights, catchment_weather)
    annual_panel = build_annual_model_panel(
        load_prelisting_hydropower_metrics(),
        load_hydropower_weather_features(),
        catchment_weather,
    )
    predictions = expanding_annual_backtest(annual_panel)
    model_summary = summarize_annual_backtest(predictions)
    fixed_lead_forecast = load_fixed_lead_weather_forecast()
    forecast_skill = audit_fixed_lead_forecast_skill(
        fixed_lead_forecast, load_hydropower_weather_features()
    )
    completion = assess_phase1_completion(
        annual_panel,
        metrics,
        fixed_lead_forecast,
        predictions,
        watershed,
    )
    print("\n年度解释模型扩展窗口结果（2018—2022，目标为来水可发电量）:")
    for row in model_summary.itertuples(index=False):
        print(
            f"  - {row.model}: MAE {row.mae_10k_kwh:.2f}万千瓦时，"
            f"MAPE {row.mape_pct:.2f}%，相对均值技能 {row.mae_skill_vs_mean_pct:.2f}%"
        )
    print(
        "固定提前24小时GFS对ERA5季度降水核验: "
        f"相关系数 {forecast_skill['correlation']:.3f}，"
        f"MAE {forecast_skill['mae_mm']:.2f}毫米，"
        f"平均偏差 {forecast_skill['mean_bias_mm']:.2f}毫米"
    )
    print(
        "Phase 1研究闭环: "
        f"{'完成' if completion['phase1_research_complete'] else '未完成'}；"
        "可部署季度nowcast: "
        f"{'就绪' if completion['deployable_nowcast_ready'] else '未就绪'}"
    )
    for reason in completion["reasons"]:
        print(f"  - {reason}")

    if args.fetch_weather:
        start = panel["period_end"].min().to_period("Q").start_time.date().isoformat()
        end = panel["period_end"].max().date().isoformat()
        try:
            weather = fetch_historical_weather(
                float(asset["latitude"]),
                float(asset["longitude"]),
                start,
                end,
                [
                    "precipitation_sum",
                    "rain_sum",
                    "snowfall_sum",
                    "temperature_2m_mean",
                    "et0_fao_evapotranspiration",
                ],
                model=args.weather_model,
            )
        except WeatherAPIError as exc:
            raise SystemExit(f"天气获取失败，可稍后重试：{exc}") from exc
        panel = join_operations_weather(metrics, weather)
        print(f"天气连接完成: {panel['precipitation_sum_mm'].notna().sum()} 个季度")

    if args.fetch_fixed_lead:
        start = panel["period_end"].min().to_period("Q").start_time.date().isoformat()
        end = panel["period_end"].max().date().isoformat()
        try:
            hourly_forecast = fetch_previous_runs(
                float(asset["latitude"]),
                float(asset["longitude"]),
                start,
                end,
                ["precipitation"],
                lead_days=1,
                model="gfs_global",
                timeout=120,
            )
        except WeatherAPIError as exc:
            raise SystemExit(f"固定提前期预报获取失败，可稍后重试：{exc}") from exc
        live_forecast = build_fixed_lead_forecast_snapshot(
            hourly_forecast,
            symbol=str(asset["symbol"]),
            asset_id=str(asset["asset_id"]),
            weather_point_id="wuyiqiao_gfs_point",
            model="gfs_global",
            lead_days=1,
            retrieved_at=pd.Timestamp.today(),
        )
        print(f"固定提前期预报构建完成: {len(live_forecast)} 个季度")
        if args.fixed_lead_out:
            forecast_output = Path(args.fixed_lead_out)
            forecast_output.parent.mkdir(parents=True, exist_ok=True)
            live_forecast.to_csv(forecast_output, index=False)
            print(f"已保存: {forecast_output}")

    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        panel.to_csv(output, index=False)
        print(f"已保存: {output}")
    if args.model_results_out:
        model_output = Path(args.model_results_out)
        model_output.parent.mkdir(parents=True, exist_ok=True)
        predictions.to_csv(model_output, index=False)
        print(f"已保存: {model_output}")


if __name__ == "__main__":
    main()
