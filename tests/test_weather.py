from unittest.mock import Mock, patch

import pandas as pd
import pytest

from creit_quant.weather import (
    HISTORICAL_FORECAST_URL,
    HISTORICAL_WEATHER_URL,
    PREVIOUS_RUNS_URL,
    fetch_historical_forecast,
    fetch_historical_weather,
    fetch_previous_runs,
)


def _response(payload):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


@patch("creit_quant.weather.requests.get")
def test_historical_weather_uses_reanalysis_endpoint(mock_get):
    mock_get.return_value = _response(
        {
            "latitude": 29.0,
            "longitude": 101.5,
            "timezone": "Asia/Shanghai",
            "daily": {"time": ["2024-01-01"], "precipitation_sum": [1.2]},
            "daily_units": {"precipitation_sum": "mm"},
        }
    )

    frame = fetch_historical_weather(
        29.0, 101.5, "2024-01-01", "2024-01-01", ["precipitation_sum"]
    )

    assert mock_get.call_args.args[0] == HISTORICAL_WEATHER_URL
    assert mock_get.call_args.kwargs["timeout"] == 30
    assert pd.api.types.is_datetime64_any_dtype(frame["time"])
    assert frame.attrs["units"]["precipitation_sum"] == "mm"


@patch("creit_quant.weather.requests.get")
def test_historical_weather_can_pin_reanalysis_model(mock_get):
    mock_get.return_value = _response(
        {"daily": {"time": ["2024-01-01"], "precipitation_sum": [1.2]}}
    )

    fetch_historical_weather(
        29.0,
        101.5,
        "2024-01-01",
        "2024-01-01",
        ["precipitation_sum"],
        model="era5",
    )

    assert mock_get.call_args.kwargs["params"]["models"] == "era5"


@patch("creit_quant.weather.requests.get")
def test_previous_runs_uses_fixed_lead_suffix_and_model(mock_get):
    mock_get.return_value = _response(
        {
            "hourly": {
                "time": ["2024-01-01T00:00"],
                "precipitation_previous_day1": [1.2],
            }
        }
    )

    frame = fetch_previous_runs(
        29.0,
        101.5,
        "2024-01-01",
        "2024-01-01",
        ["precipitation"],
        lead_days=1,
        model="gfs_global",
    )

    assert mock_get.call_args.args[0] == PREVIOUS_RUNS_URL
    params = mock_get.call_args.kwargs["params"]
    assert params["hourly"] == "precipitation_previous_day1"
    assert params["models"] == "gfs_global"
    assert frame["precipitation_previous_day1"].item() == 1.2


def test_previous_runs_rejects_unsupported_lead():
    with pytest.raises(ValueError, match="between 1 and 7"):
        fetch_previous_runs(
            29.0,
            101.5,
            "2024-01-01",
            "2024-01-01",
            ["precipitation"],
            lead_days=8,
        )


@patch("creit_quant.weather.requests.get")
def test_historical_forecast_uses_distinct_forecast_archive(mock_get):
    mock_get.return_value = _response(
        {"hourly": {"time": ["2024-01-01T00:00"], "precipitation": [0.4]}}
    )

    frame = fetch_historical_forecast(
        29.0, 101.5, "2024-01-01", "2024-01-01", ["precipitation"]
    )

    assert mock_get.call_args.args[0] == HISTORICAL_FORECAST_URL
    assert frame.loc[0, "precipitation"] == 0.4
