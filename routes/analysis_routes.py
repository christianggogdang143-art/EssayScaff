"""Flask API routes for Phase 1 live analysis + Phase 1B transparency.

Kept thin: validation here, NLP/rule logic lives in services/ and rules/.

Stage link policy (server-side, not just disabled buttons):
- Stage 2 with a linked Stage 1 session requires that session's latest
  revision to be eligible (readiness.stage2_allowed); otherwise 403.
- Stage 3 with a linked Stage 2 session requires stage3_allowed; else 403.
- Stage 4 with a linked Stage 3 session requires stage4_allowed; else 403.
- Unlinked calls (no upstream session id) remain explicitly allowed as
  the direct/research path: standalone analysis without carried history.
  The student UI always links Continue-ready sessions, so the normal
  student flow always passes readiness server-side; only the explicit
  unlinked research path skips upstream gates (by design, documented here).
"""

from __future__ import annotations

import time

from flask import Blueprint, jsonify, request

import config
from services import analysis_service, db
from services import grammar_service, source_view
from services import lab as lab_service
from services import learning_analytics
from services import stage1 as stage1_service
from services import stage2 as stage2_service
from services import stage3 as stage3_service
from services import stage4 as stage4_service
from services import transparency as transparency_mod

api_bp = Blueprint("api", __name__)


def _check_stage(stage):
    """Shared stage-label validation. Returns (body, status) or None if ok."""
    if stage is not None and (not isinstance(stage, str) or stage not in config.STAGE_VALUES):
        return {"error": "Field 'stage' must be one of: introduction, body, conclusion."}, 400
    return None


def _check_topic_keywords(topic, teacher_keywords):
    """Shared topic/keyword validation. Returns (body, status) or None if ok."""
    if topic is not None and not isinstance(topic, str):
        return {"error": "Field 'topic' must be a string."}, 400
    if teacher_keywords is not None and (
        not isinstance(teacher_keywords, list)
        or not all(isinstance(k, str) for k in teacher_keywords)
    ):
        return {"error": "Field 'teacher_keywords' must be a list of strings."}, 400
    if isinstance(topic, str) and len(topic) > config.TOPIC_MAX_CHARS:
        return {"error": f"Topic too long (max {config.TOPIC_MAX_CHARS} characters)."}, 413
    if isinstance(teacher_keywords, list) and len(teacher_keywords) > config.TEACHER_KEYWORDS_MAX:
        return {"error": f"Too many teacher keywords (max {config.TEACHER_KEYWORDS_MAX})."}, 413
    return None


def _classify_short_input(text: str) -> str | None:
    """Return a reason string if input is too degenerate to analyze."""
    if not text or not text.strip():
        return "empty"
    alpha = [c for c in text if c.isalpha()]
    if len(alpha) == 0:
        return "punctuation-only"
    return None


@api_bp.post("/api/analyze")
def analyze():
    validation_start = time.perf_counter()
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    stage = data.get("stage")
    topic = data.get("topic")
    teacher_keywords = data.get("teacher_keywords")
    if not isinstance(text, str):
        return jsonify({"error": "Field 'text' must be a string."}), 400
    err = _check_stage(stage)
    if err is not None:
        body, status = err
        return jsonify(body), status
    err = _check_topic_keywords(topic, teacher_keywords)
    if err is not None:
        body, status = err
        return jsonify(body), status
    topic = topic.strip() or None if isinstance(topic, str) else None
    if isinstance(teacher_keywords, list):
        teacher_keywords = [k.strip() for k in teacher_keywords if k.strip()] or None

    problem = _classify_short_input(text)
    if problem == "empty":
        return jsonify({"error": "No text provided. Type your writing first."}), 400
    if len(text) > config.MAX_TEXT_CHARS:
        return (
            jsonify({"error": f"Text too long (max {config.MAX_TEXT_CHARS} characters)."}),
            413,
        )
    validation_ms = (time.perf_counter() - validation_start) * 1000.0

    result = analysis_service.analyze(
        text, stage=stage, validation_ms=validation_ms, topic=topic, teacher_keywords=teacher_keywords
    )
    # Server-confirmed analytics only; never affects the analysis itself.
    learning_analytics.log_stage_completion("lab", None, result)

    if problem == "punctuation-only":
        notice = {
            "feedback_id": "FB-0000",
            "category": "General",
            "title": "Not enough writing yet",
            "severity": "info",
            "sentence_number": None,
            "text": text[:120],
            "start": 0,
            "end": len(text),
            "source": "input-validation",
            "reason": "The input contains no words yet, so linguistic analysis is limited.",
            "suggestion": "Keep writing in your own words, then review the feedback.",
        }
        result["feedback"].insert(0, notice)
        result["summary"]["feedback_count"] = len(result["feedback"])
        # Keep the stored backtrace consistent with the live response.
        if result.get("transparency"):
            extra = transparency_mod.build_backtraces(
                [notice],
                result["technical"]["rule_results"],
                result["technical"]["sentences"],
                result["technical"]["tokens"],
                text,
            )
            result["transparency"]["backtraces"] = extra + result["transparency"]["backtraces"]
            result["transparency"]["pipeline"][-2]["output"]["feedback_count"] = len(
                result["feedback"]
            )

    return jsonify(result), 200


