"""联网构建全市场季报／中报基金事实面板；PDF不写入仓库。"""

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

from creit_quant.fundamentals_parser import parse_periodic_fundamentals_text
from creit_quant.verification import build_fundamental_verification_queue

ROOT = Path(__file__).resolve().parents[2]
AUDIT_NAME = "full_market_periodic_document_audit.csv"
OUTPUT_NAME = "full_market_periodic_fundamentals.csv"
REVIEW_NAME = "full_market_periodic_fundamentals_verification_queue.csv"
RECONCILIATION_NAME = "full_market_periodic_reconciliation.csv"
COMBINED_NAME = "full_market_fundamentals.csv"
DOCUMENT_TYPES = {"quarterly_report", "semiannual_report"}
AUDIT_COLUMNS = [
    "announcement_id",
    "symbol",
    "publication_date",
    "period_end_candidate",
    "document_type",
    "is_corrected",
    "title",
    "source_url",
    "retrieved_at",
    "content_sha256",
    "content_length_bytes",
    "retrieval_status",
    "failure_reason",
    "fund_shares",
    "distributable_amount_period",
    "distributable_amount_per_unit_period",
    "nav_per_unit",
    "raw_text",
]


def _base_document_type(value: object) -> str:
    return str(value).removesuffix("_corrected")


