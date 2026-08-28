from unittest.mock import Mock, patch

import pandas as pd

from creit_quant.weather import (
    HISTORICAL_FORECAST_URL,
    HISTORICAL_WEATHER_URL,
    fetch_historical_forecast,
    fetch_historical_weather,
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
def test_historical_forecast_uses_distinct_forecast_archive(mock_get):
    mock_get.return_value = _response(
        {"hourly": {"time": ["2024-01-01T00:00"], "precipitation": [0.4]}}
    )

    frame = fetch_historical_forecast(
        29.0, 101.5, "2024-01-01", "2024-01-01", ["precipitation"]
    )

    assert mock_get.call_args.args[0] == HISTORICAL_FORECAST_URL
    assert frame.loc[0, "precipitation"] == 0.4
