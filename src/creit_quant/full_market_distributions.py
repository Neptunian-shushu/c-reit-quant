"""联网构建全市场实际DPU公告面板；PDF响应不落入仓库。"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from creit_quant.distribution_parser import (
    parse_distribution_text,
    resolve_distribution_documents,
)
from creit_quant.verification import build_distribution_verification_queue

ROOT = Path(__file__).resolve().parents[2]

DOCUMENT_AUDIT_COLUMNS = [
    "announcement_id",
    "symbol",
    "publication_date",
    "title",
    "source_url",
    "retrieved_at",
    "content_sha256",
    "content_length_bytes",
    "retrieval_status",
    "failure_reason",
    "ex_date",
    "dpu_per_unit",
    "disclosed_rmb_per_10_units",
    "raw_text",
]


def _fetch_and_parse(row: pd.Series, timeout: float) -> dict[str, object]:
    result = row.to_dict()
    result.update(
        {
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "content_sha256": "",
            "content_length_bytes": pd.NA,
            "retrieval_status": "failed",
            "failure_reason": "",
            "ex_date": pd.NaT,
            "dpu_per_unit": pd.NA,
            "disclosed_rmb_per_10_units": pd.NA,
            "raw_text": "",
        }
    )
    try:
        source_url = str(row["source_url"])
        referer = (
            "https://reits.szse.cn/disclosure/index.html"
            if "szse.cn" in source_url
            else "https://etf.sse.com.cn/disclosure/fundnotice/"
        )
        response = requests.get(
            source_url,
            headers={"User-Agent": "Mozilla/5.0 c-reit-quant/0.1", "Referer": referer},
            timeout=timeout,
        )
        response.raise_for_status()
        content = response.content
        if not content.startswith(b"%PDF"):
            raise ValueError("响应不是PDF")
        result["content_sha256"] = hashlib.sha256(content).hexdigest()
        result["content_length_bytes"] = len(content)
        converted = subprocess.run(
            ["pdftotext", "-layout", "-", "-"],
            input=content,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        if converted.returncode != 0:
            raise ValueError("pdftotext转换失败")
        text = converted.stdout.decode("utf-8", errors="ignore")
        result.update(parse_distribution_text(text))
        result["retrieval_status"] = "success"
    except (requests.RequestException, subprocess.SubprocessError, ValueError) as exc:
        result["failure_reason"] = str(exc)
    return result


def fetch_distribution_documents(
    catalog: pd.DataFrame, *, timeout: float = 30, workers: int = 6
) -> pd.DataFrame:
    """并行获取并解析目录中的分派公告，保留每个文档的审计结果。"""

    if workers <= 0:
        raise ValueError("workers必须为正整数")
    selected = catalog.loc[
        catalog["document_type_candidate"].eq("distribution_announcement")
    ].copy()
    columns = ["announcement_id", "symbol", "publication_date", "title", "source_url"]
    selected = selected[columns].sort_values(["symbol", "publication_date"])
    if selected.empty:
        return pd.DataFrame(columns=DOCUMENT_AUDIT_COLUMNS)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        rows = list(
            executor.map(
                lambda item: _fetch_and_parse(item[1], timeout),
                selected.iterrows(),
            )
        )
    return (
        pd.DataFrame(rows, columns=DOCUMENT_AUDIT_COLUMNS)
        .sort_values(["symbol", "publication_date", "announcement_id"])
        .reset_index(drop=True)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=ROOT / "data" / "snapshots" / "reit_announcement_catalog.csv",
    )
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data" / "samples")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--retry-failures", type=int, default=1)
    parser.add_argument("--refresh-all", action="store_true", help="忽略已有文档审计并重新抓取全部公告")
    parser.add_argument(
        "--retry-parser-failures-only",
        action="store_true",
        help="只重试已有审计中的非HTTP解析失败，避免反复触发上游限流",
    )
    parser.add_argument(
        "--rebuild-from-audit",
        action="store_true",
        help="不联网，仅从现有文档审计重建事件表",
    )
    args = parser.parse_args()
    catalog = pd.read_csv(args.catalog, dtype={"symbol": str})
    audit_path = args.out_dir / "full_market_distribution_document_audit.csv"
    previous = None
    if audit_path.exists() and not args.refresh_all:
        previous = pd.read_csv(audit_path, dtype={"symbol": str})
        successful_ids = set(
            previous.loc[previous["retrieval_status"].eq("success"), "announcement_id"]
        )
        pending_ids = set(previous["announcement_id"]).difference(successful_ids)
        if args.retry_parser_failures_only:
            pending_ids = set(
                previous.loc[
                    previous["retrieval_status"].eq("failed")
                    & ~previous["failure_reason"].str.contains(
                        "HTTP|Connection|Timeout|Forbidden", na=False
                    ),
                    "announcement_id",
                ]
            )
        pending_catalog = catalog.loc[catalog["announcement_id"].isin(pending_ids)]
    else:
        pending_catalog = catalog
    if args.rebuild_from_audit:
        if previous is None:
            raise ValueError("--rebuild-from-audit要求已有文档审计表")
        documents = previous
    else:
        fetched = fetch_distribution_documents(
            pending_catalog, timeout=args.timeout, workers=args.workers
        )
        if previous is not None:
            kept = previous.loc[
                ~previous["announcement_id"].isin(fetched["announcement_id"])
            ]
            documents = pd.concat([kept, fetched], ignore_index=True)
        else:
            documents = fetched
    for _ in range(0 if args.rebuild_from_audit else args.retry_failures):
        failed = documents.loc[documents["retrieval_status"].eq("failed")]
        network_failures = failed.loc[
            failed["failure_reason"].str.contains(
                "Connection|Timeout|HTTP|NameResolution|RemoteDisconnected", na=False
            )
        ]
        if network_failures.empty:
            break
        time.sleep(1)
        retry_catalog = catalog.loc[
            catalog["announcement_id"].isin(network_failures["announcement_id"])
        ]
        retried = fetch_distribution_documents(
            retry_catalog, timeout=args.timeout, workers=args.workers
        ).set_index("announcement_id")
        documents = documents.set_index("announcement_id")
        documents.update(retried)
        documents = documents.reset_index()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    documents.to_csv(audit_path, index=False)
    successful = documents.loc[documents["retrieval_status"].eq("success")]
    events = resolve_distribution_documents(successful)
    existing_path = args.out_dir / "phase4_distributions.csv"
    if existing_path.exists():
        existing = pd.read_csv(existing_path, dtype={"symbol": str})
        existing["publication_date"] = pd.to_datetime(
            existing["publication_date"], errors="raise"
        )
        existing["ex_date"] = pd.to_datetime(existing["ex_date"], errors="raise")
        overlap = existing.merge(
            events,
            on=["symbol", "publication_date"],
            suffixes=("_old", "_new"),
        )
        mismatch = overlap["ex_date_old"].ne(overlap["ex_date_new"]) | overlap[
            "dpu_per_unit_old"
        ].astype(float).sub(overlap["dpu_per_unit_new"].astype(float)).abs().gt(1e-10)
        if mismatch.any():
            keys = overlap.loc[mismatch, ["symbol", "publication_date"]].to_dict(
                "records"
            )
            raise ValueError(f"全市场自动抽取与Phase 4已核验样本冲突: {keys}")
        known_keys = pd.MultiIndex.from_frame(events[["symbol", "publication_date"]])
        existing_keys = pd.MultiIndex.from_frame(
            existing[["symbol", "publication_date"]]
        )
        supplements = existing.loc[~existing_keys.isin(known_keys), events.columns]
        events = pd.concat([events, supplements], ignore_index=True).sort_values(
            ["symbol", "publication_date"]
        )

    hash_rows = documents.loc[
        documents["content_sha256"].fillna("").astype(str).ne(""),
        ["source_url", "content_sha256"],
    ]
    phase4_registry_path = args.out_dir / "phase4_source_registry.csv"
    if phase4_registry_path.exists():
        phase4_hashes = pd.read_csv(phase4_registry_path, dtype=str)[
            ["source_url", "content_sha256"]
        ]
        hash_rows = pd.concat([hash_rows, phase4_hashes], ignore_index=True)
    hash_conflicts = (
        hash_rows.dropna().groupby("source_url")["content_sha256"].nunique()
    )
    if hash_conflicts.gt(1).any():
        raise ValueError("同一分派来源URL存在多个SHA-256")
    hash_map = (
        hash_rows.dropna()
        .drop_duplicates("source_url")
        .set_index("source_url")["content_sha256"]
    )
    events["source_sha256"] = events["source_url"].map(hash_map)
    if not events["source_sha256"].fillna("").str.fullmatch(r"[0-9a-f]{64}").all():
        raise ValueError("全市场分派事件存在缺失或非法来源SHA-256")

    events.to_csv(args.out_dir / "full_market_distributions.csv", index=False)
    review_path = args.out_dir / "full_market_distribution_verification_queue.csv"
    existing_reviews = (
        pd.read_csv(review_path, dtype=str) if review_path.exists() else None
    )
    reviews = build_distribution_verification_queue(events, existing=existing_reviews)
    reviews.to_csv(review_path, index=False)
    print(
        f"分派公告文档 {len(documents)}份；成功 {len(successful)}份；"
        f"可用事件 {len(events)}次；自动失败 {len(documents) - len(successful)}份"
    )


if __name__ == "__main__":
    main()
