"""Research interaction logging + time-on-task + feedback analytics.

Covers: event ingest/validation, interval storage + idempotent replay,
chain resolution, deterministic aggregates, indicator grouping, server
completion hooks, and VR-2 safety. All analytics are counts over stored
rows — never scores, never predictions, never NLP reruns.
"""

import ast
from pathlib import Path

import pytest

from app import create_app
from services import db
from services import learning_analytics
from services.validation import snapshot as snapshot_mod

TOPIC = "Effects of climate change on agriculture"
KWS = ["climate", "agriculture", "farmers", "crop", "temperature", "rainfall"]
IDEA_SHORT = "Climate."
IDEA_FULL = ("Climate change affects crop production because extreme temperatures "
             "and irregular rainfall create difficulties for farmers.")
THESIS = ("Extreme temperatures and irregular rainfall reduce crop production "
          "and create significant challenges for farmers.")
B1 = {"text": "Extreme temperatures reduce crop production.",
      "details": ["High heat can interfere with crop growth."]}
B2 = {"text": "Irregular rainfall disrupts farming schedules.",
      "details": ["Unpredictable rainfall can affect planting timing."]}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    application = create_app(prewarm=False)
    application.config.update(TESTING=True)
    return application.test_client()


def _idea(client, text=IDEA_FULL, session=None):
    payload = {"text": text, "topic": TOPIC, "teacher_keywords": KWS}
    if session:
        payload["session_id"] = session
    return client.post("/api/stage1/analyze", json=payload)


def _chain(client):
    s1 = _idea(client).get_json()["session_id"]
    s2 = client.post("/api/stage2/analyze", json={
        "text": THESIS, "topic": TOPIC, "teacher_keywords": KWS,
        "stage1_session_id": s1}).get_json()["session_id"]
    s3 = client.post("/api/stage3/analyze", json={
        "thesis": THESIS, "topic": TOPIC, "teacher_keywords": KWS,
        "outline": [B1, B2], "stage2_session_id": s2}).get_json()["session_id"]
    s4 = client.post("/api/stage4/reflect", json={
        "stage1_session_id": s1, "stage2_session_id": s2,
        "stage3_session_id": s3}).get_json()["session_id"]
    return s1, s2, s3, s4


# ------------------------------------------------ event logging
def test_event_insert_and_ordered_retrieval(client):
    sid = _idea(client).get_json()["session_id"]
    for i, typ in enumerate(["STAGE_ENTERED", "ANALYSIS_REQUESTED"]):
        res = client.post("/api/analytics/events", json={
            "stage": "stage1", "event_type": typ, "session_id": sid,
            "client_timestamp": f"2026-10-09T00:00:0{i}.000+00:00"})
        assert res.status_code == 201, res.get_json()
    res = client.get(f"/api/analytics/session/{sid}/events")
    assert res.status_code == 200
    body = res.get_json()
    ours = [e for e in body["events"] if e["provenance"] == "client"
            and e["event_type"] in ("STAGE_ENTERED", "ANALYSIS_REQUESTED")]
    assert [e["event_type"] for e in ours] == ["STAGE_ENTERED", "ANALYSIS_REQUESTED"]
    assert all(e["server_timestamp"] for e in ours)
    assert body["count"] >= 2


def test_event_rejects_invalid_payloads(client):
    bad = [
        {"stage": "stage9", "event_type": "APP_OPENED"},
        {"stage": "stage1", "event_type": "KEYSTROKE"},
        {"stage": "stage1", "event_type": "APP_OPENED", "active_elapsed_ms": -5},
        {"stage": "stage1", "event_type": "APP_OPENED", "revision_number": 0},
        {"stage": "stage1", "event_type": "APP_OPENED",
         "metadata": {"idea_text": "smuggled essay"}},
        {"stage": "stage1", "event_type": "APP_OPENED",
         "metadata": {"note": "x" * 5000}},
        {"stage": "stage1", "event_type": "APP_OPENED",
         "client_timestamp": "not-a-time"},
    ]
    for payload in bad:
        res = client.post("/api/analytics/events", json=payload)
        assert res.status_code == 400, payload


def test_client_cannot_forge_server_provenance(client):
    sid = _idea(client).get_json()["session_id"]
    res = client.post("/api/analytics/events", json={
        "stage": "stage1", "event_type": "APP_OPENED",
        "session_id": sid, "provenance": "server"})
    assert res.status_code == 201
    rows = [e for e in db.get_session_events(sid)
            if e["event_type"] == "APP_OPENED"]
    assert rows and all(r["provenance"] == "client" for r in rows)


