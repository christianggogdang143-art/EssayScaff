"""Phase 3 Stage 1 tests: sessions, revisions, PREWRITE rules, prompts,
readiness, comparison, authorship protection, replay, compatibility."""

import pytest

from app import create_app
from services import db, prewriting
from services.prewriting import PROMPT_BANK

TOPIC = "Effects of climate change on agriculture"
KWS = ["climate", "agriculture", "farmers", "crop", "temperature", "rainfall"]
IDEA_A = "Climate change affects agriculture."
IDEA_B = ("Climate change affects crop production because extreme temperatures "
          "and irregular rainfall create difficulties for farmers.")
IDEA_C = "Online video games help players communicate with friends and improve teamwork."
IDEA_D = "Climate."

BANNED = ["Write this:", "Use this sentence:", "Here is a better version:",
          "Your thesis should be:", "Replace it with:"]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    application = create_app(prewarm=False)
    application.config.update(TESTING=True)
    return application.test_client()


def post_idea(client, idea, session=None, topic=TOPIC, kws=KWS):
    payload = {"text": idea, "topic": topic, "teacher_keywords": kws}
    if session:
        payload["session_id"] = session
    return client.post("/api/stage1/analyze", json=payload)


# ------------------------------------------------ sessions & revisions
def test_session_creation_and_numbering(client):
    first = post_idea(client, IDEA_A).get_json()
    assert first["session_id"].startswith("SES-")
    assert first["revision_number"] == 1
    second = post_idea(client, IDEA_B, session=first["session_id"]).get_json()
    assert second["session_id"] == first["session_id"]
    assert second["revision_number"] == 2


def test_revisions_persisted_and_never_overwritten(client):
    first = post_idea(client, IDEA_A).get_json()
    post_idea(client, IDEA_B, session=first["session_id"])
    session = client.get(f"/api/stage1/session/{first['session_id']}").get_json()
    assert session["revision_count"] == 2
    assert session["revisions"][0]["idea_text"] == IDEA_A
    assert session["revisions"][1]["idea_text"] == IDEA_B
    assert session["revisions"][0]["analysis_id"] != session["revisions"][1]["analysis_id"]
    assert client.get("/api/stage1/session/SES-20990101-XXXXXX").status_code == 404


def test_empty_idea_rejected(client):
    assert post_idea(client, "").status_code == 400
    assert post_idea(client, "   ").status_code == 400


# ------------------------------------------------ rules & prompts
def test_broad_idea_asks_focus(client):
    d = post_idea(client, IDEA_A).get_json()
    fired = {r["rule_id"] for r in d["rules"] if r["status"] == "TRIGGERED"}
    assert "PREWRITE_001" in fired
    assert len(d["prompts"]["prompts"]) <= 3
    assert d["readiness"]["decision"] in ("DEVELOPING", "NEARLY READY")


def test_developed_idea_ready(client):
    d = post_idea(client, IDEA_B).get_json()
    assert d["readiness"]["decision"] == "READY FOR THESIS FORMULATION"
    assert d["readiness"]["stage2_allowed"] is True


def test_unrelated_idea_fires_topic_rule(client):
    d = post_idea(client, IDEA_C).get_json()
    fired = {r["rule_id"] for r in d["rules"] if r["status"] == "TRIGGERED"}
    assert "PREWRITE_007" in fired
    assert d["prompts"]["prompts"][0]["category"] == "TOPIC"


def test_short_idea_supported_not_crash(client):
    d = post_idea(client, IDEA_D).get_json()
    assert d["readiness"]["decision"] == "DEVELOPING"
    fired = {r["rule_id"] for r in d["rules"] if r["status"] == "TRIGGERED"}
    assert "PREWRITE_001" in fired
    assert 1 <= len(d["prompts"]["prompts"]) <= 3


def test_prompt_priority_and_max():
    rules = [
        {"rule_id": "PREWRITE_003", "status": "TRIGGERED", "priority_rank": 2,
         "priority": "MEDIUM", "prompt_category": "RELATIONSHIP", "reason": "r3"},
        {"rule_id": "PREWRITE_001", "status": "TRIGGERED", "priority_rank": 0,
         "priority": "CRITICAL", "prompt_category": "CLARIFICATION", "reason": "r1"},
        {"rule_id": "PREWRITE_004", "status": "TRIGGERED", "priority_rank": 1,
         "priority": "HIGH", "prompt_category": "PROBLEM", "reason": "r4"},
        {"rule_id": "PREWRITE_005", "status": "TRIGGERED", "priority_rank": 1,
         "priority": "HIGH", "prompt_category": "STAKEHOLDER", "reason": "r5"},
    ]
    out = prewriting.select_prompts(rules, max_n=3)
    assert [p["rule_id"] for p in out["prompts"]] == ["PREWRITE_001", "PREWRITE_004", "PREWRITE_005"]
    assert out["max_shown"] == 3


