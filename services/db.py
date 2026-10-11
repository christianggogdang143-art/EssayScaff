"""SQLite persistence for analysis runs.

One table is enough for Phase 1. Technical trace + feedback are stored as
JSON text so that, given an analysis ID, we can inspect exactly what
happened.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    id TEXT PRIMARY KEY,
    raw_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    stage TEXT,
    created_at TEXT NOT NULL,
    processing_ms REAL NOT NULL,
    summary_json TEXT NOT NULL,
    feedback_json TEXT NOT NULL,
    technical_json TEXT NOT NULL,
    transparency_json TEXT
);
"""


def _schema_columns(schema_sql: str) -> list[tuple[str, str]]:
    """Extract (name, type) pairs from a CREATE TABLE schema string.

    Parses only the parenthesised column list; table-level constraints
    (UNIQUE(...), PRIMARY KEY, ...) are skipped, never mistaken for columns.
    """
    import re

    try:
        body = schema_sql.split("(", 1)[1].rsplit(")", 1)[0]
    except IndexError:
        return []
    cols = []
    for line in body.splitlines():
        line = line.strip().rstrip(",")
        if not line:
            continue
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s+([A-Za-z]+)", line)
        if m and m.group(1).upper() not in (
            "CONSTRAINT", "PRIMARY", "FOREIGN", "UNIQUE", "CHECK",
        ):
            cols.append((m.group(1), m.group(2).upper()))
    return cols


def _migrate() -> None:
    """Backward-compatible migration: add any columns missing from existing
    tables (derived from the CREATE TABLE schemas above). Old rows keep
    NULL, which readers interpret as 'not recorded'. Never touches data."""
    import logging

    conn = sqlite3.connect(db_path())
    try:
        existing = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table, schema_sql in _TABLE_SCHEMAS.items():
            if table not in existing:
                continue
            have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            for name, coltype in _schema_columns(schema_sql):
                if name not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {coltype}")
                    conn.commit()
    except Exception:
        logging.getLogger(__name__).exception("Stage migration failed")
        raise
    finally:
        conn.close()


def _row_dict(row) -> dict:
    """sqlite3.Row -> plain dict (missing columns simply absent)."""
    try:
        return dict(row)
    except Exception:
        return {}


