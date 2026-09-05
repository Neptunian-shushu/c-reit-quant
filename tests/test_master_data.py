import pandas as pd
import pytest
from pathlib import Path

from creit_quant.master_data import (
    apply_security_overrides,
    build_month_end_tradable_universe,
    build_security_master,
    build_universe_snapshot,
    classify_asset_type_candidates,
    extract_official_asset_type_evidence,
    extract_official_listing_records,
    merge_universe_history,
)

ROOT = Path(__file__).resolve().parents[1]


def test_official_listing_records_exclude_expansion_and_accept_visual_override():
    catalog = pd.DataFrame(
        {
            "symbol": ["508026", "508026"],
            "publication_date": ["2024-03-28", "2026-06-01"],
            "title": ["某基金上市交易提示性公告", "某基金扩募份额上市交易提示性公告"],
            "source_url": ["https://sse/list.pdf", "https://sse/expansion.pdf"],
            "exchange": ["SSE", "SSE"],
        }
    )
    override = pd.DataFrame(
        {
            "symbol": ["508008"],
            "listing_date": ["2022-07-08"],
            "publication_date": ["2022-07-05"],
            "exchange": ["SSE"],
            "source_url": ["https://sse/scanned.pdf"],
            "evidence_method": ["official_listing_document_page_4"],
            "verification_status": ["visual_verified_official_pdf"],
            "raw_text": ["上市交易日期为2022年7月8日"],
        }
    )

    records = extract_official_listing_records(catalog, override).set_index("symbol")

    assert set(records.index) == {"508008", "508026"}
    assert records.loc["508026", "listing_date"] == pd.Timestamp("2024-03-28")
    assert records.loc["508008", "listing_date"] == pd.Timestamp("2022-07-08")


def test_month_end_universe_uses_listing_dates_and_excludes_unlisted_products():
    listings = pd.DataFrame(
        {
            "symbol": ["508001", "508002"],
            "listing_date": pd.to_datetime(["2021-06-21", "2021-08-02"]),
            "publication_date": pd.to_datetime(["2021-06-21", "2021-08-02"]),
            "exchange": ["SSE", "SSE"],
            "source_url": ["https://sse/1.pdf", "https://sse/2.pdf"],
            "evidence_method": ["notice", "notice"],
            "verification_status": ["official_metadata_verified"] * 2,
            "raw_text": ["notice", "notice"],
        }
    )
    latest = pd.DataFrame(
        {
            "symbol": ["508001", "508002", "508003"],
            "name": ["甲REIT", "乙REIT", "未上市REIT"],
            "exchange": ["SSE", "SSE", "SSE"],
        }
    )

    history = build_month_end_tradable_universe(
        listings, latest, as_of_date="2021-09-15"
    )

    assert history["snapshot_date"].nunique() == 3
    counts = history.groupby("snapshot_date")["symbol"].nunique().tolist()
    assert counts == [1, 1, 2]
    assert "508003" not in set(history["symbol"])


def test_repository_listing_dates_match_first_real_market_dates():
    listings = pd.read_csv(
        ROOT / "data" / "samples" / "reit_official_listing_records.csv",
        dtype={"symbol": str},
    )
    membership = pd.read_csv(
        ROOT / "data" / "samples" / "reit_tradable_universe_monthly.csv",
        dtype={"symbol": str},
    )
    prices = pd.read_csv(
        ROOT / "data" / "snapshots" / "phase2_full_market_adjusted_history.csv",
        dtype={"symbol": str},
    )
    first_prices = prices.groupby("symbol")["date"].min()

    priced_listings = listings.loc[listings["symbol"].isin(first_prices.index)]
    assert len(listings) == 89
    assert len(priced_listings) == 88
    assert priced_listings.set_index("symbol")["listing_date"].eq(first_prices).all()
    assert listings.loc[
        ~listings["symbol"].isin(first_prices.index), "symbol"
    ].tolist() == ["181001"]
    assert membership["snapshot_date"].nunique() == 63
    assert len(membership) == 2559
    assert membership["source_url"].str.startswith("https://").all()


def test_universe_snapshot_keeps_source_quality_and_exchange():
    raw = pd.DataFrame(
        {
            "symbol": [508026, 180202, 508607],
            "name": ["嘉实水电REIT", "名称被截断...", "陆家嘴R"],
        }
    )

    snapshot = build_universe_snapshot(raw, "2026-08-28")

    assert snapshot["symbol"].tolist() == ["180202", "508026", "508607"]
    assert snapshot.set_index("symbol").loc["508026", "exchange"] == "SSE"
    assert snapshot.set_index("symbol").loc["180202", "exchange"] == "SZSE"
    assert (
        snapshot.set_index("symbol").loc["180202", "record_status"]
        == "needs_name_review"
    )
    assert (
        snapshot.set_index("symbol").loc["508607", "record_status"]
        == "needs_name_review"
    )