@api_bp.get("/api/analysis/<analysis_id>")
def get_analysis(analysis_id: str):
    record = db.get_run(analysis_id)
    if record is None:
        return jsonify({"error": f"No analysis found for id '{analysis_id}'."}), 404
    transparency = record.get("transparency")
    if transparency is None:
        # Phase 1A rows predate transparency: report honestly, invent nothing.
        record["transparency"] = {
            "run_info": "not recorded (analysis predates Transparency Mode)",
            "pipeline": [],
            "execution_log": [],
            "backtraces": [],
            "historical_code_warning": True,
        }
    else:
        transparency["historical_code_warning"] = True
        transparency["code_warning"] = (
            "The source code shown is the current application implementation. "
            "It may differ from the exact source used when this historical "
            "analysis was generated."
        )
    return jsonify(record), 200


@api_bp.get("/api/source")
def get_source():
    """Serve whitelisted implementation source (read-only, inspect-based).

    Query params: file (must exactly match the whitelist), function (optional,
    must exist in that module). Traversal, absolute paths, and non-whitelisted
    files are denied with 403/404 — never touch the filesystem directly.
    """
    file = request.args.get("file", "")
    function = request.args.get("function") or None
    result = source_view.get_source(file, function)
    if not result.get("allowed"):
        error = result.get("error", "Denied.")
        status = 403 if "not allowed" in error or "not an approved" in error else 404
        return jsonify({"allowed": False, "error": error}), status
    result["code_warning"] = (
        "Current application implementation, read from the live module. "
        "For historical analyses it may differ from the original code."
    )
    return jsonify(result), 200


@api_bp.get("/api/health")
def health():
    from services import nlp_service

    try:
        model = nlp_service.get_model_name()
        spacy_ok = True
    except Exception as exc:  # noqa: BLE001
        model = None
        spacy_ok = False
        spacy_error = f"{type(exc).__name__}: {exc}"
    else:
        spacy_error = None
    # get_stats() never initializes LanguageTool; no side effects here.
    return jsonify(
        {
            "status": "ok",
            "spacy_model": model,
            "spacy_ok": spacy_ok,
            "spacy_error": spacy_error,
            "languagetool": grammar_service.get_stats(),
            "debounce_ms": config.DEBOUNCE_MS,
            "phase": "1B",
        }
    )


@api_bp.get("/api/config")
def get_config():
    return jsonify({
        "debounce_ms": config.DEBOUNCE_MS,
        "max_text_chars": config.MAX_TEXT_CHARS,
        "analytics_idle_timeout_ms": config.ANALYTICS_IDLE_TIMEOUT_MS,
        "analytics_flush_ms": config.ANALYTICS_FLUSH_MS,
    })


def _validate_stage1_input(data: dict, noun: str = "idea"):
    """Shared validation for Stage 1/2 text input. Returns (ok, payload/error)."""
    text = data.get("text", "")
    stage = data.get("stage")
    topic = data.get("topic")
    teacher_keywords = data.get("teacher_keywords")
    session_id = data.get("session_id")
    if not isinstance(text, str):
        return False, ({"error": "Field 'text' must be a string."}, 400)
    err = _check_stage(stage)
    if err is not None:
        return False, err
    if session_id is not None and not isinstance(session_id, str):
        return False, ({"error": "Field 'session_id' must be a string."}, 400)
    err = _check_topic_keywords(topic, teacher_keywords)
    if err is not None:
        return False, err
    if not text.strip():
        hint = "Write what you currently think first." if noun == "idea" else "Write your thesis statement first."
        return False, ({"error": f"No {noun} provided. {hint}"}, 400)
    if len(text) > config.MAX_TEXT_CHARS:
        return False, ({"error": f"{noun.capitalize()} too long (max {config.MAX_TEXT_CHARS} characters)."}, 413)
    topic = topic.strip() or None if isinstance(topic, str) else None
    if isinstance(teacher_keywords, list):
        teacher_keywords = [k.strip() for k in teacher_keywords if k.strip()] or None
    return True, {
        "text": text,
        "stage": stage,
        "topic": topic,
        "teacher_keywords": teacher_keywords,
        "session_id": session_id,
    }


