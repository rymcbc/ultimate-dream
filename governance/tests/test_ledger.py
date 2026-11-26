"""Conformance tests for the ledger writer (docs/LEDGER-FORMAT.md v3).

The vector below is normative. If a future change makes it fail, the change is
wrong — do not update the expectation to match the code. The three retired
shapes (v0 sketch, v1, v2-draft) are pinned as *must fail* so nobody restores
one by accident.

Signature verification fails closed: no trust root, no signature, or a bad
signature means verification fails.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from governance.ledger import (  # noqa: E402
    GENESIS_PREV_HASH,
    LedgerError,
    SignatureError,
    canonical_json,
    record_hash,
    seal,
    validate,
    verify_chain,
    verify_record,
    votes_snapshot_hash,
)

HEAD_SHA = "4f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d"

RECORD = {
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
    "head_sha": HEAD_SHA,
    "approvers": [{"gh_id": 1001, "review_id": 3912345678, "reviewed_sha": HEAD_SHA}],
    "supersedes": None,
    "created_by": "githubapp:ultimate-dream-ledger",
    "signer_key_id": "k1",
    "prev_hash": GENESIS_PREV_HASH,
}

EXPECTED_HASH = "843665b13896c04e4acb3a386d149f6f5899943000414862a19cedf360bb63dc"
EXPECTED_SNAPSHOT = "fb7fb3e41180e4e28cdb6b97355d5c3b358ebafeb2c23a6daefd3edd8a5a9563"

VOTES = [
    {
        "voter_gh_id": 1001,
        "comment_id": 191234701,
        "created_at": "2026-11-23T10:00:00.000Z",
        "updated_at": "2026-11-23T10:00:00.000Z",
        "body_sha256": "ab" * 32,
    }
]

# Retired shapes that must never verify.
V0_RECORD = dict(RECORD)
V0_RECORD["schema_version"] = 0
V0_RECORD["voting_hours"] = 72
V0_RECORD.pop("owner_notice_comment_id", None)
V0_RECORD.pop("owner_decision", None)
V0_RECORD.pop("owner_override_ground", None)

V1_RECORD = dict(RECORD)
V1_RECORD["schema_version"] = 1
V1_RECORD["voting_hours"] = 72

V2_DRAFT_RECORD = dict(RECORD)
V2_DRAFT_RECORD["notice_hours"] = 48


def make_keys():
    """Generate an Ed25519 keypair and return ({key_id: raw_public_bytes}, private_key)."""
    private = Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes_raw()
    return {"k1": public_raw}, private


def sign_record(record: dict, private_key) -> dict:
    """Sign a sealed record's hash with an Ed25519 private key."""
    sealed = seal(record)
    sig = private_key.sign(bytes.fromhex(sealed["hash"]))
    sealed["signature"] = base64.b64encode(sig).decode("ascii")
    return sealed


def test_canonical_bytes_match_doc():
    assert record_hash(RECORD) == EXPECTED_HASH


def test_record_hash_matches_vector():
    assert record_hash(RECORD) == EXPECTED_HASH


def test_votes_snapshot_hash_matches_vector():
    assert votes_snapshot_hash(VOTES) == EXPECTED_SNAPSHOT


def test_seal_and_verify_roundtrip():
    keys, private = make_keys()
    sealed = sign_record(RECORD, private)
    assert sealed["hash"] == EXPECTED_HASH
    ok, reason = verify_record(sealed, keys)
    assert ok, reason


def test_tamper_is_detected():
    keys, private = make_keys()
    sealed = sign_record(RECORD, private)
    sealed["tally"]["approve"] = 2
    ok, reason = verify_record(sealed, keys)
    assert not ok, reason
    assert "hash mismatch" in reason


def test_chain_of_two_verifies():
    keys, private = make_keys()
    first = sign_record(RECORD, private)
    second = dict(RECORD)
    second["decision_id"] = "dec-2026-0002"
    second["proposal_id"] = "prop-2026-0002"
    second["prev_hash"] = first["hash"]
    second = sign_record(second, private)
    chain = [first, second]
    ok, reason = verify_chain(chain, keys)
    assert ok, reason


def test_broken_chain_is_rejected():
    keys, private = make_keys()
    first = sign_record(RECORD, private)
    second = dict(RECORD)
    second["prev_hash"] = GENESIS_PREV_HASH
    second = sign_record(second, private)
    ok, _ = verify_chain([first, second], keys)
    assert not ok


def test_forged_record_fails():
    """A tally that was never signed must not verify."""
    keys, _ = make_keys()
    forged = dict(RECORD)
    forged["tally"] = {"approve": 999, "reject": 0, "abstain": 0}
    forged = seal(forged, signature="AAAA")
    ok, reason = verify_record(forged, keys)
    assert not ok, reason


def test_unsigned_record_fails():
    """A record with no signature must not verify."""
    keys, _ = make_keys()
    sealed = seal(RECORD)
    ok, reason = verify_record(sealed, keys)
    assert not ok, reason
    assert reason == "unsigned"


def test_no_trust_root_fails():
    """Verification with no public keys fails closed."""
    _, private = make_keys()
    sealed = sign_record(RECORD, private)
    ok, reason = verify_record(sealed, None)
    assert not ok, reason
    assert reason == "no trust root configured"


