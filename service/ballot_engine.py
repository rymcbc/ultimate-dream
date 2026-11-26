"""Ballot engine for The Ultimate Dream.

Implements docs/CONTRACTS.md Section 3 (ballot) and Section 4 (votes), plus
the 48-hour single-window rule from docs/LEDGER-FORMAT.md.

The engine is pure Python + SQLite, lives in `service/`, and writes ballot
records that the ledger writer appends to the `ledger` branch. It never
sits in the merge path: CI verifies offline from the `ledger` branch and
re-fetches GitHub artifacts independently.

Key invariants, all enforced in code:

* `voting_hours` is 48 — the vote window AND the notice period, one timer.
* `opens_at` and `closes_at` are derived from GitHub-stamped comment
  `created_at` values, never declared by any local clock.
* At close, every vote is snapshotted into `votes/<decision_id>.json` and
  hashed into `ballot_snapshot_hash`. Latest valid entry per voter counts;
  a deleted comment voids that vote; pre-close edits are legal.
* The tally is computed once, at close, from the snapshot. No running
  percentage, no drift.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


# --------------------------------------------------------------------------
# Canonical JSON — RFC 8785 (JCS), same as the ledger writer
# --------------------------------------------------------------------------

_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def _escape_string(value: str) -> str:
    out = ['"']
    for ch in value:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _reject_floats(value: Any) -> None:
    if isinstance(value, float):
        raise ValueError("floats are banned from ballot records; use an integer or a fixed decimal string")
    if isinstance(value, dict):
        for v in value.values():
            _reject_floats(v)
    elif isinstance(value, list):
        for v in value:
            _reject_floats(v)


def _sort_key(key: str) -> bytes:
    return key.encode("utf-16-be")


def canonical_json(value: Any) -> str:
    _reject_floats(value)
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: _sort_key(kv[0]))
        return "{" + ",".join(_escape_string(k) + ":" + canonical_json(v) for k, v in items) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical_json(v) for v in value) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _escape_string(value)
    raise ValueError(f"unsupported type: {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

VOTING_HOURS = 48  # the single window: vote + notice, same 48 hours

KINDS = ("ratify", "reject", "void")
VOTE_CHOICES = ("approve", "reject", "abstain")
VOTE_SOURCES = ("reaction", "comment")
RESULT_STATES = ("ratified", "rejected", "void")

BALLOT_ID_PREFIX = "bal-"
PROPOSAL_ID_PREFIX = "prop-"


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class BallotError(ValueError):
    pass


class WindowError(BallotError):
    pass


class VoteError(BallotError):
    pass


# --------------------------------------------------------------------------
# Ballot model
# --------------------------------------------------------------------------


class Ballot:
    """A single 48-hour ratification ballot, per docs/CONTRACTS.md Section 3."""

    def __init__(
        self,
        ballot_id: str,
        proposal_id: str,
        open_comment_id: int,
        close_comment_id: int | None,
        voting_hours: int,
        opens_at: str | None,
        closes_at: str | None,
        eligibility_rule: dict,
        eligibility_snapshot: dict,
        nonce: str,
        quorum_rule: dict,
        votes: list,
        tally: dict,
        quorum_met: bool,
        result: str | None,
        ballot_snapshot_hash: str | None,
        supersedes: str | None,
    ) -> None:
        self.ballot_id = ballot_id
        self.proposal_id = proposal_id
        self.open_comment_id = open_comment_id
        self.close_comment_id = close_comment_id
        self.voting_hours = voting_hours
        self.opens_at = opens_at
        self.closes_at = closes_at
        self.eligibility_rule = eligibility_rule
        self.eligibility_snapshot = eligibility_snapshot
        self.nonce = nonce
        self.quorum_rule = quorum_rule
        self.votes = votes
        self.tally = tally
        self.quorum_met = quorum_met
        self.result = result
        self.ballot_snapshot_hash = ballot_snapshot_hash
        self.supersedes = supersedes

    def to_record(self) -> dict:
        """Serialise to the canonical ballot record shape."""
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
            "votes": self.votes,
            "tally": self.tally,
            "quorum_met": self.quorum_met,
            "result": self.result,
            "ballot_snapshot_hash": self.ballot_snapshot_hash,
            "supersedes": self.supersedes,
        }

    @classmethod
    def from_record(cls, record: dict) -> "Ballot":
        return cls(
            ballot_id=record["ballot_id"],
            proposal_id=record["proposal_id"],
            open_comment_id=record["open_comment_id"],
            close_comment_id=record.get("close_comment_id"),
            voting_hours=record["voting_hours"],
            opens_at=record.get("opens_at"),
            closes_at=record.get("closes_at"),
            eligibility_rule=record["eligibility_rule"],
            eligibility_snapshot=record["eligibility_snapshot"],
            nonce=record["nonce"],
            quorum_rule=record["quorum_rule"],
            votes=record["votes"],
            tally=record["tally"],
            quorum_met=record["quorum_met"],
            result=record.get("result"),
            ballot_snapshot_hash=record.get("ballot_snapshot_hash"),
            supersedes=record.get("supersedes"),
        )


# --------------------------------------------------------------------------
# Vote snapshot
# --------------------------------------------------------------------------


def snapshot_hash(votes: list) -> str:
    """sha256(JCS(votes array)) — frozen at close, published at
    votes/<decision_id>.json."""
    return hashlib.sha256(canonical_bytes(votes)).hexdigest()


def required_quorum(eligible_count: int) -> int:
    """Voters who must participate for a ballot to count.

    Below five eligible members, quorum is every eligible voter — otherwise a
    founding ballot is void by construction and can never be re-run into a pass.
    Integer arithmetic only: 0.20 * n in binary float drifts (0.20 * 1_000_000
    is 200000.00000000003, whose ceil is 200001), and this number shapes the
    record's quorum_met, so it cannot be approximate.
    """
    if eligible_count < 5:
        return eligible_count
    return min(eligible_count, max(5, (eligible_count * 20 + 99) // 100))


def normalize_vote(
    voter_gh_id: int,
    comment_id: int,
    created_at: str,
    updated_at: str,
    body_sha256: str,
    source: str,
) -> dict:
    """One vote entry in the normalized snapshot. Latest valid entry per
    voter counts; a deleted comment voids that vote; pre-close edits are
    legal because updated_at is server-side."""
    if source not in VOTE_SOURCES:
        raise VoteError(f"unknown vote source {source!r}; must be one of {VOTE_SOURCES}")
    return {
        "voter_gh_id": voter_gh_id,
        "comment_id": comment_id,
        "created_at": created_at,
        "updated_at": updated_at,
        "body_sha256": body_sha256,
        "source": source,
    }


def compute_tally(votes: list) -> dict:
    """Count the snapshot once, at close. No running percentage."""
    tally = {"approve": 0, "reject": 0, "abstain": 0}
    for vote in votes:
        choice = vote.get("choice", "abstain")
        if choice in tally:
            tally[choice] += 1
    return tally


def latest_per_voter(votes: list) -> list:
    """Collapse to the latest valid entry per voter. A deleted comment
    voids that vote (missing comment_id means voided)."""
    latest: dict[int, dict] = {}
    for vote in votes:
        voter = vote["voter_gh_id"]
        # A voided vote (deleted comment) has no comment_id; skip it but
        # remember the voter so later entries can still count.
        if vote.get("comment_id") is None:
            latest.pop(voter, None)
            continue
        latest[voter] = vote
    return list(latest.values())


# --------------------------------------------------------------------------
# Timing — the single 48-hour window
# --------------------------------------------------------------------------


def validate_window(opens_at: str, closes_at: str, voting_hours: int = VOTING_HOURS) -> None:
    """closes_at - opens_at must equal voting_hours, both GitHub-stamped.
    Never a local clock. Compared in integer seconds so no float can drift the
    window: 48h is exactly 172800s, not 47.999999h."""
    open_dt = datetime.fromisoformat(opens_at.replace("Z", "+00:00"))
    close_dt = datetime.fromisoformat(closes_at.replace("Z", "+00:00"))
    delta_seconds = int((close_dt - open_dt).total_seconds())
    expected = voting_hours * 3600
    if delta_seconds != expected:
        raise WindowError(
            f"window is {delta_seconds}s, must be exactly {expected}s "
            f"({voting_hours}h, close - open, GitHub-stamped)"
        )


# --------------------------------------------------------------------------
# Ballot engine — SQLite-backed state
# --------------------------------------------------------------------------


class BallotEngine:
    """Opens, closes, and snapshots 48-hour ratification ballots.

    State lives in SQLite. Ballot records produced here are appended to the
    `ledger` branch by the ledger writer — this module never touches git.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ballots (
                ballot_id       TEXT PRIMARY KEY,
                proposal_id     TEXT NOT NULL,
                open_comment_id INTEGER NOT NULL,
                close_comment_id INTEGER,
                voting_hours    INTEGER NOT NULL,
                opens_at        TEXT,
                closes_at       TEXT,
                eligibility_rule TEXT NOT NULL,
                eligibility_snapshot TEXT NOT NULL,
                nonce           TEXT NOT NULL,
                quorum_rule     TEXT NOT NULL,
                votes           TEXT NOT NULL,
                tally           TEXT NOT NULL,
                quorum_met      INTEGER NOT NULL,
                result          TEXT,
                snapshot_hash   TEXT,
                supersedes      TEXT,
                opened_at       TEXT NOT NULL,
                closed_at       TEXT
            );
            CREATE TABLE IF NOT EXISTS ballot_events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ballot_id  TEXT NOT NULL,
                event      TEXT NOT NULL,
                payload    TEXT NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        self._conn.commit()

    # -- open --------------------------------------------------------------

    def open_ballot(
        self,
        ballot_id: str,
        proposal_id: str,
        open_comment_id: int,
        opens_at: str,
        eligibility_rule: dict,
        eligibility_snapshot: dict,
        nonce: str,
        quorum_rule: dict,
    ) -> Ballot:
        """Open a 48-hour ballot. `opens_at` comes from the open comment's
        GitHub-stamped created_at — never a local clock."""
        if self._conn.execute(
            "SELECT 1 FROM ballots WHERE ballot_id = ?", (ballot_id,)
        ).fetchone():
            raise BallotError(f"ballot {ballot_id} already exists")

        # Refuse what we do not implement: weighted tallies are read but never
        # applied, so refuse the flag rather than silently ignore it. Quorum is
        # derived from the frozen roster snapshot — the caller must not supply a
        # number here. threshold is a fixed-decimal string, default 0.50.
        if quorum_rule.get("weighted"):
            raise BallotError("weighted tallies are not implemented; weighted=true is refused, not ignored")
        try:
            threshold = float(quorum_rule.get("threshold", "0.50"))
        except (TypeError, ValueError):
            raise BallotError(f"threshold must be a decimal string, got {quorum_rule.get('threshold')!r}")
        if threshold < 0 or threshold > 1:
            raise BallotError(f"threshold must be between 0 and 1, got {threshold}")

        # Validate the window will be 48h: closes_at is derived, not declared
        closes_at = self._derive_closes_at(opens_at)

        ballot = Ballot(
            ballot_id=ballot_id,
            proposal_id=proposal_id,
            open_comment_id=open_comment_id,
            close_comment_id=None,
            voting_hours=VOTING_HOURS,
            opens_at=opens_at,
            closes_at=closes_at,
            eligibility_rule=eligibility_rule,
            eligibility_snapshot=eligibility_snapshot,
            nonce=nonce,
            quorum_rule=quorum_rule,
            votes=[],
            tally={"approve": 0, "reject": 0, "abstain": 0},
            quorum_met=False,
            result=None,
            ballot_snapshot_hash=None,
            supersedes=None,
        )

        self._conn.execute(
            """
            INSERT INTO ballots
            (ballot_id, proposal_id, open_comment_id, voting_hours, opens_at,
             closes_at, eligibility_rule, eligibility_snapshot, nonce,
             quorum_rule, votes, tally, quorum_met, result, snapshot_hash,
             supersedes, opened_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ballot.ballot_id,
                ballot.proposal_id,
                ballot.open_comment_id,
                ballot.voting_hours,
                ballot.opens_at,
                ballot.closes_at,
                json.dumps(ballot.eligibility_rule),
                json.dumps(ballot.eligibility_snapshot),
                ballot.nonce,
                json.dumps(ballot.quorum_rule),
                json.dumps(ballot.votes),
                json.dumps(ballot.tally),
                0,
                None,
                None,
                None,
                ballot.opens_at,
            ),
        )
        self._conn.commit()
        return ballot

    def _derive_closes_at(self, opens_at: str) -> str:
        """closes_at = opens_at + voting_hours, ISO8601 Z."""
        dt = datetime.fromisoformat(opens_at.replace("Z", "+00:00"))
        from datetime import timedelta

        close_dt = dt + timedelta(hours=VOTING_HOURS)
        return close_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    # -- vote --------------------------------------------------------------

    def cast_vote(
        self,
        ballot_id: str,
        voter_gh_id: int,
        comment_id: int,
        created_at: str,
        updated_at: str,
        body_sha256: str,
        source: str = "reaction",
        choice: str = "approve",
    ) -> None:
        """Record a vote. The vote is authored by the voter's own token —
        the engine never authors votes (CONTRACTS.md Section 4)."""
        row = self._conn.execute(
            "SELECT votes, opens_at, closes_at, close_comment_id FROM ballots WHERE ballot_id = ?",
            (ballot_id,),
        ).fetchone()
        if not row:
            raise BallotError(f"ballot {ballot_id} not found")
        if row[3] is not None:
            raise VoteError(f"ballot {ballot_id} is closed")
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        opens = datetime.fromisoformat(row[1].replace("Z", "+00:00"))
        closes = datetime.fromisoformat(row[2].replace("Z", "+00:00"))
        if not (opens <= created <= closes):
            raise VoteError(f"vote at {created_at} is outside {row[1]} .. {row[2]}")

        votes = json.loads(row[0])
        votes.append(
            normalize_vote(voter_gh_id, comment_id, created_at, updated_at, body_sha256, source)
        )
        # Add choice to the latest entry for tally purposes
        votes[-1]["choice"] = choice

        self._conn.execute(
            "UPDATE ballots SET votes = ? WHERE ballot_id = ?",
            (json.dumps(votes), ballot_id),
        )
        self._conn.commit()

    # -- close -------------------------------------------------------------

    def close_ballot(
        self,
        ballot_id: str,
        close_comment_id: int,
        closes_at: str,
    ) -> Ballot:
        """Close the ballot at the GitHub-stamped close comment time.

        Validates the 48-hour window, snapshots votes, computes the tally,
        and determines the result. The snapshot is published at
        votes/<decision_id>.json by the caller (ledger writer).
        """
        row = self._conn.execute(
            "SELECT * FROM ballots WHERE ballot_id = ?", (ballot_id,)
        ).fetchone()
        if not row:
            raise BallotError(f"ballot {ballot_id} not found")

        if row[3] is not None:  # close_comment_id
            raise BallotError(f"ballot {ballot_id} already closed")

        opens_at = row[5]
        validate_window(opens_at, closes_at, row[4])  # voting_hours

        votes = json.loads(row[11])
        # Filter by the close timestamp first — a vote that slipped in during
        # the tick gap after closes_at cannot count even if it was written.
        close_dt = datetime.fromisoformat(closes_at.replace("Z", "+00:00"))
        votes = [
            v for v in votes
            if datetime.fromisoformat(v["created_at"].replace("Z", "+00:00")) <= close_dt
        ]
        # Collapse to latest valid entry per voter; deleted comments voided
        snapshot = latest_per_voter(votes)
        snap_hash = snapshot_hash(snapshot)
        tally = compute_tally(snapshot)

        # Quorum rule from the ballot record
        quorum_rule = json.loads(row[10])
        eligibility_snapshot = json.loads(row[8])
        quorum_met = self._check_quorum(
            tally, quorum_rule, int(eligibility_snapshot["eligible_count"])
        )

        # Result: void means quorum only. Once quorum is met, the approval
        # threshold decides ratified vs rejected — a tie is rejected, never
        # void, so a re-run is never spent on a 50/50.
        if not quorum_met:
            result = "void"
        else:
            yes_no = tally["approve"] + tally["reject"]
            threshold = Decimal(str(quorum_rule.get("threshold", "0.50")))
            if yes_no > 0 and Decimal(tally["approve"]) / Decimal(yes_no) > threshold:
                result = "ratified"
            else:
                result = "rejected"

        ballot = Ballot(
            ballot_id=ballot_id,
            proposal_id=row[2],
            open_comment_id=row[3],
            close_comment_id=close_comment_id,
            voting_hours=row[4],
            opens_at=row[5],
            closes_at=closes_at,
            eligibility_rule=json.loads(row[7]),
            eligibility_snapshot=json.loads(row[8]),
            nonce=row[9],
            quorum_rule=quorum_rule,
            votes=snapshot,
            tally=tally,
            quorum_met=quorum_met,
            result=result,
            ballot_snapshot_hash=snap_hash,
            supersedes=None,
        )

        self._conn.execute(
            """
            UPDATE ballots
            SET close_comment_id = ?, closes_at = ?, votes = ?, tally = ?,
                quorum_met = ?, result = ?, snapshot_hash = ?, closed_at = ?
            WHERE ballot_id = ?
            """,
            (
                close_comment_id,
                closes_at,
                json.dumps(snapshot),
                json.dumps(tally),
                1 if quorum_met else 0,
                result,
                snap_hash,
                closes_at,
                ballot_id,
            ),
        )
        self._conn.commit()
        return ballot

    # -- quorum ------------------------------------------------------------

    def _check_quorum(self, tally: dict, quorum_rule: dict, eligible_count: int) -> bool:
        """Participation quorum: did enough of the frozen roster vote?

        Quorum is participation only. The approval threshold is applied when
        the result is decided, so a ballot that reaches quorum but fails the
        threshold is `rejected`, not `void` — a re-run is legitimate only when
        the roster did not turn out. `quorum_rule` is accepted for the record;
        the participation number is derived from the roster, never from it.
        """
        required = required_quorum(eligible_count)
        participating = tally["approve"] + tally["reject"] + tally["abstain"]  # abstain is participation
        return participating >= required

    # -- read --------------------------------------------------------------

    def get_ballot(self, ballot_id: str) -> Ballot | None:
        row = self._conn.execute(
            "SELECT * FROM ballots WHERE ballot_id = ?", (ballot_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_ballot(row)

    def list_ballots(self) -> list[Ballot]:
        rows = self._conn.execute("SELECT * FROM ballots ORDER BY opened_at").fetchall()
        return [self._row_to_ballot(r) for r in rows]

    def _row_to_ballot(self, row: tuple) -> Ballot:
        return Ballot(
            ballot_id=row[1],
            proposal_id=row[2],
            open_comment_id=row[3],
            close_comment_id=row[4],
            voting_hours=row[4],
            opens_at=row[5],
            closes_at=row[6],
            eligibility_rule=json.loads(row[7]),
            eligibility_snapshot=json.loads(row[8]),
            nonce=row[9],
            quorum_rule=json.loads(row[10]),
            votes=json.loads(row[11]),
            tally=json.loads(row[12]),
            quorum_met=bool(row[13]),
            result=row[14],
            ballot_snapshot_hash=row[15],
            supersedes=row[16],
        )

    def close(self) -> None:
        self._conn.close()


# --------------------------------------------------------------------------
# Proposal id allocation
# --------------------------------------------------------------------------


def next_proposal_id(existing: list[str]) -> str:
    """prop-YYYY-NNNN — stable, not the issue number."""
    import re

    pattern = re.compile(r"^prop-(\d{4})-(\d{4})$")
    max_n = 0
    year = datetime.now(timezone.utc).strftime("%Y")
    for eid in existing:
        m = pattern.match(eid)
        if m and m.group(1) == year:
            max_n = max(max_n, int(m.group(2)))
    return f"prop-{year}-{max_n + 1:04d}"


def next_ballot_id(existing: list[str]) -> str:
    """bal-YYYY-NNNN — stable, not the issue number."""
    import re

    pattern = re.compile(r"^bal-(\d{4})-(\d{4})$")
    max_n = 0
    year = datetime.now(timezone.utc).strftime("%Y")
    for eid in existing:
        m = pattern.match(eid)
        if m and m.group(1) == year:
            max_n = max(max_n, int(m.group(2)))
    return f"bal-{year}-{max_n + 1:04d}"
