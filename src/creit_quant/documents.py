"""公告内容哈希与抓取元数据工具；不在仓库保存原始 PDF。"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pandas as pd
import requests

PERIODIC_DOCUMENT_TYPES = {
    "quarterly_report",
    "quarterly_report_corrected",
    "semiannual_report",
    "semiannual_report_corrected",
    "annual_report",
    "annual_report_corrected",
}
DOCUMENT_REGISTRY_COLUMNS = [
    "document_id",
    "symbol",
    "document_type",
    "period_end",
    "publication_date",
    "source_url",
    "verification_status",
    "supersedes_document_id",
    "retrieved_at",
    "content_sha256",
    "parser_version",
    "notes",
    "content_type",
    "content_length_bytes",
    "retrieval_status",
    "retrieval_error",
]


def build_periodic_document_registry(
    catalog: pd.DataFrame, symbols: list[str]
) -> pd.DataFrame:
    """把指定证券的交易所定期报告候选转换为待解析来源登记记录。"""

    required = {
        "announcement_id",
        "symbol",
        "publication_date",
        "document_type_candidate",
        "period_end_candidate",
        "title",
        "source_url",
    }
    missing = sorted(required.difference(catalog.columns))
    if missing:
        raise ValueError(f"公告目录缺少来源登记字段: {missing}")
    selected = catalog.loc[
        catalog["symbol"].isin(symbols)
        & catalog["document_type_candidate"].isin(PERIODIC_DOCUMENT_TYPES)
    ].copy()
    if selected["period_end_candidate"].isna().any():
        raise ValueError("定期报告候选存在无法识别的报告期")
    registry = pd.DataFrame(
        {
            "document_id": selected["announcement_id"],
            "symbol": selected["symbol"],
            "document_type": selected["document_type_candidate"],
            "period_end": selected["period_end_candidate"],
            "publication_date": selected["publication_date"],
            "source_url": selected["source_url"],
            "verification_status": "metadata_verified",
            "supersedes_document_id": pd.NA,
            "retrieved_at": pd.NA,
            "content_sha256": pd.NA,
            "parser_version": "catalog_v1",
            "notes": selected["title"],
            "content_type": pd.NA,
            "content_length_bytes": pd.NA,
            "retrieval_status": "pending",
            "retrieval_error": pd.NA,
        }
    )
    if registry["document_id"].duplicated().any() or registry["source_url"].duplicated().any():
        raise ValueError("生成的来源登记记录存在重复 ID 或 URL")
    return registry[DOCUMENT_REGISTRY_COLUMNS].sort_values(
        ["symbol", "period_end", "publication_date", "document_id"]
    ).reset_index(drop=True)


def merge_document_registries(
    existing: pd.DataFrame, discovered: pd.DataFrame
) -> pd.DataFrame:
    """按官方 URL 幂等合并来源记录，保留既有人工登记和抓取元数据。"""

    old = existing.copy()
    new = discovered.copy()
    overlap = old.merge(new, on="source_url", suffixes=("_old", "_new"))
    for column in ["symbol", "document_type", "period_end", "publication_date"]:
        is_date = column.endswith("date") or column == "period_end"
        left = (
            pd.to_datetime(overlap[f"{column}_old"])
            if is_date
            else overlap[f"{column}_old"]
        )
        right = (
            pd.to_datetime(overlap[f"{column}_new"])
            if is_date
            else overlap[f"{column}_new"]
        )
        if left.astype(str).ne(right.astype(str)).any():
            raise ValueError(f"同一来源 URL 的 {column} 冲突")
    additions = new.loc[~new["source_url"].isin(old["source_url"])].copy()
    additions_nonempty = additions.dropna(axis=1, how="all")
    combined = pd.concat([old, additions_nonempty], ignore_index=True)
    for column in ["period_end", "publication_date"]:
        combined[column] = pd.to_datetime(combined[column], errors="raise")
    if combined["document_id"].duplicated().any() or combined["source_url"].duplicated().any():
        raise ValueError("合并后的来源登记表存在重复 ID 或 URL")
    return combined.sort_values(
        ["symbol", "period_end", "publication_date", "document_id"]
    ).reset_index(drop=True)


def enrich_document_metadata(
    documents: pd.DataFrame,
    *,
    timeout: float = 30,
    retrieved_at: str | pd.Timestamp | None = None,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """抓取缺少哈希的公告，记录响应元数据并继续保留失败行。

    响应内容只在内存中用于 SHA-256，不写入磁盘。已有成功哈希的记录
    不会重复抓取，保证增量运行不会静默改变既有证据版本。
    """

    required = {"document_id", "source_url"}
    missing = sorted(required.difference(documents.columns))
    if missing:
        raise ValueError(f"公告登记表缺少字段: {missing}")
    frame = documents.copy()
    defaults: dict[str, object] = {
        "retrieved_at": pd.NA,
        "content_sha256": pd.NA,
        "content_type": pd.NA,
        "content_length_bytes": pd.NA,
        "retrieval_status": "pending",
        "retrieval_error": pd.NA,
    }
    for column, default in defaults.items():
        if column not in frame:
            frame[column] = default
    for column in [
        "retrieved_at",
        "content_sha256",
        "content_type",
        "retrieval_status",
        "retrieval_error",
    ]:
        frame[column] = frame[column].astype("object")
    client = session or requests.Session()
    timestamp = pd.Timestamp(
        retrieved_at or datetime.now(timezone.utc).replace(microsecond=0)
    )
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    timestamp_text = timestamp.isoformat().replace("+00:00", "Z")
    headers = {"User-Agent": "c-reit-quant/0.1 research data audit"}

    already_successful = frame["content_sha256"].notna() & frame["content_sha256"].ne("")
    frame.loc[already_successful, "retrieval_status"] = "success"
    for index, row in frame.loc[~already_successful].iterrows():
        try:
            response = client.get(row["source_url"], timeout=timeout, headers=headers)
            response.raise_for_status()
            content = response.content
            if not content:
                raise ValueError("empty response body")
        except (requests.RequestException, ValueError) as exc:
            frame.loc[index, "retrieval_status"] = "failed"
            frame.loc[index, "retrieval_error"] = str(exc)[:500]
            continue
        frame.loc[index, "retrieved_at"] = timestamp_text
        frame.loc[index, "content_sha256"] = hashlib.sha256(content).hexdigest()
        frame.loc[index, "content_type"] = response.headers.get("Content-Type")
        frame.loc[index, "content_length_bytes"] = len(content)
        frame.loc[index, "retrieval_status"] = "success"
        frame.loc[index, "retrieval_error"] = pd.NA
    frame["content_length_bytes"] = pd.to_numeric(
        frame["content_length_bytes"], errors="coerce"
    ).astype("Int64")
    return frame
