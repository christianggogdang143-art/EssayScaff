"""Phase 7B: formal collection tooling, labels, packages, freeze integrity."""

import pytest

from app import create_app
from services import db
from services.validation import annotations as annotations_mod
from services.validation import datasets as datasets_mod
from services.validation import demo as demo_mod
from services.validation import errornotes as errornotes_mod
from services.validation import io as io_mod
from services.validation import quality as quality_mod
from services.validation import reporting as reporting_mod
from services.validation import runs as runs_mod
from services.validation import snapshot as snapshot_mod

RECORDED_RULES_HASH = "8ac38bf3b5b01354f679d1dbb20c3824bdbc9eb517a9ecdec543df1e85fe42c0"
RECORDED_CONFIG_HASH = "401f3a4bce3910ec8ca63d846ddce84a9e61881fb619bdf75778ac7e3e95c915"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    application = create_app(prewarm=False)
    application.config.update(TESTING=True)
    return application.test_client()


def _formal_thesis():
    return datasets_mod.create_dataset(
        name="THESIS_002 Formal Validation Round 1", detector_id="THESIS_002")


def _add_annotated(ds, text, label, annotator="R1", **kw):
    s = datasets_mod.add_sample(ds["id"], raw_text=text, **kw)
    annotations_mod.annotate(s["id"], ds["detector_id"], annotator, label)
    return s


# ------------------------------------------------ VR-2 integrity
def test_vr2_hashes_unchanged(client):
    rec = snapshot_mod.freeze_record()
    assert rec["ruleset_version"] == "VR-2"
    assert rec["status"] == "FROZEN_FOR_VALIDATION"
    assert rec["rules_dir_sha256"] == RECORDED_RULES_HASH
    assert rec["config_hash"] == RECORDED_CONFIG_HASH
    assert snapshot_mod.config_hash() == RECORDED_CONFIG_HASH  # stable
    assert rec["thresholds"]["TOPIC_MODERATE_THRESHOLD"] == 0.30
    assert rec["thresholds"]["TOPIC_STRONG_THRESHOLD"] == 0.60


# ------------------------------------------------ formal datasets
def test_formal_datasets_created_empty(client):
    ds = _formal_thesis()
    assert ds["is_demo"] is False
    assert ds["status"] == "DRAFT"
    assert ds["sample_count"] == 0
    assert ds["ruleset_version"] == "VR-2"
    assert ds["protocol_version"] == "THESIS002_PROTOCOL_V1"
    topic = datasets_mod.create_dataset(
        name="Topic Classifier Formal Validation Round 1",
        detector_id="TOPIC_CLASSIFIER")
    assert topic["protocol_version"] == "TOPIC_PROTOCOL_V1"
    assert topic["validation_type"] == "MULTICLASS"
    formal = datasets_mod.list_datasets(include_demo=False)
    assert {d["id"] for d in formal} == {ds["id"], topic["id"]}


def test_formal_demo_separation(client):
    formal = _formal_thesis()
    demo = demo_mod.ensure_demo_datasets()["binary"]
    assert formal["is_demo"] is False
    assert demo["is_demo"] is True
    # ensure_demo_datasets leaves new demos in ANNOTATING; freeze directly.
    frozen = datasets_mod.freeze_dataset(demo["id"])
    run = runs_mod.create_run(frozen["id"])
    assert reporting_mod.result_label(run["id"]).startswith("DEMO DATA")


# ------------------------------------------------ progress
def test_progress_counts_no_predictions(client):
    ds = _formal_thesis()
    _add_annotated(ds, "This essay will discuss crops.", "META_STATEMENT")
    _add_annotated(ds, "Farmers adapt to rainfall.", "NOT_META_STATEMENT")
    s3 = datasets_mod.add_sample(ds["id"], raw_text="Climate shapes harvests.")
    annotations_mod.annotate(s3["id"], "THESIS_002", "R1", "UNCLEAR")
    s4 = datasets_mod.add_sample(ds["id"], raw_text="Duplicate prose here.")
    datasets_mod.exclude_sample(s4["id"], "out of scope")
    prog = quality_mod.progress(ds["id"])
    assert prog["total_samples"] == 4
    assert prog["included"] == 3 and prog["excluded"] == 1
    assert prog["annotated"] == 2 and prog["unclear"] == 1
    assert prog["remaining"] == 0
    assert prog["class_counts"] == {"META_STATEMENT": 1, "NOT_META_STATEMENT": 1}
    assert "prediction" not in str(prog).lower()


# ------------------------------------------------ duplicates
def test_duplicates_flagged_and_retained(client):
    ds = _formal_thesis()
    _add_annotated(ds, "Farmers adapt to rainfall.", "NOT_META_STATEMENT")
    _add_annotated(ds, "  farmers ADAPT to rainfall. ", "NOT_META_STATEMENT")
    _add_annotated(ds, "This essay will discuss crops.", "META_STATEMENT")
    dupes = quality_mod.duplicates(ds["id"])
    assert len(dupes) == 1
    assert dupes[0]["flag"] == "DUPLICATE CANDIDATE"
    assert len(dupes[0]["sample_ids"]) == 2
    assert datasets_mod.list_samples(ds["id"], included_only=True) != []


