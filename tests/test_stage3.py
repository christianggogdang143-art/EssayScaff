"""Phase 5 Stage 3 tests: sessions, linkage, outline rules, prompts,
readiness, comparison, authorship, replay, compatibility, security."""

import pytest

from app import create_app
from services import db
from services.outline import OUTLINE_PROMPT_BANK

TOPIC = "Effects of climate change on agriculture"
KWS = ["climate", "agriculture", "farmers", "crop", "temperature", "rainfall"]
THESIS = ("Extreme temperatures and irregular rainfall reduce crop production "
          "and create significant challenges for farmers.")
P1 = {"text": "Extreme temperatures reduce crop production.", "details": []}
P2 = {"text": "Irregular rainfall disrupts planting schedules.", "details": []}
B1 = {"text": "Extreme temperatures reduce crop production.",
      "details": ["High heat can interfere with crop growth.",
                  "Temperature stress can affect harvest outcomes."]}
B2 = {"text": "Irregular rainfall disrupts farming schedules.",
      "details": ["Unpredictable rainfall can affect planting timing."]}
B3 = {"text": "Farmers face production challenges from changing weather conditions.",
      "details": ["Weather uncertainty can complicate farm planning."]}

BANNED = ["Use this point:", "Write:", "Add this evidence:", "Your topic sentence should be:",
          "Replace this with:", "For example, write:"]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    application = create_app(prewarm=False)
    application.config.update(TESTING=True)
    return application.test_client()


@pytest.fixture()
def s2(client):
    d = client.post("/api/stage2/analyze",
                    json={"text": THESIS, "topic": TOPIC, "teacher_keywords": KWS}).get_json()
    assert d["readiness"]["decision"] == "READY FOR OUTLINE DEVELOPMENT"
    return d["session_id"]


def post_outline(client, outline, session=None, s2_session=None, thesis=THESIS):
    payload = {"thesis": thesis, "topic": TOPIC, "teacher_keywords": KWS, "outline": outline}
    if session:
        payload["session_id"] = session
    if s2_session:
        payload["stage2_session_id"] = s2_session
    return client.post("/api/stage3/analyze", json=payload)


def fired_ids(d):
    return [r["rule_id"] for r in d["rules"] if r["status"] == "TRIGGERED"]


# ------------------------------------------------ sessions & linkage
def test_session_creation_and_stage2_link(client, s2):
    d = post_outline(client, [B1, B2], s2_session=s2).get_json()
    assert d["session_id"].startswith("SES3-")
    assert d["revision_number"] == 1
    assert d["stage2_session_id"] == s2
    assert "crop production" in d["thesis"]


def test_stage3_gate_enforced(client):
    not_ready = client.post("/api/stage2/analyze",
                            json={"text": "Climate change affects the world."}).get_json()
    s2id = not_ready["session_id"]
    assert not_ready["readiness"]["stage3_allowed"] is False
    assert client.post("/api/stage3/analyze",
                       json={"thesis": THESIS, "outline": [B1, B2],
                             "stage2_session_id": s2id}).status_code == 403


def test_unknown_stage2_link_rejected(client):
    assert client.post("/api/stage3/analyze",
                       json={"thesis": THESIS, "outline": [B1, B2],
                             "stage2_session_id": "SES2-20990101-NOPE"}).status_code in (400, 404)


def test_append_only_history_and_order(client):
    first = post_outline(client, [B1, B2]).get_json()
    second = post_outline(client, [B2, B1], session=first["session_id"]).get_json()
    assert second["revision_number"] == 2
    s = client.get(f"/api/stage3/session/{first['session_id']}").get_json()
    assert s["revision_count"] == 2
    assert [p["text"] for p in s["revisions"][0]["outline"]] == [B1["text"], B2["text"]]
    assert [p["text"] for p in s["revisions"][1]["outline"]] == [B2["text"], B1["text"]]
    assert client.get("/api/stage3/session/SES3-20990101-NOPE").status_code == 404


def test_outline_limits_validated(client):
    assert client.post("/api/stage3/analyze", json={"thesis": THESIS, "outline": []}).status_code == 400
    assert client.post("/api/stage3/analyze",
                       json={"thesis": THESIS, "outline": [{"text": "x", "details": []}] * 7}).status_code == 413
    assert client.post("/api/stage3/analyze",
                       json={"thesis": THESIS, "outline": [{"text": 5, "details": []}, B2]}).status_code == 400


# ------------------------------------------------ rules
def test_missing_support(client):
    d = post_outline(client, [P1, P2]).get_json()
    assert fired_ids(d).count("OUTLINE_005") == 2
    assert d["readiness"]["decision"] == "NEARLY READY"


def test_developed_outline_ready(client):
    d = post_outline(client, [B1, B2, B3]).get_json()
    assert d["readiness"]["decision"] == "READY FOR REFLECTION & REVISION"
    assert d["readiness"]["stage4_allowed"] is True
    assert "OUTLINE_012" in [r["rule_id"] for r in d["rules"] if r["status"] == "OBSERVED"]
    for cond in ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"):
        assert cond in [c["id"] for c in d["readiness"]["conditions"]]


def test_off_topic_detail(client):
    outline = [{"text": "Irregular rainfall affects agricultural production.",
                "details": ["Online gaming improves communication among teenagers.", "Rain falls."]}]
    d = post_outline(client, outline).get_json()
    assert "OUTLINE_004" in fired_ids(d)


