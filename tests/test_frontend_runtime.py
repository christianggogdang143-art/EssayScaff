"""Frontend runtime smoke tests: REAL JS + REAL DOM + REAL backend payloads.

jsdom executes the shipped static/js sources against the shipped
templates/index.html markup. Backend payloads are captured from the real
Flask app (tmp DB), so renderers consume genuine response shapes.
Catches runtime bugs (e.g. recursive readJson) that syntax checks miss.

Limitation (documented): jsdom is not a layout/paint browser engine;
fetch and timers are stubbed. What IS real: shipped JS, shipped markup,
DOM semantics, backend payloads.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from app import create_app
from services import db

ROOT = Path(__file__).resolve().parent.parent
SMOKE_JS = ROOT / "tests" / "frontend_smoke" / "smoke.js"

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
LAB_INTRO = ("Climate change affects crop production because extreme temperatures and irregular "
             "rainfall create difficulties for farmers. Crop farmers need stable temperature "
             "and rainfall for agriculture.")
LAB_BODY = ("Extreme temperatures reduce crop production because high heat damages growing "
            "plants during critical weeks. Farmers face irregular rainfall that disrupts "
            "planting schedules and lowers harvests across affected farming regions. "
            "Dry spells stress young crops further.")
LAB_CONC = ("Climate change threatens farming, so farmers must adapt planting to shifting "
            "rainfall and heat while protecting future crop yields.")
# Exact bug-report reproduction inputs (blocked Stage 1: short idea).
BLOCKED_TOPIC = "Effects of social media use on students' academic performance"
BLOCKED_KWS = ["social media", "students", "academic performance",
               "distraction", "concentration", "study habits", "schoolwork"]
BLOCKED_IDEA = "Social media affects students."


def _harness_dir() -> Path:
    d = Path(tempfile.gettempdir()) / "opencode" / "jsharness"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ensure_jsdom() -> Path:
    d = _harness_dir()
    marker = d / "node_modules" / "jsdom" / "package.json"
    if not marker.exists():
        subprocess.run(
            ["npm", "install", "--prefix", str(d), "--no-save",
             "--no-audit", "--no-fund", "jsdom"],
            check=True, capture_output=True, timeout=300)
    assert marker.exists(), "jsdom is required for frontend runtime tests"
    return d


@pytest.fixture(scope="module")
def verdict(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("fepayload")
    import services.db as db_mod
    orig = db_mod.db_path
    db_mod.db_path = lambda: tmp_path / "front.db"
    try:
        application = create_app(prewarm=False)
        application.config.update(TESTING=True)
        client = application.test_client()
        payloads = {}
        s1 = client.post("/api/stage1/analyze", json={
            "text": IDEA, "topic": TOPIC, "teacher_keywords": KWS}).get_json()
        assert s1["readiness"]["stage2_allowed"] is True
        payloads["stage1"] = s1
        payloads["stage1session"] = client.get(
            f"/api/stage1/session/{s1['session_id']}").get_json()
        s2 = client.post("/api/stage2/analyze", json={
            "text": THESIS, "topic": TOPIC, "teacher_keywords": KWS,
            "stage1_session_id": s1["session_id"]}).get_json()
        assert s2["readiness"]["stage3_allowed"] is True
        payloads["stage2"] = s2
        payloads["stage2session"] = client.get(
            f"/api/stage2/session/{s2['session_id']}").get_json()
        s3 = client.post("/api/stage3/analyze", json={
            "thesis": THESIS, "topic": TOPIC, "teacher_keywords": KWS,
            "outline": [B1, B2],
            "stage2_session_id": s2["session_id"]}).get_json()
        payloads["stage3"] = s3
        payloads["stage3session"] = client.get(
            f"/api/stage3/session/{s3['session_id']}").get_json()
        s4 = client.post("/api/stage4/reflect", json={}).get_json()
        payloads["stage4"] = s4
        payloads["stage4session"] = client.get(
            f"/api/stage4/session/{s4['session_id']}").get_json()
        lab_chain = {"stage1_session_id": s1["session_id"],
                     "stage2_session_id": s2["session_id"],
                     "stage3_session_id": s3["session_id"],
                     "topic": TOPIC, "teacher_keywords": KWS}
        li = client.post("/api/lab/analyze", json={
            "text": LAB_INTRO, "section": "introduction", **lab_chain}).get_json()
        assert li["lab_readiness"]["decision"] == "READY FOR BODY"
        payloads["labintro"] = li
        lb = client.post("/api/lab/analyze", json={
            "text": LAB_BODY, "section": "body",
            "lab_session_id": li["lab_session_id"], **lab_chain}).get_json()
        assert lb["lab_readiness"]["decision"] == "READY FOR CONCLUSION"
        payloads["labbody"] = lb
        lc = client.post("/api/lab/analyze", json={
            "text": LAB_CONC, "section": "conclusion",
            "lab_session_id": li["lab_session_id"], **lab_chain}).get_json()
        assert lc["lab_readiness"]["decision"] == "READY FOR FINAL REVIEW"
        payloads["labconc"] = lc
        payloads["labsession"] = client.get(
            f"/api/lab/session/{li['lab_session_id']}").get_json()
        payloads["labsummary"] = client.get(
            f"/api/lab/session/{li['lab_session_id']}/summary").get_json()
        payloads["live"] = client.post("/api/analyze", json={
            "text": IDEA, "topic": TOPIC, "teacher_keywords": KWS}).get_json()
        # Genuine blocked Stage-1 response for the badge-provenance flows.
        # Backend premise asserted here: the gate really blocks on
        # PREWRITE_001 and the visible guidance carries its rule_id.
        blocked = client.post("/api/stage1/analyze", json={
            "text": BLOCKED_IDEA, "topic": BLOCKED_TOPIC,
            "teacher_keywords": BLOCKED_KWS}).get_json()
        assert blocked["readiness"]["decision"] == "DEVELOPING"
        assert blocked["readiness"]["stage2_allowed"] is False
        assert "PREWRITE_001" in blocked["readiness"]["blocking_rules"]
        bmain = (blocked.get("guidance") or {}).get("main") or {}
        assert bmain.get("rule_id") == "PREWRITE_001", bmain
        assert (bmain.get("question") or {}).get("prompt_id") != "PREWRITE_001"
        payloads["stage1blocked"] = blocked
        paydir = tmp_path / "payloads"
        paydir.mkdir()
        for name, body in payloads.items():
            (paydir / f"{name}.json").write_text(
                json.dumps(body), encoding="utf-8")
    finally:
        db_mod.db_path = orig
    harness = _ensure_jsdom()
    env = dict(os.environ, JSDOM_PATH=str(
        harness / "node_modules" / "jsdom"))
    proc = subprocess.run(
        ["node", str(SMOKE_JS),
         "--html", str(ROOT / "templates" / "index.html"),
         "--jsdir", str(ROOT / "static" / "js"),
         "--payloads", str(paydir)],
        capture_output=True, text=True, timeout=180, env=env,
        cwd=str(ROOT))
    assert proc.returncode == 0, (
        f"smoke harness failed (exit {proc.returncode}):\n"
        f"STDOUT: {proc.stdout[-3000:]}\nSTDERR: {proc.stderr[-2000:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])["verdict"]


def _flow(verdict, name):
    assert name in verdict, f"flow {name} missing from harness verdict"
    assert verdict[name]["ok"] is True, (
        f"flow {name} failed: {verdict[name].get('error')}")


def test_runtime_stage1_analyze(verdict):
    _flow(verdict, "stage1_analyze")


def test_runtime_direct_tab_2_stays_unlinked(verdict):
    _flow(verdict, "direct_tab_2_stays_unlinked")


def test_runtime_stale_stage2_not_reused(verdict):
    _flow(verdict, "stale_stage2_not_reused_setup")


def test_runtime_direct_tab_3_stays_unlinked(verdict):
    _flow(verdict, "direct_tab_3_stays_unlinked")


def test_runtime_direct_tab_4_stays_manual(verdict):
    _flow(verdict, "direct_tab_4_stays_manual")


def test_runtime_continue_1_to_2(verdict):
    _flow(verdict, "continue_1_to_2")


def test_runtime_stage2_analyze(verdict):
    _flow(verdict, "stage2_analyze")


def test_runtime_continue_2_to_3(verdict):
    _flow(verdict, "continue_2_to_3")


def test_runtime_stage3_analyze(verdict):
    _flow(verdict, "stage3_analyze")


def test_runtime_continue_3_to_4(verdict):
    _flow(verdict, "continue_3_to_4")


def test_runtime_manual_stage3_to_4_recovers_s1(verdict):
    _flow(verdict, "manual_stage3_to_4_recovers_s1")


def test_runtime_unlinked_stage3_stays_honestly_partial(verdict):
    _flow(verdict, "unlinked_stage3_stays_honestly_partial")


def test_runtime_stage4_reflect(verdict):
    _flow(verdict, "stage4_reflect")


def test_runtime_labbtn_visibility_policy(verdict):
    _flow(verdict, "labbtn_visibility_policy")


def test_runtime_labbtn_hidden_for_unready_live(verdict):
    _flow(verdict, "labbtn_hidden_for_unready_live")


def test_runtime_lab_continue_carries_chain(verdict):
    _flow(verdict, "lab_continue_carries_chain")


def test_runtime_lab_hides_stage_prompts(verdict):
    _flow(verdict, "lab_hides_stage_prompts")


def test_runtime_lab_starter_introduction(verdict):
    _flow(verdict, "lab_starter_introduction")


def test_runtime_lab_starter_body(verdict):
    _flow(verdict, "lab_starter_body")


def test_runtime_lab_starter_conclusion(verdict):
    _flow(verdict, "lab_starter_conclusion")


def test_runtime_lab_single_primary_card(verdict):
    _flow(verdict, "lab_single_primary_card")


def test_runtime_lab_section_intro_ready(verdict):
    _flow(verdict, "lab_section_intro_ready")


def test_runtime_lab_section_drafts_isolated(verdict):
    _flow(verdict, "lab_section_drafts_isolated")


def test_runtime_lab_section_body_ready(verdict):
    _flow(verdict, "lab_section_body_ready")


def test_runtime_lab_section_conclusion_ready(verdict):
    _flow(verdict, "lab_section_conclusion_ready")


def test_runtime_lab_review_essay_and_summary(verdict):
    _flow(verdict, "lab_review_essay_and_summary")


def test_runtime_lab_progression_gates_closed(verdict):
    _flow(verdict, "lab_progression_gates_closed")


def test_runtime_hl_spans_match_offsets(verdict):
    _flow(verdict, "hl_spans_match_offsets")


def test_runtime_hl_colors_match_legend(verdict):
    _flow(verdict, "hl_colors_match_legend")


def test_runtime_hl_null_offsets_skipped(verdict):
    _flow(verdict, "hl_null_offsets_skipped")


def test_runtime_hl_typing_clears(verdict):
    _flow(verdict, "hl_typing_clears")


def test_runtime_hl_card_mark_link(verdict):
    _flow(verdict, "hl_card_mark_link")


def test_runtime_hl_no_new_requests(verdict):
    _flow(verdict, "hl_no_new_requests")


def test_runtime_select_primary_sequencing(verdict):
    _flow(verdict, "select_primary_sequencing")


def test_runtime_dash_goal_next_stages(verdict):
    _flow(verdict, "dash_goal_next_stages")


def test_runtime_dash_working_stage1(verdict):
    _flow(verdict, "dash_working_stage1")


def test_runtime_dash_checklist_stage2(verdict):
    _flow(verdict, "dash_checklist_stage2")


def test_runtime_dash_snapshot_lab(verdict):
    _flow(verdict, "dash_snapshot_lab")


def test_runtime_dash_snapshot_stage_time(verdict):
    _flow(verdict, "dash_snapshot_stage_time")


def test_runtime_dash_prev_and_switch(verdict):
    _flow(verdict, "dash_prev_and_switch")


def test_runtime_dash_one_primary_visible(verdict):
    _flow(verdict, "dash_one_primary_visible")


def test_runtime_dash_blocking_badges(verdict):
    _flow(verdict, "dash_blocking_badges")


def test_runtime_dash_blocking_unit(verdict):
    _flow(verdict, "dash_blocking_unit")


def test_runtime_badge_stage1_blocking_guidance(verdict):
    _flow(verdict, "badge_stage1_blocking_guidance")


def test_runtime_badge_next_step_states(verdict):
    _flow(verdict, "badge_next_step_states")


def test_runtime_badge_cross_stage_slots(verdict):
    _flow(verdict, "badge_cross_stage_slots")


def test_runtime_badge_starter_silent(verdict):
    _flow(verdict, "badge_starter_silent")


def test_runtime_transparency_keeps_all_findings(verdict):
    _flow(verdict, "transparency_keeps_all_findings")


def test_runtime_revisions_keep_history(verdict):
    _flow(verdict, "revisions_keep_history")


def test_runtime_live_feedback_parse(verdict):
    _flow(verdict, "live_feedback_parse")


def test_runtime_student_transparency_toggle(verdict):
    _flow(verdict, "student_transparency_toggle")


def test_walkthrough_hidden_in_student_mode(verdict):
    _flow(verdict, "walkthrough_hidden_in_student")


def test_walkthrough_shows_in_transparency_mode(verdict):
    _flow(verdict, "walkthrough_shows_in_transparency")


def test_walkthrough_renders_real_data(verdict):
    _flow(verdict, "walkthrough_renders_real_data")


def test_runtime_copy_hidden_before_analysis(verdict):
    _flow(verdict, "copy_hidden_before_analysis")


def test_runtime_copy_stage1_report(verdict):
    _flow(verdict, "copy_stage1_report")


def test_runtime_copy_stage2_report(verdict):
    _flow(verdict, "copy_stage2_report")


def test_runtime_copy_stage3_report(verdict):
    _flow(verdict, "copy_stage3_report")


def test_runtime_copy_stage4_report(verdict):
    _flow(verdict, "copy_stage4_report")


def test_runtime_copy_lab_report(verdict):
    _flow(verdict, "copy_lab_report")


def test_runtime_copy_missing_data_safe(verdict):
    _flow(verdict, "copy_missing_data_safe")


def test_runtime_copy_hidden_in_student(verdict):
    _flow(verdict, "copy_hidden_in_student")


def test_walkthrough_missing_data_safe(verdict):
    _flow(verdict, "walkthrough_missing_data_safe")


def test_walkthrough_follows_stage_tab(verdict):
    _flow(verdict, "walkthrough_follows_stage_tab")


def test_walkthrough_stage4_honest(verdict):
    _flow(verdict, "walkthrough_stage4_honest")


def test_analytics_app_opened(verdict):
    _flow(verdict, "analytics_app_opened")


def test_analytics_stage_events(verdict):
    _flow(verdict, "analytics_stage_events")


def test_analytics_active_interval(verdict):
    _flow(verdict, "analytics_active_interval")


def test_analytics_idle_pause(verdict):
    _flow(verdict, "analytics_idle_pause")


def test_analytics_progress_renders(verdict):
    _flow(verdict, "analytics_progress_renders")


def test_analytics_no_essay_text(verdict):
    _flow(verdict, "analytics_no_essay_text")


def test_analytics_refresh_recovery(verdict):
    _flow(verdict, "analytics_refresh_recovery")


def test_readjson_not_recursive():
    """Static guard: no readJson may call itself instead of res.json()."""
    jsdir = ROOT / "static" / "js"
    for path in sorted(jsdir.glob("*.js")):
        src = path.read_text(encoding="utf-8")
        assert "return await readJson(" not in src, path.name
    for name in ("stage1.js", "stage2.js", "stage3.js", "stage4.js",
                 "live_feedback.js", "validation.js"):
        src = (jsdir / name).read_text(encoding="utf-8")
        assert "res.json()" in src or "JSON.parse" in src, name
