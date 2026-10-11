"""Writing Lab sessions, essay persistence, experimental section rules.

Covers the 25-item lab contract: chain linkage without leaks, student-only
essay text, append-only section revisions, real gates (blocking blocks,
advisory never blocks), honest completion state, process summary from
stored rows, data-mode separation, and VR-2 invariance.
"""

import re

import pytest

from app import create_app
from services import db
from services import lab_rules
from services import lab as lab_service
from services.validation import snapshot as snapshot_mod

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

INTRO_STRONG = ("Climate change affects crop production because extreme temperatures and irregular "
                "rainfall create difficulties for farmers. Crop farmers need stable temperature "
                "and rainfall for agriculture.")
BODY_STRONG = ("Extreme temperatures reduce crop production because high heat damages growing "
               "plants during critical weeks. Farmers face irregular rainfall that disrupts "
               "planting schedules and lowers harvests across affected farming regions. "
               "Dry spells stress young crops further.")
CONC_STRONG = ("Climate change threatens farming, so farmers must adapt planting to shifting "
               "rainfall and heat while protecting future crop yields.")

BANNED = re.compile(
    r"excellent|passed|95%|high-quality|powerful|persuas|credible|\bgrade\b|"
    r"\bscore\b|mastery|deep semantic|flawless|perfect essay", re.IGNORECASE)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "lab.db")
    application = create_app(prewarm=False)
    application.config.update(TESTING=True)
    return application.test_client()


def _chain(client):
    s1 = client.post("/api/stage1/analyze", json={
        "text": IDEA, "topic": TOPIC, "teacher_keywords": KWS}).get_json()
    assert s1["readiness"]["stage2_allowed"] is True
    s2 = client.post("/api/stage2/analyze", json={
        "text": THESIS, "stage1_session_id": s1["session_id"]}).get_json()
    assert s2["readiness"]["stage3_allowed"] is True
    s3 = client.post("/api/stage3/analyze", json={
        "thesis": THESIS, "topic": TOPIC, "teacher_keywords": KWS,
        "outline": [B1, B2], "stage2_session_id": s2["session_id"]}).get_json()
    return s1, s2, s3


def _lab(client, text, section, sid=None, **chain):
    payload = {"text": text, "section": section}
    if sid:
        payload["lab_session_id"] = sid
    payload.update(chain)
    return client.post("/api/lab/analyze", json=payload)


def test_lab_session_links_chain(client):
    s1, s2, s3 = _chain(client)
    r = _lab(client, INTRO_STRONG, "introduction",
             stage1_session_id=s1["session_id"],
             stage2_session_id=s2["session_id"],
             stage3_session_id=s3["session_id"],
             topic=TOPIC, teacher_keywords=KWS).get_json()
    assert r["lab_session_id"].startswith("LAB-")
    assert (r["stage1_session_id"], r["stage2_session_id"],
            r["stage3_session_id"]) == (s1["session_id"], s2["session_id"], s3["session_id"])
    assert r["topic"] == TOPIC and r["teacher_keywords"] == KWS
    row = db.get_lab_session(r["lab_session_id"])
    assert (row["stage1_session_id"], row["stage2_session_id"],
            row["stage3_session_id"]) == (s1["session_id"], s2["session_id"], s3["session_id"])
    assert row["data_mode"] == "development"


def test_unrelated_session_does_not_leak(client):
    s1, s2, _ = _chain(client)
    a = _lab(client, INTRO_STRONG, "introduction",
             stage1_session_id=s1["session_id"],
             stage2_session_id=s2["session_id"]).get_json()
    s2b = client.post("/api/stage2/analyze", json={
        "text": THESIS + " Indeed so.", "stage1_session_id": s1["session_id"]}).get_json()
    b = _lab(client, INTRO_STRONG, "introduction",
             lab_session_id=a["lab_session_id"],
             stage1_session_id=s1["session_id"],
             stage2_session_id=s2b["session_id"]).get_json()
    assert b["lab_session_id"] != a["lab_session_id"]
    assert b["stage2_session_id"] == s2b["session_id"]
    assert db.get_lab_session(a["lab_session_id"])["revision_count"] == 1
    assert db.get_lab_session(b["lab_session_id"])["stage2_session_id"] == s2b["session_id"]


