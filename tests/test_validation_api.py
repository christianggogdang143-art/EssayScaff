"""Phase 7A: researcher API — blinding, gating, security, separation."""

import json

from app import create_app
from services import db
from services.validation import demo as demo_mod
import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    application = create_app(prewarm=False)
    application.config.update(TESTING=True)
    return application.test_client()


def _make(client, detector="THESIS_002", name="API pilot"):
    res = client.post("/api/validation/datasets",
                      json={"name": name, "detector_id": detector})
    assert res.status_code == 201, res.get_json()
    return res.get_json()["id"]


def _annotate_ready(client, dsid, text="This essay will discuss crops.",
                    label="META_STATEMENT"):
    res = client.post(f"/api/validation/datasets/{dsid}/samples",
                      json={"raw_text": text})
    assert res.status_code == 201, res.get_json()
    sid = res.get_json()["id"]
    client.post(f"/api/validation/datasets/{dsid}/status",
                json={"status": "ANNOTATING"})
    res = client.post(f"/api/validation/samples/{sid}/annotations",
                      json={"detector_id": "THESIS_002", "annotator_id": "R1",
                            "human_label": label})
    assert res.status_code == 201, res.get_json()
    return sid


def test_researcher_page_served_without_student_impact(client):
    assert client.get("/research/validation").status_code == 200
    assert client.get("/").status_code == 200


def test_annotation_view_never_leaks_prediction(client):
    dsid = _make(client)
    sid = _annotate_ready(client, dsid)
    res = client.get(f"/api/validation/samples/{sid}/annotate-view")
    assert res.status_code == 200
    blob = json.dumps(res.get_json()).lower()
    for forbidden in ("prediction", "similarity", "cosine", "fired",
                      "correct", "matrix", "tp", "fp"):
        assert forbidden not in blob, forbidden


def test_error_analysis_gated_on_complete_run(client):
    dsid = _make(client)
    _annotate_ready(client, dsid)
    client.post(f"/api/validation/datasets/{dsid}/freeze")
    res = client.post(f"/api/validation/datasets/{dsid}/runs")
    assert res.status_code == 201, res.get_json()
    run_id = res.get_json()["id"]
    res = client.get(f"/api/validation/runs/{run_id}/errors")
    assert res.status_code == 200
    assert res.get_json()["count"] == 1


def test_run_on_unfrozen_dataset_rejected(client):
    dsid = _make(client)
    _annotate_ready(client, dsid)
    res = client.post(f"/api/validation/datasets/{dsid}/runs")
    assert res.status_code == 400


def test_invalid_label_rejected_not_coerced(client):
    dsid = _make(client)
    res = client.post(f"/api/validation/datasets/{dsid}/samples",
                      json={"raw_text": "Some sentence here."})
    sid = res.get_json()["id"]
    res = client.post(f"/api/validation/samples/{sid}/annotations",
                      json={"detector_id": "THESIS_002", "annotator_id": "R1",
                            "human_label": "meta_statement"})
    assert res.status_code == 400
    assert "Invalid label" in res.get_json()["error"]


def test_unknown_detector_rejected(client):
    res = client.post("/api/validation/datasets",
                      json={"name": "X", "detector_id": "GRAMMAR_X"})
    assert res.status_code == 400


def test_research_token_gates_validation_api_when_configured(client, monkeypatch):
    monkeypatch.setenv("ESSAYSCAFF_API_TOKEN", "test-token-123")
    try:
        assert client.get("/api/validation/datasets").status_code == 401
        assert client.post("/api/validation/datasets", json={}).status_code == 401
        assert client.get("/api/validation/freeze-record").status_code == 401
        ok = client.get("/api/validation/datasets",
                        headers={"X-Research-Token": "test-token-123"})
        assert ok.status_code == 200
        bad = client.get("/api/validation/datasets",
                         headers={"X-Research-Token": "wrong"})
        assert bad.status_code == 401
    finally:
        monkeypatch.delenv("ESSAYSCAFF_API_TOKEN", raising=False)


def test_student_api_ignores_research_token(client, monkeypatch):
    monkeypatch.setenv("ESSAYSCAFF_API_TOKEN", "test-token-123")
    try:
        assert client.get("/api/health").status_code == 200
        res = client.post("/api/analyze", json={"text": "Climate change affects crops."})
        assert res.status_code == 200
    finally:
        monkeypatch.delenv("ESSAYSCAFF_API_TOKEN", raising=False)


def test_freeze_record_endpoint_shows_vr2_frozen(client):
    res = client.get("/api/validation/freeze-record")
    body = res.get_json()
    assert body["ruleset_version"] == "VR-2"
    assert body["status"] == "FROZEN_FOR_VALIDATION"
    assert body["config_hash"] and body["rules_dir_sha256"]
    assert body["thresholds"]["TOPIC_MODERATE_THRESHOLD"] == 0.30
    assert body["thresholds"]["TOPIC_STRONG_THRESHOLD"] == 0.60


def test_source_viewer_still_guards_traversal(client):
    res = client.get("/api/source",
                     query_string={"file": "../../app.py", "function": None})
    assert res.status_code in (400, 403, 404)
    res = client.get("/api/source", query_string={
        "file": "rules/meta_rules.py", "function": "detect_meta_statements"})
    assert res.status_code == 200
    assert "THESIS_002" in res.get_json()["source"]


def test_demo_separation_from_formal(client):
    res = client.post("/api/validation/demo/ensure")
    assert res.status_code == 201
    assert "NOT RESEARCH RESULTS" in res.get_json()["banner"]
    res = client.get("/api/validation/datasets?include_demo=0")
    assert all(not d["is_demo"] for d in res.get_json()["datasets"])
    res = client.get("/api/validation/datasets")
    assert any(d["is_demo"] for d in res.get_json()["datasets"])


def test_csv_cells_sanitized_against_formulas(client):
    from services.validation import io as io_mod
    assert io_mod.sanitize_csv_cell("=1+1") == "'=1+1"
    assert io_mod.sanitize_csv_cell("+cmd") == "'+cmd"
    assert io_mod.sanitize_csv_cell("@x") == "'@x"
    assert io_mod.sanitize_csv_cell("-2") == "'-2"
    assert io_mod.sanitize_csv_cell("plain") == "plain"
    assert io_mod.sanitize_csv_cell(None) == ""
