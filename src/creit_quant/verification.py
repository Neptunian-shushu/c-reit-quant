"""Phase 4观测级独立复核队列。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

REVIEW_COLUMNS = [
    "observation_id",
    "dataset",
    "symbol",
    "period_end",
    "publication_date",
    "metric",
    "value",
    "unit",
    "source_url",
    "source_sha256",
    "current_verification_status",
    "review_status",
    "reviewed_by",
    "reviewed_at",
    "review_notes",
]

SOURCE_REGISTRY_COLUMNS = [
    "document_id",
    "source_url",
    "symbols",
    "datasets",
    "observation_count",
    "retrieved_at",
    "content_sha256",
    "content_type",
    "content_length_bytes",
    "retrieval_status",
    "retrieval_error",
]


def _observation_id(values: list[object]) -> str:
    canonical = "\x1f".join("" if pd.isna(value) else str(value) for value in values)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _document_hashes(paths: list[str | Path]) -> dict[str, str]:
    frames = []
    for path in paths:
        frame = pd.read_csv(path, dtype=str)
        if not {"source_url", "content_sha256"}.issubset(frame.columns):
            raise ValueError(f"来源登记表缺少URL或SHA-256: {path}")
        frames.append(frame[["source_url", "content_sha256"]])
    if not frames:
        return {}
    combined = pd.concat(frames, ignore_index=True).dropna()
    conflicts = combined.groupby("source_url")["content_sha256"].nunique()
    if conflicts.gt(1).any():
        raise ValueError("同一来源URL存在冲突SHA-256")
    return (
        combined.drop_duplicates("source_url")
        .set_index("source_url")["content_sha256"]
        .to_dict()
    )


def build_phase4_verification_queue(
    fundamentals: pd.DataFrame,
    distributions: pd.DataFrame,
    *,
    document_registry_paths: list[str | Path] | None = None,
    existing: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """为每条基金指标和分派生成稳定ID，并保留既有独立复核结果。"""

    fund = fundamentals.copy()
    fund["dataset"] = "phase4_fund_fundamentals"
    fund["value"] = fund["value"].map(lambda value: format(float(value), ".15g"))
    fund = fund[
        [
            "dataset",
            "symbol",
            "period_end",
            "publication_date",
            "metric",
            "value",
            "unit",
            "source_url",
            "verification_status",
        ]
    ]
    dist = distributions.copy()
    dist["dataset"] = "phase4_distributions"
    dist["period_end"] = ""
    dist["metric"] = "distribution_per_unit"
    dist["value"] = dist["dpu_per_unit"].map(lambda value: format(float(value), ".15g"))
    dist["unit"] = "RMB_per_unit"
    dist = dist[
        [
            "dataset",
            "symbol",
            "period_end",
            "publication_date",
            "metric",
            "value",
            "unit",
            "source_url",
            "verification_status",
        ]
    ]
    queue = pd.concat([fund, dist], ignore_index=True)
    for column in ["period_end", "publication_date"]:
        queue[column] = pd.to_datetime(queue[column], errors="coerce").dt.strftime(
            "%Y-%m-%d"
        )
        queue[column] = queue[column].fillna("")
    identity_columns = [
        "dataset",
        "symbol",
        "period_end",
        "publication_date",
        "metric",
        "value",
        "unit",
        "source_url",
    ]
    queue.insert(
        0,
        "observation_id",
        queue[identity_columns].apply(
            lambda row: _observation_id(row.tolist()), axis=1
        ),
    )
    if queue["observation_id"].duplicated().any():
        raise ValueError("Phase 4复核队列生成了重复观测ID")
    hashes = _document_hashes(document_registry_paths or [])
    queue["source_sha256"] = queue["source_url"].map(hashes).fillna("")
    queue = queue.rename(columns={"verification_status": "current_verification_status"})
    queue["review_status"] = "pending_independent_review"
    queue["reviewed_by"] = ""
    queue["reviewed_at"] = ""
    queue["review_notes"] = ""
    if existing is not None and not existing.empty:
        validate_phase4_verification_queue(existing)
        reviews = existing[
            [
                "observation_id",
                "review_status",
                "reviewed_by",
                "reviewed_at",
                "review_notes",
            ]
        ]
        queue = queue.drop(
            columns=["review_status", "reviewed_by", "reviewed_at", "review_notes"]
        ).merge(reviews, on="observation_id", how="left", validate="one_to_one")
        queue["review_status"] = queue["review_status"].fillna(
            "pending_independent_review"
        )
        for column in ["reviewed_by", "reviewed_at", "review_notes"]:
            queue[column] = queue[column].fillna("")
    result = queue[REVIEW_COLUMNS].sort_values(
        ["dataset", "symbol", "publication_date", "metric", "observation_id"]
    )
    validate_phase4_verification_queue(result)
    return result.reset_index(drop=True)


def validate_phase4_verification_queue(frame: pd.DataFrame) -> None:
    """拒绝无复核人或无复核时间的完成状态。"""

    missing = sorted(set(REVIEW_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"Phase 4复核队列缺少字段: {missing}")
    if frame["observation_id"].duplicated().any():
        raise ValueError("Phase 4复核队列 observation_id 重复")
    allowed = {"pending_independent_review", "confirmed", "rejected"}
    if not set(frame["review_status"]).issubset(allowed):
        raise ValueError("Phase 4复核队列包含未知review_status")
    completed = frame["review_status"].isin({"confirmed", "rejected"})
    reviewer = frame["reviewed_by"].fillna("").astype(str).str.strip()
    reviewed_at = frame["reviewed_at"].fillna("").astype(str).str.strip()
    if reviewer[completed].eq("").any() or reviewed_at[completed].eq("").any():
        raise ValueError("完成独立复核必须填写reviewed_by和reviewed_at")
    if reviewed_at[completed].ne("").any():
        pd.to_datetime(reviewed_at[completed], errors="raise", utc=True)


def summarize_verification_queue(frame: pd.DataFrame) -> dict[str, int]:
    """汇总待复核、确认、拒绝和来源哈希覆盖。"""

    validate_phase4_verification_queue(frame)
    return {
        "observations": len(frame),
        "confirmed": int(frame["review_status"].eq("confirmed").sum()),
        "rejected": int(frame["review_status"].eq("rejected").sum()),
        "pending": int(frame["review_status"].eq("pending_independent_review").sum()),
        "source_hash_present": int(
            frame["source_sha256"].fillna("").astype(str).ne("").sum()
        ),
    }


def build_phase4_source_registry(
    queue: pd.DataFrame,
    existing: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """把观测来源去重成可增量补哈希的文档清单。"""

    validate_phase4_verification_queue(queue)
    grouped = queue.groupby("source_url", as_index=False).agg(
        symbols=("symbol", lambda values: "|".join(sorted(set(values)))),
        datasets=("dataset", lambda values: "|".join(sorted(set(values)))),
        observation_count=("observation_id", "size"),
        content_sha256=(
            "source_sha256",
            lambda values: next(
                (value for value in values.astype(str) if value), ""
            ),
        ),
    )
    grouped.insert(
        0,
        "document_id",
        grouped["source_url"].map(
            lambda url: "phase4_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
        ),
    )
    grouped["retrieved_at"] = ""
    grouped["content_type"] = ""
    grouped["content_length_bytes"] = pd.NA
    grouped["retrieval_status"] = grouped["content_sha256"].ne("").map(
        {True: "success", False: "pending"}
    )
    grouped["retrieval_error"] = ""
    if existing is not None and not existing.empty:
        missing = sorted(set(SOURCE_REGISTRY_COLUMNS).difference(existing.columns))
        if missing:
            raise ValueError(f"Phase 4来源清单缺少字段: {missing}")
        if existing["source_url"].duplicated().any():
            raise ValueError("Phase 4来源清单URL重复")
        metadata = existing[
            [
                "source_url",
                "retrieved_at",
                "content_sha256",
                "content_type",
                "content_length_bytes",
                "retrieval_status",
                "retrieval_error",
            ]
        ].copy()
        grouped = grouped.merge(
            metadata,
            on="source_url",
            how="left",
            validate="one_to_one",
            suffixes=("", "_existing"),
        )
        generated_hash = grouped["content_sha256"].fillna("").astype(str)
        existing_hash = grouped["content_sha256_existing"].fillna("").astype(str)
        conflict = generated_hash.ne("") & existing_hash.ne("") & generated_hash.ne(
            existing_hash
        )
        if conflict.any():
            raise ValueError("Phase 4来源清单与新观测的SHA-256冲突")
        for column in [
            "retrieved_at",
            "content_sha256",
            "content_type",
            "content_length_bytes",
            "retrieval_error",
        ]:
            saved = grouped[f"{column}_existing"].fillna("").astype(str)
            current = grouped[column].fillna("").astype(str)
            grouped[column] = saved.where(saved.ne(""), current)
            grouped = grouped.drop(columns=f"{column}_existing")
        saved_status = grouped["retrieval_status_existing"].fillna("").astype(str)
        current_status = grouped["retrieval_status"].fillna("pending").astype(str)
        grouped["retrieval_status"] = saved_status.where(
            saved_status.ne(""), current_status
        )
        grouped.loc[
            generated_hash.ne("") | existing_hash.ne(""), "retrieval_status"
        ] = "success"
        grouped = grouped.drop(columns="retrieval_status_existing")
    return grouped[SOURCE_REGISTRY_COLUMNS].sort_values("source_url").reset_index(
        drop=True
    )


def merge_registered_source_metadata(
    source_registry: pd.DataFrame,
    document_registry_paths: list[str | Path],
) -> pd.DataFrame:
    """从既有来源登记表补齐抓取元数据，已有值不被静默覆盖。"""

    frame = source_registry.copy()
    missing = sorted(set(SOURCE_REGISTRY_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"Phase 4来源清单缺少字段: {missing}")
    columns = [
        "source_url",
        "retrieved_at",
        "content_sha256",
        "content_type",
        "content_length_bytes",
        "retrieval_status",
        "retrieval_error",
    ]
    registered = pd.concat(
        [pd.read_csv(path, dtype=str)[columns] for path in document_registry_paths],
        ignore_index=True,
    )
    for column in ["content_sha256", "content_length_bytes"]:
        conflicts = (
            registered.dropna(subset=[column])
            .groupby("source_url")[column]
            .nunique()
        )
        if conflicts.gt(1).any():
            raise ValueError(f"同一来源URL存在冲突字段: {column}")
    for column in columns[1:]:
        current = frame[column].fillna("").astype(str)
        available = registered.loc[
            registered[column].fillna("").astype(str).ne("")
        ].drop_duplicates("source_url", keep="last")
        incoming = frame["source_url"].map(
            available.set_index("source_url")[column]
        ).fillna("")
        incoming = incoming.astype(str)
        if column == "retrieval_status":
            upgrade = current.ne("success") & incoming.eq("success")
            frame.loc[upgrade, column] = incoming[upgrade]
            continue
        conflict = current.ne("") & incoming.ne("") & current.ne(incoming)
        if conflict.any():
            raise ValueError(f"Phase 4来源清单与既有登记冲突: {column}")
        frame.loc[current.eq("") & incoming.ne(""), column] = incoming
    return frame[SOURCE_REGISTRY_COLUMNS].sort_values("source_url").reset_index(
        drop=True
    )