def _fetch(row: pd.Series, timeout: float) -> dict[str, object]:
    result = row.to_dict()
    result.update(
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        content_sha256="",
        content_length_bytes=pd.NA,
        retrieval_status="failed",
        failure_reason="",
        fund_shares=pd.NA,
        distributable_amount_period=pd.NA,
        distributable_amount_per_unit_period=pd.NA,
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
        metrics = parse_periodic_fundamentals_text(
            converted.stdout.decode("utf-8", errors="ignore"),
            row["period_end_candidate"],
            row["document_type"],
        )
        for metric in metrics:
            result[str(metric["metric"])] = metric["value"]
        result["raw_text"] = metrics[0]["raw_text"]
        result["retrieval_status"] = "success"
    except (requests.RequestException, subprocess.SubprocessError, ValueError) as exc:
        result["failure_reason"] = str(exc)
    return result


def fetch_periodic_documents(
    catalog: pd.DataFrame, *, timeout: float = 40, workers: int = 4
) -> pd.DataFrame:
    """抓取季报和中报并抽取基金事实，返回文档级审计。"""

    if workers <= 0:
        raise ValueError("workers必须为正整数")
    selected = catalog[
        [
            "announcement_id",
            "symbol",
            "publication_date",
            "period_end_candidate",
            "document_type_candidate",
            "title",
            "source_url",
        ]
    ].copy()
    selected["document_type"] = selected["document_type_candidate"].map(
        _base_document_type
    )
    selected["is_corrected"] = (
        selected["document_type_candidate"].astype(str).str.endswith("_corrected")
    )
    selected = selected.loc[selected["document_type"].isin(DOCUMENT_TYPES)].drop(
        columns="document_type_candidate"
    )
    if selected.empty:
        return pd.DataFrame(columns=AUDIT_COLUMNS)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        rows = list(
            executor.map(lambda item: _fetch(item[1], timeout), selected.iterrows())
        )
    return (
        pd.DataFrame(rows, columns=AUDIT_COLUMNS)
        .sort_values(["symbol", "period_end_candidate", "publication_date"])
        .reset_index(drop=True)
    )


def build_periodic_observations(audit: pd.DataFrame) -> pd.DataFrame:
    """把成功文档展开为long format，保留更正稿的公布时点。"""

    success = audit.loc[audit["retrieval_status"].eq("success")].copy()
    metric_units = {
        "fund_shares": "shares",
        "distributable_amount_period": "RMB",
        "distributable_amount_per_unit_period": "RMB_per_unit",
        "nav_per_unit": "RMB_per_unit",
    }
    document_keys = [
        "symbol",
        "period_end_candidate",
        "publication_date",
        "document_type",
    ]
    selected_documents = []
    for key, group in success.groupby(document_keys, sort=False):
        corrected = group.loc[group["is_corrected"].astype(bool)]
        if len(corrected) > 1:
            raise ValueError(f"同一公布时点存在多份更正稿: {key}")
        if len(corrected) == 1:
            selected_documents.append(corrected.iloc[0])
            continue
        fact_columns = list(metric_units)
        if group[fact_columns].drop_duplicates().shape[0] > 1:
            raise ValueError(f"同一公布时点存在冲突基金事实: {key}")
        selected_documents.append(group.sort_values("announcement_id").iloc[-1])

    rows: list[dict[str, object]] = []
    for document in pd.DataFrame(selected_documents).itertuples(index=False):
        expected = (
            list(metric_units)
            if document.document_type == "semiannual_report"
            else list(metric_units)[:3]
        )
        for metric in expected:
            value = getattr(document, metric)
            if pd.isna(value):
                raise ValueError(f"成功文档缺少已声明指标: {document.announcement_id} {metric}")
            rows.append(
                {
                    "symbol": document.symbol,
                    "period_end": document.period_end_candidate,
                    "publication_date": document.publication_date,
                    "document_type": document.document_type,
                    "is_corrected": document.is_corrected,
                    "metric": metric,
                    "value": value,
                    "unit": metric_units[metric],
                    "source_url": document.source_url,
                    "source_sha256": document.content_sha256,
                    "verification_status": "machine_extracted_official_pdf",
                    "raw_text": document.raw_text,
                }
            )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    key = ["symbol", "period_end", "publication_date", "metric"]
    return result.sort_values(key).reset_index(drop=True)


def build_periodic_reconciliation(observations: pd.DataFrame) -> pd.DataFrame:
    """勾稽可供分配金额、期末份额与披露单位金额。"""

    index = [
        "symbol",
        "period_end",
        "publication_date",
        "document_type",
        "source_url",
        "source_sha256",
    ]
    wide = observations.pivot(
        index=index, columns="metric", values="value"
    ).reset_index()
    required = {
        "fund_shares",
        "distributable_amount_period",
        "distributable_amount_per_unit_period",
    }
    if not required.issubset(wide.columns) or wide[list(required)].isna().any().any():
        raise ValueError("定期报告勾稽缺少必要指标")
    wide["calculated_amount_per_unit"] = (
        wide["distributable_amount_period"] / wide["fund_shares"]
    )
    wide["absolute_difference"] = (
        wide["calculated_amount_per_unit"]
        - wide["distributable_amount_per_unit_period"]
    ).abs()
    wide["reconciliation_status"] = "within_disclosure_precision"
    wide.loc[
        wide["absolute_difference"].gt(0.0051), "reconciliation_status"
    ] = "needs_review"
    return wide[
        index
        + [
            "fund_shares",
            "distributable_amount_period",
            "distributable_amount_per_unit_period",
            "calculated_amount_per_unit",
            "absolute_difference",
            "reconciliation_status",
        ]
    ].sort_values(["symbol", "period_end", "publication_date"])


def build_full_market_fundamental_panel(
    periodic: pd.DataFrame, annual: pd.DataFrame | None = None
) -> pd.DataFrame:
    """合并季报、中报和年报基金事实，保留各自公布时点。"""

    frames = [periodic.copy()]
    if annual is not None and not annual.empty:
        annual_frame = annual.copy()
        annual_frame["document_type"] = "annual_report"
        annual_frame["is_corrected"] = False
        frames.append(annual_frame)
    combined = pd.concat(frames, ignore_index=True)
    columns = [
        "symbol",
        "period_end",
        "publication_date",
        "document_type",
        "is_corrected",
        "metric",
        "value",
        "unit",
        "source_url",
        "source_sha256",
        "verification_status",
        "raw_text",
    ]
    missing = sorted(set(columns).difference(combined.columns))
    if missing:
        raise ValueError(f"全市场基金事实缺少字段: {missing}")
    combined = combined[columns]
    key = ["symbol", "period_end", "publication_date", "metric"]
    if combined.duplicated(key).any():
        raise ValueError("全市场基金事实时点键重复")
    if not combined["source_sha256"].astype(str).str.fullmatch(r"[0-9a-f]{64}").all():
        raise ValueError("全市场基金事实存在非法来源哈希")
    if (
        pd.to_datetime(combined["publication_date"], errors="raise")
        < pd.to_datetime(combined["period_end"], errors="raise")
    ).any():
        raise ValueError("基金事实公布日不能早于报告期末")
    return combined.sort_values(key).reset_index(drop=True)


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
        "--retry-parser-failures-only",
        action="store_true",
        help="只重试已有审计中的非HTTP解析失败",
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
            raise ValueError("离线重建要求已有定期报告审计表")
        documents = previous
    else:
        if previous is None:
            pending = catalog
        else:
            success_ids = set(
                previous.loc[
                    previous["retrieval_status"].eq("success"), "announcement_id"
                ]
            )
            pending_ids = set(previous["announcement_id"]).difference(success_ids)
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
            pending = catalog.loc[catalog["announcement_id"].isin(pending_ids)]
        fetched = fetch_periodic_documents(
            pending, timeout=args.timeout, workers=args.workers
        )
        kept = (
            previous.loc[
                ~previous["announcement_id"].isin(fetched["announcement_id"])
            ].copy()
            if previous is not None
            else pd.DataFrame()
        )
        numeric_columns = [
            "content_length_bytes",
            "fund_shares",
            "distributable_amount_period",
            "distributable_amount_per_unit_period",
            "nav_per_unit",
        ]
        for column in numeric_columns:
            if column in kept:
                kept[column] = pd.to_numeric(kept[column], errors="coerce")
            if column in fetched:
                fetched[column] = pd.to_numeric(fetched[column], errors="coerce")
        documents = (
            kept.reset_index(drop=True)
            if fetched.empty
            else pd.concat([kept, fetched], ignore_index=True)
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    documents.to_csv(audit_path, index=False)
    observations = build_periodic_observations(documents)
    observations.to_csv(args.out_dir / OUTPUT_NAME, index=False)
    reconciliation = build_periodic_reconciliation(observations)
    reconciliation.to_csv(args.out_dir / RECONCILIATION_NAME, index=False)
    annual_path = args.out_dir / "full_market_annual_fundamentals.csv"
    annual = (
        pd.read_csv(annual_path, dtype={"symbol": str})
        if annual_path.exists()
        else None
    )
    combined = build_full_market_fundamental_panel(observations, annual)
    combined.to_csv(args.out_dir / COMBINED_NAME, index=False)
    review_path = args.out_dir / REVIEW_NAME
    existing_review = (
        pd.read_csv(review_path, dtype=str) if review_path.exists() else None
    )
    review = build_fundamental_verification_queue(
        observations,
        dataset="full_market_periodic_fundamentals",
        existing=existing_review,
    )
    review.to_csv(review_path, index=False)
    successful = documents["retrieval_status"].eq("success")
    print(
        f"定期报告 {len(documents)}份；成功 {successful.sum()}份；"
        f"观测 {len(observations)}条 / {observations['symbol'].nunique()}只"
    )


if __name__ == "__main__":
    main()