def test_universe_history_is_idempotent_and_rejects_conflict():
    first = build_universe_snapshot(
        pd.DataFrame({"symbol": [508026], "name": ["嘉实水电REIT"]}),
        "2026-08-28",
    )
    assert len(merge_universe_history(first, first)) == 1
    changed = first.copy()
    changed["name"] = "冲突名称"

    with pytest.raises(ValueError, match="冲突"):
        merge_universe_history(first, changed)


def test_security_master_does_not_call_first_seen_a_listing_date():
    first = build_universe_snapshot(
        pd.DataFrame({"symbol": [508026, 180202], "name": ["水电REIT", "高速REIT"]}),
        "2026-08-27",
    )
    second = build_universe_snapshot(
        pd.DataFrame({"symbol": [508026], "name": ["水电REIT"]}),
        "2026-08-28",
    )
    master = build_security_master(merge_universe_history(first, second))

    assert "listing_date" not in master
    assert (
        master.set_index("symbol").loc["180202", "present_in_latest_snapshot"] == False
    )  # noqa: E712


def test_asset_classification_is_explicitly_unverified():
    master = pd.DataFrame(
        {"symbol": ["180202", "508026"], "name": ["华夏越秀高速REIT", "嘉实清洁能源REIT"]}
    )

    candidates = classify_asset_type_candidates(master).set_index("symbol")

    assert candidates.loc["180202", "candidate_asset_type"] == "toll_road"
    assert candidates.loc["508026", "candidate_asset_type"] == "renewable"
    assert candidates["classification_status"].eq("needs_human_review").all()


def test_only_official_override_promotes_candidate_to_verified():
    candidates = classify_asset_type_candidates(
        pd.DataFrame(
            {
                "symbol": ["508607"],
                "name": ["陆家嘴R"],
                "record_status": ["needs_name_review"],
            }
        )
    )
    overrides = pd.DataFrame(
        {
            "symbol": ["508607"],
            "official_name": ["华安陆家嘴商业REIT"],
            "asset_type": ["retail"],
            "verification_status": ["human_verified"],
            "source_url": ["https://www.sse.com.cn/official.pdf"],
        }
    )

    result = apply_security_overrides(candidates, overrides).iloc[0]

    assert result["name"] == "华安陆家嘴商业REIT"
    assert result["candidate_asset_type"] == "retail"
    assert result["classification_status"] == "human_verified"
    assert result["record_status"] == "human_verified"


def test_official_title_asset_type_evidence_is_not_called_human_verified():
    catalog = pd.DataFrame(
        {
            "symbol": ["508001", "508010"],
            "publication_date": ["2026-07-21", "2026-07-21"],
            "title": [
                "某高速公路封闭式基础设施证券投资基金2026年第2季度报告",
                "某产业园封闭式基础设施证券投资基金2026年第2季度报告",
            ],
            "source_url": ["https://sse/road.pdf", "https://sse/park.pdf"],
            "document_type_candidate": ["quarterly_report", "quarterly_report"],
        }
    )

    result = extract_official_asset_type_evidence(catalog).set_index("symbol")

    assert result.loc["508001", "asset_type"] == "toll_road"
    assert result.loc["508010", "asset_type"] == "industrial_park"
    assert result["classification_status"].eq("official_title_evidence").all()
    assert result.loc["508001", "evidence_phrase"] == "高速公路"


def test_official_title_conflict_requires_review_and_manual_override_wins():
    catalog = pd.DataFrame(
        {
            "symbol": ["508096", "508096"],
            "publication_date": ["2025-01-01", "2026-01-01"],
            "title": ["某新能源基金公告", "某产业园基金公告"],
            "source_url": ["https://sse/energy.pdf", "https://sse/park.pdf"],
        }
    )
    conflict = extract_official_asset_type_evidence(catalog).iloc[0]
    assert conflict["asset_type"] == "unknown"
    assert conflict["classification_status"] == "conflicting_official_title_evidence"

    override = pd.DataFrame(
        {
            "symbol": ["508096"],
            "official_name": ["中航京能国际能源REIT"],
            "asset_type": ["mixed_energy"],
            "verification_status": ["human_verified"],
            "source_url": ["https://sse/report.pdf"],
            "notes": ["项目组合人工核验"],
        }
    )
    verified = extract_official_asset_type_evidence(catalog, override).iloc[0]
    assert verified["asset_type"] == "mixed_energy"
    assert verified["classification_status"] == "human_verified"
