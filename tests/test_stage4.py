"""Phase 6 Stage 4 tests: reflection sessions, cross-stage consistency,
issue history, scaffold levels, fading prompts, readiness, authorship,
persistence, replay, security, compatibility."""

import pytest

from app import create_app
from services import db, reflection
from services.reflection import (
    CHECKLIST_ITEMS,
    REFLECT_PROMPT_BANK,
    REFLECT_RULE_DEFS,
)

TOPIC = "Effects of climate change on agriculture"
KWS = ["climate", "agriculture", "farmers", "crop", "temperature", "rainfall"]
THESIS = ("Extreme temperatures and irregular rainfall reduce crop production "
          "and create significant challenges for farmers.")
B1 = {"text": "Extreme temperatures reduce crop production.",
      "details": ["High heat can interfere with crop growth.",
                  "Temperature stress can affect harvest outcomes."]}
B2 = {"text": "Irregular rainfall disrupts farming schedules.",
      "details": ["Unpredictable rainfall can affect planting timing."]}
B3 = {"text": "Farmers face production challenges from changing weather conditions.",
      "details": ["Weather uncertainty can complicate farm planning."]}
GOOD_IDEA = ("Climate change harms farmers. Crop yields fall because "
             "rainfall is unpredictable and temperatures keep rising.")

BANNED = ["Rewrite this as:", "Use this transition:", "Your conclusion should be:",
          "Replace this paragraph with:", "Write:", "A better version is:",
          "Use this supporting detail:", "Your thesis should say:",
          "Your thesis should be", "Replace it with",
          "Furthermore, climate", "In addition to"]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    application = create_app(prewarm=False)
    application.config.update(TESTING=True)
    return application.test_client()


def post_idea(client, text):
    return client.post("/api/stage1/analyze",
                       json={"text": text, "topic": TOPIC,
                             "teacher_keywords": KWS}).get_json()


def post_thesis(client, text, s1=None):
    payload = {"text": text, "topic": TOPIC, "teacher_keywords": KWS}
    if s1:
        payload["stage1_session_id"] = s1
    return client.post("/api/stage2/analyze", json=payload).get_json()


def post_outline(client, thesis, outline, s2=None):
    payload = {"thesis": thesis, "outline": outline}
    if s2:
        payload["stage2_session_id"] = s2
    return client.post("/api/stage3/analyze", json=payload).get_json()


def post_reflect(client, s1=None, s2=None, s3=None, session=None, note=None,
                 conclusion=None):
    payload = {}
    if session:
        payload["session_id"] = session
    if s1:
        payload["stage1_session_id"] = s1
    if s2:
        payload["stage2_session_id"] = s2
    if s3:
        payload["stage3_session_id"] = s3
    if note is not None:
        payload["student_note"] = note
    if conclusion is not None:
        payload["conclusion"] = conclusion
    return client.post("/api/stage4/reflect", json=payload)


def full_chain(client):
    """Clean chain likely to reach high readiness at every stage."""
    s1 = post_idea(client, GOOD_IDEA)["session_id"]
    s2 = post_thesis(client, THESIS, s1=s1)["session_id"]
    s3 = post_outline(client, THESIS, [B1, B2, B3], s2=s2)["session_id"]
    return s1, s2, s3


# ------------------------------------------------ sessions & linkage
def test_session_creation(client):
    d = post_reflect(client).get_json()
    assert d["session_id"].startswith("SES4-")
    assert d["revision_number"] == 1
    assert d["scaffold"]["reason"].startswith("INSUFFICIENT HISTORY")


def test_stage4_gate_enforced(client):
    s1 = post_idea(client, GOOD_IDEA)["session_id"]
    weak = post_thesis(client, "Hi.", s1=s1)["session_id"]
    # Stage 3 must refuse a non-ready Stage 2 session (existing gate).
    r = client.post("/api/stage3/analyze",
                    json={"thesis": THESIS, "outline": [B1, B2],
                          "stage2_session_id": weak})
    assert r.status_code == 403


def test_unknown_session_rejected(client):
    r = client.post("/api/stage4/reflect",
                    json={"stage3_session_id": "SES3-20990101-NOPE"})
    assert r.status_code in (400, 404)
    assert client.get("/api/stage4/session/SES4-20990101-NOPE").status_code == 404