def _jval(d: dict, key: str, default):
    """json.loads with default on missing/NULL/corrupt values."""
    try:
        v = d.get(key)
        return json.loads(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def db_path() -> Path:
    return Path(__file__).resolve().parent.parent / config.DATABASE_PATH


STAGE1_SCHEMA = """
CREATE TABLE IF NOT EXISTS stage1_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    topic TEXT,
    teacher_keywords_json TEXT,
    idea_text TEXT NOT NULL,
    analysis_id TEXT NOT NULL,
    concepts_json TEXT NOT NULL,
    prompts_json TEXT NOT NULL,
    readiness_json TEXT NOT NULL,
    comparison_json TEXT NOT NULL,
    scaffold_stats_json TEXT NOT NULL,
    word_count INTEGER NOT NULL,
    sentence_count INTEGER NOT NULL,
    topic_similarity REAL,
    topic_classification TEXT,
    fired_rules_json TEXT NOT NULL,
    writing_notes_json TEXT,
    guidance_json TEXT,
    created_at TEXT NOT NULL,
    processing_ms REAL NOT NULL,
    UNIQUE(session_id, revision_number)
);
"""


STAGE2_SCHEMA = """
CREATE TABLE IF NOT EXISTS stage2_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    stage1_session_id TEXT,
    topic TEXT,
    teacher_keywords_json TEXT,
    thesis_text TEXT NOT NULL,
    analysis_id TEXT NOT NULL,
    components_json TEXT NOT NULL,
    alignment_json TEXT NOT NULL,
    prompts_json TEXT NOT NULL,
    readiness_json TEXT NOT NULL,
    comparison_json TEXT NOT NULL,
    scaffold_stats_json TEXT NOT NULL,
    word_count INTEGER NOT NULL,
    fired_rules_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    processing_ms REAL NOT NULL,
    UNIQUE(session_id, revision_number)
);
"""


STAGE4_SCHEMA = """
CREATE TABLE IF NOT EXISTS stage4_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    stage1_session_id TEXT,
    stage2_session_id TEXT,
    stage3_session_id TEXT,
    topic TEXT,
    teacher_keywords_json TEXT,
    snapshot_json TEXT NOT NULL,
    history_json TEXT NOT NULL,
    classes_json TEXT NOT NULL,
    rules_json TEXT NOT NULL,
    scaffold_json TEXT NOT NULL,
    prompts_json TEXT NOT NULL,
    readiness_json TEXT NOT NULL,
    comparison_json TEXT NOT NULL,
    scaffold_stats_json TEXT NOT NULL,
    unresolved_rules_json TEXT NOT NULL,
    student_note TEXT NOT NULL DEFAULT '',
    conclusion_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    processing_ms REAL NOT NULL,
    UNIQUE(session_id, revision_number)
);
"""


STAGE3_SCHEMA = """
CREATE TABLE IF NOT EXISTS stage3_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    revision_number INTEGER NOT NULL,
    stage2_session_id TEXT,
    stage1_session_id TEXT,
    topic TEXT,
    teacher_keywords_json TEXT,
    thesis_snapshot TEXT NOT NULL,
    outline_json TEXT NOT NULL,
    rules_json TEXT NOT NULL,
    prompts_json TEXT NOT NULL,
    readiness_json TEXT NOT NULL,
    comparison_json TEXT NOT NULL,
    scaffold_stats_json TEXT NOT NULL,
    alignments_json TEXT NOT NULL,
    unity_json TEXT NOT NULL,
    progression_json TEXT NOT NULL,
    duplicates_json TEXT NOT NULL,
    coverage_json TEXT NOT NULL,
    fired_rules_json TEXT NOT NULL,
    fired_with_json TEXT NOT NULL,
    provider TEXT,
    created_at TEXT NOT NULL,
    processing_ms REAL NOT NULL,
    UNIQUE(session_id, revision_number)
);
"""


VALIDATION_DATASETS_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_datasets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    detector_id TEXT NOT NULL,
    validation_type TEXT NOT NULL,
    label_schema_json TEXT NOT NULL,
    ruleset_version TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    frozen_at TEXT,
    sample_count INTEGER NOT NULL DEFAULT 0,
    source TEXT,
    dataset_hash TEXT,
    notes TEXT NOT NULL DEFAULT '',
    protocol_version TEXT NOT NULL,
    is_demo INTEGER NOT NULL DEFAULT 0
);
"""


VALIDATION_SAMPLES_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_samples (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    topic TEXT,
    teacher_keywords_json TEXT,
    source TEXT,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL,
    included INTEGER NOT NULL DEFAULT 1,
    exclusion_reason TEXT
);
"""


VALIDATION_ANNOTATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_annotations (
    id TEXT PRIMARY KEY,
    sample_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    detector_id TEXT NOT NULL,
    annotator_id TEXT NOT NULL,
    human_label TEXT NOT NULL,
    confidence TEXT,
    notes TEXT NOT NULL DEFAULT '',
    annotated_at TEXT NOT NULL,
    adjudicated_label TEXT,
    adjudication_notes TEXT,
    adjudicated_at TEXT,
    protocol_version TEXT NOT NULL
);
"""


VALIDATION_PREDICTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_predictions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    sample_id TEXT NOT NULL,
    detector_id TEXT NOT NULL,
    predicted_label TEXT NOT NULL,
    system_positive INTEGER,
    raw_output_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    ruleset_version TEXT NOT NULL,
    config_hash TEXT,
    predicted_at TEXT NOT NULL,
    processing_ms REAL NOT NULL
);
"""


VALIDATION_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_runs (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    dataset_hash TEXT NOT NULL,
    dataset_hash_verified INTEGER NOT NULL DEFAULT 0,
    detector_id TEXT NOT NULL,
    ruleset_version TEXT NOT NULL,
    ruleset_hash TEXT,
    config_hash TEXT,
    snapshot_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    sample_count INTEGER NOT NULL DEFAULT 0,
    excluded_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    metrics_version TEXT NOT NULL,
    environment_json TEXT NOT NULL
);
"""


VALIDATION_METRICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL,
    status TEXT NOT NULL,
    reason TEXT,
    extra_json TEXT
);
"""


