"""Stage 1 contextual-prompt tests: template filling from provenanced slots,
fallback safety, priority, persistence, authorship, and tab separation."""

import pathlib

import pytest

from app import create_app
from services import db, prewriting
from services.prewriting import CTX_TEMPLATES, PROMPT_BANK

SOCIAL_TOPIC = "Effects of Social Media Use on Senior High School Students\u2019 Study Habits"
SOCIAL_KWS = ["social media", "students", "study habits", "distraction",
              "time management", "academic performance"]
SOCIAL_IDEA = ("Social media affects senior high school students in many ways. "
               "Students use social media every day for communication, entertainment, "
               "and school activities. It can be helpful, but it can also cause problems "
               "with studying and time management. Some students spend too much time "
               "scrolling instead of completing their schoolwork. This essay will discuss "
               "the effects of social media on students.")

RENEW_TOPIC = "Benefits and Challenges of Renewable Energy in the Philippines"
RENEW_KWS = ["renewable energy", "solar power", "wind power", "electricity",
             "environment", "cost", "Philippines"]
RENEW_IDEA = ("Renewable energy can help the Philippines in many ways. Solar and wind "
              "power can provide electricity, but there are also challenges involving "
              "cost and availability.")

NOKW_TOPIC = "Effects of Online Learning on Student Participation"
NOKW_IDEA = ("Online learning changes how students participate in class because "
             "communication happens through digital platforms.")

MINIMAL_IDEA = "Technology affects people."

BANNED = ["Write this:", "Use this sentence:", "Here is a better version:",
          "Your thesis should be:", "Replace it with:",
          "you should argue", "your essay should say", "write that",
          "write this", "use this sentence", "a better idea is",
          "your focus should be", "replace with", "here is a better"]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    application = create_app(prewarm=False)
    application.config.update(TESTING=True)
    return application.test_client()


def post_idea(client, idea, session=None, topic=SOCIAL_TOPIC, kws=SOCIAL_KWS):
    payload = {"text": idea, "topic": topic, "teacher_keywords": kws}
    if session:
        payload["session_id"] = session
    return client.post("/api/stage1/analyze", json=payload)


def slot_texts(prompts):
    texts = []
    for p in prompts:
        texts.append(p["text"])
        for v in (p.get("slot_values") or {}).values():
            texts.append(v)
    return " ".join(texts).lower()


# ------------------------------------------------ live: social-media case
def test_social_case_focus_first_contextual(client):
    d = post_idea(client, SOCIAL_IDEA).get_json()
    fired = {r["rule_id"] for r in d["rules"] if r["status"] == "TRIGGERED"}
    assert "PREWRITE_002" in fired
    first = d["prompts"]["prompts"][0]
    assert first["rule_id"] == "PREWRITE_002"
    assert first["priority"] == "HIGH"
    assert first["prompt_id"] == "FOCUS_CTX_001"
    assert first["fallback_used"] is False
    assert first["text"] == ("What specific effect of social media on students "
                             "will you focus on?")


def test_social_case_no_this_situation_with_context(client):
    d = post_idea(client, SOCIAL_IDEA).get_json()
    for p in d["prompts"]["prompts"]:
        if not p["fallback_used"]:
            assert "this situation" not in p["text"].lower()


def test_social_case_meta_note_present_and_nonblocking(client):
    d = post_idea(client, SOCIAL_IDEA).get_json()
    assert len(d["writing_notes"]) >= 1
    note = d["writing_notes"][0]
    assert note["source_rule"] == "THESIS_002"
    assert note["evidence"] == "This essay will"
    assert "THESIS_002" not in d["readiness"]["blocking_rules"]
    assert d["readiness"]["decision"] == "NEARLY READY"


def test_guidance_hierarchy(client):
    d = post_idea(client, SOCIAL_IDEA).get_json()
    g = d["guidance"]
    assert g["status"] == d["readiness"]["decision"]
    assert g["main"]["rule_id"] == "PREWRITE_002"
    assert g["main"]["label"] == "Focus"
    assert g["main"]["student_why"]
    assert g["main"]["question"]["text"].startswith("What specific effect")
    assert len(g["others"]) >= 1
    assert g["writing_notes"] == d["writing_notes"]


def test_slot_provenance_valid(client):
    d = post_idea(client, SOCIAL_IDEA).get_json()
    for p in d["prompts"]["prompts"]:
        for slot, prov in (p.get("slot_provenance") or {}).items():
            assert prov["source"] in ("assignment_topic", "teacher_keyword", "student_concept"), prov
            assert prov["value"] and prov["reason"]


def test_no_invented_slot_values(client):
    d = post_idea(client, SOCIAL_IDEA).get_json()
    allowed = (SOCIAL_TOPIC + " " + " ".join(SOCIAL_KWS) + " " + SOCIAL_IDEA).lower()
    for p in d["prompts"]["prompts"]:
        for value in (p.get("slot_values") or {}).values():
            assert value.lower() in allowed, value


# ------------------------------------------------ live: generalization
def test_renewable_case_adapts_not_hardcoded(client):
    d = post_idea(client, RENEW_IDEA, topic=RENEW_TOPIC, kws=RENEW_KWS).get_json()
    text = slot_texts(d["prompts"]["prompts"])
    assert "social media" not in text
    assert "study habits" not in text
    assert any(w in text for w in ("renewable energy", "philippines", "solar", "electricity", "cost"))
    assert d["prompts"]["prompts"][0]["fallback_used"] is False