def test_essay_never_generated_from_planning(client):
    s1, s2, s3 = _chain(client)
    marker = "zxqv-unique-outline-marker"
    s3b = client.post("/api/stage3/analyze", json={
        "thesis": THESIS, "topic": TOPIC, "teacher_keywords": KWS,
        "outline": [{"text": "Body point about " + marker + " effects.",
                     "details": ["Detail mentioning " + marker + " twice."]},
                    B2], "stage2_session_id": s2["session_id"]}).get_json()
    body_text = ("Extreme heat harms crops during the growing season. "
                 "Farmers adjust planting when rains arrive late.")
    r = _lab(client, body_text, "body",
             stage1_session_id=s1["session_id"],
             stage2_session_id=s2["session_id"],
             stage3_session_id=s3b["session_id"]).get_json()
    stored = db.latest_essay_revision(r["lab_session_id"], "body")
    assert stored["essay_text"] == body_text
    assert marker not in stored["essay_text"]
    assert s1["session_id"] not in stored["essay_text"]


def test_section_revisions_append_only(client):
    r1 = _lab(client, INTRO_STRONG, "introduction").get_json()
    sid = r1["lab_session_id"]
    assert r1["revision_number"] == 1 and r1["created_new_revision"] is True
    r2 = _lab(client, INTRO_STRONG, "introduction", sid=sid).get_json()
    assert r2["revision_number"] == 1 and r2["created_new_revision"] is False
    assert db.get_lab_session(sid)["revision_count"] == 1
    r3 = _lab(client, INTRO_STRONG + " One more sentence here.", "introduction",
              sid=sid).get_json()
    assert r3["revision_number"] == 2 and r3["created_new_revision"] is True
    revs = [r for r in db.get_lab_session(sid)["revisions"] if r["section"] == "introduction"]
    assert [r["revision_number"] for r in revs] == [1, 2]
    assert revs[0]["essay_text"] == INTRO_STRONG


def test_intro_body_conclusion_gates_are_real(client):
    weak_intro = _lab(client, "Hi there.", "introduction").get_json()
    assert weak_intro["lab_readiness"]["decision"] == "NEEDS INTRODUCTION REVISION"
    assert weak_intro["lab_readiness"]["intro_ready"] is False
    strong_intro = _lab(client, INTRO_STRONG, "introduction",
                        topic=TOPIC, teacher_keywords=KWS).get_json()
    assert strong_intro["lab_readiness"]["decision"] == "READY FOR BODY"
    weak_body = _lab(client, "Short words here.", "body").get_json()
    assert weak_body["lab_readiness"]["decision"] == "NEEDS BODY REVISION"
    weak_conc = _lab(client, "Done now.", "conclusion").get_json()
    assert weak_conc["lab_readiness"]["decision"] == "NEEDS CONCLUSION REVISION"


def test_full_ready_chain_and_essay_completion(client):
    s1, s2, s3 = _chain(client)
    chain = {"stage1_session_id": s1["session_id"],
             "stage2_session_id": s2["session_id"],
             "stage3_session_id": s3["session_id"],
             "topic": TOPIC, "teacher_keywords": KWS}
    ri = _lab(client, INTRO_STRONG, "introduction", **chain).get_json()
    rb = _lab(client, BODY_STRONG, "body", lab_session_id=ri["lab_session_id"], **chain).get_json()
    rc = _lab(client, CONC_STRONG, "conclusion", lab_session_id=ri["lab_session_id"], **chain).get_json()
    assert ri["lab_readiness"]["decision"] == "READY FOR BODY"
    assert rb["lab_readiness"]["decision"] == "READY FOR CONCLUSION"
    assert rc["lab_readiness"]["decision"] == "READY FOR FINAL REVIEW"
    essay = rc["essay_status"]
    assert essay["decision"] == "READY FOR INDEPENDENT REVIEW"
    assert "no unresolved blocking scaffold issues" in essay["student_message"]
    assert essay["missing_sections"] == [] and essay["not_ready_sections"] == []


def test_advisory_never_blocks_and_blocking_blocks():
    ok = lab_rules.check_intro_readiness([
        {"rule_id": "LAB_INTRO_001", "status": "INACTIVE", "blocking": True},
        {"rule_id": "LAB_INTRO_005", "status": "TRIGGERED", "blocking": False},
    ])
    assert ok["decision"] == "READY FOR BODY"
    bad = lab_rules.check_intro_readiness([
        {"rule_id": "LAB_INTRO_001", "status": "TRIGGERED", "blocking": True},
        {"rule_id": "LAB_INTRO_005", "status": "INACTIVE", "blocking": False},
    ])
    assert bad["decision"] == "NEEDS INTRODUCTION REVISION"
    assert bad["blocking_rules"] == ["LAB_INTRO_001"]


