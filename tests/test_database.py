import pandas as pd
import pytest

from creit_quant.database import (
    audit_default_pilot_database,
    audit_research_database,
    build_metric_coverage,
    load_metric_definitions,
    load_reit_master,
    load_source_documents,
)
from creit_quant.hydropower import load_hydropower_asset, load_hydropower_metrics
from creit_quant.strategy import load_distributions


def test_default_pilot_database_has_complete_relations():
    audit = audit_default_pilot_database()

    assert audit["securities"] == 1
    assert audit["assets"] == 1
    assert audit["operating_observations"] == 32
    assert audit["source_documents"] == 10
    assert audit["verified_documents"] == 10
    assert audit["quarter_start"] == "2024Q2"
    assert audit["quarter_end"] == "2026Q1"
    assert audit["coverage_cells"] == 32
    assert audit["coverage_pct"] == 100.0


def test_metric_coverage_marks_missing_cells():
    metrics = load_hydropower_metrics().iloc[1:].copy()
    coverage = build_metric_coverage(
        metrics,
        {
            "power_generation",
            "utilization_hours",
            "settled_electricity",
            "settlement_tariff_excl_tax",
        },
    )

    assert len(coverage) == 32
    assert coverage["status"].value_counts().to_dict() == {
        "available": 31,
        "missing": 1,
    }


def test_database_audit_rejects_unregistered_source_url():
    metrics = load_hydropower_metrics()
    metrics.loc[0, "source_url"] = "https://example.test/unregistered.pdf"

    with pytest.raises(ValueError, match="未登记的来源 URL"):
        audit_research_database(
            load_reit_master(),
            load_hydropower_asset(),
            metrics,
            load_distributions(),
            load_source_documents(),
            load_metric_definitions(),
        )


def test_database_audit_rejects_mismatched_document_period():
    metrics = load_hydropower_metrics()
    metrics.loc[0, "period_end"] = metrics.loc[0, "period_end"] + pd.offsets.QuarterEnd()

    with pytest.raises(ValueError, match="与来源公告"):
        audit_research_database(
            load_reit_master(),
            load_hydropower_asset(),
            metrics,
            load_distributions(),
            load_source_documents(),
            load_metric_definitions(),
        )
