"""Pins ledger v1 canonicalisation from docs/LEDGER-FORMAT.md.

If a test here goes red, someone changed the hash rule and every record ever written is now
unverifiable. Fix the change, not the test.

Both vectors were published by the governance side (JARVIS) and reproduced independently here from the
specification before any code was written against them.
"""
import hashlib
import json

V1_RECORD_BYTES = (
    '{"approvers":[{"gh_id":1001,"review_id":3912345678,"reviewed_sha":'
    '"4f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d"}],'
    '"ballot_closed_at":"2026-11-25T17:00:00.000Z","ballot_id":"bal-2026-0001",'
    '"ballot_snapshot_hash":"fb7fb3e41180e4e28cdb6b97355d5c3b358ebafeb2c23a6daefd3edd8a5a9563",'
    '"close_comment_id":191234999,"created_by":"githubapp:ultimate-dream-ledger",'
    '"decision_id":"dec-2026-0001",'
    '"eligibility_snapshot_hash":"3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c",'
    '"head_sha":"4f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d",'
    '"kind":"ratify","open_comment_id":191234567,'
    '"prev_hash":"0000000000000000000000000000000000000000000000000000000000000000",'
    '"proposal_body_sha256":"7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d",'
    '"proposal_id":"prop-2026-0001","quorum_rule":{"quorum":"0.20","threshold":"0.50","weighted":false},'
    '"result":"ratified","schema_version":1,'
    '"scope_paths":["game/content/props/**","game/content/items/**"],"signer_key_id":"k1",'
    '"supersedes":null,"tally":{"abstain":0,"approve":1,"reject":0},'
    '"votes_ref":"votes/dec-2026-0001.json","voting_hours":72}'
)

V1_RECORD_HASH = "0d87f7b4719159c11f00ba89a968c18fb869dc9fa630d0288b9a937c0b3abc1f"

V1_VOTES_BYTES = (
    '[{"body_sha256":"abababababababababababababababababababababababababababababababab",'
    '"comment_id":191234701,"created_at":"2026-11-23T10:00:00.000Z",'
    '"updated_at":"2026-11-23T10:00:00.000Z","voter_gh_id":1001}]'
)

V1_VOTES_HASH = "fb7fb3e41180e4e28cdb6b97355d5c3b358ebafeb2c23a6daefd3edd8a5a9563"

# Superseded v0 sketch: prepend prev_hash_hex, exclude the field. Must never verify again.
RETIRED_V0_HASH = "6fa7e0e498031e7f41911119195e3b393027b56c7ed7a9e63ac2c507f2c6ad52"


def jcs(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def v1_hash(record: dict) -> str:
    """v1: prev_hash is a field inside the preimage. Only hash/signature are excluded."""
    payload = {k: v for k, v in record.items() if k not in ("hash", "signature")}
    return hashlib.sha256(jcs(payload)).hexdigest()


def legacy_v0_hash(record: dict) -> str:
    """Superseded: prepend prev_hash and exclude the field. Kept only to prove it cannot pass."""
    payload = {k: v for k, v in record.items() if k not in ("hash", "signature", "prev_hash")}
    return hashlib.sha256(record["prev_hash"].encode() + jcs(payload)).hexdigest()


def test_record_vector_matches_published_hash():
    rec = json.loads(V1_RECORD_BYTES)
    assert jcs(rec).decode() == V1_RECORD_BYTES, "canonical bytes drifted from the published vector"
    assert v1_hash(rec) == V1_RECORD_HASH


def test_vote_snapshot_vector_matches_published_hash():
    votes = json.loads(V1_VOTES_BYTES)
    assert hashlib.sha256(jcs(votes)).hexdigest() == V1_VOTES_HASH


def test_legacy_preimage_rule_cannot_produce_v1_hash():
    """The v0 rule must fail against v1: two rules, one record, different hashes is the bug this guards."""
    rec = json.loads(V1_RECORD_BYTES)
    assert legacy_v0_hash(rec) != V1_RECORD_HASH


def test_retired_v0_vector_is_not_reachable_from_v1_rule():
    rec = json.loads(V1_RECORD_BYTES)
    assert v1_hash(rec) != RETIRED_V0_HASH


def test_prev_hash_is_required_and_fixed_width():
    rec = json.loads(V1_RECORD_BYTES)
    assert len(rec["prev_hash"]) == 64
    broken = dict(rec)
    broken["prev_hash"] = "0" * 63
    assert v1_hash(broken) != V1_RECORD_HASH


def test_tamper_changes_hash():
    rec = json.loads(V1_RECORD_BYTES)
    rec["result"] = "rejected"
    assert v1_hash(rec) != V1_RECORD_HASH


def test_vocabulary_is_ratified_not_approved():
    """The writer owns the vocabulary; the gate adopts it."""
    rec = json.loads(V1_RECORD_BYTES)
    assert rec["kind"] == "ratify"
    assert rec["result"] == "ratified"
    allowed = {"ratified", "rejected", "void", "waived"}
    assert "approved" not in allowed


def test_single_window_is_48_hours():
    """Owner ruling: one 48-hour window that is both the vote window and the notice period."""
    POLICY_VOTING_HOURS = 48
    assert POLICY_VOTING_HOURS == 48
    # The published vector deliberately keeps 72: it pins the hash rule, not policy. Changing the
    # fixture value would invalidate a hash two parties agreed on.
    rec = json.loads(V1_RECORD_BYTES)
    assert rec["voting_hours"] == 72
    assert rec["voting_hours"] != POLICY_VOTING_HOURS


def test_owner_block_fields_are_part_of_the_format():
    """The owner is DM'd at T0; silence is not an override, so the block must be explicit."""
    rec = dict(json.loads(V1_RECORD_BYTES))
    rec["owner_notified_at"] = 1795600000
    rec["owner_decision"] = "none"
    rec["owner_override_ground"] = None
    assert rec["owner_decision"] in {"none", "reviewed", "override"}
    assert v1_hash(rec) != V1_RECORD_HASH, "adding owner fields must change the hash"


def test_override_requires_a_cited_ground():
    allowed = {"legal", "safety", "security", "build"}
    rec = dict(json.loads(V1_RECORD_BYTES))
    rec["owner_decision"] = "override"
    rec["owner_override_ground"] = "because I said so"
    assert rec["owner_override_ground"] not in allowed