VALIDATION_CONFUSION_CELLS_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_confusion_cells (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    human_label TEXT NOT NULL,
    predicted_label TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    sample_ids_json TEXT NOT NULL
);
"""


VALIDATION_ERROR_NOTES_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_error_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    sample_id TEXT NOT NULL,
    detector_id TEXT NOT NULL,
    category TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    analyst TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


INTERACTION_EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS interaction_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    stage TEXT,
    event_type TEXT NOT NULL,
    analysis_id TEXT,
    stage_session_id TEXT,
    revision_number INTEGER,
    rule_id TEXT,
    feedback_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    client_timestamp TEXT,
    server_timestamp TEXT NOT NULL,
    active_elapsed_ms INTEGER,
    provenance TEXT NOT NULL DEFAULT 'client'
    -- NOTE: session_id/analysis_id may both be NULL for unattributed client
    -- lifecycle events (APP_OPENED, STAGE_ENTERED before any analysis).
    -- `stage` is likewise NULL only for application-level lifecycle events
    -- (APP_OPENED, SESSION_ENDED) that occur outside any writing stage;
    -- every stage-specific event still names its stage (enforced in
    -- learning_analytics.record_event, not just by this schema).
    -- Aggregates only use attributed rows; nothing here is FK-constrained,
    -- matching the rest of this database.
);
"""


STAGE_TIME_INTERVALS_SCHEMA = """
CREATE TABLE IF NOT EXISTS stage_time_intervals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    active_ms INTEGER NOT NULL,
    interval_count INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, stage, started_at, ended_at)
    -- NOTE (deferred, documented 2026-10-09): the UNIQUE key dedups
    -- identical replays only. Manually posted OVERLAPPING intervals still
    -- sum naively. Merging overlaps on read was deferred because it would
    -- change research semantics; legitimate clients never overlap (close +
    -- reopen chains bounds). See learning_analytics.aggregate.
);
"""


_TABLE_SCHEMAS = {
    "analysis_runs": SCHEMA,
    "stage1_revisions": STAGE1_SCHEMA,
    "stage2_revisions": STAGE2_SCHEMA,
    "stage3_revisions": STAGE3_SCHEMA,
    "stage4_revisions": STAGE4_SCHEMA,
    "validation_datasets": VALIDATION_DATASETS_SCHEMA,
    "validation_samples": VALIDATION_SAMPLES_SCHEMA,
    "validation_annotations": VALIDATION_ANNOTATIONS_SCHEMA,
    "validation_predictions": VALIDATION_PREDICTIONS_SCHEMA,
    "validation_runs": VALIDATION_RUNS_SCHEMA,
    "validation_metrics": VALIDATION_METRICS_SCHEMA,
    "validation_confusion_cells": VALIDATION_CONFUSION_CELLS_SCHEMA,
    "validation_error_notes": VALIDATION_ERROR_NOTES_SCHEMA,
    "interaction_events": INTERACTION_EVENTS_SCHEMA,
    "stage_time_intervals": STAGE_TIME_INTERVALS_SCHEMA,
}