def test_bad_field_types_rejected(client):
    assert client.post("/api/stage4/reflect",
                       json={"stage3_session_id": 123}).status_code == 400
    assert client.post("/api/stage4/reflect",
                       json={"student_note": ["x"]}).status_code == 400


def test_topic_carry_forward(client):
    s1, s2, s3 = full_chain(client)
    d = post_reflect(client, s1=s1, s2=s2, s3=s3).get_json()
    assert d["snapshot"]["topic"] == TOPIC
    assert "climate" in (d["snapshot"]["teacher_keywords"] or [])
    # GOOD_IDEA deterministically contains "farmers"; assert the carry-forward.
    assert "farmers" in (d["snapshot"]["idea_text"] or "").lower()


def test_append_only_history(client):
    s1, s2, s3 = full_chain(client)
    first = post_reflect(client, s1=s1, s2=s2, s3=s3).get_json()
    second = post_reflect(client, s1=s1, s2=s2, s3=s3,
                          session=first["session_id"]).get_json()
    assert second["revision_number"] == 2
    s = client.get(f"/api/stage4/session/{first['session_id']}").get_json()
    assert s["revision_count"] == 2
    assert s["revisions"][0]["revision_number"] == 1
    assert s["revisions"][1]["revision_number"] == 2


# ------------------------------------------------ history classification (unit)
def _hist(fired_lists):
    return {1: [{"revision": i + 1, "fired": f} for i, f in enumerate(fired_lists)]}


def test_resolved_detection():
    h = reflection.build_issue_history(_hist([["PREWRITE_002"], []]))
    c = reflection.classify_history(h)
    assert [i["rule_id"] for i in c["resolved"]] == ["PREWRITE_002"]
    assert c["active"] == []


def test_unresolved_and_new_detection():
    h = reflection.build_issue_history(_hist([["PREWRITE_002"]]))
    c = reflection.classify_history(h)
    assert [i["rule_id"] for i in c["active"]] == ["PREWRITE_002"]
    assert [i["rule_id"] for i in c["new"]] == ["PREWRITE_002"]
    assert c["resolved"] == [] and c["stable"] == []


def test_recurring_detection():
    h = reflection.build_issue_history(
        _hist([["OUTLINE_006"], ["OUTLINE_006"], ["OUTLINE_006"]]))
    c = reflection.classify_history(h)
    assert [i["rule_id"] for i in c["recurring"]] == ["OUTLINE_006"]
    assert c["regressions"] == []


def test_regression_detection():
    h = reflection.build_issue_history(
        _hist([["THESIS_002"], [], ["THESIS_002"]]))
    c = reflection.classify_history(h)
    assert [i["rule_id"] for i in c["regressions"]] == ["THESIS_002"]
    assert [i["rule_id"] for i in c["active"]] == ["THESIS_002"]


def test_stable_resolution_detection():
    h = reflection.build_issue_history(
        _hist([["PREWRITE_004"], [], []]))
    c = reflection.classify_history(h)
    assert [i["rule_id"] for i in c["stable"]] == ["PREWRITE_004"]
    assert [i["rule_id"] for i in c["resolved"]] == ["PREWRITE_004"]


def test_single_resolved_is_not_stable():
    h = reflection.build_issue_history(_hist([["PREWRITE_004"], []]))
    c = reflection.classify_history(h)
    assert [i["rule_id"] for i in c["resolved"]] == ["PREWRITE_004"]
    assert c["stable"] == []  # one quiet revision is IMPROVING, not STABLE


# ------------------------------------------------ scaffold levels (unit)
def _classes(active=(), recurring=(), regressions=(), stable=(), resolved=()):
    def items(ids):
        return [{"rule_id": r, "stage": 1, "triggers": 1, "timeline": []} for r in ids]
    return {"resolved": items(resolved), "active": items(active),
            "new": [], "recurring": items(recurring),
            "regressions": items(regressions), "stable": items(stable)}


def _rules(active=()):
    return [{"rule_id": r, "status": "TRIGGERED", "priority": "HIGH",
             "priority_rank": 1} for r in active]


