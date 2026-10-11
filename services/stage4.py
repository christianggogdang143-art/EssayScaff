"""Stage 4 orchestration: reflection over stored Stage 1-3 histories.

No new NLP runs and no re-analysis: every input is a stored revision
record. Cross-stage snapshot -> issue history -> resolution classes ->
REFLECT rules -> scaffold level -> fading prompts -> readiness ->
comparison -> append-only persistence.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

import config
from services import db
from services import reflection as reflection_mod


def new_stage4_session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"SES4-{stamp}-{uuid.uuid4().hex[:6].upper()}"


def _load_linked(stage1_session_id, stage2_session_id, stage3_session_id) -> dict:
    """Load linked sessions. Unknown IDs raise ValueError (route -> 404)."""
    out = {}
    for stage, sid, getter in (
        (1, stage1_session_id, db.get_stage1_session),
        (2, stage2_session_id, db.get_stage2_session),
        (3, stage3_session_id, db.get_stage3_session),
    ):
        if not sid:
            out[stage] = None
            continue
        session = getter(sid)
        if not session["revisions"]:
            raise ValueError(f"Unknown Stage {stage} session '{sid}'.")
        out[stage] = session
    return out


def analyze_reflection(session_id=None, stage1_session_id=None,
                       stage2_session_id=None, stage3_session_id=None,
                       student_note=None, conclusion=None) -> dict:
    wall_start = time.perf_counter()
    session_id = session_id or new_stage4_session_id()

    t0 = time.perf_counter()
    linked = _load_linked(stage1_session_id, stage2_session_id, stage3_session_id)
    s3 = linked[3]
    if s3 is not None:
        last3 = s3["revisions"][-1]
        if not (last3.get("readiness", {}) or {}).get("stage4_allowed", False):
            raise PermissionError(
                f"Stage 3 session '{stage3_session_id}' is not ready for reflection "
                "(stage4_allowed is false).")
    snapshot_ms = (time.perf_counter() - t0) * 1000.0

    # ---- reflection snapshot (stored records only) ----
    t0 = time.perf_counter()
    s1_last = linked[1]["revisions"][-1] if linked[1] else None
    s2_last = linked[2]["revisions"][-1] if linked[2] else None
    s3_last = linked[3]["revisions"][-1] if linked[3] else None
    snapshot = reflection_mod.build_consistency_snapshot(s1_last, s2_last, s3_last)
    snapshot["topic"] = (s3_last or s2_last or s1_last or {}).get("topic")
    snapshot["teacher_keywords"] = (s3_last or s2_last or s1_last or {}).get("teacher_keywords")
    snapshot["idea_text"] = (s1_last or {}).get("idea_text")
    snapshot["thesis_text"] = (s2_last or {}).get("thesis_text")
    snapshot["outline"] = (s3_last or {}).get("outline")
    snapshot_ms2 = (time.perf_counter() - t0) * 1000.0

    # ---- issue history ----
    t0 = time.perf_counter()
    stage_histories = {}
    for stage in (1, 2, 3):
        sess = linked[stage]
        if sess is None:
            continue
        stage_histories[stage] = [
            {"revision": r.get("revision_number"), "fired": list(r.get("fired_rules", []))}
            for r in sess["revisions"]
        ]
    history = reflection_mod.build_issue_history(stage_histories)
    history_ms = (time.perf_counter() - t0) * 1000.0

    # ---- resolution classification ----
    t0 = time.perf_counter()
    classes = reflection_mod.classify_history(history)
    resolution_ms = (time.perf_counter() - t0) * 1000.0

    active_ids = {r["rule_id"] for r in classes["active"]}

    # ---- REFLECT rules ----
    t0 = time.perf_counter()
    reflect_rules = reflection_mod.evaluate_reflect_rules(snapshot, classes, active_ids, history)
    rules_ms = (time.perf_counter() - t0) * 1000.0

    # ---- scaffold level ----
    t0 = time.perf_counter()
    history_session = db.get_stage4_session(session_id)
    prev_level = None
    if history_session.get("revisions"):
        prev_level = history_session["revisions"][-1].get("scaffold", {}).get("level")
    if history["total_revisions"] == 0:
        scaffold = {
            "level": 2, "label": "MODERATE SUPPORT",
            "evidence": {"insufficient_history": True, "total_revisions": 0},
            "decision_rule": "No linked revision history: conservative middle support.",
            "previous_level": prev_level,
            "reason": "INSUFFICIENT HISTORY FOR FADING; normal reflection guidance given.",
        }
    else:
        scaffold = reflection_mod.decide_scaffold_level(snapshot, classes, reflect_rules, history, prev_level)
    reflect_rules = reflection_mod.finalize_reflect_011(reflect_rules, scaffold["level"])
    scaffold_ms = (time.perf_counter() - t0) * 1000.0

    # ---- prompts ----
    shown: set[str] = set()
    for rev in history_session.get("revisions", []):
        for pr in rev.get("prompts", {}).get("prompts", []):
            shown.add(pr["prompt_id"])
    t0 = time.perf_counter()
    prompts = reflection_mod.select_reflection_prompts(reflect_rules, scaffold["level"], shown_ids=shown)
    prompts_ms = (time.perf_counter() - t0) * 1000.0

    # ---- readiness ----
    t0 = time.perf_counter()
    readiness = reflection_mod.check_reflection_readiness(
        scaffold["level"], classes, reflect_rules, history["total_revisions"] > 0)
    readiness_ms = (time.perf_counter() - t0) * 1000.0

    # ---- comparison vs previous Stage 4 revision ----
    t0 = time.perf_counter()
    curr_point = {"scaffold_level": scaffold["level"],
                  "unresolved": sorted({r["rule_id"] for r in reflect_rules if r["status"] == "TRIGGERED"})}
    if history_session.get("revisions"):
        last = history_session["revisions"][-1]
        prev_point = {"scaffold_level": (last.get("scaffold", {}) or {}).get("level"),
                      "unresolved": sorted((last.get("unresolved_rules", []) or []))}
        comparison = reflection_mod.compare_reflections(prev_point, curr_point)
    else:
        comparison = reflection_mod.compare_reflections(None, curr_point)
    compare_ms = (time.perf_counter() - t0) * 1000.0

    # ---- conclusion (stored, never analyzed) ----
    if conclusion is not None and str(conclusion).strip():
        text = str(conclusion)[: config.MAX_TEXT_CHARS]
        conclusion_rec = {"present": True, "chars": len(text), "words": len(text.split()),
                          "note": "Stored only; conclusion analysis does not exist yet."}
    else:
        conclusion_rec = {"present": False, "note": "NOT AVAILABLE / NOT YET WRITTEN"}
    note = (student_note or "")
    if len(note) > config.STAGE4_NOTE_MAX_CHARS:
        note = note[: config.STAGE4_NOTE_MAX_CHARS]

    revision_number = db.next_stage4_revision(session_id)
    stats = _accumulate_stats(history_session, reflect_rules, prompts, revision_number)
    record = {
        "session_id": session_id, "revision_number": revision_number,
        "stage1_session_id": stage1_session_id, "stage2_session_id": stage2_session_id,
        "stage3_session_id": stage3_session_id,
        "topic": snapshot.get("topic"), "teacher_keywords": snapshot.get("teacher_keywords"),
        "snapshot": snapshot, "history": history, "classes": classes,
        "rules": reflect_rules, "prompts": prompts,
        "readiness": readiness, "comparison": comparison, "scaffold_stats": stats,
        "scaffold": scaffold, "unresolved_rules": curr_point["unresolved"],
        "student_note": note, "conclusion": conclusion_rec,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "processing_ms": (time.perf_counter() - wall_start) * 1000.0,
    }
    t0 = time.perf_counter()
    revision_number = db.save_stage4_revision(record)
    persist_ms = (time.perf_counter() - t0) * 1000.0

    from services.reflection import CHECKLIST_ITEMS

    timings = {"snapshot_ms": snapshot_ms + snapshot_ms2, "history_ms": history_ms,
               "resolution_ms": resolution_ms, "rules_ms": rules_ms,
               "recurring_ms": 0.0, "scaffold_ms": scaffold_ms, "prompts_ms": prompts_ms,
               "readiness_ms": readiness_ms, "compare_ms": compare_ms,
               "persist_ms": persist_ms, "total_ms": record["processing_ms"]}
    gears = _gears(record, timings)
    return {"session_id": session_id, "revision_number": revision_number,
            "stage1_session_id": stage1_session_id, "stage2_session_id": stage2_session_id,
            "stage3_session_id": stage3_session_id,
            "snapshot": snapshot, "history": history, "classes": classes,
            "rules": reflect_rules, "scaffold": scaffold, "prompts": prompts,
            "readiness": readiness, "comparison": comparison, "scaffold_stats": stats,
            "unresolved_rules": curr_point["unresolved"],
            "student_note_stored": bool(note), "conclusion": conclusion_rec,
            "return_links": _return_links(curr_point["unresolved"], stage1_session_id,
                                          stage2_session_id, stage3_session_id),
            "stage4_transparency": gears, "timings": timings,
            "checklist": list(CHECKLIST_ITEMS)}


def _return_links(unresolved: list[str], s1: str | None, s2: str | None, s3: str | None) -> list[dict]:
    """Navigation hints: which stage owns each unresolved issue. Display only."""
    links = []
    seen = set()
    for rid in unresolved:
        stage = reflection_mod.rule_stage(rid)
        sid = {1: s1, 2: s2, 3: s3}.get(stage) if stage else None
        key = (stage, rid)
        if stage in (1, 2, 3) and key not in seen:
            seen.add(key)
            links.append({"stage": stage, "session_id": sid, "rule_id": rid,
                          "action": f"Review Stage {stage}"})
    return links


def _accumulate_stats(history, rules, prompts, revision_number) -> dict:
    counts: dict[str, int] = {}
    shown: list[str] = []
    for rev in history.get("revisions", []):
        for rid in rev.get("unresolved_rules", []):
            counts[rid] = counts.get(rid, 0) + 1
        for p in rev.get("prompts", {}).get("prompts", []):
            if p["prompt_id"] not in shown:
                shown.append(p["prompt_id"])
    for r in rules:
        if r["status"] == "TRIGGERED":
            counts[r["rule_id"]] = counts.get(r["rule_id"], 0) + 1
    for p in prompts.get("prompts", []):
        if p["prompt_id"] not in shown:
            shown.append(p["prompt_id"])
    return {"revision_count": revision_number, "rule_trigger_counts": counts, "prompts_shown": shown}


def _gears(record, timings) -> list[dict]:
    return [
        {"id": "reflection_snapshot", "number": 1, "name": "Cross-Stage Snapshot",
         "purpose": "Gather the latest stored idea, thesis, and outline plus their alignment records. Read-only; no recomputation.",
         "file": "services/reflection.py", "function": "build_consistency_snapshot", "kind": "ours", "status": "COMPLETE",
         "input": {"stage1": record["stage1_session_id"], "stage2": record["stage2_session_id"], "stage3": record["stage3_session_id"]},
         "process": "Read latest stored revisions; keep topic/thesis/parent-child/progression concepts separate.",
         "output": {"stages_present": "see snapshot"}, "timing_ms": timings["snapshot_ms"], "next": "issue_history_aggregation"},
        {"id": "issue_history_aggregation", "number": 2, "name": "Issue History Aggregation",
         "purpose": "Collect every past rule firing into per-rule timelines across all linked sessions.",
         "file": "services/reflection.py", "function": "build_issue_history", "kind": "ours", "status": "COMPLETE",
         "input": {"sessions": [s for s in (record["stage1_session_id"], record["stage2_session_id"], record["stage3_session_id"]) if s]},
         "process": "Per-revision fired sets appended in order; never rewritten.",
         "output": {"total_revisions": "see history"}, "timing_ms": timings["history_ms"], "next": "resolution_classification"},
        {"id": "resolution_classification", "number": 3, "name": "Resolved/Unresolved Classification",
         "purpose": "Classify each known issue as resolved, active, new, recurring, regressed, or stable from real timelines.",
         "file": "services/reflection.py", "function": "classify_history", "kind": "ours", "status": "COMPLETE",
         "input": {"issue_timelines": "see history"},
         "process": "Latest-active vs ever-active; trailing-quiet run for stability; inactive-after-active-then-active for regression.",
         "output": {"resolved": "see classes", "active": "see classes"}, "timing_ms": timings["resolution_ms"], "next": "recurring_detection"},
        {"id": "recurring_detection", "number": 4, "name": "Recurring-Issue Detection",
         "purpose": "Flag issues active now and in at least 2 earlier revisions; trigger counts persisted.",
         "file": "services/reflection.py", "function": "classify_history", "kind": "ours", "status": "COMPLETE",
         "input": {"min_prior": config.STAGE4_RECURRING_MIN_PRIOR},
         "process": "Prior-active count compared to the centralized threshold.",
         "output": {"recurring": "see classes"}, "timing_ms": timings["resolution_ms"], "next": "scaffold_decision"},
        {"id": "scaffold_decision", "number": 5, "name": "Scaffold-Level Decision",
         "purpose": "Decide HIGH/MODERATE/LIGHT/INDEPENDENT from explicit counts. Pedagogical levels, never AI confidence.",
         "file": "services/reflection.py", "function": "decide_scaffold_level", "kind": "ours", "status": "COMPLETE",
         "input": {"scaffold_evidence": (record["scaffold"] or {}).get("evidence", {})},
         "process": (record["scaffold"] or {}).get("decision_rule", ""),
         "output": record["scaffold"], "timing_ms": timings["scaffold_ms"], "next": "prompt_detail_selection"},
        {"id": "prompt_detail_selection", "number": 6, "name": "Prompt Detail Selection",
         "purpose": "Choose the template variant matching the scaffold level (fading is structural: different template IDs).",
         "file": "services/reflection.py", "function": "select_reflection_prompts", "kind": "ours", "status": "COMPLETE",
         "input": {"level": (record["scaffold"] or {}).get("level")},
         "process": "Same issue at different levels selects different template IDs.",
         "output": {"detail_level": (record["prompts"] or {}).get("detail_level")}, "timing_ms": timings["prompts_ms"], "next": "prompt_selection"},
        {"id": "prompt_selection", "number": 7, "name": "Reflection Prompt Selection",
         "purpose": "Map fired REFLECT rules to at most N questions by priority; prefer unshown.",
         "file": "services/reflection.py", "function": "select_reflection_prompts", "kind": "ours", "status": "COMPLETE",
         "input": {"fired": record["unresolved_rules"]},
         "process": "Priority sort, level-capped count, bank mapping.",
         "output": record["prompts"], "timing_ms": timings["prompts_ms"], "next": "reflection_persistence"},
        {"id": "reflection_persistence", "number": 8, "name": "Stage 4 Persistence",
         "purpose": "Append reflection revision; history append-only.",
         "file": "services/db.py", "function": "save_stage4_revision", "kind": "ours", "status": "COMPLETE",
         "input": {"session_id": record["session_id"], "revision_number": record["revision_number"]},
         "process": "SQLite INSERT into stage4_revisions.",
         "output": {"stored": True}, "timing_ms": timings["persist_ms"], "next": None},
    ]
