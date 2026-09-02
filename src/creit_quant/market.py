"""C-REIT market data access through AKShare."""

from __future__ import annotations

import re

import akshare as ak
import pandas as pd
import requests

CSINDEX_HISTORY_URL = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
EASTMONEY_HISTORY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


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
    "amount": "turnover",
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


def fetch_reit_adjusted_history(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    adjust: str = "hfq",
) -> pd.DataFrame:
    """通过 AKShare 获取含分派复权处理的 REIT 日线行情。

    当前旧版 AKShare 可能没有 ``reits_hist_em``，但其
    ``fund_etf_hist_em`` 同样可以查询交易所基金代码。收益回测默认使用
    后复权价格，避免现金分派造成机械价格缺口。该接口仍依赖东方财富，
    失败时不会生成替代行情。
    """

    if not re.fullmatch(r"\d{6}", str(symbol)):
        raise ValueError("symbol must be a six-digit C-REIT code")
    if adjust not in {"", "qfq", "hfq"}:
        raise ValueError("adjust must be one of '', 'qfq', or 'hfq'")
    if not re.fullmatch(r"\d{8}", start_date) or not re.fullmatch(r"\d{8}", end_date):
        raise ValueError("start_date and end_date must use YYYYMMDD")
    endpoint = getattr(ak, "fund_etf_hist_em", None)
    wrapper_error: Exception | None = None
    if endpoint is None:
        wrapper_error = RuntimeError("AKShare does not provide fund_etf_hist_em")
        frame = None
    else:
        try:
            frame = endpoint(
                symbol=str(symbol),
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )
        except Exception as exc:
            wrapper_error = exc
            frame = None
    if frame is None or frame.empty:
        try:
            return fetch_reit_adjusted_history_direct(
                symbol, start_date, end_date, adjust=adjust
            )
        except MarketDataError as direct_error:
            detail = f"; AKShare wrapper error: {wrapper_error}" if wrapper_error else ""
            raise MarketDataError(
                f"AKShare and direct Eastmoney adjusted history failed for "
                f"{symbol}: {direct_error}{detail}"
            ) from direct_error
    result = _normalise_columns(frame, HISTORY_COLUMNS)
    result.insert(0, "symbol", str(symbol))
    return result


