"""Governance service: the 60-second tick that turns proposals into decisions.

This is the only place the four merged components meet:

    service/ballot_engine.py   the 48-hour clock and the tally
    governance/ledger.py       the hash-chained decision record
    fanout/delivery.py         notification delivery
    accounts/session.py        the only way in

Everything that touches the outside world is injected — proposals, votes,
comment ids, recipients, transports, the clock and the ledger path — so the dry
run exercises THIS code with a fake GitHub and a fake clock instead of a second
implementation.

The tick is deliberately one-directional and idempotent:

    open    a proposal in `voting` with no open ballot gets one, 48h from now
    sync    votes the source has that the ballot does not yet hold are cast
    close   any ballot whose derived closes_at has passed is closed, its
            decision written, its vote snapshot published, its notifications
            delivered, and its proposal moved to ratified/rejected

A `void` result leaves the proposal in `voting`, so the next tick opens a fresh
48h ballot — that is the contract's automatic re-run, and it is the only path
that gets one. A decision record is written once per ballot: decision_id is
derived from ballot_id, so a replayed tick cannot write a second record.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from accounts import session as accounts
from fanout.delivery import NotificationStore, fan_out
from governance.ledger import GENESIS_PREV_HASH, canonical_bytes, dump_line, record_hash, seal
from governance.schema import Decision
from service.ballot_engine import (
    Ballot,
    BallotEngine,
    BallotError,
    VoteError,
    canonical_bytes as ballot_canonical_bytes,
    next_ballot_id,
)

TICK_SECONDS = 60

# The contract writes this at open; the participation number is derived from
# the frozen roster by the engine, so only the approval threshold is used here.
DEFAULT_QUORUM_RULE = {"quorum": "0.20", "threshold": "0.50", "weighted": False}


class GovernanceError(Exception):
    pass


class Unauthorized(GovernanceError):
    """No valid session. Sessions from accounts/ are the only way in."""


# ---------------------------------------------------------------------------
# The three outside-world seams
# ---------------------------------------------------------------------------


class ProposalSource(Protocol):
    def voting_proposals(self) -> list[dict[str, Any]]: ...

    def set_status(self, proposal_id: str, status: str) -> None: ...


class VoteSource(Protocol):
    def votes_for(self, ballot_id: str) -> list[dict[str, Any]]: ...


class CommentPoster(Protocol):
    def post(self, body: str, at: str) -> int: ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def decision_id_for(ballot_id: str) -> str:
    """bal-YYYY-NNNN -> dec-YYYY-NNNN.

    Deterministic, so re-running a tick can never mint a second decision for
    the same ballot.
    """
    suffix = ballot_id[len("bal-") :] if ballot_id.startswith("bal-") else ballot_id
    return "dec-" + suffix


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


@dataclass
class TickReport:
    now: str
    opened: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    delivered: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------


class GovernanceService:
    def __init__(
        self,
        engine: BallotEngine,
        ledger_path: str | os.PathLike[str],
        proposals: ProposalSource,
        votes: VoteSource,
        comments: CommentPoster,
        recipients: Any,
        transports: dict[str, Any],
        store: NotificationStore | None = None,
        clock=None,
        session_lookup=None,
        quorum_rule: dict | None = None,
        votes_dir: str | os.PathLike[str] | None = None,
        signer=None,
        signer_key_id: str = "",
    ) -> None:
        self.engine = engine
        self.ledger_path = str(ledger_path)
        self.proposals = proposals
        self.votes = votes
        self.comments = comments
        self.recipients = recipients
        self.transports = transports
        self.store = store or NotificationStore(":memory:")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.session_lookup = session_lookup or accounts.get_session
        self.quorum_rule = dict(quorum_rule or DEFAULT_QUORUM_RULE)
        base = os.path.dirname(self.ledger_path) or "."
        self.votes_dir = str(votes_dir or os.path.join(base, "votes"))
        self.signer = signer
        self.signer_key_id = signer_key_id

    # -- entry ------------------------------------------------------------

    def tick(self, session_token: str, now: datetime | None = None) -> TickReport:
        """One 60-second tick. The session is the only way in."""
        if self.session_lookup(session_token) is None:
            raise Unauthorized("no session for this token; sign in through accounts/ first")
        moment = now or self.clock()
        report = TickReport(now=_iso(moment))
        self._open_due(report, moment)
        self._sync_votes(report)
        self._close_due(report, moment)
        return report

    # -- phases -----------------------------------------------------------

    def _open_due(self, report: TickReport, now: datetime) -> None:
        existing = self.engine.list_ballots()
        for proposal in self.proposals.voting_proposals():
            pid = proposal["proposal_id"]
            if any(b.proposal_id == pid and b.close_comment_id is None for b in existing):
                continue
            opens_at = _iso(now)
            open_comment_id = self.comments.post(f"Ballot opened for {pid}", opens_at)
            ballot_id = next_ballot_id([b.ballot_id for b in existing])
            self.engine.open_ballot(
                ballot_id=ballot_id,
                proposal_id=pid,
                open_comment_id=open_comment_id,
                opens_at=opens_at,
                eligibility_rule=proposal.get("eligibility_rule", {}),
                eligibility_snapshot={
                    "eligible_count": int(proposal.get("eligible_count", 0)),
                    "ref": proposal.get("eligibility_ref", ""),
                },
                nonce=proposal.get("nonce", ""),
                quorum_rule=self.quorum_rule,
            )
            existing = self.engine.list_ballots()
            report.opened.append(ballot_id)

    def _sync_votes(self, report: TickReport) -> None:
        for ballot in self.engine.list_ballots():
            if ballot.close_comment_id is not None:
                continue
            known = {v.get("comment_id") for v in ballot.votes}
            for vote in self.votes.votes_for(ballot.ballot_id):
                cid = vote["comment_id"]
                if cid in known:
                    continue
                try:
                    self.engine.cast_vote(
                        ballot.ballot_id,
                        vote["voter_gh_id"],
                        cid,
                        vote["created_at"],
                        vote["updated_at"],
                        vote["body_sha256"],
                        vote.get("source", "reaction"),
                        vote.get("choice", "approve"),
                    )
                except VoteError as exc:
                    # A late vote is refused by the engine, not smuggled in.
                    report.skipped.append(f"{ballot.ballot_id}:{cid} {exc}")

    def _close_due(self, report: TickReport, now: datetime) -> None:
        for ballot in self.engine.list_ballots():
            if ballot.close_comment_id is not None or ballot.closes_at is None:
                continue
            closes_at = ballot.closes_at
            if now < _parse(closes_at):
                continue
            # The window anchor is the derived closes_at; the comment is the
            # audit trail and is stamped at the real tick time.
            close_comment_id = self.comments.post(
                f"Ballot {ballot.ballot_id} closed", _iso(now)
            )
            try:
                closed = self.engine.close_ballot(
                    ballot.ballot_id, close_comment_id, closes_at
                )
            except BallotError as exc:
                report.skipped.append(f"{ballot.ballot_id} {exc}")
                continue
            report.closed.append(closed.ballot_id)
            record = self._write_decision(closed)
            report.decisions.append(record)
            report.delivered.extend(self._deliver(record))

    # -- close-time side effects -----------------------------------------

    def _write_decision(self, ballot: Ballot) -> dict[str, Any]:
        proposal = self._proposal(ballot.proposal_id)
        decision_id = decision_id_for(ballot.ballot_id)
        eligibility = dict(ballot.eligibility_snapshot)
        record = Decision(
            kind="ratify",
            decision_id=decision_id,
            proposal_id=ballot.proposal_id,
            ballot_id=ballot.ballot_id,
            open_comment_id=ballot.open_comment_id,
            close_comment_id=ballot.close_comment_id or 0,
            voting_hours=ballot.voting_hours,
            owner_notice_comment_id=int(proposal.get("owner_notice_comment_id", 0)),
            owner_decision=proposal.get("owner_decision", "none"),
            owner_override_ground=proposal.get("owner_override_ground"),
            ballot_snapshot_hash=ballot.ballot_snapshot_hash or "",
            votes_ref=f"votes/{decision_id}.json",
            eligibility_snapshot_hash=_canonical_sha256(eligibility),
            quorum_rule=ballot.quorum_rule,
            tally=ballot.tally,
            result=ballot.result,
            scope_paths=list(proposal.get("scope_paths", [])),
            proposal_body_sha256=proposal.get("proposal_body_sha256", ""),
            head_sha=proposal.get("head_sha", ""),
            approvers=list(proposal.get("approvers", [])),
            prev_hash=self._last_hash(),
            supersedes=proposal.get("supersedes"),
            signer_key_id=self.signer_key_id,
        ).to_dict()
        # The signature is over the record's own hash bytes, so it must be
        # produced before seal() adds anything the verifier would strip.
        signature = self.signer(record_hash(record)) if self.signer is not None else None
        sealed = seal(record, signature=signature)
        self._publish_snapshot(decision_id, ballot)
        with open(self.ledger_path, "a", encoding="utf-8") as fh:
            fh.write(dump_line(sealed))
        self.proposals.set_status(ballot.proposal_id, self._proposal_status(ballot.result))
        return sealed

    def _publish_snapshot(self, decision_id: str, ballot: Ballot) -> None:
        os.makedirs(self.votes_dir, exist_ok=True)
        path = os.path.join(self.votes_dir, f"{decision_id}.json")
        # Written with the same canonicaliser that produced ballot_snapshot_hash,
        # so sha256(file) == the hash the ledger records.
        with open(path, "wb") as fh:
            fh.write(ballot_canonical_bytes(ballot.votes))

    def _deliver(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        recipients = self.recipients() if callable(self.recipients) else self.recipients
        return asyncio.run(fan_out(record, recipients, self.transports, self.store))

    # -- read helpers -----------------------------------------------------

    def _proposal(self, proposal_id: str) -> dict[str, Any]:
        getter = getattr(self.proposals, "get", None)
        if getter is not None:
            found = getter(proposal_id)
            if found is not None:
                return found
        return {}

    def _last_hash(self) -> str:
        if not os.path.exists(self.ledger_path):
            return GENESIS_PREV_HASH
        last = GENESIS_PREV_HASH
        with open(self.ledger_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    last = json.loads(line)["hash"]
        return last

    @staticmethod
    def _proposal_status(result: str) -> str:
        # void keeps the proposal in `voting` so the next tick re-runs it.
        return {"ratified": "ratified", "rejected": "rejected"}.get(result, "voting")
