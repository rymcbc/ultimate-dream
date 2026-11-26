"""Model classes for the four contract records: proposal, ballot, decision, notification.

Each record serialises to canonical JSON bytes matching CONTRACTS.md and
docs/LEDGER-FORMAT.md v3. Canonicalisation is RFC 8785 (JCS) as implemented in
governance/ledger.py -- keys sorted by UTF-16 code units, integers only, no
floats, UTF-8 output, no whitespace.

The decision (ledger) record format is normative in docs/LEDGER-FORMAT.md v3
and is implemented in governance/ledger.py; this module reuses it rather than
duplicating the hash rule.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from governance.ledger import canonical_bytes, record_hash

# ---------------------------------------------------------------------------
# Field constants drawn from CONTRACTS.md and LEDGER-FORMAT.md
# ---------------------------------------------------------------------------

PROPOSAL_STATUSES = (
    "open",
    "voting",
    "ratified",
    "rejected",
    "withdrawn",
    "superseded",
    "merged",
)

BALLOT_RESULTS = ("ratified", "rejected", "void")

DECISION_KINDS = ("ratify", "revoke", "waive", "supersede")
DECISION_RESULTS = ("ratified", "rejected", "void", "waived")
OWNER_DECISIONS = ("none", "reviewed", "override")
OVERRIDE_GROUNDS = ("legal_licensing", "safety_tos", "security", "does_not_build")

NOTIFICATION_CHANNELS = ("discord_dm", "email", "webhook", "rss")
NOTIFICATION_STATUSES = ("queued", "sending", "sent", "failed", "suppressed", "bounced")

VOTE_SOURCES = ("reaction", "comment")
VOTE_CHOICES = ("approve", "reject", "abstain")

GENESIS_PREV_HASH = "0" * 64


# ---------------------------------------------------------------------------
# 1. Proposal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Proposal:
    """A governance proposal. proposal_id is stable and is NOT the issue number."""

    proposal_id: str
    title: str
    author_gh_id: int
    issue_number: int
    opened_at: str  # ISO8601 Z, GitHub server timestamp
    closed_at: str | None = None  # ISO8601 Z = ballot close comment's created_at
    status: str = "open"
    scope_paths: list[str] = field(default_factory=list)
    supersedes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "title": self.title,
            "author_gh_id": self.author_gh_id,
            "issue_number": self.issue_number,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "status": self.status,
            "scope_paths": self.scope_paths,
            "supersedes": self.supersedes,
        }

    def to_canonical_bytes(self) -> bytes:
        return canonical_bytes(self.to_dict())

    def hash(self) -> str:
        return hashlib.sha256(self.to_canonical_bytes()).hexdigest()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Proposal":
        return cls(**data)


# ---------------------------------------------------------------------------
# 2. Ballot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VoteEntry:
    """One vote. source is 'reaction' (default) or 'comment' (multi-choice)."""

    voter_gh_id: int
    choice: str
    comment_id: int
    created_at: str  # ISO8601 Z, server-stamped
    updated_at: str  # ISO8601 Z, server-stamped
    body_sha256: str
    source: str = "reaction"

    def to_dict(self) -> dict[str, Any]:
        return {
            "voter_gh_id": self.voter_gh_id,
            "choice": self.choice,
            "comment_id": self.comment_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "body_sha256": self.body_sha256,
            "source": self.source,
        }


@dataclass(frozen=True)
class Ballot:
    """A 48-hour ratification ballot. closes_at is derived from comments, never declared."""

    ballot_id: str
    proposal_id: str
    open_comment_id: int
    close_comment_id: int
    voting_hours: int = 48
    opens_at: str | None = None  # derived from open_comment.created_at
    closes_at: str | None = None  # derived from close_comment.created_at
    eligibility_rule: dict[str, Any] = field(default_factory=dict)
    eligibility_snapshot: dict[str, Any] = field(default_factory=dict)
    nonce: str = ""
    quorum_rule: dict[str, Any] = field(default_factory=dict)
    votes: list[VoteEntry] = field(default_factory=list)
    tally: dict[str, int] = field(default_factory=lambda: {"approve": 0, "reject": 0, "abstain": 0})
    quorum_met: bool = False
    result: str | None = None  # ratified | rejected | void

    def to_dict(self) -> dict[str, Any]:
        return {
            "ballot_id": self.ballot_id,
            "proposal_id": self.proposal_id,
            "open_comment_id": self.open_comment_id,
            "close_comment_id": self.close_comment_id,
            "voting_hours": self.voting_hours,
            "opens_at": self.opens_at,
            "closes_at": self.closes_at,
            "eligibility_rule": self.eligibility_rule,
            "eligibility_snapshot": self.eligibility_snapshot,
            "nonce": self.nonce,
            "quorum_rule": self.quorum_rule,
            "votes": [v.to_dict() for v in self.votes],
            "tally": self.tally,
            "quorum_met": self.quorum_met,
            "result": self.result,
        }

    def to_canonical_bytes(self) -> bytes:
        return canonical_bytes(self.to_dict())

    def hash(self) -> str:
        return hashlib.sha256(self.to_canonical_bytes()).hexdigest()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Ballot":
        votes = [VoteEntry(**v) for v in data.get("votes", [])]
        return cls(**{k: v for k, v in data.items() if k != "votes"}, votes=votes)


# ---------------------------------------------------------------------------
# 3. Decision (ledger record)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    """A ledger decision record in LEDGER-FORMAT.md v3 format.

    Serialises through governance/ledger.seal() which adds `hash` and
    optionally `signature`. prev_hash is an ordinary field inside the
    preimage; only hash and signature are excluded.
    """

    kind: str  # ratify | revoke | waive | supersede
    decision_id: str
    proposal_id: str
    ballot_id: str
    open_comment_id: int
    close_comment_id: int
    voting_hours: int = 48
    owner_notice_comment_id: int = 0
    owner_decision: str = "none"
    owner_override_ground: str | None = None
    ballot_snapshot_hash: str = ""
    votes_ref: str = ""
    eligibility_snapshot_hash: str = ""
    quorum_rule: dict[str, Any] = field(default_factory=dict)
    tally: dict[str, int] = field(default_factory=lambda: {"approve": 0, "reject": 0, "abstain": 0})
    result: str = "ratified"
    scope_paths: list[str] = field(default_factory=list)
    proposal_body_sha256: str = ""
    head_sha: str = ""
    approvers: list[dict[str, Any]] = field(default_factory=list)
    prev_hash: str = GENESIS_PREV_HASH
    signer_key_id: str = ""
    supersedes: str | None = None
    created_by: str = "githubapp:ultimate-dream-ledger"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "schema_version": 3,
            "decision_id": self.decision_id,
            "proposal_id": self.proposal_id,
            "ballot_id": self.ballot_id,
            "open_comment_id": self.open_comment_id,
            "close_comment_id": self.close_comment_id,
            "voting_hours": self.voting_hours,
            "owner_notice_comment_id": self.owner_notice_comment_id,
            "owner_decision": self.owner_decision,
            "owner_override_ground": self.owner_override_ground,
            "ballot_snapshot_hash": self.ballot_snapshot_hash,
            "votes_ref": self.votes_ref,
            "eligibility_snapshot_hash": self.eligibility_snapshot_hash,
            "quorum_rule": self.quorum_rule,
            "tally": self.tally,
            "result": self.result,
            "scope_paths": self.scope_paths,
            "proposal_body_sha256": self.proposal_body_sha256,
            "head_sha": self.head_sha,
            "approvers": self.approvers,
            "prev_hash": self.prev_hash,
            "signer_key_id": self.signer_key_id,
            "supersedes": self.supersedes,
            "created_by": self.created_by,
        }

    def to_canonical_bytes(self) -> bytes:
        return canonical_bytes(self.to_dict())

    def hash(self) -> str:
        return record_hash(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Decision":
        return cls(**{k: v for k, v in data.items() if k not in ("hash", "signature", "schema_version")})


# ---------------------------------------------------------------------------
# 4. Notification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Recipient:
    """A notification recipient. gh_id is the numeric GitHub id only."""

    gh_id: int
    channel: str  # discord_dm | email | webhook | rss
    address: str | None = None  # email/webhook/RSS address; never in the chain

    def to_dict(self) -> dict[str, Any]:
        return {
            "gh_id": self.gh_id,
            "channel": self.channel,
            "address": self.address,
        }


@dataclass(frozen=True)
class Notification:
    """A notification delivery record. idempotency_key = decision_id + recipient_hash + channel."""

    notification_id: str
    idempotency_key: str
    recipient: Recipient
    payload_ref: str
    sent_at: str | None = None  # ISO8601 Z
    attempt: int = 0
    status: str = "queued"  # queued | sending | sent | failed | suppressed | bounced
    delivered_ref: str | None = None  # real message id, written back on send

    def to_dict(self) -> dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "idempotency_key": self.idempotency_key,
            "recipient": self.recipient.to_dict(),
            "payload_ref": self.payload_ref,
            "sent_at": self.sent_at,
            "attempt": self.attempt,
            "status": self.status,
            "delivered_ref": self.delivered_ref,
        }

    def to_canonical_bytes(self) -> bytes:
        return canonical_bytes(self.to_dict())

    def hash(self) -> str:
        return hashlib.sha256(self.to_canonical_bytes()).hexdigest()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Notification":
        recipient = Recipient(**data["recipient"]) if isinstance(data.get("recipient"), dict) else data["recipient"]
        return cls(
            notification_id=data["notification_id"],
            idempotency_key=data["idempotency_key"],
            recipient=recipient,
            payload_ref=data["payload_ref"],
            sent_at=data.get("sent_at"),
            attempt=data.get("attempt", 0),
            status=data.get("status", "queued"),
            delivered_ref=data.get("delivered_ref"),
        )