def test_prompt_rotation_prefers_unshown():
    rules = [{"rule_id": "PREWRITE_002", "status": "TRIGGERED", "priority_rank": 1,
              "priority": "HIGH", "prompt_category": "FOCUS", "reason": "broad"}]
    first = prewriting.select_prompts(rules, shown_ids=set())["prompts"][0]
    second = prewriting.select_prompts(rules, shown_ids={first["prompt_id"]})["prompts"][0]
    assert first["prompt_id"] == "FOCUS_001"
    assert second["prompt_id"] == "FOCUS_002"


def test_concepts_come_from_real_nlp(client):
    d = post_idea(client, IDEA_B).get_json()
    assert "farmer" in d["evidence"]["selected_keywords"]
    assert d["evidence"]["concept_count"] >= 5


# ------------------------------------------------ readiness & comparison
def test_readiness_transparency_structure(client):
    d = post_idea(client, IDEA_A).get_json()
    r = d["readiness"]
    assert [c["id"] for c in r["conditions"]] == ["C1", "C2", "C3", "C4"]
    assert all(c["result"] in ("PASS", "FAIL") for c in r["conditions"])
    assert "blocking_rules" in r and "stage2_allowed" in r


def test_revision_comparison_resolved_and_new(client):
    first = post_idea(client, IDEA_A).get_json()
    second = post_idea(client, IDEA_B, session=first["session_id"]).get_json()
    cmp_ = second["comparison"]
    assert cmp_["deltas"]["added_keywords"], "IDEA_B must add keywords over IDEA_A"
    assert "farmer" in cmp_["deltas"]["added_keywords"]
    texts = [m["text"] for m in cmp_["messages"]]
    assert any(t.startswith("You added ") and "new concept(s)" in t for t in texts)
    assert second["scaffold_stats"]["revision_count"] == 2
    assert second["scaffold_stats"]["rule_trigger_counts"]["PREWRITE_001"] >= 1


def test_prompt_history_recorded(client):
    first = post_idea(client, IDEA_A).get_json()
    second = post_idea(client, IDEA_B, session=first["session_id"]).get_json()
    assert len(first["scaffold_stats"]["prompts_shown"]) > 0
    assert len(second["scaffold_stats"]["prompts_shown"]) >= len(first["scaffold_stats"]["prompts_shown"])


# ------------------------------------------------ authorship protection
def test_no_generated_replacement_text_anywhere(client):
    for idea in (IDEA_A, IDEA_B, IDEA_C, IDEA_D):
        d = post_idea(client, idea).get_json()
        texts = [p["text"] for p in d["prompts"]["prompts"]]
        texts.append(d["readiness"]["student_message"])
        texts.extend(m["text"] for m in d["comparison"]["messages"])
        texts.extend(r["reason"] for r in d["rules"])
        for t in texts:
            for banned in BANNED:
                assert banned not in t, (banned, t)
    for _cat, prompts in PROMPT_BANK.items():
        for _pid, text in prompts:
            for banned in BANNED:
                assert banned not in text
            assert text.strip().endswith("?")


# ------------------------------------------------ trace, replay, compat
def test_prompt_backtrace_chain(client):
    d = post_idea(client, IDEA_A).get_json()
    gears = {g["id"]: g for g in d["stage1_transparency"]}
    assert {"prewriting_analysis", "scaffold_rule_evaluation", "prompt_selection",
            "readiness_check", "revision_storage"} <= set(gears)
    assert all(g["status"] == "COMPLETE" for g in gears.values())
    p = d["prompts"]["prompts"][0]
    rule = next(r for r in d["rules"] if r["rule_id"] == p["rule_id"])
    assert rule["evidence"]["alpha_token_count"] > 0


def test_stage1_timings_measured(client):
    d = post_idea(client, IDEA_A).get_json()
    for key in ("rules_ms", "prompts_ms", "readiness_ms", "compare_ms", "persist_ms"):
        assert d["timings"][key] >= 0


def test_new_source_files_whitelisted(client):
    for file, func in [("services/prewriting.py", "evaluate_rules"),
                       ("services/stage1.py", "analyze_idea")]:
        res = client.get("/api/source", query_string={"file": file, "function": func})
        assert res.status_code == 200, file
        assert f"def {func}" in res.get_json()["source"]


def test_phase1_phase2_compatibility(client):
    r1 = client.post("/api/analyze", json={"text": IDEA_B}).get_json()
    assert [s["id"] for s in r1["transparency"]["pipeline"]] == [
        "raw_input", "normalization", "sentence_segmentation", "tokenization",
        "lemmatization", "stopword_identification", "pos_tagging", "rule_engine",
        "languagetool", "keyword_extraction", "wordnet_expansion", "tfidf",
        "cosine_similarity", "topic_classification", "feedback", "persistence",
    ]
    r2 = client.post("/api/analyze", json={"text": IDEA_B, "topic": TOPIC, "teacher_keywords": KWS}).get_json()
    assert r2["technical"]["phase2"]["ran"] is True
    assert r2["summary"]["topic_classification"] in ("WEAK", "MODERATE", "STRONG")