def _migrate_interaction_stage_nullable() -> None:
    """One-way relaxation: interaction_events.stage becomes nullable so
    application-level lifecycle events (APP_OPENED, SESSION_ENDED) can be
    stored without a writing stage.

    Safe for existing databases: NULL stages were previously rejected at
    ingest, so every stored row already carries a stage and the rebuild
    copies all rows verbatim. No rows are added, removed, or altered —
    only the column constraint is relaxed. Fresh databases already use
    the nullable schema and skip the rebuild (PRAGMA notnull == 0).
    """
    conn = sqlite3.connect(db_path())
    try:
        cols = conn.execute("PRAGMA table_info(interaction_events)").fetchall()
        if not cols:
            return
        stage_col = [c for c in cols if c[1] == "stage"]
        if not stage_col or stage_col[0][3] == 0:
            return
        conn.execute("ALTER TABLE interaction_events RENAME TO interaction_events_legacy")
        conn.execute(INTERACTION_EVENTS_SCHEMA.replace(
            "CREATE TABLE IF NOT EXISTS interaction_events",
            "CREATE TABLE interaction_events"))
        col_names = ", ".join(c[1] for c in cols)
        conn.execute(
            f"INSERT INTO interaction_events ({col_names}) "
            "SELECT " + col_names + " FROM interaction_events_legacy")
        conn.execute("DROP TABLE interaction_events_legacy")
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    conn = sqlite3.connect(db_path())
    try:
        conn.execute(SCHEMA)
        conn.execute(STAGE1_SCHEMA)
        conn.execute(STAGE2_SCHEMA)
        conn.execute(STAGE3_SCHEMA)
        conn.execute(STAGE4_SCHEMA)
        conn.execute(VALIDATION_DATASETS_SCHEMA)
        conn.execute(VALIDATION_SAMPLES_SCHEMA)
        conn.execute(VALIDATION_ANNOTATIONS_SCHEMA)
        conn.execute(VALIDATION_PREDICTIONS_SCHEMA)
        conn.execute(VALIDATION_RUNS_SCHEMA)
        conn.execute(VALIDATION_METRICS_SCHEMA)
        conn.execute(VALIDATION_CONFUSION_CELLS_SCHEMA)
        conn.execute(VALIDATION_ERROR_NOTES_SCHEMA)
        conn.execute(INTERACTION_EVENTS_SCHEMA)
        conn.execute(STAGE_TIME_INTERVALS_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    try:
        _migrate()
    except Exception:  # noqa: BLE001 - migration must never break boot
        import logging

        logging.getLogger(__name__).exception("DB migration failed; schema may be stale")
    try:
        _migrate_interaction_stage_nullable()
    except Exception:  # noqa: BLE001 - migration must never break boot
        import logging

        logging.getLogger(__name__).exception("Stage-nullability migration failed")


def count_runs_for_date(date_prefix: str) -> int:
    """Count runs whose ID starts with RUN-<YYYYMMDD> (for ID sequencing)."""
    init_db()
    conn = sqlite3.connect(db_path())
    try:
        cur = conn.execute(
            "SELECT COUNT(*) FROM analysis_runs WHERE id LIKE ?",
            (f"RUN-{date_prefix}-%",),
        )
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def save_run(record: dict) -> None:
    """Persist one analysis run. Plain INSERT: an ID collision raises
    sqlite3.IntegrityError so the caller can retry with a fresh ID instead
    of silently overwriting history."""
    init_db()
    conn = sqlite3.connect(db_path())
    try:
        conn.execute(
            "INSERT INTO analysis_runs "
            "(id, raw_text, normalized_text, stage, created_at, processing_ms, "
            "summary_json, feedback_json, technical_json, transparency_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record["id"],
                record["raw_text"],
                record["normalized_text"],
                record.get("stage"),
                record["created_at"],
                record["processing_ms"],
                json.dumps(record["summary"]),
                json.dumps(record["feedback"]),
                json.dumps(record["technical"]),
                json.dumps(record.get("transparency"))
                if record.get("transparency") is not None
                else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def update_transparency(analysis_id: str, transparency: dict) -> None:
    """Patch the stored transparency after persistence timing is known."""
    init_db()
    conn = sqlite3.connect(db_path())
    try:
        conn.execute(
            "UPDATE analysis_runs SET transparency_json = ? WHERE id = ?",
            (json.dumps(transparency), analysis_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_run(analysis_id: str) -> dict | None:
    init_db()
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT * FROM analysis_runs WHERE id = ?", (analysis_id,))
        row = cur.fetchone()
        if row is None:
            return None
        transparency = None
        try:
            raw_transparency = row["transparency_json"]
        except (KeyError, IndexError):  # pragma: no cover - old schema
            raw_transparency = None
        if raw_transparency:
            transparency = json.loads(raw_transparency)
        return {
            "id": row["id"],
            "raw_text": row["raw_text"],
            "normalized_text": row["normalized_text"],
            "stage": row["stage"],
            "created_at": row["created_at"],
            "processing_ms": row["processing_ms"],
            "summary": json.loads(row["summary_json"]),
            "feedback": json.loads(row["feedback_json"]),
            "technical": json.loads(row["technical_json"]),
            # Phase 1A rows predate transparency: None means "not recorded",
            # never invented.
            "transparency": transparency,
        }
    finally:
        conn.close()


# Bounded retries for concurrent revision INSERTs (MAX()+1 race).
# A failed INSERT writes nothing (statement atomicity), so retrying with a
# freshly re-read number can never duplicate content. Only the specific
# revision-number collision is retried; every other error (including a
# persistently locked database) still raises after bounded attempts.
REVISION_INSERT_RETRIES = 5


def _is_revision_collision(exc: Exception) -> bool:
    return (
        isinstance(exc, sqlite3.IntegrityError)
        and "UNIQUE constraint failed" in str(exc)
        and "revision_number" in str(exc)
    )


# ------------------------------------------------ Stage 2 revisions
def next_stage2_revision(session_id: str) -> int:
    init_db()
    conn = sqlite3.connect(db_path())
    try:
        cur = conn.execute(
            "SELECT COALESCE(MAX(revision_number), 0) FROM stage2_revisions WHERE session_id = ?",
            (session_id,),
        )
        return int(cur.fetchone()[0]) + 1
    finally:
        conn.close()


def save_stage2_revision(record: dict) -> int:
    """Append-only thesis revision history (UNIQUE pair + MAX()+1).

    Returns the persisted revision number (re-read on collision retry).
    """
    init_db()
    for attempt in range(REVISION_INSERT_RETRIES):
        conn = sqlite3.connect(db_path())
        try:
            conn.execute(
                "INSERT INTO stage2_revisions "
                "(session_id, revision_number, stage1_session_id, topic, teacher_keywords_json, "
                "thesis_text, analysis_id, components_json, alignment_json, prompts_json, "
                "readiness_json, comparison_json, scaffold_stats_json, word_count, "
                "fired_rules_json, created_at, processing_ms) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record["session_id"], record["revision_number"], record.get("stage1_session_id"),
                    record.get("topic"), json.dumps(record.get("teacher_keywords")),
                    record["thesis_text"], record["analysis_id"], json.dumps(record["components"]),
                    json.dumps(record["alignment"]), json.dumps(record["prompts"]),
                    json.dumps(record["readiness"]), json.dumps(record["comparison"]),
                    json.dumps(record["scaffold_stats"]), record["word_count"],
                    json.dumps(record["fired_rules"]), record["created_at"], record["processing_ms"],
                ),
            )
            conn.commit()
            return record["revision_number"]
        except Exception as exc:
            if not _is_revision_collision(exc) or attempt + 1 >= REVISION_INSERT_RETRIES:
                raise
            record["revision_number"] = next_stage2_revision(record["session_id"])
        finally:
            conn.close()
    raise AssertionError("unreachable")  # pragma: no cover - loop always returns or raises


def get_stage2_session(session_id: str) -> dict:
    init_db()
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT * FROM stage2_revisions WHERE session_id = ? ORDER BY revision_number ASC",
            (session_id,),
        )
        revisions = []
        for row in cur.fetchall():
            r = _row_dict(row)
            revisions.append(
                {
                    "session_id": r.get("session_id"), "revision_number": r.get("revision_number"),
                    "stage1_session_id": r.get("stage1_session_id"), "topic": r.get("topic"),
                    "teacher_keywords": _jval(r, "teacher_keywords_json", None),
                    "thesis_text": r.get("thesis_text"), "analysis_id": r.get("analysis_id"),
                    "components": _jval(r, "components_json", {}),
                    "alignment": _jval(r, "alignment_json", {}),
                    "prompts": _jval(r, "prompts_json", {}),
                    "readiness": _jval(r, "readiness_json", {}),
                    "comparison": _jval(r, "comparison_json", {}),
                    "scaffold_stats": _jval(r, "scaffold_stats_json", {}),
                    "word_count": r.get("word_count"),
                    "fired_rules": _jval(r, "fired_rules_json", []),
                    "created_at": r.get("created_at"), "processing_ms": r.get("processing_ms"),
                }
            )
        return {"session_id": session_id, "revision_count": len(revisions), "revisions": revisions}
    finally:
        conn.close()


# ------------------------------------------------ Stage 3 revisions
def next_stage3_revision(session_id: str) -> int:
    init_db()
    conn = sqlite3.connect(db_path())
    try:
        cur = conn.execute(
            "SELECT COALESCE(MAX(revision_number), 0) FROM stage3_revisions WHERE session_id = ?",
            (session_id,),
        )
        return int(cur.fetchone()[0]) + 1
    finally:
        conn.close()


def save_stage3_revision(record: dict) -> int:
    """Append-only outline history (UNIQUE pair + MAX()+1).

    Returns the persisted revision number (re-read on collision retry).
    """
    init_db()
    for attempt in range(REVISION_INSERT_RETRIES):
        conn = sqlite3.connect(db_path())
        try:
            conn.execute(
                "INSERT INTO stage3_revisions "
                "(session_id, revision_number, stage2_session_id, stage1_session_id, topic, "
                "teacher_keywords_json, thesis_snapshot, outline_json, rules_json, prompts_json, "
                "readiness_json, comparison_json, scaffold_stats_json, alignments_json, unity_json, "
                "progression_json, duplicates_json, coverage_json, fired_rules_json, fired_with_json, "
                "provider, created_at, processing_ms) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record["session_id"], record["revision_number"], record.get("stage2_session_id"),
                    record.get("stage1_session_id"), record.get("topic"),
                    json.dumps(record.get("teacher_keywords")), record["thesis_snapshot"],
                    json.dumps(record["outline"]), json.dumps(record["rules"]),
                    json.dumps(record["prompts"]), json.dumps(record["readiness"]),
                    json.dumps(record["comparison"]), json.dumps(record["scaffold_stats"]),
                    json.dumps(record["alignments"]), json.dumps(record["unity"]),
                    json.dumps(record["progression"]), json.dumps(record["duplicates"]),
                    json.dumps(record["coverage"]), json.dumps(record["fired_rules"]),
                    json.dumps(record["fired_with"]), record.get("provider"),
                    record["created_at"], record["processing_ms"],
                ),
            )
            conn.commit()
            return record["revision_number"]
        except Exception as exc:
            if not _is_revision_collision(exc) or attempt + 1 >= REVISION_INSERT_RETRIES:
                raise
            record["revision_number"] = next_stage3_revision(record["session_id"])
        finally:
            conn.close()
    raise AssertionError("unreachable")  # pragma: no cover - loop always returns or raises


def get_stage3_session(session_id: str) -> dict:
    init_db()
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT * FROM stage3_revisions WHERE session_id = ? ORDER BY revision_number ASC",
            (session_id,),
        )
        revisions = []
        for row in cur.fetchall():
            r = _row_dict(row)
            revisions.append(
                {
                    "session_id": r.get("session_id"), "revision_number": r.get("revision_number"),
                    "stage2_session_id": r.get("stage2_session_id"), "stage1_session_id": r.get("stage1_session_id"),
                    "topic": r.get("topic"),
                    "teacher_keywords": _jval(r, "teacher_keywords_json", None),
                    "thesis_snapshot": r.get("thesis_snapshot"),
                    "outline": _jval(r, "outline_json", []),
                    "rules": _jval(r, "rules_json", []),
                    "prompts": _jval(r, "prompts_json", {}),
                    "readiness": _jval(r, "readiness_json", {}),
                    "comparison": _jval(r, "comparison_json", {}),
                    "scaffold_stats": _jval(r, "scaffold_stats_json", {}),
                    "alignments": _jval(r, "alignments_json", {}),
                    "unity": _jval(r, "unity_json", []),
                    "progression": _jval(r, "progression_json", []),
                    "duplicates": _jval(r, "duplicates_json", {}),
                    "coverage": _jval(r, "coverage_json", {}),
                    "fired_rules": _jval(r, "fired_rules_json", []),
                    "fired_with": _jval(r, "fired_with_json", []),
                    "provider": r.get("provider"),
                    "created_at": r.get("created_at"), "processing_ms": r.get("processing_ms"),
                }
            )
        return {"session_id": session_id, "revision_count": len(revisions), "revisions": revisions}
    finally:
        conn.close()


