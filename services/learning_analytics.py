"""Deterministic learning analytics over stored records.

Data-collection + analytics layer only. This module MUST NOT rerun NLP,
alter stored analysis, or create predictions: every number below is an
aggregate of persisted rows (revision histories, interaction events,
closed time intervals, analysis feedback counts).

Conventions:
- "occurred" for a rule means a stored status of TRIGGERED, ISSUE, or
  OBSERVED (never INACTIVE/SKIPPED). Counts are frequencies, never scores.
- active-time values come from client-measured closed intervals; the
  server only stores and sums them. A null value with a reason means
  "no timing data", never zero.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import config
from services import db

STAGES = ("stage1", "stage2", "stage3", "stage4", "lab")

EVENT_TYPES = frozenset({
    "APP_OPENED",
    "STAGE_ENTERED",
    "STAGE_LEFT",
    "ANALYSIS_REQUESTED",
    "ANALYSIS_COMPLETED",
    "FEEDBACK_DISPLAYED",
    "REVISION_SUBMITTED",
    "READINESS_CHANGED",
    "STAGE_UNLOCKED",
    "CONTINUE_CLICKED",
    "REFLECTION_SUBMITTED",
    "SESSION_PAUSED",
    "SESSION_RESUMED",
    "SESSION_ENDED",
})

# Application/session-level lifecycle events that legitimately occur before
# any writing stage is known (page open) or after it is gone (page hide).
# ONLY these may omit `stage`; every other event type must name its stage.
# This stays strict on purpose: a missing stage on STAGE_ENTERED,
# ANALYSIS_REQUESTED, REVISION_SUBMITTED, etc. is a malformed event, not
# an application-level one.
STAGE_OPTIONAL_EVENTS = frozenset({"APP_OPENED", "SESSION_ENDED"})

# Essay-text keys are never accepted inside event metadata. Raw student
# writing already lives in revision records; events reference it by id.
FORBIDDEN_METADATA_KEYS = frozenset({
    "raw_text", "idea_text", "thesis_text", "thesis_snapshot", "outline",
    "conclusion", "student_note", "normalized_text",
})

# Per-stage readiness contract, read from stored readiness dicts.
# stage4 is terminal: readiness changes are tracked, there is no unlock.
READY_DECISION = {
    "stage1": "READY FOR THESIS FORMULATION",
    "stage2": "READY FOR OUTLINE DEVELOPMENT",
    "stage3": "READY FOR REFLECTION & REVISION",
    "stage4": "COMPLETE",
}
ALLOW_FLAG = {
    "stage1": "stage2_allowed",
    "stage2": "stage3_allowed",
    "stage3": "stage4_allowed",
    "stage4": None,
}

# Display-only grouping of EXISTING rule outputs for the indicator panel.
# Counts of detected conditions — never scores, never grades.
INDICATOR_GROUPS = {
    "thesis_clarity_indicators": (
        "THESIS_002", "THESIS_003", "THESIS_009", "THESIS_004", "THESIS_010",
    ),
    "structural_coherence_indicators": (
        "OUTLINE_003", "OUTLINE_004", "OUTLINE_006", "OUTLINE_007",
        "OUTLINE_009", "OUTLINE_010", "OUTLINE_011",
        "REFLECT_002", "REFLECT_003", "REFLECT_004", "REFLECT_006",
    ),
    "grammar_style_indicators": (
        "MECHANICS_001", "MECHANICS_002", "STYLE_001", "STYLE_002",
    ),
}

OCCURRED = ("TRIGGERED", "ISSUE", "OBSERVED")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Field '{field}' must be an ISO-8601 timestamp string.")
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Field '{field}' must be an ISO-8601 timestamp string.")


def _check_metadata(metadata) -> str:
    if metadata is None:
        return "{}"
    if not isinstance(metadata, dict):
        raise ValueError("Field 'metadata' must be an object.")
    def _walk(obj, path: str = ""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in FORBIDDEN_METADATA_KEYS:
                    raise ValueError(
                        f"Metadata key '{k}' would duplicate stored essay text; "
                        "events must reference analysis/session/revision ids instead.")
                _walk(v, path + "." + str(k))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _walk(v, f"{path}[{i}]")
    _walk(metadata)
    try:
        text = json.dumps(metadata, sort_keys=True, default=str)
    except (TypeError, ValueError):
        raise ValueError("Field 'metadata' must be JSON-serializable.")
    if len(text) > config.ANALYTICS_MAX_METADATA_CHARS:
        raise ValueError(
            f"Field 'metadata' too large (max {config.ANALYTICS_MAX_METADATA_CHARS} chars).")
    return text


def record_event(stage: str, event_type: str, session_id=None, analysis_id=None,
                 stage_session_id=None, revision_number=None, rule_id=None,
                 feedback_id=None, metadata=None, client_timestamp=None,
                 active_elapsed_ms=None, provenance: str = "client") -> int:
    """Validate + append one interaction event. Returns the event row id."""
    if stage is None:
        if event_type not in STAGE_OPTIONAL_EVENTS:
            raise ValueError(
                f"Field 'stage' is required for event_type '{event_type}'; "
                "only application-level events "
                f"({sorted(STAGE_OPTIONAL_EVENTS)}) may omit it.")
    elif stage not in STAGES:
        raise ValueError(
            f"Field 'stage' must be one of {sorted(STAGES)}.")
    if event_type not in EVENT_TYPES:
        raise ValueError(
            f"Field 'event_type' must be one of {sorted(EVENT_TYPES)}.")
    # session_id/analysis_id may both be absent for unattributed client
    # lifecycle events (e.g. APP_OPENED). Aggregates only use attributed
    # rows; unattributed rows remain visible in the raw event log.
    for name, value in (("session_id", session_id), ("analysis_id", analysis_id),
                        ("stage_session_id", stage_session_id),
                        ("rule_id", rule_id), ("feedback_id", feedback_id)):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"Field '{name}' must be a string.")
    if revision_number is not None and (
            not isinstance(revision_number, int) or revision_number < 1):
        raise ValueError("Field 'revision_number' must be a positive integer.")
    if active_elapsed_ms is not None and (
            not isinstance(active_elapsed_ms, int) or active_elapsed_ms < 0):
        raise ValueError("Field 'active_elapsed_ms' must be a non-negative integer.")
    if client_timestamp is not None:
        _parse_ts(client_timestamp, "client_timestamp")
    if provenance not in ("client", "server"):
        raise ValueError("Field 'provenance' must be 'client' or 'server'.")
    return db.log_interaction_event({
        "session_id": session_id,
        "stage": stage,
        "event_type": event_type,
        "analysis_id": analysis_id,
        "stage_session_id": stage_session_id,
        "revision_number": revision_number,
        "rule_id": rule_id,
        "feedback_id": feedback_id,
        "metadata_json": _check_metadata(metadata),
        "client_timestamp": client_timestamp,
        "server_timestamp": _now_iso(),
        "active_elapsed_ms": active_elapsed_ms,
        "provenance": provenance,
    })


def record_interval(session_id: str, stage: str, started_at: str,
                    ended_at: str, active_ms: int,
                    interval_count: int = 1) -> int | None:
    """Validate + append one closed active-time interval.

    Returns the row id, or None when the identical interval was already
    stored (client retry/refresh replay — never double-counted).
    """
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Field 'session_id' must be a non-empty string.")
    if stage not in STAGES:
        raise ValueError(f"Field 'stage' must be one of {sorted(STAGES)}.")
    start = _parse_ts(started_at, "started_at")
    end = _parse_ts(ended_at, "ended_at")
    if end <= start:
        raise ValueError("Field 'ended_at' must be after 'started_at'.")
    if not isinstance(active_ms, int) or active_ms < 0:
        raise ValueError("Field 'active_ms' must be a non-negative integer.")
    wall_ms = (end - start).total_seconds() * 1000.0
    if active_ms > wall_ms + 5000:
        raise ValueError(
            "Field 'active_ms' exceeds the interval wall time: active time "
            "can never be longer than the interval it was measured in.")
    if not isinstance(interval_count, int) or interval_count < 1:
        raise ValueError("Field 'interval_count' must be a positive integer.")
    return db.log_time_interval({
        "session_id": session_id,
        "stage": stage,
        "started_at": started_at,
        "ended_at": ended_at,
        "active_ms": active_ms,
        "interval_count": interval_count,
        "created_at": _now_iso(),
    })


_STAGE_GETTERS = {
    "stage1": db.get_stage1_session,
    "stage2": db.get_stage2_session,
    "stage3": db.get_stage3_session,
    "stage4": db.get_stage4_session,
}

_LINK_COLUMNS = {
    "stage2": ("stage1_session_id",),
    "stage3": ("stage2_session_id", "stage1_session_id"),
    "stage4": ("stage1_session_id", "stage2_session_id", "stage3_session_id"),
}


def resolve_chain(session_id: str) -> dict:
    """Resolve every stage session linked to the given entry-point session.

    Returns {"entry_stage": ..., "sessions": {stage: [session_ids]}}.
    Raises ValueError for unknown ids. Read-only.
    """
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("A session id is required.")
    entry_stage = None
    for stage, getter in _STAGE_GETTERS.items():
        try:
            if getter(session_id)["revision_count"] > 0:
                entry_stage = stage
                break
        except Exception:
            continue
    if entry_stage is None:
        raise ValueError(f"No stage session found for id '{session_id}'.")
    sessions: dict[str, list[str]] = {s: [] for s in ("stage1", "stage2", "stage3", "stage4")}
    sessions[entry_stage].append(session_id)

    def _links_of(stage: str, sid: str) -> dict:
        revs = _STAGE_GETTERS[stage](sid)["revisions"]
        return revs[-1] if revs else {}

    # Forward along stored links from the latest revisions.
    if entry_stage in ("stage1", "stage2", "stage3", "stage4"):
        # General forward walk: for each known session, pull linked ids.
        queue = [(entry_stage, session_id)]
        seen = {(entry_stage, session_id)}
        while queue:
            st, sid = queue.pop(0)
            rev = _links_of(st, sid)
            for col in _LINK_COLUMNS.get(st, ()):
                linked = rev.get(col)
                if not linked:
                    continue
                target = {"stage1_session_id": "stage1", "stage2_session_id": "stage2",
                          "stage3_session_id": "stage3"}[col]
                if linked not in sessions[target]:
                    sessions[target].append(linked)
                if (target, linked) not in seen:
                    seen.add((target, linked))
                    queue.append((target, linked))
    # Backward: sessions in later stages that reference any known session.
    _BACKWARD = (
        ("stage2", "stage2_revisions", ("stage1_session_id",)),
        ("stage3", "stage3_revisions", ("stage2_session_id", "stage1_session_id")),
        ("stage4", "stage4_revisions",
         ("stage1_session_id", "stage2_session_id", "stage3_session_id")),
    )
    for stage, table, cols in _BACKWARD:
        for col in cols:
            for known in (list(sessions["stage1"]) + list(sessions["stage2"])
                          + list(sessions["stage3"])):
                for found in db.find_sessions_by_link(table, col, known):
                    if found not in sessions[stage]:
                        sessions[stage].append(found)
    for stage in sessions:
        sessions[stage] = sorted(set(sessions[stage]))
    return {"entry_stage": entry_stage, "sessions": sessions}


def _revision_points(stage: str, sid: str) -> list[dict]:
    revs = _STAGE_GETTERS[stage](sid)["revisions"]
    points = []
    for r in revs:
        readiness = r.get("readiness", {}) or {}
        fired = r.get("fired_rules", []) or []
        points.append({
            "session_id": sid,
            "revision_number": r.get("revision_number"),
            "created_at": r.get("created_at"),
            "decision": readiness.get("decision"),
            "allowed": readiness.get(ALLOW_FLAG[stage]) if ALLOW_FLAG[stage] else None,
            "fired_rules": list(fired),
            "analysis_id": r.get("analysis_id"),
        })
    return points


def _feedback_count_for(analysis_id) -> int | None:
    if not analysis_id:
        return None
    try:
        import sqlite3

        conn = sqlite3.connect(db.db_path())
        try:
            cur = conn.execute(
                "SELECT feedback_json FROM analysis_runs WHERE id = ?", (analysis_id,))
            row = cur.fetchone()
            if not row or row[0] is None:
                return None
            return len(json.loads(row[0]))
        finally:
            conn.close()
    except Exception:
        return None


def _na(reason: str) -> dict:
    return {"value": None, "status": "N/A", "reason": reason}


def aggregate(chain: dict) -> dict:
    """Deterministic aggregates over resolved sessions. Read-only.

    No NLP, no stored-analysis mutation, no predictions. Frequencies are
    counts of stored conditions — never quality scores.
    """
    sessions = chain["sessions"]
    per_stage: dict = {}
    rule_totals: dict[str, dict] = {}
    total_revisions = 0
    total_server_analyses = 0
    total_client_requests = 0
    total_feedback_displayed = 0
    total_feedback_items_server: int | None = 0
    feedback_server_known = True
    top_stage = None
    top_stage_feedback = -1

    for stage in ("stage1", "stage2", "stage3", "stage4"):
        sids = sessions.get(stage, [])
        points: list[dict] = []
        for sid in sids:
            points.extend(_revision_points(stage, sid))
        points.sort(key=lambda p: (p["created_at"] or "", p["revision_number"] or 0))
        n_rev = len(points)
        total_revisions += n_rev

        # Analyses before first READY decision (server-confirmed).
        ready_at = None
        for i, p in enumerate(points, start=1):
            if p["decision"] == READY_DECISION[stage]:
                ready_at = i
                break

        # Feedback items from stored analyses (server-confirmed).
        fb_items: int | None = 0
        fb_known = True
        for p in points:
            c = _feedback_count_for(p["analysis_id"])
            if c is None:
                fb_known = False
            else:
                fb_items += c
        if not fb_known:
            total_feedback_items_server = None
            feedback_server_known = False
        elif total_feedback_items_server is not None:
            total_feedback_items_server += fb_items

        # Client-reported counts from events.
        ev_requested = ev_displayed = ev_display_items = 0
        for sid in sids:
            for e in db.get_session_events(sid):
                if e.get("stage") != stage:
                    continue
                if e.get("event_type") == "ANALYSIS_REQUESTED":
                    ev_requested += 1
                elif e.get("event_type") == "FEEDBACK_DISPLAYED":
                    ev_displayed += 1
                    try:
                        meta = json.loads(e.get("metadata_json") or "{}")
                        ev_display_items += int(meta.get("feedback_items", 0))
                    except (TypeError, ValueError):
                        pass
        total_client_requests += ev_requested
        total_feedback_displayed += ev_displayed
        if (fb_items is not None and fb_items > 0
                and fb_items > top_stage_feedback):
            top_stage_feedback = fb_items
            top_stage = stage

        fired_here: dict[str, int] = {}
        for p in points:
            for rid in p["fired_rules"]:
                fired_here[rid] = fired_here.get(rid, 0) + 1
                cell = rule_totals.setdefault(rid, {"occurrences": 0, "stages": []})
                cell["occurrences"] += 1
                if stage not in cell["stages"]:
                    cell["stages"].append(stage)

        # Resolved: fired in an earlier revision, absent from the latest,
        # with at least two revisions to compare.
        resolved = []
        if n_rev >= 2:
            latest = set(points[-1]["fired_rules"])
            earlier: set[str] = set()
            for p in points[:-1]:
                earlier.update(p["fired_rules"])
            resolved = sorted(earlier - latest)

        # Active time from closed intervals (client-measured, server-summed).
        intervals: list[dict] = []
        for sid in sids:
            intervals.extend(db.get_session_intervals(sid))
        active_ms = sum(int(i.get("active_ms", 0) or 0) for i in intervals)
        starts = [i.get("started_at") for i in intervals if i.get("started_at")]
        ends = [i.get("ended_at") for i in intervals if i.get("ended_at")]
        if intervals:
            time_block = {
                "active_ms": {"value": active_ms, "status": "OK", "reason": None},
                "interval_count": len(intervals),
                "session_count": len(sids),
                "average_interval_ms": (
                    {"value": active_ms / len(intervals), "status": "OK", "reason": None}),
                "first_activity": min(starts) if starts else None,
                "last_activity": max(ends) if ends else None,
            }
        else:
            time_block = {
                "active_ms": _na("No closed active-time intervals stored for this stage."),
                "interval_count": 0,
                "session_count": len(sids),
                "average_interval_ms": _na("No closed active-time intervals stored for this stage."),
                "first_activity": None,
                "last_activity": None,
            }

        latest = points[-1] if points else {}
        per_stage[stage] = {
            "sessions": sids,
            "revision_count": n_rev,
            "revisions": [
                {"revision_number": p["revision_number"], "created_at": p["created_at"],
                 "decision": p["decision"], "allowed": p["allowed"],
                 "fired_rules": p["fired_rules"], "analysis_id": p["analysis_id"]}
                for p in points
            ],
            "analyses_before_ready": (
                {"value": ready_at, "status": "OK", "reason": None} if ready_at is not None
                else _na("No READY decision in stored revisions.")),
            "server_analyses": n_rev,
            "client_analysis_requests": ev_requested,
            "feedback_items_server": (
                {"value": fb_items, "status": "OK", "reason": None} if fb_known
                else _na("Some revisions lack a stored analysis record.")),
            "feedback_displayed_events": ev_displayed,
            "feedback_displayed_items_client": ev_display_items,
            "rule_occurrences": dict(sorted(fired_here.items())),
            "resolved_rules": resolved,
            "active_time": time_block,
            "stage_progress": {
                "status": (latest.get("decision") if latest else None),
                "allowed": (latest.get("allowed") if latest else None),
                "revision_count": n_rev,
                "ready": (latest.get("decision") == READY_DECISION[stage]) if latest else False,
            },
        }
        total_server_analyses += n_rev

    rule_frequency = [
        {"rule_id": rid, "occurrences": cell["occurrences"], "stages": sorted(cell["stages"])}
        for rid, cell in sorted(rule_totals.items(), key=lambda kv: (-kv[1]["occurrences"], kv[0]))
    ]

    def _group(names: tuple) -> list[dict]:
        return [r for r in rule_frequency if r["rule_id"] in names]

    grouped_ids = {rid for names in INDICATOR_GROUPS.values() for rid in names}
    indicator_groups = {
        "thesis_clarity_indicators": _group(INDICATOR_GROUPS["thesis_clarity_indicators"]),
        "structural_coherence_indicators": _group(INDICATOR_GROUPS["structural_coherence_indicators"]),
        "grammar_style_indicators": _group(INDICATOR_GROUPS["grammar_style_indicators"]),
        "other_indicators": [r for r in rule_frequency if r["rule_id"] not in grouped_ids],
        "note": ("Counts of detected conditions grouped for display. "
                 "These indicators summarize detected conditions and are not "
                 "an overall essay grade."),
    }

    total_active = 0
    total_intervals = 0
    any_time = False
    for stage in ("stage1", "stage2", "stage3", "stage4"):
        block = per_stage[stage]["active_time"]
        if block["active_ms"].get("status") == "OK":
            any_time = True
            total_active += block["active_ms"]["value"] or 0
            total_intervals += block["interval_count"]
    active_time = {
        "stage1_ms": per_stage["stage1"]["active_time"]["active_ms"],
        "stage2_ms": per_stage["stage2"]["active_time"]["active_ms"],
        "stage3_ms": per_stage["stage3"]["active_time"]["active_ms"],
        "stage4_ms": per_stage["stage4"]["active_time"]["active_ms"],
        "total_ms": ({"value": total_active, "status": "OK", "reason": None} if any_time
                     else _na("No closed active-time intervals stored for any stage.")),
        "total_intervals": total_intervals,
    }

    return {
        "entry_stage": chain["entry_stage"],
        "sessions": sessions,
        "active_time": active_time,
        "revisions": {s: per_stage[s]["revision_count"] for s in per_stage},
        "total_revisions": total_revisions,
        "analysis_requests": {
            "server_confirmed": total_server_analyses,
            "client_reported": total_client_requests,
        },
        "feedback_frequency": {
            "displayed_events_client": total_feedback_displayed,
            "displayed_items_client": sum(
                per_stage[s]["feedback_displayed_items_client"] for s in per_stage),
            "items_server": (
                {"value": total_feedback_items_server, "status": "OK", "reason": None}
                if feedback_server_known and total_feedback_items_server is not None
                else _na("Some revisions lack a stored analysis record.")),
            "stage_with_most_feedback": top_stage,
        },
        "rule_frequency": rule_frequency,
        "indicator_groups": indicator_groups,
        "stage_progress": {s: per_stage[s]["stage_progress"] for s in per_stage},
        "per_stage": per_stage,
    }


def log_stage_completion(stage: str, session_id: str, result: dict) -> None:
    """Server-confirmed completion logging for a just-persisted revision.

    Logs ANALYSIS_COMPLETED always; READINESS_CHANGED when the stored
    decision differs from the previous revision; STAGE_UNLOCKED when the
    stage's allowed flag flips false -> true. Never raises: analytics must
    never break analysis.
    """
    try:
        readiness = result.get("readiness", {}) or {}
        decision = readiness.get("decision")
        rev_no = result.get("revision_number")
        fired = result.get("fired_rules") or [
            r.get("rule_id") for r in result.get("rules", [])
            if r.get("status") in OCCURRED and r.get("rule_id")]
        analysis = result.get("analysis", {}) or {}
        prompts = result.get("prompts", {}) or {}
        db.log_interaction_event({
            "session_id": session_id,
            "stage": stage,
            "event_type": "ANALYSIS_COMPLETED",
            "analysis_id": result.get("analysis_id") or analysis.get("analysis_id"),
            "revision_number": rev_no,
            "metadata_json": json.dumps({
                "decision": decision,
                "fired_rules": list(fired),
                "prompts_shown": len(prompts.get("prompts", []) or []),
            }, sort_keys=True),
            "client_timestamp": None,
            "server_timestamp": _now_iso(),
            "active_elapsed_ms": None,
            "provenance": "server",
        })
        analysis_id = result.get("analysis_id") or analysis.get("analysis_id")
        if isinstance(rev_no, int) and rev_no > 1:
            getter = {
                "stage1": db.get_stage1_session, "stage2": db.get_stage2_session,
                "stage3": db.get_stage3_session, "stage4": db.get_stage4_session,
            }[stage]
            revs = getter(session_id)["revisions"]
            prev = revs[-2] if len(revs) >= 2 else {}
            prev_decision = (prev.get("readiness", {}) or {}).get("decision")
            if prev_decision != decision:
                db.log_interaction_event({
                    "session_id": session_id, "stage": stage,
                    "event_type": "READINESS_CHANGED",
                    "analysis_id": analysis_id,
                    "revision_number": rev_no,
                    "metadata_json": json.dumps(
                        {"from": prev_decision, "to": decision}, sort_keys=True),
                    "client_timestamp": None, "server_timestamp": _now_iso(),
                    "active_elapsed_ms": None, "provenance": "server",
                })
            flag = ALLOW_FLAG.get(stage)
            if flag:
                was = bool((prev.get("readiness", {}) or {}).get(flag, False))
                now = bool(readiness.get(flag, False))
                if now and not was:
                    db.log_interaction_event({
                        "session_id": session_id, "stage": stage,
                        "event_type": "STAGE_UNLOCKED",
                        "analysis_id": analysis_id,
                        "revision_number": rev_no,
                        "metadata_json": json.dumps({"flag": flag}, sort_keys=True),
                        "client_timestamp": None, "server_timestamp": _now_iso(),
                        "active_elapsed_ms": None, "provenance": "server",
                    })
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "Analytics completion logging failed; analysis itself unaffected")
