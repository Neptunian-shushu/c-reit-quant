"""抓取公告响应元数据和 SHA-256，不保存大型原始文件。"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from creit_quant.announcements import load_announcement_catalog
from creit_quant.database import DEFAULT_DOCUMENTS_PATH, load_source_documents
from creit_quant.documents import (
    build_periodic_document_registry,
    enrich_document_metadata,
    merge_document_registries,
)


def main() -> None:
    """补齐公告内容哈希；只有指定 --write 才更新登记表。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default=str(DEFAULT_DOCUMENTS_PATH))
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--discover-catalog", help="从交易所公告目录发现指定证券的定期报告")
    parser.add_argument("--symbols", nargs="*", help="配合 --discover-catalog 使用的证券代码")
    parser.add_argument("--write", action="store_true", help="将抓取结果写回登记表")
    args = parser.parse_args()

    path = Path(args.registry)
    documents = load_source_documents(path)
    if args.discover_catalog:
        if not args.symbols:
            parser.error("--discover-catalog 必须同时指定 --symbols")
        catalog = load_announcement_catalog(args.discover_catalog)
        discovered = build_periodic_document_registry(catalog, args.symbols)
        before = len(documents)
        documents = merge_document_registries(documents, discovered)
        print(f"发现定期报告候选: {len(discovered)}，新增登记: {len(documents) - before}")
    enriched = enrich_document_metadata(documents, timeout=args.timeout)
    counts = enriched["retrieval_status"].value_counts().to_dict()
    print(f"公告总数: {len(enriched)}")
    print(f"抓取状态: {counts}")
    if args.write:
        serialised = enriched.copy()
        for column in ["period_end", "publication_date"]:
            serialised[column] = pd.to_datetime(
                serialised[column], errors="raise"
            ).dt.strftime("%Y-%m-%d")
        retrieved = serialised["retrieved_at"].notna()
        serialised.loc[retrieved, "retrieved_at"] = pd.to_datetime(
            serialised.loc[retrieved, "retrieved_at"], utc=True
        ).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        serialised.to_csv(path, index=False)
        print(f"公告登记表已更新: {path}")
    else:
        print("未指定 --write，登记表未修改")


if __name__ == "__main__":
    main()