@api_bp.post("/api/stage1/analyze")
def stage1_analyze():
    """Analyze one idea revision: existing NLP + scaffolding, persisted."""
    validation_start = time.perf_counter()
    data = request.get_json(silent=True) or {}
    ok, payload = _validate_stage1_input(data)
    if not ok:
        body, status = payload
        return jsonify(body), status
    validation_ms = (time.perf_counter() - validation_start) * 1000.0
    result = stage1_service.analyze_idea(
        payload["text"],
        topic=payload["topic"],
        teacher_keywords=payload["teacher_keywords"],
        stage=payload["stage"],
        session_id=payload["session_id"],
        validation_ms=validation_ms,
    )
    learning_analytics.log_stage_completion("stage1", result["session_id"], result)
    return jsonify(result), 200


@api_bp.get("/api/stage1/session/<session_id>")
def stage1_session(session_id: str):
    """Full revision history for a Stage 1 session (never overwritten)."""
    session = db.get_stage1_session(session_id)
    if not session["revisions"]:
        return jsonify({"error": f"No Stage 1 session found for id '{session_id}'."}), 404
    return jsonify(session), 200


@api_bp.post("/api/stage2/analyze")
def stage2_analyze():
    """Analyze one thesis revision: existing NLP + thesis scaffolding."""
    validation_start = time.perf_counter()
    data = request.get_json(silent=True) or {}
    ok, payload = _validate_stage1_input(data, noun="thesis")
    if not ok:
        body, status = payload
        return jsonify(body), status
    stage1_session_id = data.get("stage1_session_id")
    if stage1_session_id is not None and not isinstance(stage1_session_id, str):
        return jsonify({"error": "Field 'stage1_session_id' must be a string."}), 400
    validation_ms = (time.perf_counter() - validation_start) * 1000.0
    try:
        result = stage2_service.analyze_thesis(
            payload["text"],
            topic=payload["topic"],
            teacher_keywords=payload["teacher_keywords"],
            stage=payload["stage"],
            session_id=payload["session_id"],
            stage1_session_id=stage1_session_id,
            validation_ms=validation_ms,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    learning_analytics.log_stage_completion("stage2", result["session_id"], result)
    return jsonify(result), 200


@api_bp.get("/api/stage2/session/<session_id>")
def stage2_session(session_id: str):
    """Full thesis revision history (append-only)."""
    session = db.get_stage2_session(session_id)
    if not session["revisions"]:
        return jsonify({"error": f"No Stage 2 session found for id '{session_id}'."}), 404
    return jsonify(session), 200


@api_bp.post("/api/stage3/analyze")
def stage3_analyze():
    """Analyze one outline revision: per-level NLP + outline scaffolding."""
    data = request.get_json(silent=True) or {}
    outline = data.get("outline")
    thesis = data.get("thesis")
    topic = data.get("topic")
    teacher_keywords = data.get("teacher_keywords")
    session_id = data.get("session_id")
    stage2_session_id = data.get("stage2_session_id")
    stage1_session_id = data.get("stage1_session_id")
    if not isinstance(outline, list) or not outline:
        return jsonify({"error": "Field 'outline' must be a non-empty list of body points."}), 400
    if len(outline) > config.OUTLINE_MAX_POINTS:
        return jsonify({"error": f"Too many body points (max {config.OUTLINE_MAX_POINTS})."}), 413
    for p in outline:
        if not isinstance(p, dict) or not isinstance(p.get("text"), str):
            return jsonify({"error": "Each body point needs a 'text' string."}), 400
        details = p.get("details", [])
        if not isinstance(details, list) or not all(isinstance(d, str) for d in details):
            return jsonify({"error": "Each point's 'details' must be a list of strings."}), 400
        if len(details) > config.OUTLINE_MAX_DETAILS_PER_POINT:
            return jsonify({"error": f"Too many details per point (max {config.OUTLINE_MAX_DETAILS_PER_POINT})."}), 413
        for txt in [p["text"], *details]:
            if len(txt) > config.MAX_TEXT_CHARS:
                return jsonify({"error": "An outline item is too long."}), 413
    if thesis is not None and not isinstance(thesis, str):
        return jsonify({"error": "Field 'thesis' must be a string."}), 400
    if isinstance(thesis, str) and len(thesis) > config.MAX_TEXT_CHARS:
        return jsonify({"error": f"Thesis too long (max {config.MAX_TEXT_CHARS} characters)."}), 413
    err = _check_topic_keywords(topic, teacher_keywords)
    if err is not None:
        body, status = err
        return jsonify(body), status
    for sid_field, sid in (("session_id", session_id), ("stage2_session_id", stage2_session_id),
                           ("stage1_session_id", stage1_session_id)):
        if sid is not None and not isinstance(sid, str):
            return jsonify({"error": f"Field '{sid_field}' must be a string."}), 400
    try:
        result = stage3_service.analyze_outline(
            outline, thesis=thesis, topic=topic, teacher_keywords=teacher_keywords,
            session_id=session_id, stage2_session_id=stage2_session_id,
            stage1_session_id=stage1_session_id,
        )
    except (ValueError, PermissionError) as exc:
        status = 403 if isinstance(exc, PermissionError) else 400
        return jsonify({"error": str(exc)}), status
    learning_analytics.log_stage_completion("stage3", result["session_id"], result)
    return jsonify(result), 200


@api_bp.post("/api/stage4/reflect")
def stage4_reflect():
    """Run one Stage 4 reflection over linked Stage 1-3 histories."""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    stage1_session_id = data.get("stage1_session_id")
    stage2_session_id = data.get("stage2_session_id")
    stage3_session_id = data.get("stage3_session_id")
    student_note = data.get("student_note")
    conclusion = data.get("conclusion")
    for sid_field, sid in (("session_id", session_id),
                           ("stage1_session_id", stage1_session_id),
                           ("stage2_session_id", stage2_session_id),
                           ("stage3_session_id", stage3_session_id)):
        if sid is not None and not isinstance(sid, str):
            return jsonify({"error": f"Field '{sid_field}' must be a string."}), 400
    if student_note is not None and not isinstance(student_note, str):
        return jsonify({"error": "Field 'student_note' must be a string."}), 400
    if conclusion is not None and not isinstance(conclusion, str):
        return jsonify({"error": "Field 'conclusion' must be a string."}), 400
    try:
        result = stage4_service.analyze_reflection(
            session_id=session_id, stage1_session_id=stage1_session_id,
            stage2_session_id=stage2_session_id, stage3_session_id=stage3_session_id,
            student_note=student_note, conclusion=conclusion,
        )
    except (ValueError, PermissionError) as exc:
        status = 403 if isinstance(exc, PermissionError) else 400
        return jsonify({"error": str(exc)}), status
    learning_analytics.log_stage_completion("stage4", result["session_id"], result)
    return jsonify(result), 200


@api_bp.post("/api/lab/analyze")
def lab_analyze():
    """Analyze one Writing Lab section draft: unchanged NLP + experimental
    LAB_* section rules, append-only essay revision, section readiness."""
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    section = data.get("section")
    topic = data.get("topic")
    teacher_keywords = data.get("teacher_keywords")
    lab_session_id = data.get("lab_session_id")
    stage1_session_id = data.get("stage1_session_id")
    stage2_session_id = data.get("stage2_session_id")
    stage3_session_id = data.get("stage3_session_id")
    stage4_session_id = data.get("stage4_session_id")
    if not isinstance(text, str):
        return jsonify({"error": "Field 'text' must be a string."}), 400
    err = _check_topic_keywords(topic, teacher_keywords)
    if err is not None:
        body, status = err
        return jsonify(body), status
    for sid_field, sid in (("lab_session_id", lab_session_id),
                           ("stage1_session_id", stage1_session_id),
                           ("stage2_session_id", stage2_session_id),
                           ("stage3_session_id", stage3_session_id),
                           ("stage4_session_id", stage4_session_id)):
        if sid is not None and not isinstance(sid, str):
            return jsonify({"error": f"Field '{sid_field}' must be a string."}), 400
    try:
        result = lab_service.analyze_section(
            text, section, topic=topic, teacher_keywords=teacher_keywords,
            lab_session_id=lab_session_id, stage1_session_id=stage1_session_id,
            stage2_session_id=stage2_session_id, stage3_session_id=stage3_session_id,
            stage4_session_id=stage4_session_id,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result), 200


@api_bp.get("/api/lab/session/<session_id>")
def lab_session(session_id: str):
    """Writing Lab session: chain links, essay revisions, essay status."""
    try:
        session = lab_service.get_lab_essay(session_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify(session), 200


@api_bp.get("/api/lab/session/<session_id>/summary")
def lab_summary(session_id: str):
    """Writing Process Summary payload (read-only assembly)."""
    try:
        summary = lab_service.summarize_lab_session(session_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify(summary), 200


@api_bp.get("/api/stage4/session/<session_id>")
def stage4_session(session_id: str):
    """Full reflection revision history (append-only)."""
    session = db.get_stage4_session(session_id)
    if not session["revisions"]:
        return jsonify({"error": f"No Stage 4 session found for id '{session_id}'."}), 404
    return jsonify(session), 200


@api_bp.get("/api/stage3/session/<session_id>")
def stage3_session(session_id: str):
    """Full outline revision history (append-only, order preserved)."""
    session = db.get_stage3_session(session_id)
    if not session["revisions"]:
        return jsonify({"error": f"No Stage 3 session found for id '{session_id}'."}), 404
    return jsonify(session), 200


# ------------------------------------------------ Research interaction analytics
# Read-mostly endpoints over append-only interaction tables. Ingest is
# strictly validated (no essay text, bounded batches); aggregates are
# deterministic counts over stored rows — never scores, never predictions.


@api_bp.post("/api/analytics/events")
def analytics_events():
    """Append client-reported interaction events (single object or batch)."""
    data = request.get_json(silent=True) or {}
    items = data.get("events", [data])
    if not isinstance(items, list) or not items:
        return jsonify({"error": "Provide an event object or a non-empty 'events' list."}), 400
    if len(items) > config.ANALYTICS_MAX_BATCH:
        return jsonify({"error": f"Too many events (max {config.ANALYTICS_MAX_BATCH})."}), 413
    ids = []
    try:
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Each event must be an object.")
            ids.append(learning_analytics.record_event(
                stage=item.get("stage"),
                event_type=item.get("event_type"),
                session_id=item.get("session_id"),
                analysis_id=item.get("analysis_id"),
                stage_session_id=item.get("stage_session_id"),
                revision_number=item.get("revision_number"),
                rule_id=item.get("rule_id"),
                feedback_id=item.get("feedback_id"),
                metadata=item.get("metadata"),
                client_timestamp=item.get("client_timestamp"),
                active_elapsed_ms=item.get("active_elapsed_ms"),
                provenance="client",
            ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"logged": len(ids), "event_ids": ids}), 201


@api_bp.post("/api/analytics/intervals")
def analytics_intervals():
    """Append closed active-time intervals (single object or batch).

    Duplicate intervals (same session/stage/bounds) are ignored, never
    double-counted — safe for client retries and refresh replays.
    """
    data = request.get_json(silent=True) or {}
    items = data.get("intervals", [data])
    if not isinstance(items, list) or not items:
        return jsonify({"error": "Provide an interval object or a non-empty 'intervals' list."}), 400
    if len(items) > config.ANALYTICS_MAX_BATCH:
        return jsonify({"error": f"Too many intervals (max {config.ANALYTICS_MAX_BATCH})."}), 413
    stored = 0
    duplicates = 0
    try:
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Each interval must be an object.")
            row_id = learning_analytics.record_interval(
                session_id=item.get("session_id"),
                stage=item.get("stage"),
                started_at=item.get("started_at"),
                ended_at=item.get("ended_at"),
                active_ms=item.get("active_ms"),
                interval_count=item.get("interval_count", 1),
            )
            if row_id is None:
                duplicates += 1
            else:
                stored += 1
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"stored": stored, "duplicates_ignored": duplicates}), 201


@api_bp.get("/api/analytics/session/<session_id>")
def analytics_session(session_id: str):
    """Deterministic aggregates for a linked stage-session chain.

    Accepts any stage session id; upstream/downstream links are resolved
    server-side. Read-only.
    """
    try:
        chain = learning_analytics.resolve_chain(session_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify(learning_analytics.aggregate(chain)), 200


@api_bp.get("/api/analytics/session/<session_id>/events")
def analytics_session_events(session_id: str):
    """Interaction events across a resolved chain, oldest first (capped)."""
    try:
        chain = learning_analytics.resolve_chain(session_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    rows: list[dict] = []
    for sids in chain["sessions"].values():
        for sid in sids:
            rows.extend(db.get_session_events(sid))
    rows.sort(key=lambda e: (e.get("server_timestamp") or "", e.get("id") or 0))
    return jsonify({"entry_stage": chain["entry_stage"],
                    "count": len(rows),
                    "events": rows[:500]}), 200
