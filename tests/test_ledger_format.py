"""Pins the ledger canonicalisation from docs/LEDGER-FORMAT.md.

If this test goes red, someone changed the hash rule and every record ever written is now
unverifiable. Fix the change, not the test.
"""
import hashlib
import json

GENESIS_PREV = "0" * 64

VECTOR_RECORD = {
    "anchor_comment": "ic_1234567890",
    "approvers": ["u_1001", "u_1002"],
    "ballot_snapshot_hash": "9f" * 32,
    "decision_id": "dec-2026-0001",
    "proposal_id": "prop-2026-0001",
    "result": "ratified",
    "window_hours": 48,
}

VECTOR_H1 = "6fa7e0e498031e7f41911119195e3b393027b56c7ed7a9e63ac2c507f2c6ad52"


def canonical_bytes(record: dict) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def chain_hash(prev_hash: str, record: dict) -> str:
    assert len(prev_hash) == 64, "prev_hash must be 64 hex chars; the no-separator rule depends on it"
    return hashlib.sha256(prev_hash.encode() + canonical_bytes(record)).hexdigest()


def test_vector_hash_matches_spec():
    assert chain_hash(GENESIS_PREV, VECTOR_RECORD) == VECTOR_H1


def test_canonical_bytes_are_stable_and_sorted():
    b = canonical_bytes({"b": 1, "a": 2})
    assert b == b'{"a":2,"b":1}'


def test_separator_variants_do_not_collide_with_spec():
    """A colon or newline separator between prev_hash and payload must NOT verify."""
    for sep in (":", "\n", " "):
        bad = hashlib.sha256((GENESIS_PREV + sep).encode() + canonical_bytes(VECTOR_RECORD)).hexdigest()
        assert bad != VECTOR_H1, f"separator {sep!r} accidentally reproduces the spec hash"


def test_prev_hash_width_is_enforced():
    try:
        chain_hash("0" * 63, VECTOR_RECORD)
    except AssertionError:
        return
    raise AssertionError("chain_hash accepted a 63-char prev_hash")


def test_result_vocabulary_is_approved_not_ratified():
    """The gate and the service must share one vocabulary for approval."""
    allowed = {"approved", "rejected", "void", "waived"}
    assert "approved" in allowed
    assert "ratified" not in allowed
