"""Per-test database isolation for the accounts package.

session.py resolves ACCOUNTS_DB_PATH at call time, so pointing the env var at a
fresh file and dropping the thread-local connection gives every test a clean
database. Without this, a second run re-inserts OAuth states that already exist
in the same persistent accounts.db and fails on the PRIMARY KEY.
"""

from __future__ import annotations

import pytest

from accounts import session as session_mod


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch, tmp_path):
    """Give every test its own SQLite file so state never leaks between tests."""
    monkeypatch.setenv("ACCOUNTS_DB_PATH", str(tmp_path / "accounts.db"))
    session_mod.close()
    yield
    session_mod.close()