# ------------------------------------------------ quality + freeze preview
def test_quality_summary_and_preview(client):
    ds = _formal_thesis()
    _add_annotated(ds, "This essay will discuss crops.", "META_STATEMENT")
    q = quality_mod.quality_summary(ds["id"])
    assert q["dataset_name"] == "THESIS_002 Formal Validation Round 1"
    assert q["detector_id"] == "THESIS_002"
    assert q["protocol_version"] == "THESIS002_PROTOCOL_V1"
    assert q["ruleset_version"] == "VR-2"
    assert q["total_samples"] == 1 and q["included_samples"] == 1
    assert q["annotator_count"] == 1
    assert q["double_coded_samples"] == 0
    assert q["provenance_breakdown"] == {"HUMAN_CREATED_RESEARCH_SAMPLE": 1}
    assert q["freeze_eligible"] is False  # still DRAFT
    assert any("ANNOTATING" in r for r in q["freeze_blockers"])
    preview = quality_mod.freeze_preview(ds["id"])
    assert preview["approval_statement"].startswith("This action locks")
    assert len(preview["current_hash_if_frozen_now"]) == 64


def test_freeze_rejects_incomplete_and_unresolved(client):
    ds = _formal_thesis()
    datasets_mod.add_sample(ds["id"], raw_text="Climate shapes harvests.")
    datasets_mod.set_status(ds["id"], "ANNOTATING")
    with pytest.raises(datasets_mod.ValidationError):
        datasets_mod.freeze_dataset(ds["id"])  # unannotated
    s = datasets_mod.list_samples(ds["id"])[0]
    annotations_mod.annotate(s["id"], "THESIS_002", "R1", "UNCLEAR")
    with pytest.raises(datasets_mod.ValidationError) as exc:
        datasets_mod.freeze_dataset(ds["id"])  # unresolved UNCLEAR
    assert "UNCLEAR" in str(exc.value)
    annotations_mod.adjudicate(s["id"], "NOT_META_STATEMENT", "clear on re-read")
    frozen = datasets_mod.freeze_dataset(ds["id"])
    assert frozen["status"] == "FROZEN"


# ------------------------------------------------ formal run + labels
def test_formal_run_labeled_formal(client):
    ds = _formal_thesis()
    _add_annotated(ds, "This essay will discuss crops.", "META_STATEMENT")
    _add_annotated(ds, "Farmers adapt to rainfall.", "NOT_META_STATEMENT")
    datasets_mod.set_status(ds["id"], "ANNOTATING")
    datasets_mod.freeze_dataset(ds["id"])
    run = runs_mod.create_run(ds["id"])
    assert run["sample_count"] == 2
    assert reporting_mod.result_label(run["id"]) == "FORMAL VR-2 VALIDATION RESULT"
    ms = reporting_mod.manuscript_summary(run["id"])
    assert ms["result_label"] == "FORMAL VR-2 VALIDATION RESULT"
    detail = runs_mod.get_run_detail(run["id"])
    f1 = next(m["metric_value"] for m in detail["metrics"]
              if m["metric_name"] == "f1")
    assert f"F1: {f1:.4f}" in ms["text"]
    assert "THESIS002_PROTOCOL_V1" in ms["text"]


# ------------------------------------------------ error categories
def test_error_categories_document_only(client):
    assert "THRESHOLD_BOUNDARY" in errornotes_mod.ERROR_CATEGORIES
    assert len(errornotes_mod.ERROR_CATEGORIES) == 8
    ds = _formal_thesis()
    _add_annotated(ds, "This essay will discuss crops.", "META_STATEMENT")
    datasets_mod.set_status(ds["id"], "ANNOTATING")
    datasets_mod.freeze_dataset(ds["id"])
    run = runs_mod.create_run(ds["id"])
    sid = datasets_mod.list_samples(ds["id"])[0]["id"]
    with pytest.raises(datasets_mod.ValidationError):
        errornotes_mod.add_error_note(run["id"], sid, "NOPE", "x", "analyst")
    note = errornotes_mod.add_error_note(
        run["id"], sid, "PATTERN_FALSE_POSITIVE", "review", "analyst-A")
    assert note["category"] == "PATTERN_FALSE_POSITIVE"
    assert len(errornotes_mod.list_error_notes(run["id"])) == 1


# ------------------------------------------------ export package
def test_research_package_complete(client):
    pair = demo_mod.ensure_demo_datasets()
    ds = datasets_mod.freeze_dataset(pair["binary"]["id"])
    run = runs_mod.create_run(ds["id"])
    pkg = reporting_mod.research_package(run["id"])
    for key in ("dataset_metadata", "sample_counts", "provenance_summary",
                "annotation_protocol", "annotator_summary", "dataset_hash",
                "ruleset_snapshot", "config_hash", "validation_run_id",
                "confusion_matrix", "metrics", "excluded_sample_report",
                "unclear_adjudication_report", "error_case_table",
                "error_notes", "environment_snapshot", "manuscript_summary",
                "artifacts"):
        assert key in pkg, key
    assert pkg["result_label"].startswith("DEMO DATA")
    data_lines = [ln for ln in pkg["artifacts"]["dataset_csv"].splitlines()
                  if not ln.startswith("#")]
    assert data_lines[0].startswith("sample_id,")
    assert len(pkg["error_case_table"]) == 6


def test_student_workflow_unchanged(client):
    assert client.get("/").status_code == 200
    assert client.get("/research/validation").status_code == 200