def test_duplicate_points(client):
    d = post_outline(client, [
        {"text": "Climate change reduces crop production.", "details": ["Yields fall."]},
        {"text": "Crop production decreases because of climate change.", "details": ["Harvests shrink."]},
    ]).get_json()
    assert "OUTLINE_006" in fired_ids(d)
    assert d["readiness"]["decision"] == "NEARLY READY"


def test_overloaded_point(client):
    d = post_outline(client, [{
        "text": "Climate change reduces crops, increases disease, causes migration, damages roads, affects tourism, and changes the economy.",
        "details": ["Many effects exist."]}]).get_json()
    assert "OUTLINE_008" in fired_ids(d)


def test_thesis_weak_point_but_topic_related(client):
    d = post_outline(client, [{
        "text": "People should learn about climate change.", "details": ["Awareness is important."]}]).get_json()
    assert "OUTLINE_003" in fired_ids(d)


def test_empty_point_and_insufficient_points(client):
    d = post_outline(client, [{"text": "   ", "details": []}]).get_json()
    assert "OUTLINE_001" in fired_ids(d)
    assert "OUTLINE_002" in fired_ids(d)
    assert d["readiness"]["decision"] == "DEVELOPING"


def test_unity_statuses_present(client):
    d = post_outline(client, [B1, B2]).get_json()
    assert [u["point"] for u in d["unity"]] == [1, 2]
    assert {u["status"] for u in d["unity"]} <= {"COHESIVE", "MIXED", "POSSIBLY OFF-TOPIC", "NO SUPPORT"}


# ------------------------------------------------ prompts & comparison
def test_prompt_selection_max3_and_history(client):
    d = post_outline(client, [P1, P2]).get_json()
    assert 1 <= len(d["prompts"]["prompts"]) <= 3
    assert d["prompts"]["prompts"][0]["priority"] in ("CRITICAL", "HIGH")
    ids = [p["prompt_id"] for p in d["prompts"]["prompts"]]
    assert len(ids) == len(set(ids))


def test_revision_comparison_support_added(client):
    first = post_outline(client, [P1, P2]).get_json()
    d = post_outline(client, [B1, B2], session=first["session_id"]).get_json()
    texts = [m["text"] for m in d["comparison"]["messages"]]
    assert "You added support to Body Point 1." in texts
    assert d["scaffold_stats"]["revision_count"] == 2


def test_reorder_reanalyzes_progression(client):
    first = post_outline(client, [B1, B2]).get_json()
    d = post_outline(client, [B2, B1], session=first["session_id"]).get_json()
    assert any("reorder" in m["text"] for m in d["comparison"]["messages"])


# ------------------------------------------------ authorship
def test_no_generated_outline_content(client):
    for outline in ([P1, P2], [B1, B2, B3]):
        d = post_outline(client, outline).get_json()
        texts = [p["text"] for p in d["prompts"]["prompts"]]
        texts.append(d["readiness"]["student_message"])
        texts.extend(m["text"] for m in d["comparison"]["messages"])
        texts.extend(r["reason"] for r in d["rules"])
        for t in texts:
            for banned in BANNED:
                assert banned not in t, (banned, t)
    for _cat, prompts in OUTLINE_PROMPT_BANK.items():
        for _pid, text in prompts:
            for banned in BANNED:
                assert banned not in text
            assert text.strip().endswith("?")


# ------------------------------------------------ trace, replay, compat
def test_backtrace_gears_and_timings(client):
    d = post_outline(client, [B1, B2]).get_json()
    gear_ids = {g["id"] for g in d["stage3_transparency"]}
    assert {"outline_input", "outline_structure_parsing", "thesis_point_alignment",
            "point_detail_alignment", "unity_analysis", "progression", "duplication_check",
            "outline_rule_evaluation", "prompt_selection", "readiness_check",
            "revision_storage"} <= gear_ids
    assert all(g["status"] == "COMPLETE" for g in d["stage3_transparency"])
    for key in ("parse_ms", "nlp_ms", "wordnet_ms", "thesis_point_ms", "point_detail_ms",
                "progression_ms", "duplication_ms", "rules_ms", "prompts_ms",
                "readiness_ms", "persist_ms"):
        assert d["timings"][key] >= 0


def test_replay_and_provider_label(client):
    created = post_outline(client, [B1, B2]).get_json()
    again = client.get(f"/api/stage3/session/{created['session_id']}").get_json()
    assert again["revisions"][0]["rules"] == created["rules"]
    assert "TeacherConceptProvider" in created["provider"]
    assert "WordNet" in created["provider"]
    assert "knowledge base" not in created["provider"].lower(), (
        "WordNet must never be labeled an academic knowledge base")


def test_new_source_files_whitelisted(client):
    for file, func in [("services/outline.py", "evaluate_outline"),
                       ("services/stage3.py", "analyze_outline"),
                       ("services/knowledge_base/interface.py", "expand")]:
        res = client.get("/api/source", query_string={"file": file, "function": func} if func != "expand" else {"file": file})
        assert res.status_code == 200, file


def test_phase1_2_stage1_stage2_compatibility(client):
    assert client.post("/api/analyze", json={"text": THESIS}).status_code == 200
    s1 = client.post("/api/stage1/analyze", json={"text": "Climate change affects agriculture."}).get_json()
    assert s1["revision_number"] == 1
    s2 = client.post("/api/stage2/analyze", json={"text": THESIS}).get_json()
    assert s2["revision_number"] == 1
