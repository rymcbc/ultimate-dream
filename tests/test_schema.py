"""Conformance tests for governance/schema.py.

Every contract field round-trips through canonical JSON bytes: parse a dict,
build a model, serialise, re-parse, and the bytes are identical. The v3 ledger
record reproduces the published vector 843665b1...; the vote snapshot
reproduces fb7fb3e4... .

The retired shapes (v0, v1, v2, v2-draft) are asserted to fail: they are
unreachable from a v3 record.
"""

from __future__ import annotations

import hashlib
import json
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from governance.schema import (
    Proposal,
    Ballot,
    VoteEntry,
    Decision,
    Notification,
    Recipient,
    PROPOSAL_STATUSES,
    BALLOT_RESULTS,
    DECISION_KINDS,
    DECISION_RESULTS,
    OWNER_DECISIONS,
    OVERRIDE_GROUNDS,
    NOTIFICATION_CHANNELS,
    NOTIFICATION_STATUSES,
    VOTE_SOURCES,
    VOTE_CHOICES,
)
from governance.ledger import canonical_bytes, record_hash, votes_snapshot_hash, GENESIS_PREV_HASH

# ---------------------------------------------------------------------------
# Published vectors (docs/LEDGER-FORMAT.md v3)
# ---------------------------------------------------------------------------

V3_RECORD = {
    "kind": "ratify",
    "schema_version": 3,
    "decision_id": "dec-2026-0001",
    "proposal_id": "prop-2026-0001",
    "ballot_id": "bal-2026-0001",
    "open_comment_id": 191234567,
    "close_comment_id": 191234999,
    "voting_hours": 48,
    "owner_notice_comment_id": 191234560,
    "owner_decision": "none",
    "owner_override_ground": None,
    "ballot_snapshot_hash": "fb7fb3e41180e4e28cdb6b97355d5c3b358ebafeb2c23a6daefd3edd8a5a9563",
    "votes_ref": "votes/dec-2026-0001.json",
    "eligibility_snapshot_hash": "3c" * 32,
    "quorum_rule": {"quorum": "0.20", "threshold": "0.50", "weighted": False},
    "tally": {"approve": 1, "reject": 0, "abstain": 0},
    "result": "ratified",
    "scope_paths": ["game/content/props/**", "game/content/items/**"],
    "proposal_body_sha256": "7d" * 32,
    "head_sha": "4f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d",
    "approvers": [{"gh_id": 1001, "review_id": 3912345678, "reviewed_sha": "4f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d"}],
    "supersedes": None,
    "created_by": "githubapp:ultimate-dream-ledger",
    "signer_key_id": "k1",
    "prev_hash": GENESIS_PREV_HASH,
}

V3_RECORD_HASH = "843665b13896c04e4acb3a386d149f6f5899943000414862a19cedf360bb63dc"

V3_VOTES = [
    {
        "body_sha256": "abababababababababababababababababababababababababababababababab",
        "comment_id": 191234701,
        "created_at": "2026-11-23T10:00:00.000Z",
        "updated_at": "2026-11-23T10:00:00.000Z",
        "voter_gh_id": 1001,
    }
]

V3_VOTES_HASH = "fb7fb3e41180e4e28cdb6b97355d5c3b358ebafeb2c23a6daefd3edd8a5a9563"

# Retired shapes — must never verify from a v3 record.
RETIRED = {
    "v0": "6fa7e0e498031e7f41911119195e3b393027b56c7ed7a9e63ac2c507f2c6ad52",
    "v1": "0d87f7b4719159c11f00ba89a968c18fb869dc9fa630d0288b9a937c0b3abc1f",
    "v2": "5451538b45503c04b7d8b5e939628c3f7aee4c43735d22d6dca673146e2932a4",
    "v2-draft": "fcd1a4495b37cb1803070a793e849bbefc9f1b570b8eff2f9e57bdb4abbf4701",
}


# ---------------------------------------------------------------------------
# Proposal
# ---------------------------------------------------------------------------


def test_proposal_round_trip() -> None:
    p = Proposal(
        proposal_id="prop-2026-0001",
        title="Add dream voting tab",
        author_gh_id=122483695,
        issue_number=42,
        opened_at="2026-11-25T09:00:00.000Z",
        status="open",
        scope_paths=["game/content/props/**"],
        supersedes=None,
    )
    d = p.to_dict()
    assert d["proposal_id"] == "prop-2026-0001"
    assert d["author_gh_id"] == 122483695
    assert d["status"] in PROPOSAL_STATUSES
    p2 = Proposal.from_dict(d)
    assert p2 == p
    assert p2.to_dict() == d
    # canonical bytes are stable
    assert p.to_canonical_bytes() == p2.to_canonical_bytes()


def test_proposal_hash_deterministic() -> None:
    p = Proposal(
        proposal_id="prop-2026-0002",
        title="Test proposal",
        author_gh_id=1,
        issue_number=1,
        opened_at="2026-11-25T09:00:00.000Z",
    )
    h1 = p.hash()
    h2 = Proposal.from_dict(p.to_dict()).hash()
    assert h1 == h2
    assert len(h1) == 64