# ------------------------------------------------ Stage 4 revisions
def next_stage4_revision(session_id: str) -> int:
    init_db()
    conn = sqlite3.connect(db_path())
    try:
        cur = conn.execute(
            "SELECT COALESCE(MAX(revision_number), 0) FROM stage4_revisions WHERE session_id = ?",
            (session_id,),
        )
        return int(cur.fetchone()[0]) + 1
    finally:
        conn.close()


def save_stage4_revision(record: dict) -> int:
    """Append-only reflection history (UNIQUE pair + MAX()+1).

    Returns the persisted revision number (re-read on collision retry).
    """
    init_db()
    for attempt in range(REVISION_INSERT_RETRIES):
        conn = sqlite3.connect(db_path())
        try:
            conn.execute(
                "INSERT INTO stage4_revisions "
                "(session_id, revision_number, stage1_session_id, stage2_session_id, "
                "stage3_session_id, topic, teacher_keywords_json, snapshot_json, "
                "history_json, classes_json, rules_json, scaffold_json, prompts_json, "
                "readiness_json, comparison_json, scaffold_stats_json, unresolved_rules_json, "
                "student_note, conclusion_json, created_at, processing_ms) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record["session_id"], record["revision_number"],
                    record.get("stage1_session_id"), record.get("stage2_session_id"),
                    record.get("stage3_session_id"), record.get("topic"),
                    json.dumps(record.get("teacher_keywords")), json.dumps(record["snapshot"]),
                    json.dumps(record["history"]), json.dumps(record["classes"]),
                    json.dumps(record["rules"]), json.dumps(record["scaffold"]),
                    json.dumps(record["prompts"]), json.dumps(record["readiness"]),
                    json.dumps(record["comparison"]), json.dumps(record["scaffold_stats"]),
                    json.dumps(record["unresolved_rules"]), record.get("student_note", ""),
                    json.dumps(record["conclusion"]), record["created_at"],
                    record["processing_ms"],
                ),
            )
            conn.commit()
            return record["revision_number"]
        except Exception as exc:
            if not _is_revision_collision(exc) or attempt + 1 >= REVISION_INSERT_RETRIES:
                raise
            record["revision_number"] = next_stage4_revision(record["session_id"])
        finally:
            conn.close()
    raise AssertionError("unreachable")  # pragma: no cover - loop always returns or raises


