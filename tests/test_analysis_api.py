"""API + determinism tests for POST /api/analyze."""

import re

import pytest

from app import create_app
from services import db

SAMPLE = (
    "This essay will discuss climate change and agriculture. "
    "Climate change have serious effects on farmers. "
    "Farmers experience lower crop production because extreme temperatures affect crops. "
    "Farmers also experience problems because rainfall patterns continue to change."
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    application = create_app()
    application.config.update(TESTING=True)
    return application.test_client()


def test_analyze_happy_path_structure(client):
    res = client.post("/api/analyze", json={"text": SAMPLE, "stage": "introduction"})
    assert res.status_code == 200
    data = res.get_json()
    assert re.fullmatch(r"RUN-\d{8}-\d{6}", data["analysis_id"])
    for key in ("analysis_id", "summary", "feedback", "technical"):
        assert key in data
    tech = data["technical"]
    for key in ("raw_input", "normalized_input", "sentences", "tokens",
                "rule_results", "language_tool_results", "timings"):
        assert key in tech
    assert data["summary"]["sentence_count"] == 4
    assert data["summary"]["processing_ms"] > 0
    # Meta-statement must surface in feedback on the real sample.
    sources = [f["source"] for f in data["feedback"]]
    assert "THESIS_002" in sources
    # Every feedback item is explainable.
    for f in data["feedback"]:
        for key in ("feedback_id", "category", "severity", "source", "reason", "suggestion"):
            assert f[key]


def test_empty_and_whitespace_rejected(client):
    assert client.post("/api/analyze", json={"text": ""}).status_code == 400
    assert client.post("/api/analyze", json={"text": "   \n\t "}).status_code == 400
    assert client.post("/api/analyze", json={}).status_code == 400


def test_edge_inputs_handled_safely(client):
    for text in [".", "...", "Hello", "Hi there."]:
        res = client.post("/api/analyze", json={"text": text})
        assert res.status_code == 200
        data = res.get_json()
        assert "technical" in data and "feedback" in data


def test_long_input_rejected(client):
    import config

    res = client.post("/api/analyze", json={"text": "x " * (config.MAX_TEXT_CHARS + 10)})
    assert res.status_code == 413


def test_deterministic_repeated_analysis(client):
    first = client.post("/api/analyze", json={"text": SAMPLE}).get_json()
    second = client.post("/api/analyze", json={"text": SAMPLE}).get_json()
    assert first["analysis_id"] != second["analysis_id"]  # unique IDs
    assert first["technical"]["sentences"] == second["technical"]["sentences"]
    assert first["technical"]["tokens"] == second["technical"]["tokens"]
    assert first["technical"]["rule_results"] == second["technical"]["rule_results"]
    # LanguageTool may vary only if backend unavailable; statuses must match.
    assert first["technical"]["language_tool_results"]["status"] == \
        second["technical"]["language_tool_results"]["status"]


def test_analysis_persisted_and_retrievable(client):
    created = client.post("/api/analyze", json={"text": SAMPLE}).get_json()
    res = client.get(f"/api/analysis/{created['analysis_id']}")
    assert res.status_code == 200
    assert res.get_json()["id"] == created["analysis_id"]
    assert client.get("/api/analysis/RUN-20990101-000000").status_code == 404


def test_health_and_front_page(client):
    assert client.get("/api/health").get_json()["status"] == "ok"
    assert client.get("/").status_code == 200
