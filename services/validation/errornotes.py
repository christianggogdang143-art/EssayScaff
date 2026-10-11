"""Phase 7B error-category notes: DOCUMENT errors, never fix detectors.

Categories describe failure modes for FUTURE VR-3 consideration.
Recording a category modifies no production code, threshold, or rule.
"""

from __future__ import annotations

from datetime import datetime, timezone

from services.validation import datasets as datasets_mod
from services.validation import runs as runs_mod
from services.validation import store

ERROR_CATEGORIES = (
    "PATTERN_TOO_NARROW",
    "PATTERN_FALSE_POSITIVE",
    "LEXICAL_OVERLAP_LIMITATION",
    "SYNONYM_MISS",
    "THRESHOLD_BOUNDARY",
    "TOPIC_AMBIGUITY",
    "ANNOTATION_AMBIGUITY",
    "OTHER",
)


def add_error_note(run_id: str, sample_id: str, category: str,
                   note: str, analyst: str) -> dict:
    """Attach an analyst's error category to one evaluated sample."""
    run = runs_mod.get_run(run_id)
    if run is None:
        raise datasets_mod.ValidationError(f"Run '{run_id}' not found.")
    if run["status"] != "COMPLETE":
        raise datasets_mod.ValidationError(
            "Error notes require a COMPLETE run.")
    if category not in ERROR_CATEGORIES:
        raise datasets_mod.ValidationError(
            f"Unknown category '{category}'. Allowed: {list(ERROR_CATEGORIES)}.")
    preds = store.list_where(
        "validation_predictions", "run_id = ? AND sample_id = ?",
        (run_id, sample_id))
    if not preds:
        raise datasets_mod.ValidationError(
            f"Sample '{sample_id}' was not evaluated in run '{run_id}'.")
    if not isinstance(analyst, str) or not analyst.strip():
        raise datasets_mod.ValidationError("'analyst' is required.")
    record = {
        "run_id": run_id,
        "sample_id": sample_id,
        "detector_id": run["detector_id"],
        "category": category,
        "note": note or "",
        "analyst": analyst.strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # AUTOINCREMENT id needed back: use a direct insert (store.insert
    # returns no id by design, keeping bulk paths append-only).
    import sqlite3

    from services import db as db_mod
    db_mod.init_db()
    conn = sqlite3.connect(db_mod.db_path())
    try:
        cur = conn.execute(
            "INSERT INTO validation_error_notes "
            "(run_id, sample_id, detector_id, category, note, analyst, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (record["run_id"], record["sample_id"], record["detector_id"],
             record["category"], record["note"], record["analyst"],
             record["created_at"]),
        )
        record["id"] = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return record


def list_error_notes(run_id: str) -> list[dict]:
    rows = store.list_where(
        "validation_error_notes", "run_id = ?", (run_id,))
    return sorted(rows, key=lambda r: r["id"])