def get_stage4_session(session_id: str) -> dict:
    init_db()
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT * FROM stage4_revisions WHERE session_id = ? ORDER BY revision_number ASC",
            (session_id,),
        )
        revisions = []
        for row in cur.fetchall():
            r = _row_dict(row)
            revisions.append(
                {
                    "session_id": r.get("session_id"), "revision_number": r.get("revision_number"),
                    "stage1_session_id": r.get("stage1_session_id"),
                    "stage2_session_id": r.get("stage2_session_id"),
                    "stage3_session_id": r.get("stage3_session_id"),
                    "topic": r.get("topic"),
                    "teacher_keywords": _jval(r, "teacher_keywords_json", None),
                    "snapshot": _jval(r, "snapshot_json", {}),
                    "history": _jval(r, "history_json", {}),
                    "classes": _jval(r, "classes_json", {}),
                    "rules": _jval(r, "rules_json", []),
                    "scaffold": _jval(r, "scaffold_json", {}),
                    "prompts": _jval(r, "prompts_json", {}),
                    "readiness": _jval(r, "readiness_json", {}),
                    "comparison": _jval(r, "comparison_json", {}),
                    "scaffold_stats": _jval(r, "scaffold_stats_json", {}),
                    "unresolved_rules": _jval(r, "unresolved_rules_json", []),
                    "student_note": r.get("student_note", ""),
                    "conclusion": _jval(r, "conclusion_json", {}),
                    "created_at": r.get("created_at"), "processing_ms": r.get("processing_ms"),
                }
            )
        return {"session_id": session_id, "revision_count": len(revisions), "revisions": revisions}
    finally:
        conn.close()