def fetch_reit_adjusted_history_direct(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    adjust: str = "hfq",
    timeout: float = 30,
) -> pd.DataFrame:
    """绕过AKShare全ETF代码映射，直接获取东方财富REIT历史K线。

    AKShare包装器会先请求全市场ETF代码表；该辅助请求失败时，已知六位
    REIT代码仍可直接映射为沪市 ``1`` 或深市 ``0``。返回字段和复权参数
    与 ``fund_etf_hist_em`` 保持一致，失败时同样不生成替代数据。
    """

    if not re.fullmatch(r"\d{6}", str(symbol)):
        raise ValueError("symbol must be a six-digit C-REIT code")
    if adjust not in {"", "qfq", "hfq"}:
        raise ValueError("adjust must be one of '', 'qfq', or 'hfq'")
    if not re.fullmatch(r"\d{8}", start_date) or not re.fullmatch(
        r"\d{8}", end_date
    ):
        raise ValueError("start_date and end_date must use YYYYMMDD")
    market_id = "1" if str(symbol).startswith("5") else "0"
    params = {
        "secid": f"{market_id}.{symbol}",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": {"": "0", "qfq": "1", "hfq": "2"}[adjust],
        "beg": start_date,
        "end": end_date,
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
    }
    try:
        response = requests.get(EASTMONEY_HISTORY_URL, params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        klines = payload.get("data", {}).get("klines")
    except (requests.RequestException, ValueError, AttributeError) as exc:
        raise MarketDataError(
            f"direct Eastmoney history request failed for {symbol}: {exc}"
        ) from exc
    if not klines:
        raise MarketDataError(f"direct Eastmoney returned no history for {symbol}")
    frame = pd.DataFrame([row.split(",") for row in klines])
    if frame.shape[1] != 11:
        raise MarketDataError(f"direct Eastmoney history fields changed for {symbol}")
    frame.columns = [
        "日期",
        "开盘",
        "收盘",
        "最高",
        "最低",
        "成交量",
        "成交额",
        "振幅",
        "涨跌幅",
        "涨跌额",
        "换手率",
    ]
    result = _normalise_columns(frame, HISTORY_COLUMNS)
    numeric = [column for column in result.columns if column != "date"]
    result[numeric] = result[numeric].apply(pd.to_numeric, errors="raise")
    result.insert(0, "symbol", str(symbol))
    return result


def fetch_index_history(
    symbol: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """通过 AKShare 获取指数日线，默认供 932047 REIT 全收益指数使用。"""

    if not re.fullmatch(r"(?:sh|sz|csi)\d{6}", symbol):
        raise ValueError("index symbol must include sh, sz, or csi plus six digits")
    endpoint = getattr(ak, "stock_zh_index_daily_em", None)
    if endpoint is None:
        raise MarketDataError("This AKShare installation does not provide stock_zh_index_daily_em")
    try:
        frame = endpoint(symbol=symbol, start_date=start_date, end_date=end_date)
    except Exception as exc:
        raise MarketDataError(f"AKShare index history request failed for {symbol}: {exc}") from exc
    if frame is None or frame.empty:
        raise MarketDataError(f"AKShare returned no index history for {symbol}")
    return _normalise_columns(frame, HISTORY_COLUMNS)


def fetch_reit_history_sina(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """通过 AKShare 的新浪接口获取 REIT 不复权日线，作为上游备用源。"""

    if not re.fullmatch(r"\d{6}", str(symbol)):
        raise ValueError("symbol must be a six-digit C-REIT code")
    endpoint = getattr(ak, "fund_etf_hist_sina", None)
    if endpoint is None:
        raise MarketDataError("This AKShare installation does not provide fund_etf_hist_sina")
    market_symbol = f"sh{symbol}" if str(symbol).startswith("5") else f"sz{symbol}"
    try:
        frame = endpoint(symbol=market_symbol)
    except Exception as exc:
        raise MarketDataError(f"AKShare Sina history request failed for {symbol}: {exc}") from exc
    if frame is None or frame.empty:
        raise MarketDataError(f"AKShare Sina returned no history for {symbol}")
    result = _normalise_columns(frame, HISTORY_COLUMNS)
    start = pd.to_datetime(start_date, format="%Y%m%d")
    end = pd.to_datetime(end_date, format="%Y%m%d")
    result = result.loc[result["date"].between(start, end)].copy()
    if result.empty:
        raise MarketDataError(f"AKShare Sina returned no history in range for {symbol}")
    result.insert(0, "symbol", str(symbol))
    return result.reset_index(drop=True)


def fetch_csindex_history(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    timeout: float = 30,
) -> pd.DataFrame:
    """从中证指数官网获取只有官方源可稳定提供的指数收盘历史。"""

    if not re.fullmatch(r"\d{6}", symbol):
        raise ValueError("CSI index symbol must contain six digits")
    params = {"indexCode": symbol, "startDate": start_date, "endDate": end_date}
    headers = {"Referer": "https://www.csindex.com.cn/", "User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(CSINDEX_HISTORY_URL, params=params, headers=headers, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise MarketDataError(f"CSI index history request failed for {symbol}: {exc}") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not data:
        raise MarketDataError(f"CSI returned no index history for {symbol}")
    frame = pd.DataFrame(data).rename(columns={"tradeDate": "date"})
    frame["date"] = pd.to_datetime(frame["date"], format="%Y%m%d", errors="raise")
    frame["close"] = pd.to_numeric(frame["close"], errors="raise")
    return frame.sort_values("date").reset_index(drop=True)
