"""Delivery implementation for fanout notification system.

Implements idempotent delivery with status tracking, private delivery log,
and public chain with only hashes.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any


# Valid channels (email is not shipped - deferred to owner)
SHIPPING_CHANNELS = ("discord_dm", "webhook", "rss")

# Valid status transitions
VALID_STATUSES = ("queued", "sending", "sent", "failed", "suppressed", "bounced")

# Valid transitions: from -> allowed next statuses
STATUS_TRANSITIONS = {
    "queued": ("sending", "suppressed"),
    "sending": ("sent", "failed", "bounced"),
    "sent": (),
    "failed": ("sending",),  # retry
    "suppressed": (),
    "bounced": ("sending",),  # retry
}


def recipient_hash(gh_id: int) -> str:
    """Hash of the numeric GitHub id only (no email - dictionary attackable).
    
    Returns first 16 chars of sha256 for compactness in keys.
    """
    return hashlib.sha256(str(gh_id).encode("utf-8")).hexdigest()[:16]


def make_idempotency_key(decision_id: str, gh_id: int, channel: str) -> str:
    """Create idempotency key: decision_id:recipient_hash:channel."""
    return f"{decision_id}:{recipient_hash(gh_id)}:{channel}"


def _hash_delivered_ref(ref: str) -> str:
    """Hash a delivered_ref for public chain storage."""
    return hashlib.sha256(ref.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class PrivateLogEntry:
    """Private delivery log entry - holds real addresses, never in public chain."""
    decision_id: str
    notification_id: str
    idempotency_key: str
    gh_id: int
    channel: str
    address: str  # real email/webhook URL/RSS feed URL/Discord user id
    status: str
    attempt: int
    sent_at: str | None = None
    delivered_ref: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "notification_id": self.notification_id,
            "idempotency_key": self.idempotency_key,
            "gh_id": self.gh_id,
            "channel": self.channel,
            "address": self.address,
            "status": self.status,
            "attempt": self.attempt,
            "sent_at": self.sent_at,
            "delivered_ref": self.delivered_ref,
            "error": self.error,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class PublicChainEntry:
    """Public chain entry - holds only hashes, no PII."""
    decision_id: str
    notification_id: str
    idempotency_key: str
    recipient_hash: str  # hash of gh_id only
    channel: str
    status: str
    attempt: int
    sent_at: str | None = None
    delivered_ref_hash: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "notification_id": self.notification_id,
            "idempotency_key": self.idempotency_key,
            "recipient_hash": self.recipient_hash,
            "channel": self.channel,
            "status": self.status,
            "attempt": self.attempt,
            "sent_at": self.sent_at,
            "delivered_ref_hash": self.delivered_ref_hash,
            "created_at": self.created_at,
        }


def _row_to(cls, row):
    """Build a frozen dataclass from a sqlite row.

    The tables carry an autoincrement `id` that the dataclasses deliberately do
    not model, so passing the row through **dict would raise TypeError.
    """
    allowed = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in dict(row).items() if k in allowed})


class NotificationStore:
    """SQLite-backed notification store with private delivery log and public chain."""
    
    def __init__(self, db_path: str | Path):
        # Use a file-based DB for :memory: to share across connections
        if str(db_path) == ":memory:":
            self.db_path = Path(":memory:")
            self._shared_conn = None
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._shared_conn = None
        self._init_db()
    
    def _get_conn(self):
        """Get a connection, sharing for in-memory DBs."""
        if str(self.db_path) == ":memory:":
            if self._shared_conn is None:
                self._shared_conn = sqlite3.connect(":memory:")
                self._shared_conn.row_factory = sqlite3.Row
                # Initialize tables on shared connection
                self._init_db_on_conn(self._shared_conn)
            return self._shared_conn
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn
    
    def _init_db_on_conn(self, conn) -> None:
        """Initialize tables on a specific connection."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                notification_id TEXT PRIMARY KEY,
                idempotency_key TEXT UNIQUE NOT NULL,
                decision_id TEXT NOT NULL,
                gh_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                payload_ref TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                attempt INTEGER NOT NULL DEFAULT 0,
                sent_at TEXT,
                delivered_ref TEXT,
                created_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_notifications_decision 
            ON notifications(decision_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_notifications_idempotency 
            ON notifications(idempotency_key)
        """)
        
        # Private delivery log - holds real addresses
        conn.execute("""
            CREATE TABLE IF NOT EXISTS delivery_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id TEXT NOT NULL,
                notification_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                gh_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                address TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                sent_at TEXT,
                delivered_ref TEXT,
                error TEXT,
                created_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_delivery_log_decision 
            ON delivery_log(decision_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_delivery_log_idempotency 
            ON delivery_log(idempotency_key)
        """)
        
        # Public chain - holds only hashes
        conn.execute("""
            CREATE TABLE IF NOT EXISTS public_chain (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id TEXT NOT NULL,
                notification_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                recipient_hash TEXT NOT NULL,
                channel TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                sent_at TEXT,
                delivered_ref_hash TEXT,
                created_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_public_chain_decision 
            ON public_chain(decision_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_public_chain_idempotency 
            ON public_chain(idempotency_key)
        """)
    
    def _init_db(self) -> None:
        conn = self._get_conn()
        self._init_db_on_conn(conn)
        if str(self.db_path) != ":memory:":
            conn.close()

    @contextmanager
    def _conn(self, write: bool = False):
        """Every statement goes through here.

        sqlite3.connect(":memory:") hands back a FRESH, empty database on every
        call, so a method that opens its own connection sees no tables at all
        ("no such table: notifications"). _get_conn() returns one shared
        connection for :memory: and a new one for a file; this wrapper commits
        writes and closes file connections without ever closing the shared one.
        """
        conn = self._get_conn()
        try:
            yield conn
            if write and str(self.db_path) != ":memory:":
                conn.commit()
        finally:
            if str(self.db_path) != ":memory:":
                conn.close()
    
    def get_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        """Get notification by idempotency key (for idempotency check).
        
        Returns dict with notification data or None if not found.
        """
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM notifications WHERE idempotency_key = ?", (key,)
            ).fetchone()
            if not row:
                return None
            return dict(row)
        finally:
            if str(self.db_path) != ":memory:":
                conn.close()
    
    def insert_queued(
        self,
        notification_id: str,
        idempotency_key: str,
        decision_id: str,
        gh_id: int,
        channel: str,
        payload_ref: str,
        address: str,
        status: str = "queued",
    ) -> None:
        """Insert a new queued notification with its delivery address (private)."""
        now = time.time()
        conn = self._get_conn()
        try:
            # Main notifications table
            conn.execute("""
                INSERT INTO notifications 
                (notification_id, idempotency_key, decision_id, gh_id, channel,
                 payload_ref, status, attempt, sent_at, delivered_ref, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                notification_id,
                idempotency_key,
                decision_id,
                gh_id,
                channel,
                payload_ref,
                status,
                0,
                None,
                None,
                now,
            ))
            # Private delivery log
            conn.execute("""
                INSERT INTO delivery_log
                (decision_id, notification_id, idempotency_key, gh_id, channel,
                 address, status, attempt, sent_at, delivered_ref, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                decision_id,
                notification_id,
                idempotency_key,
                gh_id,
                channel,
                address,
                status,
                0,
                None,
                None,
                None,
                now,
            ))
            # Public chain entry
            conn.execute("""
                INSERT INTO public_chain
                (decision_id, notification_id, idempotency_key, recipient_hash,
                 channel, status, attempt, sent_at, delivered_ref_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                decision_id,
                notification_id,
                idempotency_key,
                recipient_hash(gh_id),
                channel,
                status,
                0,
                None,
                None,
                now,
            ))
            if str(self.db_path) != ":memory:":
                conn.commit()
        finally:
            if str(self.db_path) != ":memory:":
                conn.close()
    
    def update_status(
        self,
        idempotency_key: str,
        new_status: str,
        attempt: int | None = None,
        sent_at: str | None = None,
        delivered_ref: str | None = None,
        error: str | None = None,
    ) -> bool:
        """Update notification status with validation.
        
        Returns True if row was updated, False if not found.
        Raises ValueError if transition is invalid.
        """
        # Validate transition
        current = self.get_by_idempotency_key(idempotency_key)
        if not current:
            return False
        
        current_status = current["status"]
        if new_status not in STATUS_TRANSITIONS.get(current_status, ()):
            raise ValueError(
                f"Invalid status transition: {current_status} -> {new_status}"
            )
        
        with self._conn(write=True) as conn:
            # Update main table
            fields = ["status = ?"]
            params = [new_status]
            if attempt is not None:
                fields.append("attempt = ?")
                params.append(attempt)
            if sent_at is not None:
                fields.append("sent_at = ?")
                params.append(sent_at)
            if delivered_ref is not None:
                fields.append("delivered_ref = ?")
                params.append(delivered_ref)
            params.append(idempotency_key)
            
            cursor = conn.execute(
                f"UPDATE notifications SET {', '.join(fields)} WHERE idempotency_key = ?",
                params,
            )
            if cursor.rowcount == 0:
                return False
            
            # Update delivery log
            log_fields = ["status = ?"]
            log_params = [new_status]
            if attempt is not None:
                log_fields.append("attempt = ?")
                log_params.append(attempt)
            if sent_at is not None:
                log_fields.append("sent_at = ?")
                log_params.append(sent_at)
            if delivered_ref is not None:
                log_fields.append("delivered_ref = ?")
                log_params.append(delivered_ref)
            if error is not None:
                log_fields.append("error = ?")
                log_params.append(error)
            log_params.append(idempotency_key)
            
            conn.execute(
                f"UPDATE delivery_log SET {', '.join(log_fields)} WHERE idempotency_key = ?",
                log_params,
            )
            
            # Update public chain
            pub_fields = ["status = ?"]
            pub_params = [new_status]
            if attempt is not None:
                pub_fields.append("attempt = ?")
                pub_params.append(attempt)
            if sent_at is not None:
                pub_fields.append("sent_at = ?")
                pub_params.append(sent_at)
            if delivered_ref is not None:
                pub_fields.append("delivered_ref_hash = ?")
                pub_params.append(_hash_delivered_ref(delivered_ref))
            pub_params.append(idempotency_key)
            
            conn.execute(
                f"UPDATE public_chain SET {', '.join(pub_fields)} WHERE idempotency_key = ?",
                pub_params,
            )
            return True
    
    def get_all_for_decision(self, decision_id: str) -> list[dict[str, Any]]:
        """Get all notifications for a decision."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM notifications WHERE decision_id = ? ORDER BY created_at",
                (decision_id,),
            ).fetchall()
            return [dict(r) for r in rows]
    
    def get_private_log(self, decision_id: str) -> list[PrivateLogEntry]:
        """Get private delivery log for a decision."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM delivery_log WHERE decision_id = ? ORDER BY created_at",
                (decision_id,),
            ).fetchall()
            return [_row_to(PrivateLogEntry, r) for r in rows]

    def get_public_chain(self, decision_id: str) -> list[PublicChainEntry]:
        """Get public chain for a decision."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM public_chain WHERE decision_id = ? ORDER BY created_at",
                (decision_id,),
            ).fetchall()
            return [_row_to(PublicChainEntry, r) for r in rows]


async def fan_out(
    decision: dict[str, Any],
    recipients: list[dict[str, Any]],
    transports: dict[str, Any],
    store: NotificationStore | None = None,
) -> list[dict[str, Any]]:
    """Fan out a decision to all eligible recipients via injected transports.
    
    Args:
        decision: Decision dict with at least decision_id, result, kind, proposal_id
        recipients: List of recipient dicts with gh_id and optional addresses per channel
        transports: Dict of channel -> transport callable (async, returns delivered_ref)
        store: Optional NotificationStore for persistence (creates in-memory if None)
    
    Returns:
        List of result dicts with: notification_id, idempotency_key, gh_id, channel,
        status, delivered_ref (on success), error (on failure)
    
    Idempotency: A second call for the same idempotency key returns the existing
    notification and never re-sends.
    
    Status flow: queued -> sending -> sent | failed | suppressed | bounced
    """
    decision_id = decision["decision_id"]
    payload_ref = f"votes/{decision_id}.json"
    
    # Create in-memory store if none provided
    if store is None:
        store = NotificationStore(":memory:")
    
    results = []
    
    for recipient in recipients:
        gh_id = recipient["gh_id"]
        addresses = recipient.get("addresses", {})
        
        for channel in SHIPPING_CHANNELS:
            idempotency_key = make_idempotency_key(decision_id, gh_id, channel)
            notification_id = f"not-{decision_id}-{gh_id}-{channel}"
            address = addresses.get(channel)
            
            # Check idempotency - return existing if already processed
            existing = store.get_by_idempotency_key(idempotency_key)
            if existing:
                results.append({
                    "notification_id": existing["notification_id"],
                    "idempotency_key": idempotency_key,
                    "gh_id": gh_id,
                    "channel": channel,
                    "status": existing["status"],
                    "delivered_ref": existing["delivered_ref"],
                    "error": None,
                    "skipped": True,
                })
                continue
            
            # No address for this channel -> suppressed
            if not address:
                store.insert_queued(
                    notification_id=notification_id,
                    idempotency_key=idempotency_key,
                    decision_id=decision_id,
                    gh_id=gh_id,
                    channel=channel,
                    payload_ref=payload_ref,
                    address="",
                    status="suppressed",
                )
                results.append({
                    "notification_id": notification_id,
                    "idempotency_key": idempotency_key,
                    "gh_id": gh_id,
                    "channel": channel,
                    "status": "suppressed",
                    "delivered_ref": None,
                    "error": "No address configured for channel",
                    "skipped": False,
                })
                continue
            
            # Insert as queued
            store.insert_queued(
                notification_id=notification_id,
                idempotency_key=idempotency_key,
                decision_id=decision_id,
                gh_id=gh_id,
                channel=channel,
                payload_ref=payload_ref,
                address=address,
                status="queued",
            )
            
            # Update to sending
            store.update_status(idempotency_key, "sending", attempt=1)
            
            # Get transport
            transport = transports.get(channel)
            if not transport:
                store.update_status(
                    idempotency_key, "failed", attempt=1,
                    error=f"No transport for channel: {channel}"
                )
                results.append({
                    "notification_id": notification_id,
                    "idempotency_key": idempotency_key,
                    "gh_id": gh_id,
                    "channel": channel,
                    "status": "failed",
                    "delivered_ref": None,
                    "error": f"No transport for channel: {channel}",
                    "skipped": False,
                })
                continue
            
            # Deliver via transport. An injected transport may be sync or async;
            # awaiting a plain return value would raise TypeError and wrongly
            # mark a successful delivery as failed.
            try:
                outcome = transport(decision, address)
                delivered_ref = await outcome if inspect.isawaitable(outcome) else outcome
                
                # Success - update to sent with delivered_ref
                sent_at = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
                store.update_status(
                    idempotency_key,
                    "sent",
                    attempt=1,
                    sent_at=sent_at,
                    delivered_ref=delivered_ref,
                )
                
                results.append({
                    "notification_id": notification_id,
                    "idempotency_key": idempotency_key,
                    "gh_id": gh_id,
                    "channel": channel,
                    "status": "sent",
                    "delivered_ref": delivered_ref,
                    "error": None,
                    "skipped": False,
                })
                
            except Exception as e:
                # Failure - update to failed with error
                store.update_status(
                    idempotency_key,
                    "failed",
                    attempt=1,
                    error=str(e)[:500],
                )
                results.append({
                    "notification_id": notification_id,
                    "idempotency_key": idempotency_key,
                    "gh_id": gh_id,
                    "channel": channel,
                    "status": "failed",
                    "delivered_ref": None,
                    "error": str(e)[:500],
                    "skipped": False,
                })
    
    return results