def test_scaffold_high_on_critical():
    r = [{"rule_id": "REFLECT_001", "status": "TRIGGERED", "priority": "CRITICAL",
          "priority_rank": 0}]
    s = reflection.decide_scaffold_level({}, _classes(), r, {"total_revisions": 5}, None)
    assert s["level"] == 3 and s["label"] == "HIGH SUPPORT"


def test_scaffold_high_on_recurring_major():
    rec = [{"rule_id": "OUTLINE_006", "stage": 3, "triggers": 3, "timeline": []},
           {"rule_id": "PREWRITE_002", "stage": 1, "triggers": 3, "timeline": []}]
    c = _classes(active=("OUTLINE_006", "PREWRITE_002"), recurring=("OUTLINE_006", "PREWRITE_002"))
    r = [{"rule_id": "REFLECT_004", "status": "TRIGGERED", "priority": "HIGH", "priority_rank": 1}]
    s = reflection.decide_scaffold_level({}, c, r, {"total_revisions": 6}, 2)
    assert s["level"] == 3
    assert s["previous_level"] == 2


def test_scaffold_moderate_default():
    r = [{"rule_id": "REFLECT_003", "status": "TRIGGERED", "priority": "HIGH", "priority_rank": 1}]
    s = reflection.decide_scaffold_level({}, _classes(active=("X",)), r, {"total_revisions": 2}, None)
    assert s["level"] == 2


def test_scaffold_light_when_only_minor():
    s = reflection.decide_scaffold_level({}, _classes(), [], {"total_revisions": 2}, None)
    assert s["level"] == 1
    assert s["label"] == "LIGHT SUPPORT"
    assert "LIGHT" in s["decision_rule"]
    r = reflection.decide_scaffold_level({}, _classes(), [], {"total_revisions": 2}, 2)
    assert r["level"] == 1 and r["reason"].startswith("support reduced")


def test_scaffold_independent_needs_stability_and_history():
    c = _classes(stable=("PREWRITE_004",), resolved=("PREWRITE_004",))
    s = reflection.decide_scaffold_level({}, c, [], {"total_revisions": 4}, 1)
    assert s["level"] == 0
    # Same evidence but too few revisions: not independent.
    s2 = reflection.decide_scaffold_level({}, c, [], {"total_revisions": 2}, 1)
    assert s2["level"] == 1


def test_insufficient_history_path(client):
    d = post_reflect(client).get_json()
    assert d["scaffold"]["level"] == 2
    assert "INSUFFICIENT HISTORY" in d["scaffold"]["reason"]
    assert d["readiness"]["decision"] == "REFLECTING"
    assert any(c["id"] == "R0" and c["result"] == "FAIL"
               for c in d["readiness"]["conditions"])


# ------------------------------------------------ prompts & fading
def test_prompt_counts_by_level():
    rules = [{"rule_id": "REFLECT_002", "status": "TRIGGERED", "priority": "HIGH",
              "priority_rank": 1, "prompt_category": "ALIGNMENT", "reason": "weak"}]
    assert len(reflection.select_reflection_prompts(rules, 3)["prompts"]) <= 3
    assert len(reflection.select_reflection_prompts(rules, 2)["prompts"]) <= 2
    assert len(reflection.select_reflection_prompts(rules, 1)["prompts"]) <= 1
    out = reflection.select_reflection_prompts(rules, 0)
    assert len(out["prompts"]) <= 1 and out["detail_level"] == "INDEPENDENT"


def test_fading_changes_template_ids():
    rules = [{"rule_id": "REFLECT_004", "status": "TRIGGERED", "priority": "HIGH",
              "priority_rank": 1, "prompt_category": "DISTINCTION", "reason": "dup"}]
    high = reflection.select_reflection_prompts(rules, 3)["prompts"][0]
    light = reflection.select_reflection_prompts(rules, 1)["prompts"][0]
    assert high["prompt_id"] != light["prompt_id"]
    assert high["detail_level"] == "HIGH" and light["detail_level"] == "LIGHT"


def test_independent_reachable_on_clean_stable_history():
    c = _classes(stable=("PREWRITE_004",), resolved=("PREWRITE_004",))
    s = reflection.decide_scaffold_level({}, c, [], {"total_revisions": 4}, 1)
    assert s["level"] == 0
    assert s["label"] == "INDEPENDENT REFLECTION"