# ------------------------------------------------ Stage 1 revisions
def next_stage1_revision(session_id: str) -> int:
    """Next revision number for a session (1-based, never reused)."""
    init_db()
    conn = sqlite3.connect(db_path())
    try:
        cur = conn.execute(
            "SELECT COALESCE(MAX(revision_number), 0) FROM stage1_revisions WHERE session_id = ?",
            (session_id,),
        )
        return int(cur.fetchone()[0]) + 1
    finally:
        conn.close()


def save_stage1_revision(record: dict) -> int:
    """INSERT a revision. UNIQUE(session_id, revision_number) plus
    MAX()+1 numbering means earlier revisions can never be overwritten.

    Returns the persisted revision number (re-read on collision retry).
    """
    init_db()
    for attempt in range(REVISION_INSERT_RETRIES):
        conn = sqlite3.connect(db_path())
        try:
            conn.execute(
                "INSERT INTO stage1_revisions "
                "(session_id, revision_number, topic, teacher_keywords_json, idea_text, "
                "analysis_id, concepts_json, prompts_json, readiness_json, comparison_json, "
                "scaffold_stats_json, word_count, sentence_count, topic_similarity, "
                "topic_classification, fired_rules_json, writing_notes_json, guidance_json, "
                "created_at, processing_ms) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record["session_id"],
                    record["revision_number"],
                    record.get("topic"),
                    json.dumps(record.get("teacher_keywords")),
                    record["idea_text"],
                    record["analysis_id"],
                    json.dumps(record["concepts"]),
                    json.dumps(record["prompts"]),
                    json.dumps(record["readiness"]),
                    json.dumps(record["comparison"]),
                    json.dumps(record["scaffold_stats"]),
                    record["word_count"],
                    record["sentence_count"],
                    record.get("topic_similarity"),
                    record.get("topic_classification"),
                    json.dumps(record["fired_rules"]),
                    json.dumps(record.get("writing_notes", [])),
                    json.dumps(record.get("guidance")),
                    record["created_at"],
                    record["processing_ms"],
                ),
            )
            conn.commit()
            return record["revision_number"]
        except Exception as exc:
            if not _is_revision_collision(exc) or attempt + 1 >= REVISION_INSERT_RETRIES:
                raise
            record["revision_number"] = next_stage1_revision(record["session_id"])
        finally:
            conn.close()
    raise AssertionError("unreachable")  # pragma: no cover - loop always returns or raises


