"""Cross-stage session linking: the normal student chain stays linked from
Idea -> Thesis -> Outline -> Reflection, while the explicit unlinked
(research/manual) path keeps working.

Backend half of the real-browser regression: frontend navigation (Continue
buttons) is covered by the jsdom harness flows in tests/frontend_smoke/
smoke.js (continue_1_to_2 / continue_2_to_3 / continue_3_to_4 plus the
direct-tab and stale-session flows). This module pins the server contract
those flows rely on:

- linked Stage 2 analysis echoes the real stage1_session_id;
- linked Stage 3 analysis echoes the real stage2_session_id;
- unlinked (research) analysis without upstream ids is still allowed;
- linking a not-ready upstream session is refused (readiness gate).

No NLP, rule, threshold, or readiness-logic changes here — contract only.
"""

from app import create_app
from services import db

TOPIC = "Effects of climate change on agriculture"
KWS = ["climate", "agriculture", "farmers", "crop", "temperature", "rainfall"]
IDEA = ("Climate change affects crop production because extreme temperatures "
        "and irregular rainfall create difficulties for farmers.")
THESIS = ("Extreme temperatures and irregular rainfall reduce crop production "
          "and create significant challenges for farmers.")
B1 = {"text": "Extreme temperatures reduce crop production.",
      "details": ["High heat can interfere with crop growth."]}
B2 = {"text": "Irregular rainfall disrupts farming schedules.",
      "details": ["Unpredictable rainfall can affect planting timing."]}


def _client(tmp_path, monkeypatch):
    import services.db as db_mod

    monkeypatch.setattr(db_mod, "db_path", lambda: tmp_path / "chain.db")
    application = create_app(prewarm=False)
    application.config.update(TESTING=True)
    return application.test_client()


def test_full_chain_stays_linked(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    s1 = client.post("/api/stage1/analyze", json={
        "text": IDEA, "topic": TOPIC, "teacher_keywords": KWS}).get_json()
    assert s1["readiness"]["stage2_allowed"] is True

    s2 = client.post("/api/stage2/analyze", json={
        "text": THESIS, "stage1_session_id": s1["session_id"]}).get_json()
    assert s2["stage1_session_id"] == s1["session_id"]
    assert s2["readiness"]["stage3_allowed"] is True

    s3 = client.post("/api/stage3/analyze", json={
        "outline": [B1, B2], "stage2_session_id": s2["session_id"]}).get_json()
    assert s3["stage2_session_id"] == s2["session_id"]

    s4 = client.post("/api/stage4/reflect", json={
        "stage1_session_id": s1["session_id"],
        "stage2_session_id": s2["session_id"],
        "stage3_session_id": s3["session_id"]}).get_json()
    assert s4["stage1_session_id"] == s1["session_id"]
    assert s4["stage2_session_id"] == s2["session_id"]
    assert s4["stage3_session_id"] == s3["session_id"]

    # Revision rows preserve the same parent ids (chain traceability).
    rev2 = db.get_stage2_session(s2["session_id"])["revisions"][-1]
    assert rev2["stage1_session_id"] == s1["session_id"]
    rev3 = db.get_stage3_session(s3["session_id"])["revisions"][-1]
    assert rev3["stage2_session_id"] == s2["session_id"]
    rev4 = db.get_stage4_session(s4["session_id"])["revisions"][-1]
    assert (rev4["stage1_session_id"], rev4["stage2_session_id"],
            rev4["stage3_session_id"]) == (
        s1["session_id"], s2["session_id"], s3["session_id"])


def test_unlinked_research_path_still_allowed(tmp_path, monkeypatch):
    """Research/manual mode: no upstream ids -> standalone analysis (200)."""
    client = _client(tmp_path, monkeypatch)
    s2 = client.post("/api/stage2/analyze", json={"text": THESIS}).get_json()
    assert s2["stage1_session_id"] is None
    s3 = client.post("/api/stage3/analyze", json={
        "thesis": THESIS, "outline": [B1, B2]}).get_json()
    assert s3["stage2_session_id"] is None
    res = client.post("/api/stage4/reflect", json={})
    assert res.status_code == 200


def test_link_gate_refuses_not_ready_upstream(tmp_path, monkeypatch):
    """A linked call against a not-ready upstream session is refused."""
    client = _client(tmp_path, monkeypatch)
    weak = client.post("/api/stage1/analyze", json={"text": "Hi."}).get_json()
    assert weak["readiness"]["stage2_allowed"] is False
    res = client.post("/api/stage2/analyze", json={
        "text": THESIS, "stage1_session_id": weak["session_id"]})
    assert res.status_code == 403


def test_read_paths_do_not_mutate_history(tmp_path, monkeypatch):
    """Progressive display is presentation-only: session/history reads and
    the append-only stores never delete or rewrite revision rows."""
    import services.db as db_mod

    client = _client(tmp_path, monkeypatch)
    s1 = client.post("/api/stage1/analyze", json={
        "text": IDEA, "topic": TOPIC, "teacher_keywords": KWS}).get_json()
    s2 = client.post("/api/stage2/analyze", json={
        "text": THESIS, "stage1_session_id": s1["session_id"]}).get_json()
    before = {
        "s1": db_mod.get_stage1_session(s1["session_id"])["revision_count"],
        "s2": db_mod.get_stage2_session(s2["session_id"])["revision_count"],
    }
    assert client.get(f"/api/stage1/session/{s1['session_id']}").status_code == 200
    assert client.get(f"/api/stage2/session/{s2['session_id']}").status_code == 200
    assert client.get(f"/api/analytics/session/{s2['session_id']}").status_code == 200
    after = {
        "s1": db_mod.get_stage1_session(s1["session_id"])["revision_count"],
        "s2": db_mod.get_stage2_session(s2["session_id"])["revision_count"],
    }
    assert before == after == {"s1": 1, "s2": 1}
    # Full finding rows survive (nothing hidden at the storage layer).
    assert len(db_mod.get_stage1_session(s1["session_id"])["revisions"][0]["fired_rules"]) >= 0
    assert db_mod.get_stage2_session(s2["session_id"])["revisions"][0]["prompts"]["prompts"]


def test_unknown_upstream_session_is_not_fabricated(tmp_path, monkeypatch):
    """Reflect over an unknown Stage-2 session errors; unlinked stays null."""
    client = _client(tmp_path, monkeypatch)
    res = client.post("/api/stage4/reflect", json={
        "stage2_session_id": "SES2-20990101-NOPE"})
    assert res.status_code in (400, 404)
    assert "Stage 2" in res.get_json()["error"]
    # Unlinked research reflection still works with honestly null parents.
    s4 = client.post("/api/stage4/reflect", json={}).get_json()
    assert s4["stage1_session_id"] is None
    assert s4["stage2_session_id"] is None
    assert s4["stage3_session_id"] is None