def test_support_can_increase_again():
    before = {"scaffold_level": 1, "unresolved": ["OUTLINE_004"]}
    curr = {"scaffold_level": 3, "unresolved": ["OUTLINE_004", "OUTLINE_006"]}
    msgs = [m["text"] for m in reflection.compare_reflections(before, curr)["messages"]]
    assert any("increased" in m for m in msgs)


def test_support_can_decrease():
    before = {"scaffold_level": 3, "unresolved": ["OUTLINE_004", "OUTLINE_006"]}
    curr = {"scaffold_level": 1, "unresolved": []}
    msgs = [m["text"] for m in reflection.compare_reflections(before, curr)["messages"]]
    assert any("reduced" in m for m in msgs)


def test_no_duplicate_prompts_within_one_response():
    # All variants shown + two same-category rules: must not repeat an ID.
    rules = [
        {"rule_id": "REFLECT_001", "status": "TRIGGERED", "priority": "CRITICAL",
         "priority_rank": 0, "prompt_category": "CONSISTENCY", "reason": "drift"},
        {"rule_id": "REFLECT_007", "status": "TRIGGERED", "priority": "HIGH",
         "priority_rank": 1, "prompt_category": "CONSISTENCY", "reason": "recurs"},
        {"rule_id": "REFLECT_012", "status": "TRIGGERED", "priority": "HIGH",
         "priority_rank": 1, "prompt_category": "CONSISTENCY", "reason": "regressed"},
    ]
    shown = {"RCON_H1", "RCON_H2"}
    out = reflection.select_reflection_prompts(rules, 3, shown_ids=shown)["prompts"]
    ids = [p["prompt_id"] for p in out]
    assert len(ids) == len(set(ids))


def test_prompt_history_rotation():
    rules = [{"rule_id": "REFLECT_002", "status": "TRIGGERED", "priority": "HIGH",
              "priority_rank": 1, "prompt_category": "ALIGNMENT", "reason": "weak"}]
    first = reflection.select_reflection_prompts(rules, 3)["prompts"]
    assert [p["prompt_id"] for p in first] == ["RALI_H1"]
    shown = {p["prompt_id"] for p in first}
    second = reflection.select_reflection_prompts(rules, 3, shown_ids=shown)["prompts"]
    assert [p["prompt_id"] for p in second] == ["RALI_H2"]


def test_checklist_single_source_of_truth(client):
    from services.reflection import CHECKLIST_ITEMS

    d = post_reflect(client).get_json()
    assert d["checklist"] == CHECKLIST_ITEMS
    assert len(d["checklist"]) == 5


def test_checklist_present_and_unchecked():
    assert len(reflection.CHECKLIST_ITEMS) == 5
    assert all(isinstance(i, str) and i for i in reflection.CHECKLIST_ITEMS)


def test_independent_review_behavior():
    rules = []
    out = reflection.select_reflection_prompts(rules, 0)
    assert out["prompts"] == []
    assert out["detail_level"] == "INDEPENDENT"
    r = reflection.check_reflection_readiness(0, _classes(stable=("X",)), [], True)
    assert r["decision"] == "COMPLETE"
    assert r["reflection_complete"] is True


# ------------------------------------------------ readiness & rules
def test_reflect_013_carries_earlier_major_issues():
    snap = {"idea_thesis": None, "thesis_points": [], "point_details": {},
            "progression": []}
    empty_classes = {"recurring": [], "resolved": [], "stable": [], "regressions": [],
                     "active": [], "new": []}
    history = {"by_rule": {"PREWRITE_007": {"stage": 1, "timeline": [], "triggers": 1}}}
    rules = reflection.evaluate_reflect_rules(
        snap, empty_classes, {"PREWRITE_007", "OUTLINE_004"}, history)
    by_id = {r["rule_id"]: r for r in rules}
    assert len(rules) == 13
    assert by_id["REFLECT_013"]["status"] == "TRIGGERED"
    assert "PREWRITE_007" in by_id["REFLECT_013"]["reason"]
    rules2 = reflection.evaluate_reflect_rules(
        snap, empty_classes, set(), {"by_rule": {}})
    assert {r["rule_id"]: r["status"] for r in rules2}["REFLECT_013"] == "INACTIVE"
    from services.rhetorical_moves import RULE_MOVE_MAP

    assert RULE_MOVE_MAP["REFLECT_013"] == "REFLECTION"