def _stage1_col(row, name: str, default):
    try:
        value = row[name]
    except (KeyError, IndexError):
        return default
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def log_interaction_event(record: dict) -> int:
    """Append one interaction event. Append-only: no UPDATE/DELETE path exists."""
    init_db()
    conn = sqlite3.connect(db_path())
    try:
        cur = conn.execute(
            "INSERT INTO interaction_events "
            "(session_id, stage, event_type, analysis_id, stage_session_id, "
            "revision_number, rule_id, feedback_id, metadata_json, "
            "client_timestamp, server_timestamp, active_elapsed_ms, provenance) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                record.get("session_id"),
                record["stage"],
                record["event_type"],
                record.get("analysis_id"),
                record.get("stage_session_id"),
                record.get("revision_number"),
                record.get("rule_id"),
                record.get("feedback_id"),
                record.get("metadata_json", "{}"),
                record.get("client_timestamp"),
                record["server_timestamp"],
                record.get("active_elapsed_ms"),
                record.get("provenance", "client"),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def log_time_interval(record: dict) -> int | None:
    """Append one closed active-time interval. INSERT OR IGNORE makes client
    retries/refresh replays idempotent: a duplicate returns None instead of
    double-counting active time."""
    init_db()
    conn = sqlite3.connect(db_path())
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO stage_time_intervals "
            "(session_id, stage, started_at, ended_at, active_ms, "
            "interval_count, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                record["session_id"],
                record["stage"],
                record["started_at"],
                record["ended_at"],
                record["active_ms"],
                record.get("interval_count", 1),
                record["created_at"],
            ),
        )
        conn.commit()
        return int(cur.lastrowid) if cur.rowcount else None
    finally:
        conn.close()


def get_session_events(session_id: str, limit: int = 500) -> list[dict]:
    """Interaction events for one stage session, oldest first (read-only)."""
    init_db()
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT * FROM interaction_events WHERE session_id = ? "
            "ORDER BY id ASC LIMIT ?",
            (session_id, limit),
        )
        return [_row_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_session_intervals(session_id: str) -> list[dict]:
    """Closed active-time intervals for one stage session (read-only)."""
    init_db()
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT * FROM stage_time_intervals WHERE session_id = ? "
            "ORDER BY started_at ASC",
            (session_id,),
        )
        return [_row_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def find_sessions_by_link(table: str, link_column: str, link_id: str) -> list[str]:
    """Stage session IDs in one table whose revisions reference a linked
    upstream session. Used only to resolve an analytics chain from any
    entry-point session. Both names are restricted to a fixed allowlist
    (never raw SQL): stage1_revisions has no upstream link column.
    """
    allowed = {
        "stage2_revisions": ("stage1_session_id",),
        "stage3_revisions": ("stage2_session_id", "stage1_session_id"),
        "stage4_revisions": ("stage1_session_id", "stage2_session_id", "stage3_session_id"),
    }
    if table not in allowed or link_column not in allowed[table]:
        return []
    init_db()
    conn = sqlite3.connect(db_path())
    try:
        cur = conn.execute(
            f"SELECT DISTINCT session_id FROM {table} WHERE {link_column} = ?",
            (link_id,),
        )
        return sorted({r[0] for r in cur.fetchall() if r[0]})
    finally:
        conn.close()


def get_stage1_session(session_id: str) -> dict:
    """Full revision history for a session, oldest first."""
    init_db()
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT * FROM stage1_revisions WHERE session_id = ? ORDER BY revision_number ASC",
            (session_id,),
        )
        revisions = []
        for row in cur.fetchall():
            revisions.append(
                {
                    "session_id": row["session_id"],
                    "revision_number": row["revision_number"],
                    "topic": row["topic"],
                    "teacher_keywords": json.loads(row["teacher_keywords_json"] or "null"),
                    "idea_text": row["idea_text"],
                    "analysis_id": row["analysis_id"],
                    "concepts": json.loads(row["concepts_json"]),
                    "prompts": json.loads(row["prompts_json"]),
                    "readiness": json.loads(row["readiness_json"]),
                    "comparison": json.loads(row["comparison_json"]),
                    "scaffold_stats": json.loads(row["scaffold_stats_json"]),
                    "word_count": row["word_count"],
                    "sentence_count": row["sentence_count"],
                    "topic_similarity": row["topic_similarity"],
                    "topic_classification": row["topic_classification"],
                    "fired_rules": json.loads(row["fired_rules_json"]),
                    "writing_notes": _stage1_col(row, "writing_notes_json", []),
                    "guidance": _stage1_col(row, "guidance_json", None),
                    "created_at": row["created_at"],
                    "processing_ms": row["processing_ms"],
                }
            )
        return {"session_id": session_id, "revision_count": len(revisions), "revisions": revisions}
    finally:
        conn.close()
