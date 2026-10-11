"""Phase 4 Stage 2 tests: sessions, linkage, thesis rules, prompts,
readiness, comparison, authorship, replay, compatibility, security."""

import pytest

from app import create_app
from services import db
from services.thesis import THESIS_PROMPT_BANK

TOPIC = "Effects of climate change on agriculture"
KWS = ["climate", "agriculture", "farmers", "crop", "temperature", "rainfall"]
IDEA = ("Climate change affects crop production because extreme temperatures "
        "and irregular rainfall create difficulties for farmers.")
TH_A = "This essay will discuss climate change and agriculture."
TH_B = "Climate change affects the world."
TH_C = ("Extreme temperatures and irregular rainfall reduce crop production "
        "and create significant challenges for farmers.")
TH_D = ("Climate change affects farmers, reduces crops, damages roads, changes "
        "economies, increases disease, causes migration, and creates many "
        "environmental problems.")
TH_E = "Competitive online games improve teamwork among students."

BANNED = ["Your thesis should be", "Use this thesis", "Replace it with",
          "Write this", "A better thesis is", "Revised thesis:",
          "Replace your thesis with", "Here is a revised thesis"]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    application = create_app(prewarm=False)
    application.config.update(TESTING=True)
    return application.test_client()


@pytest.fixture()
def s1(client):
    return client.post("/api/stage1/analyze", json={"text": IDEA, "topic": TOPIC, "teacher_keywords": KWS}).get_json()["session_id"]


def post_thesis(client, text, session=None, s1_session=None, topic=TOPIC, kws=KWS):
    payload = {"text": text, "topic": topic, "teacher_keywords": kws}
    if session:
        payload["session_id"] = session
    if s1_session:
        payload["stage1_session_id"] = s1_session
    return client.post("/api/stage2/analyze", json=payload)


# ------------------------------------------------ sessions & linkage
def test_session_creation_and_linkage(client, s1):
    d = post_thesis(client, TH_C, s1_session=s1).get_json()
    assert d["session_id"].startswith("SES2-")
    assert d["revision_number"] == 1
    assert d["stage1_session_id"] == s1
    assert "crop production" in d["stage1_reference"]["final_idea"]
    d2 = post_thesis(client, TH_B, session=d["session_id"], s1_session=s1).get_json()
    assert d2["revision_number"] == 2


def test_topic_carry_forward_from_stage1(client, s1):
    d = client.post("/api/stage2/analyze", json={"text": TH_C, "stage1_session_id": s1}).get_json()
    assert d["analysis"]["summary"]["topic_classification"] in ("WEAK", "MODERATE", "STRONG")
    assert d["alignment"]["classification"] in ("ALIGNED", "PARTIALLY ALIGNED", "POSSIBLY DRIFTED")


def test_unknown_stage1_link_rejected(client):
    assert client.post("/api/stage2/analyze",
                       json={"text": TH_C, "stage1_session_id": "SES-20990101-NOPE"}).status_code == 404


def test_append_only_history(client):
    first = post_thesis(client, TH_A).get_json()
    post_thesis(client, TH_C, session=first["session_id"])
    s = client.get(f"/api/stage2/session/{first['session_id']}").get_json()
    assert s["revision_count"] == 2
    assert s["revisions"][0]["thesis_text"] == TH_A
    assert s["revisions"][1]["thesis_text"] == TH_C
    assert client.get("/api/stage2/session/SES2-20990101-NOPE").status_code == 404


# ------------------------------------------------ thesis rules
def test_thesis_001_002_integration_meta(client):
    d = post_thesis(client, TH_A).get_json()
    by_id = {r["rule_id"]: r for r in d["thesis_rules"]}
    assert by_id["THESIS_002"]["status"] == "ISSUE"
    assert by_id["THESIS_001"]["status"] == "NOT_CANDIDATE"  # single-sentence idea: meta sentence rejected
    fired = [r["rule_id"] for r in d["thesis_rules"] if r["status"] in ("TRIGGERED", "ISSUE")]
    assert "THESIS_002" in fired
    assert d["prompts"]["prompts"][0]["rule_id"] == "THESIS_002"


def test_specificity_rule_broad(client):
    d = post_thesis(client, TH_B).get_json()
    assert "THESIS_003" in [r["rule_id"] for r in d["thesis_rules"] if r["status"] == "TRIGGERED"]


def test_scope_and_overload_rules(client):
    d = post_thesis(client, TH_D).get_json()
    fired = [r["rule_id"] for r in d["thesis_rules"] if r["status"] == "TRIGGERED"]
    assert "THESIS_005" in fired and "THESIS_008" in fired


def test_direction_and_focus_observed_for_developed(client):
    d = post_thesis(client, TH_C).get_json()
    obs = {r["rule_id"] for r in d["thesis_rules"] if r["status"] == "OBSERVED"}
    assert {"THESIS_004", "THESIS_010"} <= obs
    assert d["readiness"]["decision"] == "READY FOR OUTLINE DEVELOPMENT"
    assert d["readiness"]["stage3_allowed"] is True


def test_topic_alignment_rule_drift(client):
    d = post_thesis(client, TH_E).get_json()
    assert "THESIS_006" in [r["rule_id"] for r in d["thesis_rules"] if r["status"] == "TRIGGERED"]


