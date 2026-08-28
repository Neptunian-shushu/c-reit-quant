from unittest.mock import Mock

import pandas as pd
import pytest

from creit_quant.announcements import (
    fetch_sse_reit_announcements,
    fetch_szse_reit_announcements,
    merge_announcement_catalogs,
    reclassify_announcement_catalog,
)


def test_sse_catalog_classifies_reports_but_keeps_them_unreviewed():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "pageHelp": {
            "data": [
                {
                    "SSEDATE": "2026-07-21",
                    "TITLE": "某基金2026年第2季度报告",
                    "SECURITY_CODE": "508026",
                    "URL": "/disclosure/fund/report.pdf",
                    "BULLETIN_TYPE_DESC": "定期报告(REITS)",
                    "ORG_BULLETIN_TYPE_DESC": "季度报告",
                }
            ]
        }
    }
    session = Mock()
    session.get.return_value = response

    frame = fetch_sse_reit_announcements(
        "508026", "2026-01-01", "2026-08-28", session=session
    )

    assert frame.loc[0, "document_type_candidate"] == "quarterly_report"
    assert frame.loc[0, "period_end_candidate"] == "2026-06-30"
    assert frame.loc[0, "catalog_status"] == "unreviewed"
    assert frame.loc[0, "source_url"] == "https://www.sse.com.cn/disclosure/fund/report.pdf"


def test_catalog_merge_is_idempotent_and_rejects_changed_title():
    columns = {
        "announcement_id": ["SSE_doc"],
        "symbol": ["508026"],
        "publication_date": pd.to_datetime(["2026-07-21"]),
        "title": ["季度报告"],
        "bulletin_type": ["定期报告(REITS)"],
        "original_type": ["季度报告"],
        "document_type_candidate": ["quarterly_report"],
        "period_end_candidate": ["2026-06-30"],
        "source_url": ["https://www.sse.com.cn/doc.pdf"],
        "exchange": ["SSE"],
        "catalog_status": ["unreviewed"],
    }
    frame = pd.DataFrame(columns)

    assert len(merge_announcement_catalogs(frame, frame)) == 1
    changed = frame.copy()
    changed["title"] = "冲突标题"
    with pytest.raises(ValueError, match="内容冲突"):
        merge_announcement_catalogs(frame, changed)


def test_valuation_and_audit_reports_are_not_fund_annual_reports():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "pageHelp": {
            "data": [
                {
                    "SSEDATE": "2026-03-31",
                    "TITLE": "某基金2025年度评估报告",
                    "SECURITY_CODE": "508026",
                    "URL": "/disclosure/fund/valuation.pdf",
                    "BULLETIN_TYPE_DESC": "定期报告(REITS)",
                    "ORG_BULLETIN_TYPE_DESC": "年度报告",
                },
                {
                    "SSEDATE": "2026-03-31",
                    "TITLE": "某基金2025年度审计报告",
                    "SECURITY_CODE": "508026",
                    "URL": "/disclosure/fund/audit.pdf",
                    "BULLETIN_TYPE_DESC": "定期报告(REITS)",
                    "ORG_BULLETIN_TYPE_DESC": "年度报告",
                },
            ]
        }
    }
    session = Mock()
    session.get.return_value = response

    frame = fetch_sse_reit_announcements(
        "508026", "2026-01-01", "2026-08-28", session=session
    )

    assert frame["document_type_candidate"].eq("other").all()
    assert frame["period_end_candidate"].isna().all()


def test_reclassification_excludes_notices_and_understands_chinese_years():
    frame = pd.DataFrame(
        {
            "title": [
                "某管理人旗下基金2025年年度报告提示性公告",
                "某基金二0二一年年度报告",
                "某基金2024年第2季度报告（更正稿）",
                "某基金2023年4季度报告",
            ],
            "original_type": ["年度报告", "年度报告", "季度报告", "季度报告"],
        }
    )

    result = reclassify_announcement_catalog(frame)

    assert result["document_type_candidate"].tolist() == [
        "other",
        "annual_report",
        "quarterly_report_corrected",
        "quarterly_report",
    ]
    assert result["period_end_candidate"].tolist() == [
        None,
        "2021-12-31",
        "2024-06-30",
        "2023-12-31",
    ]


def test_szse_catalog_uses_post_json_and_classifies_report():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "announceCount": 1,
        "data": [
            {
                "id": "uuid",
                "annId": 123,
                "title": "某REIT：某基金2026年中期报告",
                "publishTime": "2026-08-27 00:00:00",
                "attachPath": "/disc/report.pdf",
                "attachFormat": "PDF",
                "secCode": ["180101"],
            }
        ],
    }
    session = Mock()
    session.post.return_value = response

    frame = fetch_szse_reit_announcements(
        "180101", "2021-01-01", "2026-08-28", session=session
    )

    assert frame.loc[0, "announcement_id"] == "SZSE_123"
    assert frame.loc[0, "document_type_candidate"] == "semiannual_report"
    assert frame.loc[0, "period_end_candidate"] == "2026-06-30"
    assert frame.loc[0, "source_url"] == "https://disc.static.szse.cn/disc/report.pdf"
    request = session.post.call_args
    assert request.kwargs["json"]["stock"] == ["180101"]


def test_szse_catalog_follows_all_pages():
    responses = []
    for ann_id, day in [(1, "2026-08-26"), (2, "2026-08-27")]:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "announceCount": 2,
            "data": [
                {
                    "id": str(ann_id),
                    "annId": ann_id,
                    "title": f"某REIT：某基金{day[:4]}年第2季度报告",
                    "publishTime": f"{day} 00:00:00",
                    "attachPath": f"/disc/{ann_id}.pdf",
                    "attachFormat": "PDF",
                    "secCode": ["180101"],
                }
            ],
        }
        responses.append(response)
    session = Mock()
    session.post.side_effect = responses

    frame = fetch_szse_reit_announcements(
        "180101",
        "2021-01-01",
        "2026-08-28",
        page_size=1,
        session=session,
    )

    assert frame["announcement_id"].tolist() == ["SZSE_1", "SZSE_2"]
    assert session.post.call_count == 2