def test_lab_response_carries_all_findings(client):
    r = _lab(client, INTRO_STRONG, "introduction",
             topic=TOPIC, teacher_keywords=KWS).get_json()
    assert [x["rule_id"] for x in r["lab_rules"]] == [
        "LAB_INTRO_001", "LAB_INTRO_002", "LAB_INTRO_003",
        "LAB_INTRO_004", "LAB_INTRO_005"]
    assert all("blocking" in x for x in r["lab_rules"])
    assert r["analysis"]["technical"]["tokens"]  # full pipeline attached


def test_final_essay_contains_only_student_text(client):
    s1, s2, s3 = _chain(client)
    chain = {"stage1_session_id": s1["session_id"],
             "stage2_session_id": s2["session_id"],
             "stage3_session_id": s3["session_id"]}
    ri = _lab(client, INTRO_STRONG, "introduction", **chain).get_json()
    _lab(client, BODY_STRONG, "body", lab_session_id=ri["lab_session_id"], **chain)
    _lab(client, CONC_STRONG, "conclusion", lab_session_id=ri["lab_session_id"], **chain)
    essay = client.get("/api/lab/session/%s" % ri["lab_session_id"]).get_json()["essay"]
    assert essay == {"introduction": INTRO_STRONG, "body": BODY_STRONG,
                     "conclusion": CONC_STRONG}
    blob = "\n".join(essay.values())
    assert "zxqv" not in blob and "SES-" not in blob


def test_no_quality_claims_anywhere(client):
    s1, s2, s3 = _chain(client)
    chain = {"stage1_session_id": s1["session_id"],
             "stage2_session_id": s2["session_id"],
             "stage3_session_id": s3["session_id"]}
    texts = []
    for section, text in (("introduction", INTRO_STRONG), ("body", BODY_STRONG),
                          ("conclusion", CONC_STRONG)):
        r = _lab(client, text, section, **chain).get_json()
        for rule in r["lab_rules"]:
            texts.append(rule["rule_name"] + " " + rule["reason"])
        rd = r["lab_readiness"]
        texts.append(rd["decision"] + " " + rd["student_message"])
        texts.append(r["essay_status"]["decision"] + " " + r["essay_status"]["student_message"])
    assert not BANNED.search("\n".join(texts))


def test_missing_section_prevents_final_readiness(client):
    r = _lab(client, INTRO_STRONG, "introduction").get_json()
    essay = r["essay_status"]
    assert essay["decision"] == "REVISION NEEDED"
    assert essay["missing_sections"] == ["body", "conclusion"]


def test_summary_uses_latest_revisions_and_counts(client):
    s1, s2, s3 = _chain(client)
    chain = {"stage1_session_id": s1["session_id"],
             "stage2_session_id": s2["session_id"],
             "stage3_session_id": s3["session_id"],
             "topic": TOPIC, "teacher_keywords": KWS}
    ri = _lab(client, INTRO_STRONG, "introduction", **chain).get_json()
    _lab(client, INTRO_STRONG + " Extra sentence now.", "introduction",
         lab_session_id=ri["lab_session_id"], **chain)
    _lab(client, BODY_STRONG, "body", lab_session_id=ri["lab_session_id"], **chain)
    s = client.get("/api/lab/session/%s/summary" % ri["lab_session_id"]).get_json()
    assert s["student_essay"]["introduction"] == INTRO_STRONG + " Extra sentence now."
    assert s["revision_info"]["per_section"] == {"introduction": 2, "body": 1, "conclusion": 0}
    assert s["revision_info"]["per_stage"] == {"stage1": 1, "stage2": 1, "stage3": 1, "stage4": 0}
    assert s["revision_info"]["total_revisions"] == (
        s["revision_info"]["total_stage_revisions"] + s["revision_info"]["total_lab_revisions"])
    assert s["process_status"]["stages"]["stage1"]["decision"] == "READY FOR THESIS FORMULATION"
    assert s["assignment"] == {"topic": TOPIC, "teacher_keywords": KWS}
    assert isinstance(s["timeline"], list) and len(s["timeline"]) >= 5
    created = [e["created_at"] for e in s["timeline"]]
    assert created == sorted(created)


