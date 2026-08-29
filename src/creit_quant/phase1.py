"""Phase 1 水电试点覆盖审计与天气面板构建入口。"""

from __future__ import annotations

import argparse
from pathlib import Path

from creit_quant.hydropower import (
    assess_model_readiness,
    join_operations_weather,
    load_hydropower_asset,
    load_hydropower_metrics,
    pivot_quarterly_metrics,
)
from creit_quant.weather import WeatherAPIError, fetch_historical_weather


def main() -> None:
    """运行覆盖审计；按需联网构建天气连接面板。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-weather", action="store_true", help="从 Open-Meteo 获取点位再分析天气")
    parser.add_argument(
        "--weather-model",
        default="era5",
        help="Open-Meteo固定历史模型；默认era5，避免best-match跨期模型切换",
    )
    parser.add_argument("--out", default=None, help="可选的季度面板 CSV 输出路径")
    args = parser.parse_args()

    metrics = load_hydropower_metrics()
    asset = load_hydropower_asset().iloc[0]
    panel = pivot_quarterly_metrics(metrics)
    readiness = assess_model_readiness(panel)

    print(f"试点标的: {asset['symbol']} / {asset['asset_name']}")
    print(f"季度覆盖: {panel['quarter'].min()} 至 {panel['quarter'].max()}，共 {len(panel)} 个季度")
    print(f"核心指标: {', '.join(sorted(set(metrics['metric'])))}")
    print(f"Nowcast 建模就绪: {'是' if readiness['ready'] else '否'}")
    for reason in readiness["reasons"]:
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

    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        panel.to_csv(output, index=False)
        print(f"已保存: {output}")


if __name__ == "__main__":
    main()
