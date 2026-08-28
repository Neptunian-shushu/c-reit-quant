import pandas as pd
import pytest

from creit_quant.database import (
    audit_cross_asset_seed_database,
    audit_default_pilot_database,
    audit_periodic_document_sequences,
    audit_research_database,
    build_asset_type_coverage,
    build_metric_coverage,
    build_observation_versions,
    export_default_pilot_database,
    load_asset_metric_requirements,
    load_metric_definitions,
    load_reit_master,
    DEFAULT_CROSS_DOCUMENTS_PATH,
    load_source_documents,
    select_observations_as_of,
)
from creit_quant.hydropower import load_hydropower_asset, load_hydropower_metrics
from creit_quant.strategy import load_distributions


def test_default_pilot_database_has_complete_relations():
    audit = audit_default_pilot_database()

    assert audit["securities"] == 3
    assert audit["assets"] == 1
    assert audit["operating_observations"] == 36
    assert audit["source_documents"] == 11
    assert audit["verified_documents"] == 11
    assert audit["quarter_start"] == "2024Q2"
    assert audit["quarter_end"] == "2026Q2"
    assert audit["coverage_cells"] == 36
    assert audit["coverage_pct"] == 100.0
    assert audit["observation_versions"] == 36
    assert audit["revised_observations"] == 0


def test_cross_asset_seed_preserves_real_missing_coverage():
    audit = audit_cross_asset_seed_database()

    assert audit["securities"] == 3
    assert audit["assets"] == 3
    assert audit["operating_observations"] == 20
    assert audit["source_documents"] == 56
    assert audit["source_documents_used"] == 5
    assert audit["metadata_verified_documents"] == 51
    assert audit["coverage_cells"] == 12
    assert audit["available_cells"] == 10
    assert audit["coverage_pct"] == pytest.approx(83.3333, rel=1e-4)


def test_expansion_symbols_have_continuous_hashed_report_sequences():
    sequences = audit_periodic_document_sequences(
        load_source_documents(DEFAULT_CROSS_DOCUMENTS_PATH), ["508018", "508056"]
    ).set_index("symbol")

    assert sequences.loc["508018", "covered_quarters"] == 17
    assert sequences.loc["508056", "covered_quarters"] == 20
    assert sequences["consecutive"].all()
    assert sequences["registered_documents"].tolist() == [25, 30]
    assert sequences["hashed_documents"].tolist() == [25, 30]


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

    assert len(coverage) == 36
    assert coverage["status"].value_counts().to_dict() == {
        "available": 35,
        "missing": 1,
    }


def test_asset_type_coverage_uses_core_requirements():
    metrics = load_hydropower_metrics().iloc[1:].copy()
    coverage = build_asset_type_coverage(
        load_hydropower_asset(),
        metrics,
        load_asset_metric_requirements(),
    )

    assert len(coverage) == 36
    assert coverage["status"].eq("missing").sum() == 1


def test_point_in_time_versions_preserve_old_and_revised_values():
    metrics = pd.DataFrame(
        {
            "symbol": ["508026", "508026"],
            "asset_id": ["asset", "asset"],
            "period_end": pd.to_datetime(["2025-06-30", "2025-06-30"]),
            "metric": ["power_generation", "power_generation"],
            "value": [100.0, 105.0],
            "unit": ["10k_kWh", "10k_kWh"],
            "publication_date": pd.to_datetime(["2025-07-20", "2025-08-01"]),
            "source_url": ["https://example.test/initial", "https://example.test/revised"],
        }
    )
    documents = pd.DataFrame(
        {
            "document_id": ["initial", "revised"],
            "source_url": ["https://example.test/initial", "https://example.test/revised"],
            "verification_status": ["human_verified", "human_verified"],
        }
    )

    versions = build_observation_versions(metrics, documents)
    old = select_observations_as_of(versions, "2025-07-31")
    revised = select_observations_as_of(versions, "2025-08-01")

    assert old["value"].tolist() == [100.0]
    assert revised["value"].tolist() == [105.0]
    assert versions.loc[1, "supersedes_observation_id"] == versions.loc[0, "observation_id"]
    assert versions.loc[0, "valid_to"] == pd.Timestamp("2025-08-01")


def test_database_export_builds_versions_coverage_and_snapshot(tmp_path):
    paths = export_default_pilot_database(tmp_path, as_of="2025-07-31")

    assert set(paths) == {
        "observation_versions",
        "core_metric_coverage",
        "point_in_time_snapshot",
    }
    assert all(path.exists() for path in paths.values())
    snapshot = pd.read_csv(paths["point_in_time_snapshot"], dtype={"symbol": str})
    assert snapshot["snapshot_as_of"].eq("2025-07-31").all()
    assert pd.to_datetime(snapshot["valid_from"]).le(pd.Timestamp("2025-07-31")).all()


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


def test_source_document_lineage_accepts_later_correction(tmp_path):
    documents = pd.DataFrame(
        {
            "document_id": ["original", "corrected"],
            "symbol": ["508026", "508026"],
            "document_type": ["quarterly_report", "quarterly_report_corrected"],
            "period_end": ["2025-06-30", "2025-06-30"],
            "publication_date": ["2025-07-20", "2025-08-01"],
            "source_url": ["https://example.test/original", "https://example.test/corrected"],
            "verification_status": ["human_verified", "human_verified"],
            "supersedes_document_id": [pd.NA, "original"],
            "content_sha256": ["a" * 64, "b" * 64],
        }
    )
    path = tmp_path / "documents.csv"
    documents.to_csv(path, index=False)

    loaded = load_source_documents(path)

    assert loaded.loc[1, "supersedes_document_id"] == "original"


def test_source_document_lineage_rejects_unknown_parent(tmp_path):
    documents = pd.DataFrame(
        {
            "document_id": ["corrected"],
            "symbol": ["508026"],
            "document_type": ["quarterly_report_corrected"],
            "period_end": ["2025-06-30"],
            "publication_date": ["2025-08-01"],
            "source_url": ["https://example.test/corrected"],
            "verification_status": ["human_verified"],
            "supersedes_document_id": ["missing"],
        }
    )
    path = tmp_path / "documents.csv"
    documents.to_csv(path, index=False)

    with pytest.raises(ValueError, match="未登记 document_id"):
        load_source_documents(path)