def test_reflect_rules_shape_and_grounding():
    snap = {"idea_thesis": {"classification": "POSSIBLY DRIFTED", "overlap": 0.1},
            "thesis_points": [{"point": 1, "classification": "WEAKLY ALIGNED"}],
            "point_details": {"1.1": {"classification": "WEAKLY ALIGNED"}},
            "progression": [{"pair": [1, 2], "abrupt_shift": True}]}
    rules = reflection.evaluate_reflect_rules(
        snap, {"recurring": [], "resolved": [], "stable": [], "regressions": [],
               "active": [], "new": []},
        {"OUTLINE_006", "OUTLINE_008"})
    by_id = {r["rule_id"]: r for r in rules}
    assert len(rules) == 13
    for rid in [f"REFLECT_{i:03d}" for i in range(1, 14)]:
        assert rid in by_id
        assert set(by_id[rid]) >= {"rule_id", "rule_name", "status", "evidence",
                                   "reason", "prompt_category", "priority", "priority_rank"}
    assert by_id["REFLECT_001"]["status"] == "TRIGGERED"
    assert by_id["REFLECT_001"]["priority"] == "CRITICAL"
    assert by_id["REFLECT_002"]["status"] == "TRIGGERED"
    assert by_id["REFLECT_004"]["status"] == "TRIGGERED"
    g = reflection.ground_reflect("REFLECT_002", "ALIGNMENT")
    assert g["source_type"] == "ESSAYSCAFF_RULE"
    assert g["theoretical_basis"] == "Scaffolding Theory"
    glt = reflection.ground_reflect("ANY", "ALIGNMENT")
    assert glt["source_type"] == "ESSAYSCAFF_RULE" and glt["external_basis"] is None


def test_readiness_conditions_all_present(client):
    s1, s2, s3 = full_chain(client)
    d = post_reflect(client, s1=s1, s2=s2, s3=s3).get_json()
    ids = [c["id"] for c in d["readiness"]["conditions"]]
    assert ids == ["R0", "R1", "R2", "R3", "R4"]
    assert all(c["result"] in ("PASS", "FAIL") for c in d["readiness"]["conditions"])
    assert "stage4_allowed" not in d["readiness"]  # no gate invented here
    assert d["readiness"]["decision"] in (
        "REFLECTING", "REVISION_RECOMMENDED",
        "READY_FOR_INDEPENDENT_REVIEW", "COMPLETE")


def test_completion_needs_independent_not_warnings_cleared(client):
    # Even a clean single-revision chain must not jump to COMPLETE without stability.
    d = post_reflect(client).get_json()
    assert d["readiness"]["decision"] != "COMPLETE"
    assert "master" not in d["readiness"]["student_message"].lower()


# ------------------------------------------------ authorship
def test_no_replacement_writing_anywhere(client):
    s1, s2, s3 = full_chain(client)
    d = post_reflect(client, s1=s1, s2=s2, s3=s3,
                     note="I think point two is weak.",
                     conclusion="In conclusion, climate matters.").get_json()
    texts = [p["text"] for p in d["prompts"]["prompts"]]
    texts.append(d["readiness"]["student_message"])
    texts.extend(m["text"] for m in d["comparison"]["messages"])
    texts.extend(r["reason"] for r in d["rules"])
    texts.extend(reflection.CHECKLIST_ITEMS)
    for t in texts:
        for banned in BANNED:
            assert banned not in t, (banned, t)
    for _cat, levels in reflection.REFLECT_PROMPT_BANK.items():
        for _lvl, pairs in levels.items():
            for _pid, text in pairs:
                if _lvl in ("HIGH", "MODERATE", "INDEPENDENT"):
                    assert text.strip().endswith("?"), (_pid, text)
                else:  # LIGHT review nudges are statements, not questions
                    assert text.strip().endswith(("?", ".")), (_pid, text)
                for banned in BANNED:
                    assert banned not in text, (banned, text)