def test_summary_time_uses_intervals_not_processing(client):
    s1, s2, _ = _chain(client)
    ri = _lab(client, INTRO_STRONG, "introduction",
              stage1_session_id=s1["session_id"],
              stage2_session_id=s2["session_id"]).get_json()
    sid = ri["lab_session_id"]
    assert client.post("/api/analytics/intervals", json={
        "session_id": sid, "stage": "lab",
        "started_at": "2026-10-11T00:00:00+00:00",
        "ended_at": "2026-10-11T00:05:00+00:00", "active_ms": 120000}).status_code == 201
    assert client.post("/api/analytics/intervals", json={
        "session_id": s1["session_id"], "stage": "stage1",
        "started_at": "2026-10-11T00:00:00+00:00",
        "ended_at": "2026-10-11T00:02:00+00:00", "active_ms": 60000}).status_code == 201
    s = client.get("/api/lab/session/%s/summary" % sid).get_json()
    assert s["time"]["active_ms"] == {"value": 180000, "status": "OK", "reason": None}
    assert set(s["time"].keys()) == {"active_ms", "overlap_adjusted_ms", "per_session_ms",
                                     "started_at", "latest_activity_at"}
    assert s["feedback"]["lab_feedback_items"] >= 0


def test_data_modes_distinguishable_and_formal_untouched(client, tmp_path, monkeypatch):
    from services.validation import datasets as vdatasets

    before = len(vdatasets.list_datasets(include_demo=True))
    monkeypatch.setenv("ESSAYSCAFF_DATA_MODE", "pilot")
    try:
        r = _lab(client, INTRO_STRONG, "introduction").get_json()
        assert db.get_lab_session(r["lab_session_id"])["data_mode"] == "pilot"
    finally:
        monkeypatch.delenv("ESSAYSCAFF_DATA_MODE", raising=False)
    r2 = _lab(client, INTRO_STRONG, "introduction").get_json()
    assert db.get_lab_session(r2["lab_session_id"])["data_mode"] == "development"
    assert len(vdatasets.list_datasets(include_demo=True)) == before
    assert db.get_lab_session(r["lab_session_id"])["revision_count"] == 1


def test_db_path_env_override(tmp_path, monkeypatch):
    # conftest isolates db_path per test; undo that here to exercise the real
    # env-override path (still isolated: points at a tmp file).
    monkeypatch.undo()
    target = tmp_path / "custom.db"
    monkeypatch.setenv("ESSAYSCAFF_DB_PATH", str(target))
    assert db.db_path() == target
    db.init_db()
    assert target.exists()


def test_stage_outputs_unchanged(client):
    s1 = client.post("/api/stage1/analyze", json={
        "text": IDEA, "topic": TOPIC, "teacher_keywords": KWS}).get_json()
    assert s1["readiness"]["decision"] == "READY FOR THESIS FORMULATION"
    assert s1["readiness"]["stage2_allowed"] is True
    s2 = client.post("/api/stage2/analyze", json={
        "text": THESIS, "stage1_session_id": s1["session_id"]}).get_json()
    assert s2["readiness"]["decision"] == "READY FOR OUTLINE DEVELOPMENT"
    assert "analysis" in s1 and "analysis" in s2


def test_lab_constants_excluded_from_vr2_freeze():
    import config

    for name in ("LAB_INTRO_MIN_TOKENS", "LAB_BODY_MIN_TOKENS", "LAB_CONC_MIN_TOKENS",
                 "LAB_BODY_ALIGN_LOW", "LAB_BODY_ALIGN_HIGH", "LAB_CONC_NOVEL_MIN_CONCEPTS",
                 "DATA_MODE_DEFAULT"):
        assert hasattr(config, name), name
        assert name not in snapshot_mod.FROZEN_THRESHOLDS, name
    assert snapshot_mod.verify_vr2_freeze()["problems"] == []
    assert snapshot_mod.PINNED_VR2_RULES_HASH == "8ac38bf3b5b01354f679d1dbb20c3824bdbc9eb517a9ecdec543df1e85fe42c0"
    assert snapshot_mod.PINNED_VR2_CONFIG_HASH == "401f3a4bce3910ec8ca63d846ddce84a9e61881fb619bdf75778ac7e3e95c915"


def test_unknown_lab_ids_rejected(client):
    assert client.get("/api/lab/session/LAB-20990101-NOPE").status_code == 404
    assert client.get("/api/lab/session/LAB-20990101-NOPE/summary").status_code == 404
    # Single-character text is analyzable input (just not READY): honest 200.
    res = client.post("/api/lab/analyze", json={"text": "x", "section": "body"})
    assert res.status_code == 200
    assert res.get_json()["lab_readiness"]["decision"] == "NEEDS BODY REVISION"
