"""Phase 7A: CSV import/export, JSON export envelope, provenance."""

import json

import pytest

from app import create_app
from services import db
from services.validation import datasets as datasets_mod
from services.validation import demo as demo_mod
from services.validation import io as io_mod
from services.validation import protocols
from services.validation import runs as runs_mod


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    application = create_app(prewarm=False)
    application.config.update(TESTING=True)
    return application.test_client()


def test_thesis_csv_import_roundtrip(client):
    ds = datasets_mod.create_dataset(name="CSV", detector_id="THESIS_002")
    csv_text = ("sample_id,text,human_label,source,notes\n"
                "a1,This essay will discuss crops.,META_STATEMENT,field,ok\n"
                "a2,Farmers adapt to rainfall.,NOT_META_STATEMENT,field,ok\n")
    result = io_mod.import_csv(ds["id"], csv_text, annotator_id="R1")
    assert result["added"] == 2
    assert result["errors"] == []
    assert result["dataset"]["sample_count"] == 2
    out = io_mod.export_dataset_csv(ds["id"])
    assert "META_STATEMENT" in out
    assert "VR-2" in out


def test_csv_import_rejects_bad_rows_and_header(client):
    ds = datasets_mod.create_dataset(name="CSV2", detector_id="THESIS_002")
    bad_header = "id,text,label\nx,Some text here.,META_STATEMENT\n"
    with pytest.raises(datasets_mod.ValidationError):
        io_mod.import_csv(ds["id"], bad_header, annotator_id="R1")
    csv_text = ("sample_id,text,human_label,source,notes\n"
                "a1,This essay will discuss crops.,META_STATEMENT,field,ok\n"
                "a2,Another real sentence here.,BOGUS_LABEL,field,ok\n"
                "a3,,NOT_META_STATEMENT,field,empty text\n")
    result = io_mod.import_csv(ds["id"], csv_text, annotator_id="R1")
    assert result["added"] == 1
    assert [e["row"] for e in result["errors"]] == [3, 4]


def test_topic_csv_import_requires_topic_fields(client):
    ds = datasets_mod.create_dataset(name="CSV3", detector_id="TOPIC_CLASSIFIER")
    csv_text = ("sample_id,topic,teacher_keywords,text,human_label,source,notes\n"
                "t1,Effects of climate change on agriculture,climate;crop,"
                "Climate change affects crop production.,STRONG,field,ok\n")
    result = io_mod.import_csv(ds["id"], csv_text, annotator_id="R1")
    assert result["added"] == 1
    sample = datasets_mod.list_samples(ds["id"])[0]
    assert sample["topic"] == "Effects of climate change on agriculture"
    assert sample["teacher_keywords"] == ["climate", "crop"]


def test_csv_import_rejects_unknown_provenance(client):
    ds = datasets_mod.create_dataset(name="CSV4", detector_id="THESIS_002")
    csv_text = ("sample_id,text,human_label,source,notes\n"
                "a1,This essay will discuss crops.,META_STATEMENT,field,ok\n")
    with pytest.raises(datasets_mod.ValidationError):
        io_mod.import_csv(ds["id"], csv_text, annotator_id="R1",
                          provenance="TRUST_ME")


def test_run_json_export_envelope(client):
    pair = demo_mod.ensure_demo_datasets()
    ds = datasets_mod.freeze_dataset(pair["binary"]["id"])
    run = runs_mod.create_run(ds["id"])
    env = io_mod.export_run_json(run["id"])
    assert env["envelope"] == "essayscaff-validation-run"
    assert env["ruleset_version"] == "VR-2"
    assert env["validation_run_id"] == run["id"]
    assert env["dataset_hash"] == ds["dataset_hash"]
    assert env["dataset_hash_verified"] is True
    assert env["exported_at"]
    assert env["snapshot"]["status"] == "FROZEN_FOR_VALIDATION"
    assert env["class_balance"]["N"] == 6
    json.dumps(env)  # machine-readable


def test_run_csv_export_sanitized(client):
    pair = demo_mod.ensure_demo_datasets()
    ds = datasets_mod.get_dataset(pair["multiclass"]["id"])
    datasets_mod.freeze_dataset(ds["id"])  # demo sets ANNOTATING on creation
    run = runs_mod.create_run(ds["id"])
    text = io_mod.export_run_csv(run["id"])
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    header = lines[0]
    assert header == ("sample_id,human_label,system_prediction,correct,"
                      "matrix_cell,ruleset_version,validation_run_id")
    assert len(lines) == 7  # header + 6 samples
    assert "VR-2" in text


def test_provenance_values_documented(client):
    assert set(protocols.PROVENANCE_VALUES) == {
        "HUMAN_CREATED_RESEARCH_SAMPLE", "DEIDENTIFIED_STUDENT_SAMPLE",
        "OPEN_CORPUS", "DEMO_FIXTURE", "OTHER"}
