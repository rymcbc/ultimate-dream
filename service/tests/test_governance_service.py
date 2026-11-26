"""Conformance tests for the governance service (the 60-second tick).

The dry run is deliberately time-warped: the service's clock is injected, so a
ballot is opened, votes are cast, and the tick closes it 48h later within one
test. Nothing is faked except the outside world (proposals, votes, comment ids,
channel transports) — the ballot engine, the ledger, fanout and accounts all
run for real.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from accounts import session as accounts  # noqa: E402
from accounts.oauth import FakeProvider  # noqa: E402
from governance.ledger import load_lines, verify_chain  # noqa: E402
from service.ballot_engine import BallotEngine  # noqa: E402
from service.governance_service import (  # noqa: E402
    GovernanceService,
    Unauthorized,
    decision_id_for,
)

T0 = datetime(2026, 11, 25, 10, 0, 0, tzinfo=timezone.utc)
T_PLUS_1H = datetime(2026, 11, 25, 11, 0, 0, tzinfo=timezone.utc)
T_PLUS_48H_1S = datetime(2026, 11, 27, 10, 0, 1, tzinfo=timezone.utc)

PROPOSAL = {
    "proposal_id": "prop-2026-0001",
    "title": "Add the Dream tab",
    "author_gh_id": 1001,
    "issue_number": 7,
    "opened_at": "2026-11-25T09:00:00.000Z",
    "status": "voting",
    "scope_paths": ["game/content/props/**"],
    "eligible_count": 3,
    "nonce": "nonce-1",
    "head_sha": "4f2a9c1e" * 8,
    "proposal_body_sha256": "7d" * 32,
}

RECIPIENTS = [
    {
        "gh_id": 1001,
        "addresses": {"discord_dm": "dm://1001", "webhook": "https://example.test/hook/1001"},
    },
    {"gh_id": 1002, "addresses": {"discord_dm": "dm://1002"}},
]


# ---------------------------------------------------------------------------
# Fakes for the outside world only
# ---------------------------------------------------------------------------


class FakeProposalSource:
    def __init__(self, proposals):
        self._p = {p["proposal_id"]: dict(p) for p in proposals}

    def voting_proposals(self):
        return [p for p in self._p.values() if p["status"] == "voting"]

    def set_status(self, proposal_id, status):
        self._p[proposal_id]["status"] = status

    def get(self, proposal_id):
        return self._p.get(proposal_id)


class FakeVoteSource:
    def __init__(self):
        self._votes = {}

    def add(self, ballot_id, **vote):
        self._votes.setdefault(ballot_id, []).append(vote)

    def votes_for(self, ballot_id):
        return list(self._votes.get(ballot_id, []))


class FakeCommenter:
    def __init__(self, start=900000):
        self._next = start
        self.posted = []

    def post(self, body, at):
        self._next += 1
        self.posted.append({"id": self._next, "body": body, "at": at})
        return self._next


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_accounts_db(monkeypatch, tmp_path):
    monkeypatch.setenv("ACCOUNTS_DB_PATH", str(tmp_path / "accounts.db"))
    accounts.close()
    yield
    accounts.close()


@pytest.fixture
def session_token():
    """A real session, minted through accounts/ with the fake provider."""
    provider = FakeProvider()
    state = "dry-run-state"
    provider.authorize_url(state)
    return accounts.sign_in(provider, "code", state)


KEY_ID = "dry-run-key"


def _service(tmp_path, clock):
    private = Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )

    def signer(hash_hex: str) -> str:
        return base64.b64encode(private.sign(bytes.fromhex(hash_hex))).decode()

    engine = BallotEngine(":memory:")
    proposals = FakeProposalSource([PROPOSAL])
    votes = FakeVoteSource()
    comments = FakeCommenter()
    transports = {
        "discord_dm": lambda decision, address: f"dm-{decision['decision_id']}-{address}",
        "webhook": lambda decision, address: f"wh-{decision['decision_id']}-{address}",
        # rss has no transport and no address here -> never 'sent'
    }
    svc = GovernanceService(
        engine=engine,
        ledger_path=tmp_path / "ledger.jsonl",
        proposals=proposals,
        votes=votes,
        comments=comments,
        recipients=RECIPIENTS,
        transports=transports,
        clock=lambda: clock["now"],
        signer=signer,
        signer_key_id=KEY_ID,
    )
    return svc, engine, proposals, votes, comments, public_raw


def _ledger(tmp_path):
    path = tmp_path / "ledger.jsonl"
    if not path.exists():
        return []
    return load_lines(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The dry run: one proposal, one ballot, one real decision record
# ---------------------------------------------------------------------------


def test_time_warped_dry_run_produces_a_real_record(tmp_path, session_token):
    clock = {"now": T0}
    svc, engine, proposals, votes, comments, public_raw = _service(tmp_path, clock)

    # T0 — the tick opens a ballot from the proposal
    r1 = svc.tick(session_token)
    assert r1.opened == ["bal-2026-0001"]
    ballot_id = r1.opened[0]
    assert engine.get_ballot(ballot_id).close_comment_id is None
    assert comments.posted[0]["body"] == "Ballot opened for prop-2026-0001"

    # Three votes arrive inside the window, 2 approve / 1 reject
    for i, choice in enumerate(["approve", "approve", "reject"]):
        votes.add(
            ballot_id,
            voter_gh_id=2001 + i,
            comment_id=500 + i,
            created_at="2026-11-25T12:00:00.000Z",
            updated_at="2026-11-25T12:00:00.000Z",
            body_sha256="ab" * 32,
            source="reaction",
            choice=choice,
        )

    # T0 + 1h — votes are cast, nothing closes
    clock["now"] = T_PLUS_1H
    r2 = svc.tick(session_token)
    assert r2.opened == []
    assert r2.closed == []
    assert len(engine.get_ballot(ballot_id).votes) == 3

    # T0 + 48h + 1s — the tick closes it and everything downstream runs
    clock["now"] = T_PLUS_48H_1S
    r3 = svc.tick(session_token)
    assert r3.closed == [ballot_id]
    assert len(r3.decisions) == 1

    record = r3.decisions[0]
    assert record["decision_id"] == "dec-2026-0001"
    assert record["ballot_id"] == "bal-2026-0001"
    assert record["proposal_id"] == "prop-2026-0001"
    assert record["result"] == "ratified"
    assert record["tally"] == {"approve": 2, "reject": 1, "abstain": 0}
    assert record["voting_hours"] == 48
    assert record["votes_ref"] == "votes/dec-2026-0001.json"
    assert len(record["hash"]) == 64

    # the record is a real ledger line and the chain verifies
    lines = _ledger(tmp_path)
    assert len(lines) == 1
    assert lines[0]["hash"] == record["hash"]
    ok, why = verify_chain(lines, {KEY_ID: public_raw})
    assert ok, why

    # the published snapshot hashes to the hash the ledger carries
    snapshot = (tmp_path / "votes" / "dec-2026-0001.json").read_bytes()
    assert hashlib.sha256(snapshot).hexdigest() == record["ballot_snapshot_hash"]

    # notifications went out through fanout/ over the injected transports
    sent = [r for r in r3.delivered if r["status"] == "sent"]
    assert {r["channel"] for r in sent} == {"discord_dm", "webhook"}
    assert all(r["delivered_ref"] for r in sent)

    # the proposal moved to its result
    assert proposals.get("prop-2026-0001")["status"] == "ratified"

    # a replayed tick writes nothing new — one decision per ballot
    r4 = svc.tick(session_token)
    assert r4.opened == [] and r4.closed == [] and r4.decisions == []
    assert len(_ledger(tmp_path)) == 1


def test_tick_requires_a_session(tmp_path):
    svc, *_ = _service(tmp_path, {"now": T0})
    with pytest.raises(Unauthorized):
        svc.tick("not-a-real-token")


def test_void_leaves_the_proposal_in_voting_and_the_next_tick_reopens(tmp_path, session_token):
    clock = {"now": T0}
    svc, engine, proposals, *_ = _service(tmp_path, clock)

    first = svc.tick(session_token).opened[0]

    # no votes at all -> quorum miss -> void
    clock["now"] = T_PLUS_48H_1S
    r2 = svc.tick(session_token)
    assert r2.closed == [first]
    assert r2.decisions[0]["result"] == "void"
    assert proposals.get("prop-2026-0001")["status"] == "voting"

    # the next tick opens a fresh 48h ballot — the contract's automatic re-run
    r3 = svc.tick(session_token)
    assert len(r3.opened) == 1
    assert r3.opened[0] != first


def test_late_vote_is_refused_at_cast_not_counted(tmp_path, session_token):
    clock = {"now": T0}
    svc, engine, proposals, votes, *_ = _service(tmp_path, clock)
    ballot_id = svc.tick(session_token).opened[0]

    votes.add(
        ballot_id,
        voter_gh_id=2001,
        comment_id=700,
        created_at="2026-11-27T10:00:01.000Z",  # one second after closes_at
        updated_at="2026-11-27T10:00:01.000Z",
        body_sha256="ab" * 32,
        source="reaction",
        choice="approve",
    )

    clock["now"] = T_PLUS_48H_1S
    report = svc.tick(session_token)

    assert any("outside" in s for s in report.skipped)
    assert report.decisions[0]["tally"] == {"approve": 0, "reject": 0, "abstain": 0}


def test_decision_id_is_derived_from_the_ballot():
    assert decision_id_for("bal-2026-0007") == "dec-2026-0007"
