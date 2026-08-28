import pandas as pd
import pytest

from creit_quant.master_data import (
    apply_security_overrides,
    build_security_master,
    build_universe_snapshot,
    classify_asset_type_candidates,
    merge_universe_history,
)


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
    assert snapshot.set_index("symbol").loc["180202", "record_status"] == "needs_name_review"
    assert snapshot.set_index("symbol").loc["508607", "record_status"] == "needs_name_review"


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
    assert master.set_index("symbol").loc["180202", "present_in_latest_snapshot"] == False  # noqa: E712


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
        pd.DataFrame({"symbol": ["508607"], "name": ["陆家嘴R"], "record_status": ["needs_name_review"]})
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