def test_unattributed_lifecycle_event_allowed(client):
    res = client.post("/api/analytics/events", json={
        "stage": "stage1", "event_type": "APP_OPENED"})
    assert res.status_code == 201


def test_batch_cap_rejects_oversize(client):
    res = client.post("/api/analytics/events", json={
        "events": [{"stage": "stage1", "event_type": "APP_OPENED"}] * 101})
    assert res.status_code == 413


def test_events_endpoint_is_append_only(client):
    assert client.put("/api/analytics/events", json={}).status_code == 405
    assert client.delete("/api/analytics/events").status_code == 405


# ------------------------------------------------ time intervals
def _interval(sid, start="2026-10-09T00:00:00+00:00",
              end="2026-10-09T00:05:00+00:00", active=60000):
    return {"session_id": sid, "stage": "stage1",
            "started_at": start, "ended_at": end, "active_ms": active}


def test_interval_stored_and_summed(client):
    sid = _idea(client).get_json()["session_id"]
    res = client.post("/api/analytics/intervals", json=_interval(sid))
    assert res.status_code == 201
    assert res.get_json() == {"stored": 1, "duplicates_ignored": 0}
    body = client.get(f"/api/analytics/session/{sid}").get_json()
    assert body["active_time"]["stage1_ms"] == {
        "value": 60000, "status": "OK", "reason": None}
    assert body["active_time"]["total_ms"]["value"] == 60000


def test_duplicate_interval_ignored_never_double_counted(client):
    sid = _idea(client).get_json()["session_id"]
    payload = _interval(sid)
    assert client.post("/api/analytics/intervals", json=payload).status_code == 201
    res = client.post("/api/analytics/intervals", json=payload)
    assert res.get_json() == {"stored": 0, "duplicates_ignored": 1}
    body = client.get(f"/api/analytics/session/{sid}").get_json()
    assert body["active_time"]["stage1_ms"]["value"] == 60000


def test_interval_rejects_impossible_durations(client):
    sid = _idea(client).get_json()["session_id"]
    bad = [
        _interval(sid, end="2026-10-09T00:00:00+00:00"),  # ended <= started
        _interval(sid, active=-1),
        _interval(sid, active=3600000),  # active far beyond wall time
    ]
    for payload in bad:
        res = client.post("/api/analytics/intervals", json=payload)
        assert res.status_code == 400, payload


def test_overlapping_intervals_never_double_count(client):
    sid = _idea(client).get_json()["session_id"]
    a = _interval(sid, start="2026-10-09T00:00:00+00:00",
                  end="2026-10-09T00:10:00+00:00", active=600000)
    b = _interval(sid, start="2026-10-09T00:05:00+00:00",
                  end="2026-10-09T00:15:00+00:00", active=600000)
    assert client.post("/api/analytics/intervals", json=a).status_code == 201
    assert client.post("/api/analytics/intervals", json=b).status_code == 201
    per = client.get(f"/api/analytics/session/{sid}").get_json()["per_stage"]["stage1"]
    # Merged wall clock [00:00, 00:15] caps the total at 900000, not 1200000.
    assert per["active_time"]["active_ms"] == {"value": 900000, "status": "OK", "reason": None}
    assert per["active_time"]["overlap_adjusted_ms"] == 300000
    assert per["active_time"]["interval_count"] == 2


def test_disjoint_intervals_sum_unchanged(client):
    sid = _idea(client).get_json()["session_id"]
    a = _interval(sid, start="2026-10-09T00:00:00+00:00",
                  end="2026-10-09T00:05:00+00:00", active=60000)
    b = _interval(sid, start="2026-10-09T00:10:00+00:00",
                  end="2026-10-09T00:15:00+00:00", active=60000)
    assert client.post("/api/analytics/intervals", json=a).status_code == 201
    assert client.post("/api/analytics/intervals", json=b).status_code == 201
    per = client.get(f"/api/analytics/session/{sid}").get_json()["per_stage"]["stage1"]
    assert per["active_time"]["active_ms"] == {"value": 120000, "status": "OK", "reason": None}
    assert per["active_time"]["overlap_adjusted_ms"] == 0


# ------------------------------------------------ chain + aggregates
def test_chain_resolution_all_directions(client):
    s1, s2, s3, s4 = _chain(client)
    from_s4 = client.get(f"/api/analytics/session/{s4}").get_json()
    assert from_s4["entry_stage"] == "stage4"
    assert from_s4["sessions"] == {
        "stage1": [s1], "stage2": [s2], "stage3": [s3], "stage4": [s4]}
    from_s1 = client.get(f"/api/analytics/session/{s1}").get_json()
    assert from_s1["entry_stage"] == "stage1"
    assert from_s1["sessions"]["stage2"] == [s2]
    assert from_s1["sessions"]["stage3"] == [s3]
    assert from_s1["sessions"]["stage4"] == [s4]


