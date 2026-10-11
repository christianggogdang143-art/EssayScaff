"""F-03 regression: concurrent revision writes must not 500, duplicate,
overwrite, or disorder revision numbers.

Drives the REAL Flask app (per-thread test clients) against the isolated
tmp database. A threading.Barrier forces near-simultaneous INSERTs to
exercise the MAX()+1 race that previously raised IntegrityError → 500.
"""

import threading

import pytest

from app import create_app
from services import db

IDEA = ("Climate change affects crop production because extreme temperatures "
        "and irregular rainfall create difficulties for farmers.")


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    application = create_app(prewarm=False)
    application.config.update(TESTING=True)
    return application


def _post(client, session_id, text):
    return client.post("/api/stage1/analyze", json={"text": text, "session_id": session_id})


def test_concurrent_same_session_no_500(app_client):
    """N simultaneous revisions on one session: all succeed, numbers unique+ordered."""
    N = 8
    seed = app_client.test_client().post(
        "/api/stage1/analyze", json={"text": IDEA}).get_json()
    sid = seed["session_id"]
    barrier = threading.Barrier(N)
    results = [None] * N

    def worker(i):
        c = app_client.test_client()
        barrier.wait(timeout=30)
        try:
            r = _post(c, sid, f"{IDEA} Concurrent variant {i}.")
            results[i] = (r.status_code, r.get_json().get("revision_number"))
        except Exception as exc:  # noqa: BLE001 - record, do not hide
            results[i] = ("EXC", repr(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert all(r is not None for r in results), f"thread died: {results}"
    codes = [s for s, _ in results]
    assert all(s == 200 for s in codes), f"non-200 under concurrency: {results}"
    numbers = sorted(n for _, n in results)
    assert numbers == list(range(2, 2 + N)), f"numbers not unique/ordered: {results}"
    # Stored history matches exactly what was reported (no overwrite).
    session = app_client.test_client().get(f"/api/stage1/session/{sid}").get_json()
    stored = sorted(r["revision_number"] for r in session["revisions"])
    assert stored == list(range(1, 2 + N)), stored
    assert len(session["revisions"]) == 1 + N


def test_concurrent_distinct_content_no_duplicates(app_client):
    """Retry path must persist each revision once with distinct content intact."""
    N = 6
    seed = app_client.test_client().post(
        "/api/stage1/analyze", json={"text": IDEA}).get_json()
    sid = seed["session_id"]
    barrier = threading.Barrier(N)
    bodies = [None] * N

    def worker(i):
        c = app_client.test_client()
        barrier.wait(timeout=30)
        r = _post(c, sid, f"{IDEA} Unique marker ALPHA-{i}-OMEGA.")
        bodies[i] = r.get_json()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    session = app_client.test_client().get(f"/api/stage1/session/{sid}").get_json()
    texts = [r["idea_text"] for r in session["revisions"][1:]]
    assert len(texts) == N, texts
    for i in range(N):
        assert sum(f"ALPHA-{i}-OMEGA" in t for t in texts) == 1, f"marker {i} duplicated/lost"


def test_stale_number_bumped_not_failed(tmp_path, monkeypatch):
    """Deterministic retry proof: a stale revision number is re-read, not fatal."""
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    db.init_db()
    base = {
        "session_id": "SES-Y", "topic": None, "teacher_keywords": None,
        "idea_text": "x", "analysis_id": "a", "concepts": {}, "prompts": {},
        "readiness": {}, "comparison": {}, "scaffold_stats": {}, "word_count": 1,
        "sentence_count": 1, "topic_similarity": None, "topic_classification": None,
        "fired_rules": [], "writing_notes": [], "guidance": None,
        "created_at": "t", "processing_ms": 0.0,
    }
    assert db.save_stage1_revision(dict(base, revision_number=1)) == 1
    assert db.save_stage1_revision(dict(base, revision_number=2)) == 2
    # Simulate a raced caller holding stale number 3 after 3 already landed.
    assert db.save_stage1_revision(dict(base, revision_number=3)) == 3
    assert db.save_stage1_revision(dict(base, revision_number=3)) == 4
    session = db.get_stage1_session("SES-Y")
    assert [r["revision_number"] for r in session["revisions"]] == [1, 2, 3, 4]


def test_unrelated_integrity_errors_still_raise(tmp_path, monkeypatch):
    """Only revision-number collisions are retried; other integrity errors surface."""
    import sqlite3

    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    db.init_db()
    rec = {
        "session_id": "SES-X", "revision_number": 1,
        "topic": None, "teacher_keywords": None, "idea_text": "x",
        "analysis_id": "a", "concepts": {}, "prompts": {}, "readiness": {},
        "comparison": {}, "scaffold_stats": {}, "word_count": 1,
        "sentence_count": 1, "topic_similarity": None, "topic_classification": None,
        "fired_rules": [], "writing_notes": [], "guidance": None,
        "created_at": "t", "processing_ms": 0.0,
    }
    assert db.save_stage1_revision(rec) == 1
    # Violate a DIFFERENT constraint surface: NULL into NOT NULL idea_text.
    bad = dict(rec, revision_number=2, idea_text=None)
    with pytest.raises(sqlite3.IntegrityError):
        db.save_stage1_revision(bad)
