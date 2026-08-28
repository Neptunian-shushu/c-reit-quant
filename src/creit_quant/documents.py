"""公告内容哈希与抓取元数据工具；不在仓库保存原始 PDF。"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pandas as pd
import requests


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
