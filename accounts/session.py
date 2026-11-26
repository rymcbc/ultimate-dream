"""Session and channel-preference storage (SQLite)."""

from __future__ import annotations

import os
import secrets
import sqlite3
import threading
import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from accounts.oauth import Identity, MissingCredentials, OAuthProvider


def _db_path() -> str:
    """Database path, resolved at call time so tests/deployments can redirect it."""
    return os.getenv("ACCOUNTS_DB_PATH", "accounts.db")


@dataclass(frozen=True)
class Session:
    """User session with preferences."""

    token: str
    gh_id: int
    login: str
    email: str | None
    dm_reachable: bool
    prefs: dict[str, bool]  # discord_dm, webhook, rss


class UnknownToken(Exception):
    """Raised when a session token is not found."""

    pass


class InvalidState(Exception):
    """Raised when OAuth state is invalid or missing."""

    pass


# Default preferences - NO email key
DEFAULT_PREFS = {"discord_dm": False, "webhook": False, "rss": False}

# Thread-local connection for SQLite
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """Get or create a thread-local database connection."""
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(_db_path(), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _init_db(_local.conn)
    return _local.conn


def _init_db(conn: sqlite3.Connection) -> None:
    """Initialize the database schema."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            gh_id INTEGER NOT NULL,
            login TEXT NOT NULL,
            email TEXT,
            dm_reachable INTEGER NOT NULL DEFAULT 0,
            prefs TEXT NOT NULL DEFAULT '{"discord_dm":0,"webhook":0,"rss":0}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS oauth_states (
            state TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


@contextmanager
def _transaction():
    """Context manager for database transactions."""
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def store_state(state: str) -> None:
    """Store an OAuth state for later validation."""
    with _transaction() as conn:
        conn.execute("INSERT INTO oauth_states (state) VALUES (?)", (state,))


def validate_state(state: str) -> bool:
    """Validate and consume an OAuth state. Returns True if valid."""
    with _transaction() as conn:
        cur = conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        return cur.rowcount > 0


def sign_in(provider: OAuthProvider, code: str, state: str) -> str:
    """
    Complete OAuth sign-in. Returns a session token.
    Raises InvalidState if state is invalid, MissingCredentials if provider lacks config.
    """
    if not validate_state(state):
        raise InvalidState("Invalid or missing OAuth state")

    identity = provider.exchange_code(code)

    token = secrets.token_urlsafe(32)
    prefs_json = json.dumps(DEFAULT_PREFS)

    with _transaction() as conn:
        conn.execute(
            """
            INSERT INTO sessions (token, gh_id, login, email, dm_reachable, prefs)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (token, identity["gh_id"], identity["login"], identity["email"], 0, prefs_json),
        )

    return token


def get_session(token: str) -> Session | None:
    """Get a session by token. Returns None if not found."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT token, gh_id, login, email, dm_reachable, prefs FROM sessions WHERE token = ?",
        (token,),
    ).fetchone()

    if not row:
        return None

    import json
    prefs = json.loads(row["prefs"])

    return Session(
        token=row["token"],
        gh_id=row["gh_id"],
        login=row["login"],
        email=row["email"],
        dm_reachable=bool(row["dm_reachable"]),
        prefs=prefs,
    )


def get_prefs(token: str) -> dict[str, bool] | None:
    """Get preferences for a session token. Returns None if token unknown."""
    session = get_session(token)
    if session is None:
        return None
    return session.prefs


def set_prefs(token: str, prefs: dict[str, bool]) -> None:
    """Set preferences for a session token. Raises UnknownToken if not found."""
    session = get_session(token)
    if session is None:
        raise UnknownToken("Unknown session token")

    # Only allow known preference keys
    allowed_keys = {"discord_dm", "webhook", "rss"}
    filtered_prefs = {k: bool(v) for k, v in prefs.items() if k in allowed_keys}

    # Merge with existing prefs to preserve unspecified keys
    merged = {**session.prefs, **filtered_prefs}
    import json
    prefs_json = json.dumps(merged)

    with _transaction() as conn:
        conn.execute(
            "UPDATE sessions SET prefs = ? WHERE token = ?",
            (prefs_json, token),
        )


def set_dm_reachable(token: str, reachable: bool) -> None:
    """Set DM reachable status for a session token."""
    session = get_session(token)
    if session is None:
        raise UnknownToken("Unknown session token")

    with _transaction() as conn:
        conn.execute(
            "UPDATE sessions SET dm_reachable = ? WHERE token = ?",
            (1 if reachable else 0, token),
        )


def close() -> None:
    """Close the database connection for the current thread."""
    if hasattr(_local, "conn"):
        _local.conn.close()
        delattr(_local, "conn")