def test_verify_chain_no_trust_root_fails():
    _, private = make_keys()
    sealed = sign_record(RECORD, private)
    ok, reason = verify_chain([sealed], None)
    assert not ok, reason
    assert reason == "no trust root configured"


def test_wrong_key_fails():
    """A signature made with a different key must not verify."""
    keys, _ = make_keys()
    other_private = Ed25519PrivateKey.generate()
    sealed = sign_record(RECORD, other_private)
    ok, reason = verify_record(sealed, keys)
    assert not ok, reason
    assert "bad signature" in reason


def test_unsealed_record_reports_not_sealed():
    """A record without a hash field reports "not sealed", not "hash mismatch"."""
    keys = make_keys()
    unsealed = dict(RECORD)
    unsealed.pop("hash", None)
    ok, reason = verify_record(unsealed, keys)
    assert not ok, reason
    assert reason == "not sealed"


def test_floats_are_rejected():
    bad = dict(RECORD)
    bad["quorum_rule"] = {"quorum": 0.2}
    try:
        canonical_json(bad)
    except LedgerError as exc:
        assert "float" in str(exc)
    else:
        raise AssertionError("floats must be rejected")


def test_python_sort_keys_not_jcs():
    # RFC 8785 UTF-16 ordering: high surrogate 0xD83D < 0xFFFD, so emoji key sorts first
    obj = {chr(0x1F600) + "x": 1, chr(0xFFFD): 2}
    result = canonical_json(obj)
    emoji_key = chr(0x1F600) + "x"
    fffd_key = chr(0xFFFD)
    expected = "{" + chr(34) + emoji_key + chr(34) + ":1," + chr(34) + fffd_key + chr(34) + ":2}"
    assert result == expected


def test_stale_approval_is_rejected():
    bad = dict(RECORD)
    bad["approvers"] = [{"gh_id": 1001, "review_id": 1, "reviewed_sha": "ab" * 32}]
    try:
        validate(bad)
    except LedgerError as exc:
        assert "head_sha" in str(exc)
    else:
        raise AssertionError("stale approval must be rejected")


def test_override_requires_ground():
    bad = dict(RECORD)
    bad["owner_decision"] = "override"
    bad["owner_override_ground"] = None
    try:
        validate(bad)
    except LedgerError:
        pass
    else:
        raise AssertionError("override without a ground must be rejected")


def test_override_ground_must_be_valid():
    bad = dict(RECORD)
    bad["owner_decision"] = "override"
    bad["owner_override_ground"] = "not_a_valid_ground"
    try:
        validate(bad)
    except LedgerError as exc:
        assert "legal_licensing" in str(exc) or "ground" in str(exc)
    else:
        raise AssertionError("invalid override ground must be rejected")


def test_voting_hours_is_48_only():
    bad = dict(RECORD)
    bad["voting_hours"] = 72
    try:
        validate(bad)
    except LedgerError:
        pass
    else:
        raise AssertionError("voting_hours must be 48")


def test_schema_version_is_3_only():
    bad = dict(RECORD)
    bad["schema_version"] = 2
    try:
        validate(bad)
    except LedgerError as exc:
        assert "schema_version" in str(exc)
    else:
        raise AssertionError("schema_version must be 3")


def test_retired_v0_fails():
    """v0 used prefix rule with prev_hash excluded — must not verify."""
    try:
        record_hash(V0_RECORD)
    except LedgerError:
        pass
    else:
        h = record_hash(V0_RECORD)
        assert h != "2de74e9d9d9d9d9d9d9d9d9d9d9d9d9d9d9d9d9d9d9d9d9d9d9d9d9d9d9d9d9d"


def test_retired_v1_fails():
    """v1 had schema_version 1, voting_hours 72 — must not verify."""
    bad = dict(V1_RECORD)
    bad.pop("owner_notice_comment_id", None)
    bad.pop("owner_decision", None)
    bad.pop("owner_override_ground", None)
    h = record_hash(bad)
    assert h != "0d87f7b4719159c11f00ba89a968c18fb869dc9fa630d0288b9a937c0b3abc1f"


def test_retired_v2_draft_fails():
    """v2-draft had notice_hours — must not verify."""
    bad = dict(V2_DRAFT_RECORD)
    h = record_hash(bad)
    assert h != "fcd1a4495b37cb1803070a793e849bbefc9f1b570b8eff2f9e57bdb4abbf4701"


def test_doc_vector_self_hashes():
    "The canonical line in docs/LEDGER-FORMAT.md at bc9c4a4 must hash to EXPECTED_HASH."
    import subprocess
    result = subprocess.run(
        ["git", "show", "bc9c4a4:docs/LEDGER-FORMAT.md"],
        capture_output=True, text=True, check=True,
    )
    text = result.stdout
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('{"approvers"'):
            h = hashlib.sha256(stripped.encode("utf-8")).hexdigest()
            assert h == EXPECTED_HASH, "doc vector 843665b1... does not match " + str(h[:8]) + "..."
            return
    raise AssertionError("no canonical vector line found in doc")


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