def test_unknown_session_404(client):
    assert client.get("/api/analytics/session/SES-20990101-NOPE").status_code == 404
    assert client.get("/api/analytics/session/SES-20990101-NOPE/events").status_code == 404


def test_revision_and_rule_counts(client):
    s1, _, _, _ = _chain(client)
    body = client.get(f"/api/analytics/session/{s1}").get_json()
    assert body["revisions"]["stage1"] == 1
    assert body["total_revisions"] == 4
    assert body["analysis_requests"]["server_confirmed"] == 4
    freq = {r["rule_id"]: r["occurrences"] for r in body["rule_frequency"]}
    assert freq, "chain with analyzed revisions must record rule occurrences"
    for r in body["rule_frequency"]:
        assert set(r) == {"rule_id", "occurrences", "stages"}
        assert isinstance(r["occurrences"], int) and r["occurrences"] >= 1
        assert r["stages"] and set(r["stages"]) <= {"stage1", "stage2", "stage3", "stage4"}


def test_before_ready_shape_and_resolved_subset(client):
    s1, _, _, _ = _chain(client)
    _idea(client, IDEA_SHORT, session=s1)
    body = client.get(f"/api/analytics/session/{s1}").get_json()
    assert body["revisions"]["stage1"] == 2
    before = body["per_stage"]["stage1"]["analyses_before_ready"]
    assert set(before) == {"value", "status", "reason"}
    if before["status"] == "OK":
        assert isinstance(before["value"], int) and before["value"] >= 1
    # Structural invariant: resolved never contains a latest-fired rule,
    # and every resolved rule fired in some earlier revision.
    resolved = body["per_stage"]["stage1"]["resolved_rules"]
    revs = body["per_stage"]["stage1"]["revisions"]
    assert set(resolved).isdisjoint(set(revs[-1]["fired_rules"]))
    assert set(resolved) <= {r for rev in revs[:-1] for r in rev["fired_rules"]}


def test_empty_timing_is_na_not_zero(client):
    sid = _idea(client).get_json()["session_id"]
    body = client.get(f"/api/analytics/session/{sid}").get_json()
    assert body["active_time"]["stage1_ms"]["status"] == "N/A"
    assert body["active_time"]["stage1_ms"]["value"] is None
    assert body["active_time"]["stage1_ms"]["reason"]
    assert body["active_time"]["total_ms"]["status"] == "N/A"


def test_indicator_groups_shape_no_scores(client):
    s1, _, _, _ = _chain(client)
    groups = client.get(f"/api/analytics/session/{s1}").get_json()["indicator_groups"]
    assert set(groups) == {"thesis_clarity_indicators",
                           "structural_coherence_indicators",
                           "grammar_style_indicators", "other_indicators", "note"}
    assert "not" in groups["note"] and "grade" in groups["note"]
    blob = str(groups)
    assert "score" not in blob.lower().replace("occurrences", "")


def test_analytics_module_never_touches_nlp():
    import re

    src = Path(learning_analytics.__file__).read_text(encoding="utf-8")
    imported = set()
    for line in src.splitlines():
        m = re.match(r"^\s*(?:from|import)\s+([\w.]+)", line)
        if m:
            imported.add(m.group(1).split(".")[0] + (
                "." + m.group(1).split(".")[1] if "." in m.group(1) else ""))
    banned = {"services.nlp_service", "services.similarity",
              "services.wordnet_service", "services.grammar_service",
              "services.analysis_service", "services.prewriting",
              "services.thesis", "services.outline", "services.reflection",
              "services.stage1", "services.stage2", "services.stage3",
              "services.stage4", "sklearn", "nltk", "spacy", "rules"}
    assert not (imported & banned), imported & banned


# ------------------------------------------------ server completion hooks
def test_server_logs_analysis_completed(client):
    sid = _idea(client).get_json()["session_id"]
    rows = db.get_session_events(sid)
    completed = [e for e in rows if e["event_type"] == "ANALYSIS_COMPLETED"
                 and e["provenance"] == "server"]
    assert len(completed) == 1
    assert completed[0]["revision_number"] == 1
    assert completed[0]["stage"] == "stage1"


