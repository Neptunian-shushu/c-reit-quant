from unittest.mock import patch

import pandas as pd

from creit_quant.market import fetch_reit_history, fetch_reit_universe


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
