"""Conformance tests for the ballot engine (docs/CONTRACTS.md Sections 3-4).

The 48-hour window, vote snapshot, tally, and quorum rules are normative.
If a future change makes a test fail, the change is wrong — do not update
the expectation to match the code.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from service.ballot_engine import (  # noqa: E402
    Ballot,
    BallotEngine,
    BallotError,
    WindowError,
    VoteError,
    canonical_json,
    canonical_bytes,
    compute_tally,
    latest_per_voter,
    next_ballot_id,
    next_proposal_id,
    required_quorum,
    normalize_vote,
    snapshot_hash,
    validate_window,
    VOTING_HOURS,
)

OPENED_AT = "2026-11-25T10:00:00.000Z"
CLOSED_AT = "2026-11-27T10:00:00.000Z"  # exactly 48h later
IN_WINDOW_AT = "2026-11-26T10:00:00.000Z"  # 24h into the 48h window


def _make_engine() -> BallotEngine:
    return BallotEngine(":memory:")


# --------------------------------------------------------------------------
# Timing — the single 48-hour window
# --------------------------------------------------------------------------


def test_window_exactly_48h_passes():
    validate_window(OPENED_AT, CLOSED_AT, VOTING_HOURS)


def test_window_too_short_fails():
    try:
        validate_window(OPENED_AT, "2026-11-26T10:00:00.000Z", VOTING_HOURS)
    except WindowError:
        return
    raise AssertionError("47h window must be rejected")


def test_window_too_long_fails():
    try:
        validate_window(OPENED_AT, "2026-11-28T10:00:00.000Z", VOTING_HOURS)
    except WindowError:
        return
    raise AssertionError("72h window must be rejected")


def test_voting_hours_is_48_constant():
    assert VOTING_HOURS == 48


# --------------------------------------------------------------------------
# Ballot open / close
# --------------------------------------------------------------------------


def test_open_ballot_creates_record():
    eng = _make_engine()
    b = eng.open_ballot(
        ballot_id="bal-2026-0001",
        proposal_id="prop-2026-0001",
        open_comment_id=191234567,
        opens_at=OPENED_AT,
        eligibility_rule={"rule": "founding_roster"},
        eligibility_snapshot={"hash": "ab" * 32, "ref": "refs/heads/main"},
        nonce="nonce-abc123",
        quorum_rule={"quorum": "0.20", "threshold": "0.50", "weighted": False},
    )
    assert b.ballot_id == "bal-2026-0001"
    assert b.proposal_id == "prop-2026-0001"
    assert b.open_comment_id == 191234567
    assert b.voting_hours == 48
    assert b.opens_at == OPENED_AT
    assert b.closes_at == CLOSED_AT  # derived, 48h after open
    assert b.result is None
    assert b.close_comment_id is None


def test_open_ballot_duplicate_fails():
    eng = _make_engine()
    eng.open_ballot(
        ballot_id="bal-2026-0001",
        proposal_id="prop-2026-0001",
        open_comment_id=191234567,
        opens_at=OPENED_AT,
        eligibility_rule={},
        eligibility_snapshot={},
        nonce="n",
        quorum_rule={},
    )
    try:
        eng.open_ballot(
            ballot_id="bal-2026-0001",
            proposal_id="prop-2026-0001",
            open_comment_id=191234568,
            opens_at=OPENED_AT,
            eligibility_rule={},
            eligibility_snapshot={},
            nonce="n",
            quorum_rule={},
        )
    except BallotError:
        return
    raise AssertionError("duplicate ballot id must be rejected")


def test_close_ballot_validates_window():
    eng = _make_engine()
    eng.open_ballot(
        ballot_id="bal-2026-0001",
        proposal_id="prop-2026-0001",
        open_comment_id=191234567,
        opens_at=OPENED_AT,
        eligibility_rule={},
        eligibility_snapshot={},
        nonce="n",
        quorum_rule={},
    )
    try:
        eng.close_ballot(
            ballot_id="bal-2026-0001",
            close_comment_id=191234999,
            closes_at="2026-11-26T10:00:00.000Z",  # 24h, not 48
        )
    except WindowError:
        return
    raise AssertionError("close outside 48h window must be rejected")


def test_close_ballot_twice_fails():
    eng = _make_engine()
    eng.open_ballot(
        ballot_id="bal-2026-0001",
        proposal_id="prop-2026-0001",
        open_comment_id=191234567,
        opens_at=OPENED_AT,
        eligibility_rule={},
        eligibility_snapshot={"eligible_count": 1},
        nonce="n",
        quorum_rule={"threshold": "0.50", "weighted": False},
    )
    eng.close_ballot(
        ballot_id="bal-2026-0001",
        close_comment_id=191234999,
        closes_at=CLOSED_AT,
    )
    try:
        eng.close_ballot(
            ballot_id="bal-2026-0001",
            close_comment_id=191235000,
            closes_at=CLOSED_AT,
        )
    except BallotError:
        return
    raise AssertionError("double close must be rejected")


# --------------------------------------------------------------------------
# Votes — snapshot, tally, latest-per-voter
# --------------------------------------------------------------------------


def test_vote_snapshot_hash():
    votes = [
        {
            "voter_gh_id": 1001,
            "comment_id": 191234701,
            "created_at": "2026-11-23T10:00:00.000Z",
            "updated_at": "2026-11-23T10:00:00.000Z",
            "body_sha256": "ab" * 32,
            "source": "reaction",
            "choice": "approve",
        }
    ]
    h = snapshot_hash(votes)
    expected = hashlib_sha256_json(votes)
    assert h == expected


def test_tally_counts_once():
    votes = [
        {"voter_gh_id": 1001, "choice": "approve"},
        {"voter_gh_id": 1002, "choice": "reject"},
        {"voter_gh_id": 1003, "choice": "abstain"},
        {"voter_gh_id": 1004, "choice": "approve"},
    ]
    t = compute_tally(votes)
    assert t == {"approve": 2, "reject": 1, "abstain": 1}


def test_latest_per_voter_collapses():
    votes = [
        {"voter_gh_id": 1001, "comment_id": 1, "choice": "reject"},
        {"voter_gh_id": 1001, "comment_id": 2, "choice": "approve"},
        {"voter_gh_id": 1002, "comment_id": 3, "choice": "approve"},
    ]
    collapsed = latest_per_voter(votes)
    assert len(collapsed) == 2
    ids = {v["comment_id"] for v in collapsed}
    assert ids == {2, 3}  # voter 1001's latest (id 2) wins


def test_deleted_comment_voides_vote():
    votes = [
        {"voter_gh_id": 1001, "comment_id": 1, "choice": "approve"},
        {"voter_gh_id": 1001, "comment_id": None, "choice": None},  # deleted
    ]
    collapsed = latest_per_voter(votes)
    assert collapsed == []  # voided, nothing left


def test_vote_source_validation():
    try:
        normalize_vote(1001, 1, "2026-11-23T10:00:00.000Z", "2026-11-23T10:00:00.000Z", "ab" * 32, "email")
    except VoteError:
        return
    raise AssertionError("invalid vote source must be rejected")


# --------------------------------------------------------------------------
# Close flow — snapshot + tally + result
# --------------------------------------------------------------------------


def test_close_snapshot_hash_stored():
    eng = _make_engine()
    eng.open_ballot(
        ballot_id="bal-2026-0001",
        proposal_id="prop-2026-0001",
        open_comment_id=191234567,
        opens_at=OPENED_AT,
        eligibility_rule={},
        eligibility_snapshot={"eligible_count": 1},
        nonce="n",
        quorum_rule={"threshold": "0.50", "weighted": False},
    )
    eng.cast_vote("bal-2026-0001", 1001, 191234701, IN_WINDOW_AT, IN_WINDOW_AT, "ab" * 32, "reaction", "approve")
    b = eng.close_ballot("bal-2026-0001", 191234999, CLOSED_AT)
    assert b.ballot_snapshot_hash is not None
    assert len(b.ballot_snapshot_hash) == 64
    assert b.votes == [
        {
            "voter_gh_id": 1001,
            "comment_id": 191234701,
            "created_at": IN_WINDOW_AT,
            "updated_at": IN_WINDOW_AT,
            "body_sha256": "ab" * 32,
            "source": "reaction",
            "choice": "approve",
        }
    ]


def test_close_result_ratified():
    eng = _make_engine()
    eng.open_ballot(
        ballot_id="bal-2026-0001",
        proposal_id="prop-2026-0001",
        open_comment_id=191234567,
        opens_at=OPENED_AT,
        eligibility_rule={},
        eligibility_snapshot={"eligible_count": 3},
        nonce="n",
        quorum_rule={"threshold": "0.50", "weighted": False},
    )
    eng.cast_vote("bal-2026-0001", 1001, 1, IN_WINDOW_AT, IN_WINDOW_AT, "ab" * 32, "reaction", "approve")
    eng.cast_vote("bal-2026-0001", 1002, 2, IN_WINDOW_AT, IN_WINDOW_AT, "ab" * 32, "reaction", "approve")
    eng.cast_vote("bal-2026-0001", 1003, 3, IN_WINDOW_AT, IN_WINDOW_AT, "ab" * 32, "reaction", "reject")
    b = eng.close_ballot("bal-2026-0001", 191234999, CLOSED_AT)
    assert b.result == "ratified"
    assert b.tally == {"approve": 2, "reject": 1, "abstain": 0}
    assert b.quorum_met is True


def test_close_result_rejected():
    eng = _make_engine()
    eng.open_ballot(
        ballot_id="bal-2026-0001",
        proposal_id="prop-2026-0001",
        open_comment_id=191234567,
        opens_at=OPENED_AT,
        eligibility_rule={},
        eligibility_snapshot={"eligible_count": 3},
        nonce="n",
        quorum_rule={"threshold": "0.50", "weighted": False},
    )
    eng.cast_vote("bal-2026-0001", 1001, 1, IN_WINDOW_AT, IN_WINDOW_AT, "ab" * 32, "reaction", "reject")
    eng.cast_vote("bal-2026-0001", 1002, 2, IN_WINDOW_AT, IN_WINDOW_AT, "ab" * 32, "reaction", "reject")
    eng.cast_vote("bal-2026-0001", 1003, 3, IN_WINDOW_AT, IN_WINDOW_AT, "ab" * 32, "reaction", "approve")
    b = eng.close_ballot("bal-2026-0001", 191234999, CLOSED_AT)
    assert b.result == "rejected"
    assert b.quorum_met is True  # quorum is participation; the rejection is the threshold


def test_close_result_void_no_quorum():
    eng = _make_engine()
    eng.open_ballot(
        ballot_id="bal-2026-0001",
        proposal_id="prop-2026-0001",
        open_comment_id=191234567,
        opens_at=OPENED_AT,
        eligibility_rule={},
        eligibility_snapshot={"eligible_count": 3},
        nonce="n",
        quorum_rule={"threshold": "0.50", "weighted": False},
    )
    # No votes cast — quorum cannot be met with zero participation
    b = eng.close_ballot("bal-2026-0001", 191234999, CLOSED_AT)
    assert b.result == "void"
    assert b.quorum_met is False
    assert b.tally == {"approve": 0, "reject": 0, "abstain": 0}


def test_close_result_tie_rejected():
    """A tie is rejected, never void. Void is reserved for a quorum miss, and
    only void triggers the automatic re-run — so a 50/50 does not get a fresh
    48h window."""
    eng = _make_engine()
    eng.open_ballot(
        ballot_id="bal-2026-0001",
        proposal_id="prop-2026-0001",
        open_comment_id=191234567,
        opens_at=OPENED_AT,
        eligibility_rule={},
        eligibility_snapshot={"eligible_count": 2},
        nonce="n",
        quorum_rule={"threshold": "0.50", "weighted": False},
    )
    eng.cast_vote("bal-2026-0001", 1001, 1, IN_WINDOW_AT, IN_WINDOW_AT, "ab" * 32, "reaction", "approve")
    eng.cast_vote("bal-2026-0001", 1002, 2, IN_WINDOW_AT, IN_WINDOW_AT, "ab" * 32, "reaction", "reject")
    b = eng.close_ballot("bal-2026-0001", 191234999, CLOSED_AT)
    assert b.result == "rejected"
    assert b.result != "void"  # void would spend a 48h re-run on a 50/50
    assert b.quorum_met is True


# --------------------------------------------------------------------------
# Quorum — measured against the frozen roster, not the ballots received
# --------------------------------------------------------------------------


def _open(eng: BallotEngine, eligible_count: int, quorum_rule: dict | None = None) -> None:
    eng.open_ballot(
        ballot_id="bal-2026-0001",
        proposal_id="prop-2026-0001",
        open_comment_id=191234567,
        opens_at=OPENED_AT,
        eligibility_rule={},
        eligibility_snapshot={"eligible_count": eligible_count},
        nonce="n",
        quorum_rule=quorum_rule or {"threshold": "0.50", "weighted": False},
    )


def test_quorum_100_eligible_one_vote_is_void():
    eng = _make_engine()
    _open(eng, 100)
    eng.cast_vote("bal-2026-0001", 1001, 1, IN_WINDOW_AT, IN_WINDOW_AT, "ab" * 32, "reaction", "approve")
    b = eng.close_ballot("bal-2026-0001", 191234999, CLOSED_AT)
    assert b.quorum_met is False
    assert b.result == "void"


def test_quorum_100_eligible_20_votes_is_met():
    eng = _make_engine()
    _open(eng, 100)
    for i in range(20):
        choice = "approve" if i < 12 else "reject"
        eng.cast_vote("bal-2026-0001", 2000 + i, 100 + i, IN_WINDOW_AT, IN_WINDOW_AT, "ab" * 32, "reaction", choice)
    b = eng.close_ballot("bal-2026-0001", 191234999, CLOSED_AT)
    assert b.quorum_met is True
    assert b.result == "ratified"


def test_quorum_four_eligible_all_vote_is_met():
    eng = _make_engine()
    _open(eng, 4)
    for i in range(4):
        choice = "approve" if i < 3 else "reject"
        eng.cast_vote("bal-2026-0001", 3000 + i, 200 + i, IN_WINDOW_AT, IN_WINDOW_AT, "ab" * 32, "reaction", choice)
    b = eng.close_ballot("bal-2026-0001", 191234999, CLOSED_AT)
    assert b.quorum_met is True
    assert b.result == "ratified"


def test_quorum_four_eligible_three_votes_is_void():
    eng = _make_engine()
    _open(eng, 4)
    for i in range(3):
        eng.cast_vote("bal-2026-0001", 3000 + i, 200 + i, IN_WINDOW_AT, IN_WINDOW_AT, "ab" * 32, "reaction", "approve")
    b = eng.close_ballot("bal-2026-0001", 191234999, CLOSED_AT)
    assert b.quorum_met is False
    assert b.result == "void"


def test_majority_reject_is_rejected_not_void():
    """A ballot that reaches quorum but is rejected is `rejected`, not `void`.
    Void must mean a quorum miss only, or every rejection buys a 48h re-run."""
    eng = _make_engine()
    _open(eng, 100)
    for i in range(20):
        choice = "approve" if i < 8 else "reject"  # 8 approve / 12 reject
        eng.cast_vote("bal-2026-0001", 2000 + i, 100 + i, IN_WINDOW_AT, IN_WINDOW_AT, "ab" * 32, "reaction", choice)
    b = eng.close_ballot("bal-2026-0001", 191234999, CLOSED_AT)
    assert b.quorum_met is True
    assert b.result == "rejected"


def test_vote_after_close_rejected_on_cast():
    eng = _make_engine()
    _open(eng, 1)
    late = "2026-11-27T10:00:01.000Z"  # one second after closes_at
    try:
        eng.cast_vote("bal-2026-0001", 1001, 1, late, late, "ab" * 32, "reaction", "approve")
    except VoteError:
        return
    raise AssertionError("a vote after closes_at must be rejected on cast")


def test_vote_after_close_excluded_from_snapshot():
    eng = _make_engine()
    _open(eng, 1)
    late = {
        "voter_gh_id": 1001,
        "comment_id": 1,
        "created_at": "2026-11-27T10:00:01.000Z",  # slipped in after the close
        "updated_at": "2026-11-27T10:00:01.000Z",
        "body_sha256": "ab" * 32,
        "source": "reaction",
        "choice": "approve",
    }
    # Seed it directly, as the tick-gap race would: the row is written but late.
    eng._conn.execute(
        "UPDATE ballots SET votes = ? WHERE ballot_id = ?",
        (json.dumps([late]), "bal-2026-0001"),
    )
    eng._conn.commit()
    b = eng.close_ballot("bal-2026-0001", 191234999, CLOSED_AT)
    assert b.votes == []
    assert b.tally == {"approve": 0, "reject": 0, "abstain": 0}


def test_open_refuses_weighted():
    eng = _make_engine()
    try:
        _open(eng, 3, {"threshold": "0.50", "weighted": True})
    except BallotError:
        return
    raise AssertionError("weighted=true must be refused at open, not ignored")


def test_required_quorum_is_exact_at_scale():
    """20% is integer arithmetic, not a float multiply: 0.20 * 1_000_000 in
    binary float is 200000.00000000003, whose ceil is 200001."""
    assert required_quorum(1_000_000) == 200_000
    assert required_quorum(100) == 20
    assert required_quorum(26) == 6
    assert required_quorum(25) == 5
    assert required_quorum(5) == 5
    assert required_quorum(4) == 4  # below five, every eligible voter
    assert required_quorum(0) == 0


# --------------------------------------------------------------------------
# Id allocation
# --------------------------------------------------------------------------


def test_proposal_id_format():
    assert next_proposal_id([]) == f"prop-{__import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime('%Y')}-0001"
    assert next_proposal_id(["prop-2026-0001", "prop-2026-0005"]) == "prop-2026-0006"


def test_ballot_id_format():
    assert next_ballot_id([]) == f"bal-{__import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime('%Y')}-0001"
    assert next_ballot_id(["bal-2026-0001", "bal-2026-0003"]) == "bal-2026-0004"


# --------------------------------------------------------------------------
# Canonical JSON (JCS)
# --------------------------------------------------------------------------


def test_canonical_json_no_whitespace():
    obj = {"b": 2, "a": 1}
    assert canonical_json(obj) == '{"a":1,"b":2}'


def test_canonical_json_integers_only():
    try:
        canonical_json({"x": 0.5})
    except ValueError as exc:
        assert "float" in str(exc)
    else:
        raise AssertionError("floats must be rejected")


def test_canonical_bytes_match_doc_example():
    votes = [
        {
            "voter_gh_id": 1001,
            "comment_id": 191234701,
            "created_at": "2026-11-23T10:00:00.000Z",
            "updated_at": "2026-11-23T10:00:00.000Z",
            "body_sha256": "ab" * 32,
            "source": "reaction",
        }
    ]
    h = snapshot_hash(votes)
    expected = hashlib_sha256_json(votes)
    assert h == expected


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def hashlib_sha256_json(obj):
    import hashlib

    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {exc}")
    print("ALL GREEN" if failures == 0 else f"{failures} FAILED")
    raise SystemExit(1 if failures else 0)