def test_server_logs_readiness_transition(client):
    sid = _idea(client, IDEA_SHORT).get_json()["session_id"]
    first = db.get_stage1_session(sid)["revisions"][0]
    d1 = (first.get("readiness", {}) or {}).get("decision")
    _idea(client, IDEA_FULL, session=sid)
    second = db.get_stage1_session(sid)["revisions"][-1]
    d2 = (second.get("readiness", {}) or {}).get("decision")
    rows = db.get_session_events(sid)
    changed = [e for e in rows if e["event_type"] == "READINESS_CHANGED"]
    if d1 != d2:
        assert len(changed) == 1
        assert changed[0]["provenance"] == "server"
    else:
        assert changed == []
    unlocked = [e for e in rows if e["event_type"] == "STAGE_UNLOCKED"]
    a1 = bool((first.get("readiness", {}) or {}).get("stage2_allowed", False))
    a2 = bool((second.get("readiness", {}) or {}).get("stage2_allowed", False))
    assert (len(unlocked) == 1) == (a2 and not a1)


def test_completion_logging_never_breaks_analysis(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("analytics store down")
    monkeypatch.setattr(db, "log_interaction_event", boom)
    res = _idea(client)
    assert res.status_code == 200
    assert res.get_json()["session_id"].startswith("SES-")


# ------------------------------------------------ validation safety
def test_hashes_still_pinned():
    problems = snapshot_mod.verify_vr2_freeze()["problems"]
    assert problems == []


def test_logging_config_outside_frozen_scope():
    import config

    assert hasattr(config, "ANALYTICS_IDLE_TIMEOUT_MS")
    assert config.ANALYTICS_IDLE_TIMEOUT_MS == 300000
    assert "ANALYTICS_IDLE_TIMEOUT_MS" not in snapshot_mod.FROZEN_THRESHOLDS
    assert "ANALYTICS_FLUSH_MS" not in snapshot_mod.FROZEN_THRESHOLDS
    assert "ANALYTICS_MAX_BATCH" not in snapshot_mod.FROZEN_THRESHOLDS
    assert "ANALYTICS_MAX_METADATA_CHARS" not in snapshot_mod.FROZEN_THRESHOLDS


# ------------------------------------------------ app-level events without stage
def test_app_opened_without_stage_accepted(client):
    """Real-browser startup posts APP_OPENED before any stage is known."""
    res = client.post("/api/analytics/events", json={"event_type": "APP_OPENED"})
    assert res.status_code == 201, res.get_json()


def test_session_ended_without_stage_accepted(client):
    res = client.post("/api/analytics/events", json={"event_type": "SESSION_ENDED"})
    assert res.status_code == 201, res.get_json()


def test_stage_specific_events_require_stage(client):
    """Strict policy: only APP_OPENED/SESSION_ENDED may omit `stage`."""
    for typ in ["STAGE_ENTERED", "STAGE_LEFT", "ANALYSIS_REQUESTED",
                "ANALYSIS_COMPLETED", "FEEDBACK_DISPLAYED",
                "REVISION_SUBMITTED", "READINESS_CHANGED", "STAGE_UNLOCKED",
                "CONTINUE_CLICKED", "REFLECTION_SUBMITTED",
                "SESSION_PAUSED", "SESSION_RESUMED"]:
        res = client.post("/api/analytics/events", json={"event_type": typ})
        assert res.status_code == 400, typ
    # ... and with an explicit null stage too.
    res = client.post("/api/analytics/events", json={
        "event_type": "ANALYSIS_REQUESTED", "stage": None})
    assert res.status_code == 400


def test_invalid_stage_rejected_even_for_optional_events(client):
    for payload in [{"event_type": "APP_OPENED", "stage": "stage9"},
                    {"event_type": "SESSION_ENDED", "stage": ""},
                    {"event_type": "SESSION_ENDED", "stage": 42}]:
        res = client.post("/api/analytics/events", json=payload)
        assert res.status_code == 400, payload


def test_unattributed_app_events_do_not_break_aggregation(client):
    sid = _idea(client).get_json()["session_id"]
    assert client.post("/api/analytics/events",
                       json={"event_type": "APP_OPENED"}).status_code == 201
    assert client.post("/api/analytics/events", json={
        "stage": "stage1", "event_type": "STAGE_ENTERED",
        "session_id": sid}).status_code == 201
    res = client.get(f"/api/analytics/session/{sid}")
    assert res.status_code == 200
    body = res.get_json()
    assert body["per_stage"]["stage1"]["revision_count"] == 1


def test_validation_tables_untouched_by_analytics(client):
    from services.validation import datasets as vdatasets
    ds = vdatasets.create_dataset(name="analytics-separation", detector_id="THESIS_002")
    before = db.get_session_events(ds["id"])
    assert before == []
    res = client.get(f"/api/analytics/session/{ds['id']}")
    assert res.status_code == 404
    assert vdatasets.get_dataset(ds["id"])["status"] == "DRAFT"