def test_no_keywords_uses_topic_and_student_concepts(client):
    payload = {"text": NOKW_IDEA, "topic": NOKW_TOPIC}
    d = client.post("/api/stage1/analyze", json=payload).get_json()
    assert d["prompt_context"]["focus"] is None  # nothing invented
    first = d["prompts"]["prompts"][0]
    assert first["prompt_id"] == "TOPIC_CTX_001"
    assert NOKW_TOPIC in first["text"]


def test_minimal_context_falls_back_generic(client):
    payload = {"text": MINIMAL_IDEA}
    d = client.post("/api/stage1/analyze", json=payload).get_json()
    assert d["prompt_context"]["focus"] is None
    assert d["prompt_context"]["topic"] is None
    for p in d["prompts"]["prompts"]:
        assert p["fallback_used"] is True
    assert d["readiness"]["decision"] == "DEVELOPING"


# ------------------------------------------------ unit: templates & rotation
def test_all_ctx_templates_render_from_slots():
    ctx = {
        "topic": {"value": "Climate", "source": "assignment_topic", "reason": "t"},
        "focus": {"value": "rainfall", "source": "teacher_keyword", "reason": "m"},
        "target": {"value": "farmers", "source": "teacher_keyword", "reason": "m"},
        "stakeholder": {"value": "farmers", "source": "student_concept", "reason": "s"},
        "issue": {"value": "drought", "source": "student_concept", "reason": "i"},
    }
    for category, templates in CTX_TEMPLATES.items():
        assert templates, category
        for t in templates:
            assert set(t["slots"]) <= set(ctx), (category, t["template_id"])
            assert t["template"].strip().endswith("?")
            assert "{" in t["template"] and "}" in t["template"]


def test_contextual_rotation_prefers_unused_template():
    rules = [{"rule_id": "PREWRITE_002", "status": "TRIGGERED", "priority_rank": 1,
              "priority": "HIGH", "prompt_category": "FOCUS", "reason": "broad"}]
    ctx = {"focus": {"value": "rain", "source": "s", "reason": "r"},
           "target": {"value": "crops", "source": "s", "reason": "r"},
           "topic": {"value": "Climate", "source": "s", "reason": "r"}}
    first = prewriting.select_prompts(rules, context=ctx)["prompts"][0]
    assert first["prompt_id"] == "FOCUS_CTX_001"
    second = prewriting.select_prompts(rules, shown_ids={first["template_id"]},
                                       context=ctx)["prompts"][0]
    assert second["prompt_id"] == "FOCUS_CTX_002"


def test_priority_ordering_broad_before_exploration(client):
    d = post_idea(client, SOCIAL_IDEA).get_json()
    order = [p["rule_id"] for p in d["prompts"]["prompts"]]
    assert order[0] == "PREWRITE_002"
    assert len(d["prompts"]["prompts"]) <= 3


# ------------------------------------------------ persistence & transparency
def test_prompt_provenance_persisted(client):
    first = post_idea(client, SOCIAL_IDEA).get_json()
    session = client.get(f"/api/stage1/session/{first['session_id']}").get_json()
    stored = session["revisions"][0]["prompts"]["prompts"][0]
    assert stored["template_id"] == "FOCUS_CTX_001"
    assert stored["slot_provenance"]["focus"]["source"] == "teacher_keyword"
    assert stored["fallback_used"] is False
    assert len(session["revisions"][0]["writing_notes"]) >= 1


def test_transparency_shows_template_provenance(client):
    d = post_idea(client, SOCIAL_IDEA).get_json()
    gears = {g["id"]: g for g in d["stage1_transparency"]}
    assert "prompt_selection" in gears
    assert gears["prompt_selection"]["output"]["prompts"][0]["template_id"] == "FOCUS_CTX_001"


# ------------------------------------------------ authorship & UI separation
def test_no_generated_answers_anywhere(client):
    for idea, topic, kws in ((SOCIAL_IDEA, SOCIAL_TOPIC, SOCIAL_KWS),
                             (RENEW_IDEA, RENEW_TOPIC, RENEW_KWS),
                             (NOKW_IDEA, NOKW_TOPIC, None),
                             (MINIMAL_IDEA, None, None)):
        payload = {"text": idea}
        if topic:
            payload["topic"] = topic
        if kws:
            payload["teacher_keywords"] = kws
        d = client.post("/api/stage1/analyze", json=payload).get_json()
        texts = [p["text"] for p in d["prompts"]["prompts"]]
        texts.append(d["guidance"]["status_message"])
        if d["guidance"]["main"]:
            texts.append(d["guidance"]["main"]["student_why"])
        texts.extend(n["message"] for n in d["writing_notes"])
        for t in texts:
            lowered = t.lower()
            for banned in BANNED:
                assert banned not in lowered, (banned, t)


def test_bank_entries_still_questions():
    for _cat, prompts in PROMPT_BANK.items():
        for _pid, text in prompts:
            assert text.strip().endswith("?")
            for banned in BANNED:
                assert banned not in text.lower()


def test_student_transparency_tab_separation():
    css = pathlib.Path(__file__).resolve().parent.parent / "static" / "css" / "style.css"
    assert "[hidden]" in css.read_text(encoding="utf-8")
