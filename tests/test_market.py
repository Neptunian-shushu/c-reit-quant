from unittest.mock import patch

import pandas as pd

from creit_quant.market import (
    fetch_csindex_history,
    fetch_reit_adjusted_history,
    fetch_reit_adjusted_history_direct,
    fetch_reit_history,
    fetch_reit_history_sina,
    fetch_reit_universe,
)


@patch("creit_quant.market.ak.reits_realtime_em")
def test_universe_normalises_newer_akshare_column_aliases(mock_endpoint):
    mock_endpoint.return_value = pd.DataFrame(
        {
            "代码": [508026],
            "名称": ["sample"],
            "开盘价": [2.1],
            "最高价": [2.2],
            "最低价": [2.0],
        }
    )

    frame = fetch_reit_universe()

    assert frame.loc[0, "symbol"] == "508026"
    assert frame.loc[0, "open"] == 2.1
    assert frame.loc[0, "high"] == 2.2
    assert frame.loc[0, "low"] == 2.0


@patch("creit_quant.market.time.sleep")
@patch("creit_quant.market.ak.reits_realtime_em")
def test_universe_retries_transient_upstream_disconnect(mock_endpoint, mock_sleep):
    mock_endpoint.side_effect = [
        ConnectionError("disconnect"),
        ConnectionError("disconnect"),
        pd.DataFrame({"代码": [508026], "名称": ["sample"]}),
    ]

    frame = fetch_reit_universe(attempts=3, retry_delay=0.1)

    assert frame.loc[0, "symbol"] == "508026"
    assert mock_endpoint.call_count == 3
    assert mock_sleep.call_count == 2


def test_history_normalises_current_akshare_columns(monkeypatch):
    endpoint = lambda symbol: pd.DataFrame(  # noqa: E731 - compact test double
        {
            "日期": ["2024-01-02"],
            "今开": [2.1],
            "最新价": [2.15],
            "最高": [2.2],
            "最低": [2.0],
            "成交量": [100],
            "成交额": [21500],
            "振幅": [1.2],
            "换手": [0.3],
        }
    )
    monkeypatch.setattr("creit_quant.market.ak.reits_hist_em", endpoint, raising=False)

    frame = fetch_reit_history("508026")

    assert frame.loc[0, "symbol"] == "508026"
    assert frame.loc[0, "open"] == 2.1
    assert frame.loc[0, "close"] == 2.15
    assert frame.loc[0, "turnover_rate_pct"] == 0.3
    assert pd.api.types.is_datetime64_any_dtype(frame["date"])


def test_sina_fallback_filters_dates_and_normalises_symbol(monkeypatch):
    endpoint = lambda symbol: pd.DataFrame(  # noqa: E731 - compact test double
        {"date": ["2024-01-01", "2024-01-02"], "close": [2.0, 2.1]}
    )
    monkeypatch.setattr("creit_quant.market.ak.fund_etf_hist_sina", endpoint)

    frame = fetch_reit_history_sina("508026", "20240102", "20240131")

    assert frame["symbol"].tolist() == ["508026"]
    assert frame["close"].tolist() == [2.1]


@patch("creit_quant.market.requests.get")
def test_direct_adjusted_history_bypasses_etf_code_map(mock_get):
    response = mock_get.return_value
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": {
            "klines": [
                "2024-01-02,2.0,2.1,2.2,1.9,100,21000,1.0,5.0,0.1,0.3"
            ]
        }
    }

    frame = fetch_reit_adjusted_history_direct(
        "508026", "20240101", "20240131", adjust="hfq"
    )

    assert frame.loc[0, "symbol"] == "508026"
    assert frame.loc[0, "close"] == 2.1
    assert mock_get.call_args.kwargs["params"]["secid"] == "1.508026"
    assert mock_get.call_args.kwargs["params"]["fqt"] == "2"


@patch("creit_quant.market.fetch_reit_adjusted_history_direct")
def test_adjusted_history_uses_direct_fallback(mock_direct, monkeypatch):
    def broken_endpoint(**kwargs):
        raise RuntimeError("mapping unavailable")

    monkeypatch.setattr("creit_quant.market.ak.fund_etf_hist_em", broken_endpoint)
    mock_direct.return_value = pd.DataFrame(
        {"symbol": ["508026"], "date": [pd.Timestamp("2024-01-02")], "close": [2.1]}
    )

    frame = fetch_reit_adjusted_history("508026", "20240101", "20240131")

    assert frame.loc[0, "close"] == 2.1
    mock_direct.assert_called_once_with(
        "508026", "20240101", "20240131", adjust="hfq"
    )


@patch("creit_quant.market.fetch_reit_adjusted_history_direct")
def test_adjusted_history_uses_direct_fallback_when_wrapper_missing(
    mock_direct, monkeypatch
):
    monkeypatch.delattr("creit_quant.market.ak.fund_etf_hist_em")
    mock_direct.return_value = pd.DataFrame(
        {"symbol": ["180401"], "date": [pd.Timestamp("2024-01-02")], "close": [3.1]}
    )

    frame = fetch_reit_adjusted_history("180401", "20240101", "20240131")

    assert frame.loc[0, "close"] == 3.1
    mock_direct.assert_called_once_with(
        "180401", "20240101", "20240131", adjust="hfq"
    )


@patch("creit_quant.market.requests.get")
def test_csindex_history_parses_official_response(mock_get):
    response = mock_get.return_value
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "code": 200,
        "data": [{"tradeDate": "20250102", "close": 1001.2, "indexCode": "932047"}],
    }

    frame = fetch_csindex_history("932047", "20250101", "20250131")

    assert frame.loc[0, "close"] == 1001.2
    assert frame.loc[0, "date"] == pd.Timestamp("2025-01-02")
    assert mock_get.call_args.kwargs["timeout"] == 30
