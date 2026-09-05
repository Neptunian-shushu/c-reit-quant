"""联网构建全市场年末基金份额与账面NAV面板；PDF不写入仓库。"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from creit_quant.fundamentals_parser import parse_annual_fundamentals_text
from creit_quant.verification import build_fundamental_verification_queue

ROOT = Path(__file__).resolve().parents[2]
AUDIT_NAME = "full_market_annual_document_audit.csv"
AUDIT_COLUMNS = [
    "announcement_id",
    "symbol",
    "publication_date",
    "period_end_candidate",
    "title",
    "source_url",
    "retrieved_at",
    "content_sha256",
    "content_length_bytes",
    "retrieval_status",
    "failure_reason",
    "fund_shares",
    "nav_per_unit",
    "raw_text",
]


def _fetch(row: pd.Series, timeout: float) -> dict[str, object]:
    result = row.to_dict()
    result.update(
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        content_sha256="",
        content_length_bytes=pd.NA,
        retrieval_status="failed",
        failure_reason="",
        fund_shares=pd.NA,
        nav_per_unit=pd.NA,
        raw_text="",
    )
    try:
        if shutil.which("pdftotext") is None:
            raise ValueError("未找到pdftotext，请先安装Poppler")
        url = str(row["source_url"])
        referer = (
            "https://reits.szse.cn/disclosure/index.html"
            if "szse.cn" in url
            else "https://etf.sse.com.cn/disclosure/fundnotice/"
        )
        response = requests.get(
            url,
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
            timeout=timeout,
            check=False,
        )
        if converted.returncode != 0:
            raise ValueError("pdftotext转换失败")
        metrics = parse_annual_fundamentals_text(
            converted.stdout.decode("utf-8", errors="ignore"),
            row["period_end_candidate"],
        )
        values = {item["metric"]: item["value"] for item in metrics}
        result["fund_shares"] = values["fund_shares"]
        result["nav_per_unit"] = values["nav_per_unit"]
        result["raw_text"] = metrics[0]["raw_text"]
        result["retrieval_status"] = "success"
    except (requests.RequestException, subprocess.SubprocessError, ValueError) as exc:
        result["failure_reason"] = str(exc)
    return result


def fetch_annual_documents(
    catalog: pd.DataFrame, *, timeout: float = 40, workers: int = 4
) -> pd.DataFrame:
    """抓取年报并抽取两项事实，返回文档级断点审计。"""

    if workers <= 0:
        raise ValueError("workers必须为正整数")
    selected = catalog.loc[catalog["document_type_candidate"].eq("annual_report")][
        [
            "announcement_id",
            "symbol",
            "publication_date",
            "period_end_candidate",
            "title",
            "source_url",
        ]
    ].copy()
    if selected.empty:
        return pd.DataFrame(columns=AUDIT_COLUMNS)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        rows = list(
            executor.map(lambda item: _fetch(item[1], timeout), selected.iterrows())
        )
    return (
        pd.DataFrame(rows)
        .sort_values(["symbol", "period_end_candidate", "announcement_id"])
        .reset_index(drop=True)
    )


def build_annual_observations(audit: pd.DataFrame) -> pd.DataFrame:
    """把成功文档展开为long format；重复年度事实不一致时拒绝合并。"""

    success = audit.loc[audit["retrieval_status"].eq("success")].copy()
    rows: list[dict[str, object]] = []
    for key, group in success.groupby(["symbol", "period_end_candidate"]):
        if group[["fund_shares", "nav_per_unit"]].drop_duplicates().shape[0] > 1:
            raise ValueError(f"同一证券年度存在冲突基金事实: {key}")
        row = group.sort_values("announcement_id").iloc[-1]
        for metric, unit in [
            ("fund_shares", "shares"),
            ("nav_per_unit", "RMB_per_unit"),
        ]:
            rows.append(
                {
                    "symbol": row["symbol"],
                    "period_end": row["period_end_candidate"],
                    "publication_date": row["publication_date"],
                    "metric": metric,
                    "value": row[metric],
                    "unit": unit,
                    "source_url": row["source_url"],
                    "source_sha256": row["content_sha256"],
                    "verification_status": "machine_extracted_official_pdf",
                    "raw_text": row["raw_text"],
                }
            )
    return pd.DataFrame(rows).sort_values(["symbol", "period_end", "metric"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=ROOT / "data" / "snapshots" / "reit_announcement_catalog.csv",
    )
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data" / "samples")
    parser.add_argument("--timeout", type=float, default=40)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--refresh-all", action="store_true")
    parser.add_argument(
        "--retry-parse-failures",
        action="store_true",
        help="仅重试上交所已失败年报，用于验证规则修订或恢复短暂网络失败",
    )
    parser.add_argument("--rebuild-from-audit", action="store_true")
    args = parser.parse_args()
    catalog = pd.read_csv(args.catalog, dtype={"symbol": str})
    audit_path = args.out_dir / AUDIT_NAME
    previous = (
        pd.read_csv(audit_path, dtype={"symbol": str})
        if audit_path.exists() and not args.refresh_all
        else None
    )
    if args.rebuild_from_audit:
        if previous is None:
            raise ValueError("离线重建要求已有年报审计表")
        audit = previous
    else:
        successful_ids = (
            set(
                previous.loc[
                    previous["retrieval_status"].eq("success"), "announcement_id"
                ]
            )
            if previous is not None
            else set()
        )
        if args.retry_parse_failures and previous is not None:
            retry_ids = set(
                previous.loc[
                    previous["retrieval_status"].eq("failed")
                    & previous["source_url"].str.contains("sse.com.cn", na=False),
                    "announcement_id",
                ]
            )
            pending = catalog.loc[catalog["announcement_id"].isin(retry_ids)]
        else:
            pending = catalog.loc[~catalog["announcement_id"].isin(successful_ids)]
        fetched = fetch_annual_documents(
            pending, timeout=args.timeout, workers=args.workers
        )
        kept = (
            previous.loc[
                ~previous["announcement_id"].isin(fetched.get("announcement_id", []))
            ]
            if previous is not None
            else pd.DataFrame()
        )
        audit = (
            kept.reset_index(drop=True)
            if fetched.empty
            else pd.concat([kept, fetched], ignore_index=True)
        )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    audit.to_csv(audit_path, index=False)
    observations = build_annual_observations(audit)
    observations.to_csv(
        args.out_dir / "full_market_annual_fundamentals.csv", index=False
    )
    review_path = (
        args.out_dir / "full_market_annual_fundamentals_verification_queue.csv"
    )
    existing_review = (
        pd.read_csv(review_path, dtype=str) if review_path.exists() else None
    )
    review = build_fundamental_verification_queue(
        observations, existing=existing_review
    )
    review.to_csv(review_path, index=False)
    print(
        f"年报 {len(audit)}份；成功 {audit['retrieval_status'].eq('success').sum()}份；"
        f"观测 {len(observations)}条 / {observations['symbol'].nunique()}只"
    )


if __name__ == "__main__":
    main()
