"""交易所官方 C-REIT 公告目录采集与候选分类。"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pandas as pd
import requests

SSE_ANNOUNCEMENT_URL = "https://query.sse.com.cn/commonQuery.do"
SSE_REFERER = "https://etf.sse.com.cn/disclosure/fundnotice/"
SSE_DOCUMENT_PREFIX = "https://www.sse.com.cn"
SZSE_ANNOUNCEMENT_URL = "https://reits.szse.cn/api/disc/announcement/annList"
SZSE_REFERER = "https://reits.szse.cn/disclosure/index.html"
SZSE_DOCUMENT_PREFIX = "https://disc.static.szse.cn"

CATALOG_COLUMNS = [
    "announcement_id",
    "symbol",
    "publication_date",
    "title",
    "bulletin_type",
    "original_type",
    "document_type_candidate",
    "period_end_candidate",
    "source_url",
    "exchange",
    "catalog_status",
]


def _candidate_type(title: str, original_type: str) -> str:
    text = f"{title} {original_type}"
    if "收益分配" in text:
        return "distribution_announcement"
    excluded_reports = ("摘要", "评估报告", "审计报告", "提示性公告", "更正公告")
    if any(label in title for label in excluded_reports):
        return "other"
    corrected = "更正稿" in title or title.endswith("（更正）")
    if "年度报告" in text:
        return "annual_report_corrected" if corrected else "annual_report"
    if "季度报告" in text:
        return "quarterly_report_corrected" if corrected else "quarterly_report"
    if "中期报告" in text or "半年度报告" in text:
        return "semiannual_report_corrected" if corrected else "semiannual_report"
    return "other"


def _extract_year(title: str) -> int | None:
    """兼容阿拉伯数字及公告中偶见的“二0二一年”年份写法。"""

    match = re.search(r"(20\d{2})年", title)
    if match:
        return int(match.group(1))
    chinese_match = re.search(r"([二〇零0一二三四五六七八九]{4})年", title)
    if not chinese_match:
        return None
    digits = {"〇": "0", "零": "0", "0": "0", "一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}
    year_text = "".join(digits[char] for char in chinese_match.group(1))
    return int(year_text) if year_text.startswith("20") else None


def _candidate_period_end(title: str, document_type: str) -> str | None:
    year = _extract_year(title)
    if year is None:
        return None
    base_type = document_type.removesuffix("_corrected")
    if base_type == "annual_report":
        return f"{year}-12-31"
    if base_type == "semiannual_report":
        return f"{year}-06-30"
    if base_type == "quarterly_report":
        quarter_match = re.search(r"第?([一二三四1234])季度", title)
        if not quarter_match:
            return None
        quarter_map = {
            "一": "03-31",
            "1": "03-31",
            "二": "06-30",
            "2": "06-30",
            "三": "09-30",
            "3": "09-30",
            "四": "12-31",
            "4": "12-31",
        }
        return f"{year}-{quarter_map[quarter_match.group(1)]}"
    return None


def reclassify_announcement_catalog(frame: pd.DataFrame) -> pd.DataFrame:
    """用当前规则重算候选类型与期间，支持不联网的规则升级迁移。"""

    result = frame.copy()
    result["document_type_candidate"] = result.apply(
        lambda row: _candidate_type(str(row["title"]), str(row["original_type"])),
        axis=1,
    )
    result["period_end_candidate"] = result.apply(
        lambda row: _candidate_period_end(
            str(row["title"]), str(row["document_type_candidate"])
        ),
        axis=1,
    )
    return result


def fetch_sse_reit_announcements(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    timeout: float = 30,
    page_size: int = 1000,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """从上交所官方基金公告接口获取单只 REIT 的公告目录。"""

    if not re.fullmatch(r"508\d{3}", str(symbol)):
        raise ValueError("上交所 REIT symbol 必须是 508 开头的六位代码")
    params = {
        "sqlId": "COMMON_PL_JJXX_JJGG_NEW_L",
        "isPagination": "true",
        "type": "inParams",
        "SECURITY_CODE": symbol,
        "BULLETIN_TYPE": "",
        "TITLE": "",
        "OTHER_TYPE": "",
        "START_DATE": start_date,
        "END_DATE": end_date,
        "DATE_DESC": "1",
        "pageHelp.pageSize": page_size,
        "pageHelp.pageNo": 1,
        "pageHelp.beginPage": 1,
        "pageHelp.cacheSize": 1,
        "pageHelp.endPage": 5,
    }
    headers = {"Referer": SSE_REFERER, "User-Agent": "Mozilla/5.0 c-reit-quant/0.1"}
    client = session or requests.Session()
    try:
        response = client.get(SSE_ANNOUNCEMENT_URL, params=params, headers=headers, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"上交所公告目录请求失败 {symbol}: {exc}") from exc
    page_help = payload.get("pageHelp", {}) if isinstance(payload, dict) else {}
    rows = page_help.get("data", [])
    if not isinstance(rows, list):
        raise RuntimeError(f"上交所公告目录响应结构异常 {symbol}")
    if not rows:
        return pd.DataFrame(columns=CATALOG_COLUMNS)

    records: list[dict[str, object]] = []
    for row in rows:
        url = str(row.get("URL", ""))
        title = str(row.get("TITLE", "")).strip()
        original_type = str(row.get("ORG_BULLETIN_TYPE_DESC", "")).strip()
        candidate = _candidate_type(title, original_type)
        filename = Path(url).stem
        records.append(
            {
                "announcement_id": f"SSE_{filename}",
                "symbol": str(row.get("SECURITY_CODE", symbol)).zfill(6),
                "publication_date": row.get("SSEDATE"),
                "title": title,
                "bulletin_type": row.get("BULLETIN_TYPE_DESC"),
                "original_type": original_type,
                "document_type_candidate": candidate,
                "period_end_candidate": _candidate_period_end(title, candidate),
                "source_url": f"{SSE_DOCUMENT_PREFIX}{url}",
                "exchange": "SSE",
                "catalog_status": "unreviewed",
            }
        )
    frame = pd.DataFrame(records, columns=CATALOG_COLUMNS)
    frame["publication_date"] = pd.to_datetime(frame["publication_date"], errors="raise")
    if frame["announcement_id"].duplicated().any() or frame["source_url"].duplicated().any():
        raise RuntimeError(f"上交所公告目录返回重复记录 {symbol}")
    if not frame["symbol"].eq(symbol).all():
        raise RuntimeError(f"上交所公告目录混入其他证券 {symbol}")
    return frame.sort_values(["publication_date", "announcement_id"]).reset_index(drop=True)


def fetch_szse_reit_announcements(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    timeout: float = 30,
    page_size: int = 50,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """从深交所官方 REIT 信息披露接口分页获取单只基金公告目录。"""

    if not re.fullmatch(r"18[01]\d{3}", str(symbol)):
        raise ValueError("深交所 REIT symbol 必须是 180/181 开头的六位代码")
    if page_size <= 0:
        raise ValueError("page_size 必须为正整数")
    client = session or requests.Session()
    headers = {
        "Referer": f"{SZSE_REFERER}?stock={symbol}",
        "User-Agent": "Mozilla/5.0 c-reit-quant/0.1",
        "Content-Type": "application/json",
    }
    records: list[dict[str, object]] = []
    page_count = 1
    page_num = 1
    while page_num <= page_count:
        body = {
            "stock": [symbol],
            "channelCode": ["reits-xxpl"],
            "pageSize": page_size,
            "pageNum": page_num,
        }
        try:
            response = client.post(
                SZSE_ANNOUNCEMENT_URL,
                json=body,
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RuntimeError(f"深交所公告目录请求失败 {symbol} 第 {page_num} 页: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            message = payload.get("msg") if isinstance(payload, dict) else "非 JSON 对象"
            raise RuntimeError(f"深交所公告目录响应结构异常 {symbol}: {message}")
        if page_num == 1:
            page_count = max(1, math.ceil(int(payload.get("announceCount", 0)) / page_size))
        for row in payload["data"]:
            title = str(row.get("title", "")).strip()
            candidate = _candidate_type(title, "")
            attach_path = str(row.get("attachPath", ""))
            row_symbols = [str(value).zfill(6) for value in row.get("secCode", [])]
            if symbol not in row_symbols:
                raise RuntimeError(f"深交所公告目录混入其他证券 {symbol}")
            records.append(
                {
                    "announcement_id": f"SZSE_{row.get('annId', row.get('id'))}",
                    "symbol": symbol,
                    "publication_date": row.get("publishTime"),
                    "title": title,
                    "bulletin_type": row.get("attachFormat"),
                    "original_type": "",
                    "document_type_candidate": candidate,
                    "period_end_candidate": _candidate_period_end(title, candidate),
                    "source_url": f"{SZSE_DOCUMENT_PREFIX}{attach_path}",
                    "exchange": "SZSE",
                    "catalog_status": "unreviewed",
                }
            )
        page_num += 1
    if not records:
        return pd.DataFrame(columns=CATALOG_COLUMNS)
    frame = pd.DataFrame(records, columns=CATALOG_COLUMNS)
    frame["publication_date"] = pd.to_datetime(frame["publication_date"], errors="raise")
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    frame = frame.loc[frame["publication_date"].between(start, end)].copy()
    if frame["announcement_id"].duplicated().any() or frame["source_url"].duplicated().any():
        raise RuntimeError(f"深交所公告目录返回重复记录 {symbol}")
    return frame.sort_values(["publication_date", "announcement_id"]).reset_index(drop=True)


def merge_announcement_catalogs(
    existing: pd.DataFrame | None, new: pd.DataFrame
) -> pd.DataFrame:
    """幂等合并公告目录；同 ID 内容变化时拒绝静默覆盖。"""

    fresh = new[CATALOG_COLUMNS].copy()
    fresh["publication_date"] = pd.to_datetime(fresh["publication_date"], errors="raise")
    if existing is None or existing.empty:
        return fresh.sort_values(["symbol", "publication_date", "announcement_id"]).reset_index(
            drop=True
        )
    old = existing[CATALOG_COLUMNS].copy()
    old["publication_date"] = pd.to_datetime(old["publication_date"], errors="raise")
    overlap = old.merge(fresh, on="announcement_id", suffixes=("_old", "_new"))
    conflicts = pd.Series(False, index=overlap.index)
    for column in CATALOG_COLUMNS:
        if column == "announcement_id":
            continue
        conflicts |= overlap[f"{column}_old"].fillna("").astype(str).ne(
            overlap[f"{column}_new"].fillna("").astype(str)
        )
    if conflicts.any():
        raise ValueError("公告目录同一 announcement_id 内容冲突")
    combined = pd.concat([old, fresh], ignore_index=True).drop_duplicates(
        "announcement_id", keep="first"
    )
    return combined.sort_values(["symbol", "publication_date", "announcement_id"]).reset_index(
        drop=True
    )


def load_announcement_catalog(path: str | Path) -> pd.DataFrame:
    """读取并校验已保存的公告候选目录。"""

    frame = pd.read_csv(path, dtype={"symbol": str})
    missing = sorted(set(CATALOG_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"公告目录缺少字段: {missing}")
    frame = frame[CATALOG_COLUMNS].copy()
    frame["publication_date"] = pd.to_datetime(frame["publication_date"], errors="raise")
    if frame["announcement_id"].duplicated().any() or frame["source_url"].duplicated().any():
        raise ValueError("公告目录 ID 和 URL 必须唯一")
    frame = reclassify_announcement_catalog(frame)
    return frame.sort_values(["symbol", "publication_date", "announcement_id"]).reset_index(
        drop=True
    )