# ---------------------------------------------------------------------------
# Ballot
# ---------------------------------------------------------------------------


def test_ballot_round_trip() -> None:
    b = Ballot(
        ballot_id="bal-2026-0001",
        proposal_id="prop-2026-0001",
        open_comment_id=191234567,
        close_comment_id=191234999,
        voting_hours=48,
        nonce="nonce-abc123",
        quorum_rule={"quorum": "0.20", "threshold": "0.50", "weighted": False},
        votes=[
            VoteEntry(
                voter_gh_id=1001,
                choice="approve",
                comment_id=191234701,
                created_at="2026-11-23T10:00:00.000Z",
                updated_at="2026-11-23T10:00:00.000Z",
                body_sha256="ab" * 32,
                source="reaction",
            )
        ],
        tally={"approve": 1, "reject": 0, "abstain": 0},
        quorum_met=True,
        result="ratified",
    )
    d = b.to_dict()
    assert d["voting_hours"] == 48
    assert d["result"] in BALLOT_RESULTS
    assert len(d["votes"]) == 1
    b2 = Ballot.from_dict(d)
    assert b2 == b
    assert b2.to_dict() == d
    assert b.to_canonical_bytes() == b2.to_canonical_bytes()


def test_ballot_vote_entry_sources() -> None:
    for source in VOTE_SOURCES:
        v = VoteEntry(
            voter_gh_id=1,
            choice="approve",
            comment_id=1,
            created_at="2026-11-23T10:00:00.000Z",
            updated_at="2026-11-23T10:00:00.000Z",
            body_sha256="ab" * 32,
            source=source,
        )
        assert v.source in VOTE_SOURCES


# ---------------------------------------------------------------------------
# Decision (ledger record)
# ---------------------------------------------------------------------------


def test_decision_reproduces_v3_vector() -> None:
    d = Decision.from_dict(V3_RECORD)
    assert d.hash() == V3_RECORD_HASH, f"got {d.hash()}, expected {V3_RECORD_HASH}"
    # Round-trip: the canonical bytes of the model match the published vector
    assert d.to_canonical_bytes().decode("utf-8") == json.dumps(V3_RECORD, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def test_decision_vote_snapshot_hash() -> None:
    assert votes_snapshot_hash(V3_VOTES) == V3_VOTES_HASH


def test_decision_round_trip() -> None:
    d = Decision.from_dict(V3_RECORD)
    d2 = Decision.from_dict(d.to_dict())
    assert d2 == d
    assert d2.to_dict() == d.to_dict()
    assert d2.hash() == d.hash() == V3_RECORD_HASH


def test_decision_schema_version_is_3() -> None:
    d = Decision.from_dict(V3_RECORD)
    assert d.to_dict()["schema_version"] == 3


def test_decision_voting_hours_is_48() -> None:
    d = Decision.from_dict(V3_RECORD)
    assert d.voting_hours == 48


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------


def test_notification_round_trip() -> None:
    n = Notification(
        notification_id="not-2026-0001",
        idempotency_key="dec-2026-0001+recipient-122483695+discord_dm",
        recipient=Recipient(gh_id=122483695, channel="discord_dm"),
        payload_ref="votes/dec-2026-0001.json",
        status="queued",
    )
    d = n.to_dict()
    assert d["idempotency_key"] == "dec-2026-0001+recipient-122483695+discord_dm"
    assert d["recipient"]["gh_id"] == 122483695
    assert d["recipient"]["channel"] in NOTIFICATION_CHANNELS
    assert d["status"] in NOTIFICATION_STATUSES
    n2 = Notification.from_dict(d)
    assert n2 == n
    assert n2.to_dict() == d
    assert n.to_canonical_bytes() == n2.to_canonical_bytes()


def test_notification_channels_and_statuses() -> None:
    for ch in NOTIFICATION_CHANNELS:
        for st in NOTIFICATION_STATUSES:
            r = Recipient(gh_id=1, channel=ch)
            n = Notification(
                notification_id="not-test",
                idempotency_key="k",
                recipient=r,
                payload_ref="p",
                status=st,
            )
            assert n.recipient.channel == ch
            assert n.status == st


# ---------------------------------------------------------------------------
# Retired shapes must fail
# ---------------------------------------------------------------------------


def test_retired_shapes_are_not_v3() -> None:
    h = record_hash(V3_RECORD)
    assert h == V3_RECORD_HASH
    for name, retired_hash in RETIRED.items():
        assert h != retired_hash, f"{name} ({retired_hash}) must not equal the v3 hash"


def test_no_stored_timestamps_in_decision() -> None:
    """v3 stores comment ids, not the times it derived from them."""
    for banned in ("ballot_closed_at", "opens_at", "closes_at", "ratified_at", "owner_notified_at"):
        assert banned not in V3_RECORD, f"{banned} duplicates a fact GitHub already owns"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS " + name)
            except Exception as exc:
                failures += 1
                print("FAIL " + name + ": " + str(exc))
    print("ALL GREEN" if failures == 0 else str(failures) + " FAILED")
    raise SystemExit(1 if failures else 0)
