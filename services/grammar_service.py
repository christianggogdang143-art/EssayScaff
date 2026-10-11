"""LanguageTool grammar analysis wrapper.

Uses language-tool-python locally. Never fabricates results: if the
LanguageTool backend cannot start, returns status 'unavailable' with the
real error message and the rest of the pipeline still works.
Never auto-applies corrections.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import config

_tool = None
_tool_error: str | None = None
# Lifecycle instrumentation (all measured, never fabricated):
# init = one-time local server boot; check = per-analysis work.
_init_ms: float | None = None
_init_at: str | None = None
_check_count = 0
_last_check_ms: float | None = None


def _resolve_jar_dir() -> str | None:
    """Find the real local LanguageTool install (honest local reuse).

    Prefers config.LANGUAGETOOL_JAR_DIR, else the newest `LanguageTool*`
    directory in language-tool-python's cache (~/.cache/language_tool_python).
    Returns None when nothing is installed (caller then reports unavailable).
    """
    if config.LANGUAGETOOL_JAR_DIR:
        return config.LANGUAGETOOL_JAR_DIR
    cache = Path.home() / ".cache" / "language_tool_python"
    candidates = sorted(
        (p for p in cache.glob("LanguageTool*") if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
    )
    if candidates and (candidates[-1] / "languagetool-server.jar").exists():
        return str(candidates[-1])
    return None


def _get_tool():
    """Return the SHARED LanguageTool instance (one Java process per app).

    Initialized lazily on first analysis (or by prewarm at startup), then
    reused for all later requests. Never one process per request.
    """
    global _tool, _tool_error, _init_ms, _init_at
    if _tool is not None:
        return _tool
    from datetime import datetime, timezone

    t0 = time.perf_counter()
    try:
        jar_dir = _resolve_jar_dir()
        if jar_dir:
            # Use the genuine local install; prevents re-downloading the
            # snapshot on every process start (see config.py note).
            os.environ.setdefault("LTP_JAR_DIR_PATH", jar_dir)
        import language_tool_python

        _tool = language_tool_python.LanguageTool(config.LANGUAGETOOL_LANG)
        _tool_error = None
        _init_ms = (time.perf_counter() - t0) * 1000.0
        _init_at = datetime.now(timezone.utc).isoformat()
    except Exception as exc:  # noqa: BLE001 - must surface the real error
        _tool = None
        _tool_error = f"{type(exc).__name__}: {exc}"
        _init_ms = None
    return _tool


def prewarm() -> None:
    """Initialize the shared instance now (safe to call at startup).

    Runs in a daemon thread from app.py so boot never blocks and never
    fails when LanguageTool is unavailable.
    """
    import threading

    thread = threading.Thread(target=_get_tool, name="lt-prewarm", daemon=True)
    thread.start()


def get_stats() -> dict:
    """Lifecycle stats WITHOUT triggering initialization (safe for /health)."""
    return {
        "initialized": _tool is not None,
        "reused": _check_count > 0 and _tool is not None,
        "init_ms": _init_ms,
        "init_at": _init_at,
        "check_count": _check_count,
        "last_check_ms": _last_check_ms,
        "error": _tool_error if _tool is None else None,
    }


def check_grammar(raw_text: str, sentences: list[dict]) -> dict:
    """Run LanguageTool on the raw text.

    Returns {status, issues, processing_ms, error?}.
    status is 'available' or 'unavailable'.
    """
    global _check_count, _last_check_ms
    already_initialized = _tool is not None
    t0 = time.perf_counter()
    tool = _get_tool()
    init_happened_here = (not already_initialized) and (tool is not None)
    check_start = time.perf_counter()
    if tool is None:
        return {
            "status": "unavailable",
            "issues": [],
            "processing_ms": (time.perf_counter() - t0) * 1000.0,
            "init_ms": None,
            "check_ms": (time.perf_counter() - check_start) * 1000.0,
            "cold_init_in_this_call": False,
            "error": _tool_error or "LanguageTool could not be started.",
        }
    try:
        matches = tool.check(raw_text)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unavailable",
            "issues": [],
            "processing_ms": (time.perf_counter() - t0) * 1000.0,
            "init_ms": None,
            "check_ms": (time.perf_counter() - check_start) * 1000.0,
            "cold_init_in_this_call": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    # Coordinate system: spaCy sentences use newline-unified coordinates
    # (CRLF/CR -> LF, same transform as nlp_service), but LanguageTool
    # checks the true raw text. Map every raw offset deterministically into
    # unified coordinates so issue offsets, sentence links, and matched
    # slices agree with the rest of the pipeline. Only CR characters that
    # are part of CRLF pairs shrink the text; lone CR becomes LF in place.
    unified = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    removed = [0] * (len(raw_text) + 1)
    for i, ch in enumerate(raw_text):
        removed[i + 1] = removed[i] + (
            1 if (ch == "\r" and raw_text[i + 1 : i + 2] == "\n") else 0)

    def to_unified(raw_offset: int) -> int:
        raw_offset = max(0, min(raw_offset, len(raw_text)))
        return raw_offset - removed[raw_offset]

    def sentence_of(offset: int):
        for s in sentences:
            if s["start"] <= offset < s["end"]:
                return s["number"]
        return None

    issues = []
    dropped_matches = 0
    for m in matches:
        try:
            # language_tool_python.Match uses snake_case attributes
            # (rule_id, error_length, matched_text, ...). Read them exactly;
            # never invent values when an attribute is missing.
            category = getattr(m, "category", None)
            rule_id = getattr(m, "rule_id", None)
            message = getattr(m, "message", None)
            raw_offset = int(getattr(m, "offset", 0) or 0)
            raw_length = int(getattr(m, "error_length", 0) or 0)
            matched = getattr(m, "matched_text", None)
            replacements = list(getattr(m, "replacements", []) or [])[:5]
        except Exception:  # noqa: BLE001 - defensive, keep pipeline alive
            dropped_matches += 1
            continue
        offset = to_unified(raw_offset)
        length = to_unified(raw_offset + raw_length) - offset
        if not matched:
            matched = unified[offset : offset + length] if length else ""
        matched_text = matched
        issues.append(
            {
                "rule_id": rule_id,
                "category": str(category) if category is not None else None,
                "message": message,
                "matched_text": matched_text,
                "offset": offset,
                "length": length,
                "sentence": sentence_of(offset),
                "replacements": replacements,
            }
        )
    check_ms = (time.perf_counter() - check_start) * 1000.0
    _check_count += 1
    _last_check_ms = check_ms
    if dropped_matches:
        import logging

        logging.getLogger(__name__).warning(
            "Dropped %d malformed LanguageTool match(es)", dropped_matches
        )
    return {
        "status": "available",
        "issues": issues,
        "coordinate_system": ("newline-unified (CRLF/CR -> LF, same transform "
                              "as the spaCy parse); offsets index the unified "
                              "text, identical to raw-text offsets when the "
                              "input has no carriage returns."),
        "dropped_matches": dropped_matches,
        "processing_ms": (time.perf_counter() - t0) * 1000.0,
        # Cold vs warm, measured: init cost only when the server booted here.
        "init_ms": _init_ms if init_happened_here else None,
        "check_ms": check_ms,
        "cold_init_in_this_call": init_happened_here,
    }
