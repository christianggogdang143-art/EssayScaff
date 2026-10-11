"""Phase 7A persistence layer for validation tables.

Thin CRUD over the validation_* tables owned by services/db.py.
References db.db_path() dynamically so tests can redirect the database.
No UPDATE/DELETE for frozen artifacts: datasets mutate only via status
transitions, annotations only via adjudication columns, runs never.
"""

from __future__ import annotations

import json
import sqlite3

from services import db


def _connect():
    db.init_db()
    conn = sqlite3.connect(db.db_path())
    conn.row_factory = sqlite3.Row
    return conn


def insert(table: str, record: dict) -> None:
    conn = _connect()
    try:
        cols = ", ".join(record.keys())
        placeholders = ", ".join("?" for _ in record)
        conn.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
            tuple(record.values()),
        )
        conn.commit()
    finally:
        conn.close()


def get_one(table: str, row_id: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            f"SELECT * FROM {table} WHERE id = ?", (row_id,)
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def list_where(table: str, where: str = "1=1", params: tuple = ()) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(f"SELECT * FROM {table} WHERE {where}", params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update(table: str, row_id: str, fields: dict) -> None:
    """Restricted mutation primitive. Callers enforce append-only policy."""
    conn = _connect()
    try:
        assignments = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE {table} SET {assignments} WHERE id = ?",
            tuple(fields.values()) + (row_id,),
        )
        conn.commit()
    finally:
        conn.close()


def jdump(value) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def jload(raw, default):
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default