def test_stage1_consistency_classifications(client, s1):
    aligned = post_thesis(client, TH_C, s1_session=s1).get_json()["alignment"]["classification"]
    assert aligned == "ALIGNED"
    drifted = post_thesis(client, TH_E, s1_session=s1).get_json()["alignment"]["classification"]
    assert drifted == "POSSIBLY DRIFTED"


def test_components_detected(client):
    d = post_thesis(client, TH_C).get_json()
    c = d["components"]
    assert c["detected_subject"] == "temperatures"
    assert c["main_verb"] == "reduce"
    assert c["complete_structure"] is True
    assert "farmer" in c["important_concepts"]


# ------------------------------------------------ prompts & readiness
def test_prompt_mapping_priority_max3(client):
    d = post_thesis(client, TH_D).get_json()
    prompts = d["prompts"]["prompts"]
    assert 1 <= len(prompts) <= 3
    from config import PREWRITE_PRIORITY

    ranks = [PREWRITE_PRIORITY[p["priority"]] for p in prompts]
    assert ranks == sorted(ranks), "prompts must be priority-ordered, highest first"
    assert prompts[0]["priority"] in ("CRITICAL", "HIGH")


def test_prompt_history_rotation(client):
    first = post_thesis(client, TH_A).get_json()
    shown = {p["prompt_id"] for p in first["prompts"]["prompts"]}
    assert len(shown) == len(first["prompts"]["prompts"])
    first_meta = next(p["prompt_id"] for p in first["prompts"]["prompts"] if p["category"] == "META")
    second = post_thesis(client, TH_A, session=first["session_id"]).get_json()
    second_meta = next(p["prompt_id"] for p in second["prompts"]["prompts"] if p["category"] == "META")
    assert second_meta != first_meta, "rotation must prefer the unshown META variant on revisit"


def test_meta_resolution_comparison(client):
    first = post_thesis(client, TH_A).get_json()
    second = post_thesis(client, TH_C, session=first["session_id"]).get_json()
    assert "THESIS_002" in second["comparison"]["deltas"]["resolved_rules"]
    assert any("meta-statement" in m["text"] for m in second["comparison"]["messages"])


def test_readiness_conditions_all_present(client):
    d = post_thesis(client, TH_A).get_json()
    assert [c["id"] for c in d["readiness"]["conditions"]] == ["C1", "C2", "C3", "C4", "C5", "C6", "C7"]
    assert d["readiness"]["decision"] == "DEVELOPING"


def test_empty_short_long_thesis(client):
    assert client.post("/api/stage2/analyze", json={"text": ""}).status_code == 400
    assert client.post("/api/stage2/analyze", json={"text": "   "}).status_code == 400
    short = post_thesis(client, "Climate.").get_json()
    assert short["readiness"]["decision"] == "DEVELOPING"
    long_text = "Climate change affects farmers. " * 400
    assert client.post("/api/stage2/analyze", json={"text": long_text}).status_code == 200


# ------------------------------------------------ authorship
def test_no_replacement_thesis_anywhere(client):
    for text in (TH_A, TH_B, TH_C, TH_D, TH_E):
        d = post_thesis(client, text).get_json()
        texts = [p["text"] for p in d["prompts"]["prompts"]]
        texts.append(d["readiness"]["student_message"])
        texts.extend(m["text"] for m in d["comparison"]["messages"])
        texts.extend(r["reason"] for r in d["thesis_rules"])
        for t in texts:
            for banned in BANNED:
                assert banned not in t, (banned, t)
    for _cat, prompts in THESIS_PROMPT_BANK.items():
        for _pid, text in prompts:
            for banned in BANNED:
                assert banned not in text
            assert text.strip().endswith("?")


# ------------------------------------------------ trace, replay, compat
def test_prompt_backtrace_and_gears(client, s1):
    d = post_thesis(client, TH_A, s1_session=s1).get_json()
    gear_ids = {g["id"] for g in d["stage2_transparency"]}
    assert {"thesis_input", "thesis_component_extraction", "thesis_rule_evaluation",
            "stage1_alignment_check", "thesis_prompt_selection", "thesis_readiness",
            "revision_storage"} <= gear_ids
    assert all(g["status"] == "COMPLETE" for g in d["stage2_transparency"])
    p = d["prompts"]["prompts"][0]
    assert p["rule_id"] in [r["rule_id"] for r in d["thesis_rules"]]


def test_stage2_timings_measured(client):
    d = post_thesis(client, TH_C).get_json()
    for key in ("doc_parse_ms", "rules_ms", "prompts_ms", "readiness_ms", "compare_ms", "persist_ms"):
        assert d["timings"][key] >= 0


def test_new_source_files_whitelisted(client):
    for file, func in [("services/thesis.py", "evaluate_new_rules"),
                       ("services/stage2.py", "analyze_thesis")]:
        res = client.get("/api/source", query_string={"file": file, "function": func})
        assert res.status_code == 200, file
        assert f"def {func}" in res.get_json()["source"]


def test_phase1_2_3_compatibility(client, s1):
    r1 = client.post("/api/analyze", json={"text": TH_C}).get_json()
    assert len(r1["transparency"]["pipeline"]) == 16
    r2 = post_thesis(client, TH_C).get_json()
    assert r2["analysis"]["summary"]["token_count"] > 0
    s = client.post("/api/stage1/analyze", json={"text": IDEA, "topic": TOPIC, "teacher_keywords": KWS}).get_json()
    assert s["readiness"]["decision"] in ("DEVELOPING", "NEARLY READY", "READY FOR THESIS FORMULATION")
