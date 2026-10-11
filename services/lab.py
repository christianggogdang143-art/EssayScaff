"""Writing Lab sessions, essay persistence, and section readiness.

Student-authored text only: essay revisions store EXACTLY what the student
wrote in the lab — never generated from planning artifacts, never
rewritten, never merged across sections. Revisions are append-only per
(lab session, section); re-analyzing unchanged text reuses the revision.

Section rules (services/lab_rules.py) are EXPERIMENTAL and outside VR-2.
Stage 1-4 machinery is called, never modified: analysis runs through the
unchanged analysis_service.analyze, and stage histories are only read.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone

import config
from services import analysis_service, db
from services import lab_rules

LAB_SECTIONS = ("introduction", "body", "conclusion")

READY_DECISIONS = {
    "introduction": "READY FOR BODY",
    "body": "READY FOR CONCLUSION",
    "conclusion": "READY FOR FINAL REVIEW",
}

ESSAY_READY = "READY FOR INDEPENDENT REVIEW"
ESSAY_NEEDS_WORK = "REVISION NEEDED"

ESSAY_READY_MESSAGE = (
    "Your essay has no unresolved blocking scaffold issues. "
    "Review the full essay using your own judgment before submitting."
)


def new_lab_session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"LAB-{stamp}-{uuid.uuid4().hex[:6].upper()}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_row_exists(getter, sid: str) -> bool:
    try:
        session = getter(sid)
    except Exception:
        return False
    return bool(session.get("revisions"))


def _resolve_session(lab_session_id: str | None, chain: dict,
                     topic: str | None, teacher_keywords: list | None) -> dict:
    """Load or mint the lab session for this call.

    Chain links are immutable after creation: if the caller presents
    different non-null parent ids than stored, a NEW session is minted
    (stale chains are never silently re-linked; old rows untouched).
    Provided-but-unknown parent ids raise ValueError (no dangling links).
    """
    for key, getter, label in (
        ("stage1_session_id", db.get_stage1_session, "Stage 1"),
        ("stage2_session_id", db.get_stage2_session, "Stage 2"),
        ("stage3_session_id", db.get_stage3_session, "Stage 3"),
        ("stage4_session_id", db.get_stage4_session, "Stage 4"),
    ):
        sid = chain.get(key)
        if sid is not None and not _session_row_exists(getter, sid):
            raise ValueError(f"Unknown {label} session '{sid}'.")
    if lab_session_id is not None:
        stored = db.get_lab_session(lab_session_id)
        if stored.get("created_at") is None:
            raise ValueError(f"Unknown Writing Lab session '{lab_session_id}'.")
        for key in ("stage1_session_id", "stage2_session_id",
                    "stage3_session_id", "stage4_session_id"):
            old, new = stored.get(key), chain.get(key)
            if old is not None and new is not None and old != new:
                return _mint(chain, topic, teacher_keywords)
        return stored
    return _mint(chain, topic, teacher_keywords)


def _mint(chain: dict, topic: str | None, teacher_keywords: list | None) -> dict:
    now = _now_iso()
    return db.create_lab_session({
        "id": new_lab_session_id(),
        "stage1_session_id": chain.get("stage1_session_id"),
        "stage2_session_id": chain.get("stage2_session_id"),
        "stage3_session_id": chain.get("stage3_session_id"),
        "stage4_session_id": chain.get("stage4_session_id"),
        "topic": topic, "teacher_keywords": teacher_keywords,
        "status": "active", "data_mode": db.current_data_mode(),
        "created_at": now,
    })


def _thesis_keywords(session: dict) -> list[str] | None:
    sid = session.get("stage2_session_id")
    if not sid:
        return None
    revs = db.get_stage2_session(sid)["revisions"]
    if not revs:
        return None
    concepts = (revs[-1].get("components") or {}).get("important_concepts") or []
    return [str(c) for c in concepts]


def _outline_points(session: dict) -> list[dict] | None:
    sid = session.get("stage3_session_id")
    if not sid:
        return None
    revs = db.get_stage3_session(sid)["revisions"]
    if not revs:
        return None
    return revs[-1].get("outline") or []


def _evaluate(section: str, analysis: dict, session: dict) -> tuple[list[dict], dict]:
    if section == "introduction":
        rules = lab_rules.evaluate_intro(analysis)
        return rules, lab_rules.check_intro_readiness(rules)
    if section == "body":
        rules = lab_rules.evaluate_body(
            analysis, _thesis_keywords(session), _outline_points(session))
        return rules, lab_rules.check_body_readiness(rules)
    rules = lab_rules.evaluate_conclusion(analysis, _thesis_keywords(session))
    return rules, lab_rules.check_conc_readiness(rules)


def _log_lab_event(session_id: str, event_type: str, revision_number: int | None,
                   metadata: dict | None = None) -> None:
    try:
        db.log_interaction_event({
            "session_id": session_id, "stage": "lab", "event_type": event_type,
            "analysis_id": None, "revision_number": revision_number,
            "metadata_json": json.dumps(metadata or {}, sort_keys=True, default=str),
            "client_timestamp": None, "server_timestamp": _now_iso(),
            "active_elapsed_ms": None, "provenance": "server",
        })
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Lab event logging failed; analysis unaffected")


def _section_ready_map(session_id: str) -> dict:
    """Latest readiness decision per section from stored revisions."""
    out: dict[str, str | None] = {}
    session = db.get_lab_session(session_id)
    for rev in session.get("revisions", []):
        out[rev.get("section")] = ((rev.get("readiness") or {}).get("decision"))
    return out


def essay_status_for(session_id: str) -> dict:
    """Structural essay status. READY means: all three sections exist and
    each meets its blocking conditions. Never a quality grade."""
    ready = _section_ready_map(session_id)
    missing = [s for s in LAB_SECTIONS if s not in ready]
    not_ready = [s for s in LAB_SECTIONS
                 if s in ready and ready[s] != READY_DECISIONS[s]]
    if not missing and not not_ready:
        return {"decision": ESSAY_READY, "student_message": ESSAY_READY_MESSAGE,
                "sections": {s: ready[s] for s in LAB_SECTIONS},
                "missing_sections": [], "not_ready_sections": []}
    problems = [f"missing {s}" for s in missing] + [
        f"{s} ({ready[s]})" for s in not_ready]
    return {"decision": ESSAY_NEEDS_WORK,
            "student_message": ("Some sections still need work: " + "; ".join(problems) + ". "
                                "Revise them in your own words, then analyze each section again."),
            "sections": {s: ready.get(s) for s in LAB_SECTIONS},
            "missing_sections": missing, "not_ready_sections": not_ready}


def analyze_section(text: str, section: str, topic: str | None = None,
                    teacher_keywords: list | None = None,
                    lab_session_id: str | None = None,
                    stage1_session_id: str | None = None,
                    stage2_session_id: str | None = None,
                    stage3_session_id: str | None = None,
                    stage4_session_id: str | None = None,
                    validation_ms: float = 0.0) -> dict:
    """Analyze one lab-section draft: unchanged NLP + experimental LAB rules,
    append-only essay revision, section + essay readiness, transition events.
    """
    wall_start = time.perf_counter()
    if section not in LAB_SECTIONS:
        raise ValueError("Field 'section' must be one of: introduction, body, conclusion.")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("No section text provided. Write your draft first.")
    if len(text) > config.MAX_TEXT_CHARS:
        raise ValueError(f"Section text too long (max {config.MAX_TEXT_CHARS} characters).")
    chain = {"stage1_session_id": stage1_session_id, "stage2_session_id": stage2_session_id,
             "stage3_session_id": stage3_session_id, "stage4_session_id": stage4_session_id}
    session = _resolve_session(lab_session_id, chain, topic, teacher_keywords)
    sid = session["lab_session_id"]
    if topic is None:
        topic = session.get("topic")
    if teacher_keywords is None:
        teacher_keywords = session.get("teacher_keywords")

    analysis = analysis_service.analyze(
        text, stage=section, validation_ms=validation_ms,
        topic=topic, teacher_keywords=teacher_keywords)
    lab_rules_out, readiness = _evaluate(section, analysis, session)
    fired = sorted({r["rule_id"] for r in lab_rules_out
                    if r["status"] == "TRIGGERED" and r["blocking"]})

    prev = db.latest_essay_revision(sid, section)
    prev_ready = ((prev or {}).get("readiness") or {}).get("decision")
    essay_before = essay_status_for(sid)
    if prev is not None and prev.get("essay_text") == text:
        revision_number = prev["revision_number"]
        created_new = False
        record = dict(prev)
    else:
        revision_number = db.next_essay_revision(sid, section)
        created_new = True
        record = {
            "lab_session_id": sid, "section": section,
            "revision_number": revision_number, "essay_text": text,
            "analysis_id": analysis["analysis_id"], "readiness": readiness,
            "fired_rules": fired, "created_at": _now_iso(),
        }
        revision_number = db.save_essay_revision(record)
    db.touch_lab_session(sid, _now_iso())

    _log_lab_event(sid, "ANALYSIS_COMPLETED", revision_number,
                   {"section": section, "decision": readiness.get("decision"),
                    "fired_rules": fired})
    if readiness.get("decision") == READY_DECISIONS[section] and prev_ready != READY_DECISIONS[section]:
        _log_lab_event(sid, "LAB_SECTION_READY", revision_number,
                       {"section": section, "decision": readiness.get("decision")})
    essay_after = essay_status_for(sid)
    if (essay_after["decision"] == ESSAY_READY
            and essay_before["decision"] != ESSAY_READY):
        _log_lab_event(sid, "ESSAY_READY_FOR_REVIEW", revision_number,
                       {"sections": essay_after["sections"]})

    comparison = _compare_section(prev, text)
    return {
        "lab_session_id": sid, "section": section,
        "revision_number": revision_number, "created_new_revision": created_new,
        "stage1_session_id": session.get("stage1_session_id"),
        "stage2_session_id": session.get("stage2_session_id"),
        "stage3_session_id": session.get("stage3_session_id"),
        "stage4_session_id": session.get("stage4_session_id"),
        "topic": topic, "teacher_keywords": teacher_keywords,
        # Passthrough of the unchanged analysis shape so transparency,
        # walkthrough, highlights, and dashboard keep consuming one shape.
        "analysis_id": analysis["analysis_id"],
        "summary": analysis.get("summary", {}),
        "feedback": analysis.get("feedback", []),
        "technical": analysis.get("technical", {}),
        "transparency": analysis.get("transparency"),
        "analysis": analysis, "lab_rules": lab_rules_out,
        "lab_readiness": readiness, "comparison": comparison,
        "essay_status": essay_after,
        "processing_ms": (time.perf_counter() - wall_start) * 1000.0,
    }


def _compare_section(prev: dict | None, text: str) -> dict:
    """Minimal honest revision comparison (word-count movement only)."""
    import re

    def words(t: str) -> int:
        return len(re.findall(r"\S+", t or ""))
    if prev is None:
        return {"deltas": None, "messages": [
            {"text": "This is your first saved revision of this section.",
             "evidence": "No prior revision."}]}
    delta = words(text) - words(prev.get("essay_text") or "")
    return {"deltas": {"word_delta": delta}, "messages": [
        {"text": ("You added words since the last revision." if delta > 0
                  else "You shortened the text since the last revision." if delta < 0
                  else "Same text as the stored revision."),
         "evidence": f"word_delta={delta}."}]}


def get_lab_essay(session_id: str) -> dict:
    """Latest student-written text per section (concatenation-ready)."""
    session = db.get_lab_session(session_id)
    if session.get("created_at") is None:
        raise ValueError(f"Unknown Writing Lab session '{session_id}'.")
    essay = {}
    for section in LAB_SECTIONS:
        rev = db.latest_essay_revision(session_id, section)
        essay[section] = (rev or {}).get("essay_text")
    return {"lab_session_id": session_id, "essay": essay,
            "essay_status": essay_status_for(session_id)}


def _interval_union_ms(session_ids: list[str]) -> tuple[int, int]:
    from services.learning_analytics import _union_active_ms

    rows = []
    for sid in session_ids:
        rows.extend(db.get_session_intervals(sid))
    return _union_active_ms(rows)


def summarize_lab_session(session_id: str) -> dict:
    """Writing Process Summary payload (read-only assembly, then one
    PROCESS_SUMMARY_VIEWED event). Every number below counts stored rows."""
    import json

    session = db.get_lab_session(session_id)
    if session.get("created_at") is None:
        raise ValueError(f"Unknown Writing Lab session '{session_id}'.")
    chain_ids = [session.get("stage1_session_id"), session.get("stage2_session_id"),
                 session.get("stage3_session_id"), session.get("stage4_session_id")]

    stages = {}
    for key, getter, label in (
        ("stage1", db.get_stage1_session, "Idea"),
        ("stage2", db.get_stage2_session, "Thesis"),
        ("stage3", db.get_stage3_session, "Outline"),
        ("stage4", db.get_stage4_session, "Reflection"),
    ):
        sid = session.get(key + "_session_id")
        if not sid:
            stages[key] = {"label": label, "linked": False}
            continue
        revs = getter(sid)["revisions"]
        last = revs[-1] if revs else {}
        stages[key] = {
            "label": label, "linked": True, "session_id": sid,
            "revision_count": len(revs),
            "decision": ((last.get("readiness") or {}).get("decision")),
            "created_at": (revs[0].get("created_at") if revs else None),
        }
    planning = {
        "idea": _final_text(db.get_stage1_session, session.get("stage1_session_id"), "idea_text"),
        "thesis": _final_text(db.get_stage2_session, session.get("stage2_session_id"), "thesis_text"),
        "outline": _final_outline(session.get("stage3_session_id")),
        "reflection": _final_reflection(session.get("stage4_session_id")),
    }
    essay_revs = session.get("revisions", [])
    by_section: dict[str, list] = {s: [] for s in LAB_SECTIONS}
    for rev in essay_revs:
        if rev.get("section") in by_section:
            by_section[rev["section"]].append(rev)
    essay = {s: (by_section[s][-1].get("essay_text") if by_section[s] else None)
             for s in LAB_SECTIONS}
    section_ready = {}
    for s in LAB_SECTIONS:
        last = by_section[s][-1] if by_section[s] else None
        section_ready[s] = ((last or {}).get("readiness") or {}).get("decision")

    lab_counts = {s: len(by_section[s]) for s in LAB_SECTIONS}
    total_lab = sum(lab_counts.values())
    total_stage = sum((stages[k].get("revision_count") or 0)
                      for k in ("stage1", "stage2", "stage3", "stage4"))
    all_sids = [s for s in ([session_id] + chain_ids) if s]
    active_ms, overlap_adjusted_ms = _interval_union_ms(all_sids)
    per_session_time = {}
    for sid in all_sids:
        ms, _ = _interval_union_ms([sid])
        per_session_time[sid] = ms

    fb_items = 0
    fb_known = True
    rule_hits: dict[str, int] = {}
    first_ready_at: dict[str, str | None] = {}
    for s in LAB_SECTIONS:
        for rev in by_section[s]:
            for rid in rev.get("fired_rules", []) or []:
                rule_hits[rid] = rule_hits.get(rid, 0) + 1
            if section_ready[s] and first_ready_at.get(s) is None and rev.get("readiness", {}).get("decision") == READY_DECISIONS[s]:
                first_ready_at[s] = rev.get("created_at")
            if rev.get("analysis_id"):
                try:
                    run = db.get_run(rev["analysis_id"])
                    fb_items += len(run.get("feedback", []) or []) if run else 0
                except Exception:
                    fb_known = False
    current_unresolved: dict[str, list] = {}
    for s in LAB_SECTIONS:
        last = by_section[s][-1] if by_section[s] else None
        current_unresolved[s] = list((last or {}).get("fired_rules", []) or [])
    resolved: dict[str, list] = {}
    for s in LAB_SECTIONS:
        seen: set[str] = set()
        for rev in by_section[s]:
            seen.update(rev.get("fired_rules", []) or [])
        last_fired = set(current_unresolved[s])
        resolved[s] = sorted(seen - last_fired)

    timeline = []
    for key in ("stage1", "stage2", "stage3", "stage4"):
        st = stages[key]
        if not st.get("linked"):
            continue
        sid = st["session_id"]
        getter = {"stage1": db.get_stage1_session, "stage2": db.get_stage2_session,
                  "stage3": db.get_stage3_session, "stage4": db.get_stage4_session}[key]
        for rev in getter(sid)["revisions"]:
            timeline.append({"kind": st["label"], "revision_number": rev.get("revision_number"),
                             "decision": (rev.get("readiness") or {}).get("decision"),
                             "created_at": rev.get("created_at")})
    for rev in essay_revs:
        timeline.append({"kind": "Essay " + str(rev.get("section")).capitalize(),
                         "revision_number": rev.get("revision_number"),
                         "decision": (rev.get("readiness") or {}).get("decision"),
                         "created_at": rev.get("created_at")})
    timeline.sort(key=lambda e: (e.get("created_at") or "",))

    latest_activity = None
    for e in timeline:
        if e.get("created_at") and (latest_activity is None or e["created_at"] > latest_activity):
            latest_activity = e["created_at"]

    payload = {
        "lab_session_id": session_id,
        "assignment": {"topic": session.get("topic"),
                       "teacher_keywords": session.get("teacher_keywords")},
        "data_mode": session.get("data_mode"),
        "process_status": {
            "stages": stages,
            "lab_sections": {s: {"ready": section_ready[s] == READY_DECISIONS[s],
                                 "decision": section_ready[s],
                                 "revision_count": lab_counts[s],
                                 "completed_at": first_ready_at.get(s)} for s in LAB_SECTIONS},
            "final_review": essay_status_for(session_id),
        },
        "planning_artifacts": planning,
        "student_essay": essay,
        "revision_info": {
            "per_stage": {k: (stages[k].get("revision_count") or 0)
                           for k in ("stage1", "stage2", "stage3", "stage4")},
            "per_section": lab_counts,
            "total_stage_revisions": total_stage,
            "total_lab_revisions": total_lab,
            "total_revisions": total_stage + total_lab,
        },
        "time": {
            "active_ms": {"value": active_ms, "status": "OK", "reason": None},
            "overlap_adjusted_ms": overlap_adjusted_ms,
            "per_session_ms": per_session_time,
            "started_at": session.get("created_at"),
            "latest_activity_at": latest_activity,
        },
        "feedback": {
            "lab_feedback_items": fb_items if fb_known else None,
            "feedback_known": fb_known,
            "resolved_lab_rules": resolved,
            "current_unresolved_lab_rules": current_unresolved,
            "most_frequent_lab_rules": sorted(
                rule_hits.items(), key=lambda kv: (-kv[1], kv[0]))[:10],
        },
        "timeline": timeline,
    }
    _log_lab_event(session_id, "PROCESS_SUMMARY_VIEWED", None, {})
    return payload


def _final_text(getter, sid: str | None, field: str):
    if not sid:
        return None
    try:
        revs = getter(sid)["revisions"]
    except Exception:
        return None
    return (revs[-1].get(field) if revs else None)


def _final_outline(sid: str | None):
    if not sid:
        return None
    try:
        revs = db.get_stage3_session(sid)["revisions"]
    except Exception:
        return None
    return (revs[-1].get("outline") if revs else None)


def _final_reflection(sid: str | None):
    if not sid:
        return None
    try:
        revs = db.get_stage4_session(sid)["revisions"]
    except Exception:
        return None
    if not revs:
        return None
    last = revs[-1]
    return {"decision": (last.get("readiness") or {}).get("decision"),
            "scaffold": (last.get("scaffold") or {}).get("label"),
            "student_note_stored": bool(last.get("student_note"))}
