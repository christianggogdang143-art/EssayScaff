"""F-05 regression: global request-body cap (engineering limit, not research).

Verifies normal and maximum-legitimate payloads pass while unbounded
bodies are refused with 413 — without disturbing per-field validation.
"""

import pytest

from app import MAX_CONTENT_LENGTH, create_app
from services import db
from services.validation import snapshot as snapshot_mod


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    application = create_app(prewarm=False)
    application.config.update(TESTING=True)
    return application


def test_cap_value_documented_and_sane():
    assert MAX_CONTENT_LENGTH == 5 * 1024 * 1024
    assert "MAX_CONTENT_LENGTH" not in snapshot_mod.FROZEN_THRESHOLDS


def test_normal_request_passes(client):
    c = client.test_client()
    res = c.post("/api/analyze", json={"text": "Climate change affects farmers."})
    assert res.status_code == 200


def test_maximum_legitimate_essay_passes(client):
    c = client.test_client()
    res = c.post("/api/analyze", json={"text": "word " * 3980})
    assert res.status_code == 200


def test_oversized_body_refused(client):
    c = client.test_client()
    res = c.post("/api/analyze", json={"text": "word " * 2000000})
    assert res.status_code == 413


def test_per_field_validation_still_applies(client):
    c = client.test_client()
    res = c.post("/api/analyze", json={"text": ""})
    assert res.status_code == 400
    res = c.post("/api/stage3/analyze",
                 json={"thesis": "T", "outline": [{"text": "x", "details": []}] * 7})
    assert res.status_code == 413


def test_vr2_pins_unchanged():
    assert snapshot_mod.PINNED_VR2_RULES_HASH == \
        "8ac38bf3b5b01354f679d1dbb20c3824bdbc9eb517a9ecdec543df1e85fe42c0"
    assert snapshot_mod.PINNED_VR2_CONFIG_HASH == \
        "401f3a4bce3910ec8ca63d846ddce84a9e61881fb619bdf75778ac7e3e95c915"
    assert snapshot_mod.verify_vr2_freeze()["problems"] == []
