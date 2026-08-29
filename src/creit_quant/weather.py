"""Open-Meteo historical weather clients with point-in-time semantics."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import requests

HISTORICAL_WEATHER_URL = "https://archive-api.open-meteo.com/v1/archive"
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
DEFAULT_HISTORICAL_VARIABLES = (
    "temperature_2m_mean",
    "precipitation_sum",
    "wind_speed_10m_max",
)
DEFAULT_FORECAST_VARIABLES = ("temperature_2m", "precipitation", "wind_speed_10m")


class WeatherAPIError(RuntimeError):
    """Raised when Open-Meteo cannot return a valid weather time series."""


def _request_weather(
    url: str,
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    variables: Sequence[str],
    frequency: str,
    timeout: float,
    model: str | None = None,
) -> pd.DataFrame:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        frequency: ",".join(variables),
        "timezone": "Asia/Shanghai",
    }
    if model:
        params["models"] = model
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise WeatherAPIError(f"Open-Meteo request failed: {exc}") from exc

    series = payload.get(frequency)
    if not isinstance(series, dict) or "time" not in series:
        reason = payload.get("reason", "response contains no weather time series")
        raise WeatherAPIError(f"Open-Meteo response is unusable: {reason}")

    try:
        frame = pd.DataFrame(series)
    except ValueError as exc:
        raise WeatherAPIError(f"Open-Meteo returned inconsistent series lengths: {exc}") from exc
    frame["time"] = pd.to_datetime(frame["time"], errors="raise")
    frame.insert(0, "longitude", payload.get("longitude", longitude))
    frame.insert(0, "latitude", payload.get("latitude", latitude))
    frame.attrs["units"] = payload.get(f"{frequency}_units", {})
    frame.attrs["timezone"] = payload.get("timezone")
    return frame


def fetch_historical_weather(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    variables: Sequence[str] | None = None,
    *,
    timeout: float = 30,
    model: str | None = None,
) -> pd.DataFrame:
    """Fetch daily historical/reanalysis weather from Open-Meteo.

    This is reconstructed ex-post weather suitable for explanatory analysis.
    It must not be treated as information known at a historical trading time.
    Pin ``model`` (for example ``era5``) when building a long-lived panel so
    Open-Meteo's default best-match selection cannot change model over time.
    """

    selected = tuple(variables or DEFAULT_HISTORICAL_VARIABLES)
    if not selected:
        raise ValueError("variables cannot be empty")
    return _request_weather(
        HISTORICAL_WEATHER_URL,
        latitude,
        longitude,
        start_date,
        end_date,
        selected,
        "daily",
        timeout,
        model,
    )


def fetch_historical_forecast(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    variables: Sequence[str] | None = None,
    *,
    timeout: float = 30,
) -> pd.DataFrame:
    """Fetch Open-Meteo's stitched archive of historical forecast output.

    Coverage is mainly from 2021/2022 and changes by model. This archive uses
    the first hours of successive model runs. For a strict fixed-lead trading
    backtest, preserve forecast issue times and prefer Open-Meteo's Previous
    Runs or Single Runs products rather than assuming this stitched series is
    a forecast with a chosen lead time.
    """

    selected = tuple(variables or DEFAULT_FORECAST_VARIABLES)
    if not selected:
        raise ValueError("variables cannot be empty")
    return _request_weather(
        HISTORICAL_FORECAST_URL,
        latitude,
        longitude,
        start_date,
        end_date,
        selected,
        "hourly",
        timeout,
    )