# ------------------------------------------------ trace, replay, compat
def test_backtrace_gears_and_timings(client):
    s1, s2, s3 = full_chain(client)
    d = post_reflect(client, s1=s1, s2=s2, s3=s3).get_json()
    gears = {g["id"]: g for g in d["stage4_transparency"]}
    assert {"reflection_snapshot", "issue_history_aggregation",
            "resolution_classification", "recurring_detection",
            "scaffold_decision", "prompt_detail_selection",
            "prompt_selection", "reflection_persistence"} <= set(gears)
    for g in gears.values():
        for key in ("file", "function", "input", "output", "timing_ms", "next"):
            assert key in g, (g["id"], key)
        assert g["timing_ms"] >= 0
    for key in ("snapshot_ms", "history_ms", "resolution_ms", "rules_ms",
                "scaffold_ms", "prompts_ms", "readiness_ms", "compare_ms",
                "persist_ms", "total_ms"):
        assert d["timings"][key] >= 0


def test_replay_and_history_trace(client):
    s1, s2, s3 = full_chain(client)
    created = post_reflect(client, s1=s1, s2=s2, s3=s3).get_json()
    again = client.get(f"/api/stage4/session/{created['session_id']}").get_json()
    assert again["revision_count"] == 1
    rev = again["revisions"][0]
    assert rev["scaffold"]["level"] == created["scaffold"]["level"]
    assert rev["readiness"]["decision"] == created["readiness"]["decision"]
    assert [p["prompt_id"] for p in rev["prompts"]["prompts"]] == \
        [p["prompt_id"] for p in created["prompts"]["prompts"]]


def test_new_source_files_whitelisted(client):
    for file, func in [("services/reflection.py", "decide_scaffold_level"),
                       ("services/stage4.py", "analyze_reflection")]:
        res = client.get("/api/source", query_string={"file": file, "function": func})
        assert res.status_code == 200, file
        assert f"def {func}" in res.get_json()["source"]


def test_stage1_2_3_compatibility(client):
    s1 = post_idea(client, GOOD_IDEA)
    assert s1["revision_number"] == 1
    s2 = post_thesis(client, THESIS, s1=s1["session_id"])
    assert "thesis_rules" in s2
    s3 = post_outline(client, THESIS, [B1, B2], s2=s2["session_id"])
    assert "outline" in s3


def test_note_truncated_and_conclusion_optional(client):
    s1, s2, s3 = full_chain(client)
    d = post_reflect(client, s1=s1, s2=s2, s3=s3, note="x" * 5000).get_json()
    assert d["student_note_stored"] is True
    rev = client.get(f"/api/stage4/session/{d['session_id']}").get_json()["revisions"][0]
    from config import STAGE4_NOTE_MAX_CHARS

    assert rev["student_note"] == ("x" * 5000)[:STAGE4_NOTE_MAX_CHARS]
    assert len(rev["student_note"]) == STAGE4_NOTE_MAX_CHARS
    assert rev["conclusion"] == {"present": False, "note": "NOT AVAILABLE / NOT YET WRITTEN"}
    conclusion = "In conclusion, farmers adapt."
    d2 = post_reflect(client, s1=s1, s2=s2, s3=s3, session=d["session_id"],
                      conclusion=conclusion).get_json()
    assert d2["conclusion"]["present"] is True
    assert d2["conclusion"]["words"] == len(conclusion.split())


def test_refresh_restore_wiring():
    import re
    from pathlib import Path

    shell = (Path(__file__).resolve().parent.parent / "static" / "js" / "shell.js").read_text(encoding="utf-8")
    assert "sessionStorage" in shell
    assert "essayscaff.ws" in shell
    # Restore covers tabs + link IDs only — never editor drafts.
    for id_ in ('"s4Stage1"', '"s4Stage2"', '"s4Stage3"'):
        assert id_ in shell
    stored = set(re.findall(r'essayscaff\.([A-Za-z0-9]+)', shell))
    assert stored <= {"ws"}, stored


def test_return_links_point_at_stages(client):
    s1, s2, s3 = full_chain(client)
    d = post_reflect(client, s1=s1, s2=s2, s3=s3).get_json()
    for link in d["return_links"]:
        assert link["stage"] in (1, 2, 3)
        assert link["action"] == f"Review Stage {link['stage']}"

