"""C-REIT market data access through AKShare."""

from __future__ import annotations

import re

import akshare as ak
import pandas as pd


class MarketDataError(RuntimeError):
    """Raised when an AKShare C-REIT endpoint cannot return usable data."""


UNIVERSE_COLUMNS = {
    "序号": "rank",
    "代码": "symbol",
    "名称": "name",
    "最新价": "last",
    "涨跌额": "change",
    "涨跌幅": "change_pct",
    "成交量": "volume",
    "成交额": "turnover",
    "振幅": "amplitude_pct",
    "最高": "high",
    "最高价": "high",
    "最低": "low",
    "最低价": "low",
    "今开": "open",
    "开盘价": "open",
    "昨收": "previous_close",
    "量比": "volume_ratio",
    "换手率": "turnover_rate_pct",
}

HISTORY_COLUMNS = {
    "日期": "date",
    "开盘": "open",
    "今开": "open",
    "收盘": "close",
    "最新价": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "turnover",
    "振幅": "amplitude_pct",
    "涨跌幅": "change_pct",
    "涨跌额": "change",
    "换手率": "turnover_rate_pct",
    "换手": "turnover_rate_pct",
}


def _normalise_columns(frame: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    result = frame.rename(columns=mapping).copy()
    if "symbol" in result:
        result["symbol"] = result["symbol"].astype(str).str.zfill(6)
    if "date" in result:
        result["date"] = pd.to_datetime(result["date"], errors="raise")
    return result


def fetch_reit_universe() -> pd.DataFrame:
    """Fetch the current full-market C-REIT quote table from AKShare.

    The result doubles as the current universe snapshot. Column names exposed
    by the Eastmoney-backed endpoint are normalised where known; unknown
    columns are retained because upstream fields may change.
    """

    try:
        frame = ak.reits_realtime_em()
    except Exception as exc:  # AKShare wraps several network/parser errors.
        raise MarketDataError(f"AKShare C-REIT universe request failed: {exc}") from exc
    if frame is None or frame.empty:
        raise MarketDataError("AKShare returned an empty C-REIT universe table")
    return _normalise_columns(frame, UNIVERSE_COLUMNS)


def fetch_reit_history(symbol: str) -> pd.DataFrame:
    """Fetch daily price history for one six-digit C-REIT symbol.

    AKShare's ``reits_hist_em`` endpoint is an unofficial wrapper around an
    Eastmoney web source. Older AKShare releases may not contain it, and the
    upstream source may change without notice. In either case this function
    raises :class:`MarketDataError` rather than manufacturing fallback data.
    """

    if not re.fullmatch(r"\d{6}", str(symbol)):
        raise ValueError("symbol must be a six-digit C-REIT code")
    endpoint = getattr(ak, "reits_hist_em", None)
    if endpoint is None:
        version = getattr(ak, "__version__", "unknown")
        raise MarketDataError(
            "This AKShare installation does not provide reits_hist_em "
            f"(installed version: {version}); upgrade AKShare and retry"
        )
    try:
        frame = endpoint(symbol=str(symbol))
    except Exception as exc:
        raise MarketDataError(f"AKShare history request failed for {symbol}: {exc}") from exc
    if frame is None or frame.empty:
        raise MarketDataError(f"AKShare returned no daily history for {symbol}")
    result = _normalise_columns(frame, HISTORY_COLUMNS)
    result.insert(0, "symbol", str(symbol))
    return result
