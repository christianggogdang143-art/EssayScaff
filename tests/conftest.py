"""Global test isolation: no test may touch the production database.

Redirects services.db.db_path to a per-test temp file automatically.
Per-module client fixtures may re-apply the same redirect explicitly;
this only guarantees isolation for tests that never build a client.
"""

import pytest

from services import db


@pytest.fixture(autouse=True)
def _isolate_database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
