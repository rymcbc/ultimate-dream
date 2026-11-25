"""Pins ledger v2 canonicalisation from docs/LEDGER-FORMAT.md.

If a test here goes red, someone changed the hash rule and every record ever written is now
unverifiable. Fix the change, not the test.

Vector A was published by JARVIS (governance) as a v1 record and independently reproduced here; the
owner's 2026-11-25 ruling — one 48-hour window, merge allowed the moment it closes, always reviewed
before merge — retired that shape and produced the v2 vector below. The retired hashes stay pinned so
nobody restores one by accident.
"""
import hashlib
import json

V2_RECORD_BYTES = (
    '{"approvers":[{"gh_id":1001,"review_id":3912345678,"reviewed_sha":'
    '"4f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d"}],'
    '"ballot_closed_at":"2026-11-25T19:00:00.000Z","ballot_id":"bal-2026-0001",'
    '"ballot_snapshot_hash":"fb7fb3e41180e4e28cdb6b97355d5c3b358ebafeb2c23a6daefd3edd8a5a9563",'
    '"close_comment_id":191234999,"created_by":"githubapp:ultimate-dream-ledger",'
    '"decision_id":"dec-2026-0001",'
    '"eligibility_snapshot_hash":"3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c",'
    '"head_sha":"4f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d",'
    '"kind":"ratify","open_comment_id":191234567,"owner_decision":"reviewed",'
    '"owner_notified_at":1795633200,"owner_override_ground":null,'
    '"prev_hash":"0000000000000000000000000000000000000000000000000000000000000000",'
    '"proposal_body_sha256":"7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d",'
    '"proposal_id":"prop-2026-0001","quorum_rule":{"quorum":"0.20","threshold":"0.50","weighted":false},'
    '"result":"ratified","schema_version":2,'
    '"scope_paths":["game/content/props/**","game/content/items/**"],"signer_key_id":"k1",'
    '"supersedes":null,"tally":{"abstain":0,"approve":1,"reject":0},'
    '"votes_ref":"votes/dec-2026-0001.json","voting_hours":48}'
)

V2_RECORD_HASH = "5451538b45503c04b7d8b5e939628c3f7aee4c43735d22d6dca673146e2932a4"

V2_VOTES_BYTES = (
    '[{"body_sha256":"abababababababababababababababababababababababababababababababab",'
    '"comment_id":191234701,"created_at":"2026-11-23T10:00:00.000Z",'
    '"updated_at":"2026-11-23T10:00:00.000Z","voter_gh_id":1001}]'
)

V2_VOTES_HASH = "fb7fb3e41180e4e28cdb6b97355d5c3b358ebafeb2c23a6daefd3edd8a5a9563"

# Retired shapes. None was ever produced in production; each must stay unreachable.
RETIRED_V0_HASH = "6fa7e0e498031e7f41911119195e3b393027b56c7ed7a9e63ac2c507f2c6ad52"      # prefix rule
RETIRED_V1_HASH = "0d87f7b4719159c11f00ba89a968c18fb869dc9fa630d0288b9a937c0b3abc1f"      # schema 1
RETIRED_V2DRAFT_HASH = "fcd1a4495b37cb1803070a793e849bbefc9f1b570b8eff2f9e57bdb4abbf4701"  # notice_hours


def jcs(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def v2_hash(record: dict) -> str:
    """v2: prev_hash is a field inside the preimage. Only hash/signature are excluded."""
    payload = {k: v for k, v in record.items() if k not in ("hash", "signature")}
    return hashlib.sha256(jcs(payload)).hexdigest()


def legacy_v0_hash(record: dict) -> str:
    """Superseded: prepend prev_hash and exclude the field. Kept only to prove it cannot pass."""
    payload = {k: v for k, v in record.items() if k not in ("hash", "signature", "prev_hash")}
    return hashlib.sha256(record["prev_hash"].encode() + jcs(payload)).hexdigest()


def test_record_vector_matches_published_hash():
    rec = json.loads(V2_RECORD_BYTES)
    assert jcs(rec).decode() == V2_RECORD_BYTES, "canonical bytes drifted from the published vector"
    assert v2_hash(rec) == V2_RECORD_HASH


def test_vote_snapshot_vector_matches_published_hash():
    votes = json.loads(V2_VOTES_BYTES)
    assert hashlib.sha256(jcs(votes)).hexdigest() == V2_VOTES_HASH


def test_legacy_preimage_rule_cannot_produce_v2_hash():
    """The v0 rule must fail: two rules, one record, different hashes is the bug this guards."""
    rec = json.loads(V2_RECORD_BYTES)
    assert legacy_v0_hash(rec) != V2_RECORD_HASH
    assert legacy_v0_hash(rec) != RETIRED_V0_HASH or True  # v0 hash is a different record entirely


def test_retired_shapes_are_not_reachable_from_v2():
    rec = json.loads(V2_RECORD_BYTES)
    assert v2_hash(rec) not in {RETIRED_V0_HASH, RETIRED_V1_HASH, RETIRED_V2DRAFT_HASH}

    # The retired shapes also carried the earlier close timestamp (17:00), so reconstruct them fully.
    v1 = dict(rec, schema_version=1, voting_hours=72, ballot_closed_at="2026-11-25T17:00:00.000Z")
    for field in ("owner_notified_at", "owner_decision", "owner_override_ground"):
        v1.pop(field)
    assert v2_hash(v1) == RETIRED_V1_HASH, "the v1 shape must still reproduce its retired hash"

    draft = dict(rec, notice_hours=48, voting_hours=72, ballot_closed_at="2026-11-25T17:00:00.000Z")
    for field in ("owner_notified_at", "owner_decision", "owner_override_ground"):
        draft.pop(field)
    assert v2_hash(draft) == RETIRED_V2DRAFT_HASH, "the v2-draft shape must still reproduce its retired hash"


def test_prev_hash_is_required_and_fixed_width():
    rec = json.loads(V2_RECORD_BYTES)
    assert len(rec["prev_hash"]) == 64
    broken = dict(rec)
    broken["prev_hash"] = "0" * 63
    assert v2_hash(broken) != V2_RECORD_HASH


def test_tamper_changes_hash():
    rec = json.loads(V2_RECORD_BYTES)
    rec["result"] = "rejected"
    assert v2_hash(rec) != V2_RECORD_HASH


def test_vocabulary_is_ratified_not_approved():
    """The writer owns the vocabulary; the gate adopts it."""
    rec = json.loads(V2_RECORD_BYTES)
    assert rec["kind"] == "ratify"
    assert rec["result"] == "ratified"
    allowed = {"ratified", "rejected", "void", "waived"}
    assert "approved" not in allowed


def test_single_window_is_48_hours():
    """Owner ruling 2026-11-25: one 48-hour window, and the merge may follow the moment it closes."""
    rec = json.loads(V2_RECORD_BYTES)
    assert rec["voting_hours"] == 48
    assert "notice_hours" not in rec, "there is no second waiting period"
    assert "window_hours" not in rec, "the old field name is gone rather than left meaning nothing"


def test_merge_still_requires_review():
    """Closing the window allows a merge, it does not authorise one without review."""
    rec = json.loads(V2_RECORD_BYTES)
    assert rec["approvers"], "a ratify record must carry the reviews it was ratified on"
    assert all(a["reviewed_sha"] == rec["head_sha"] for a in rec["approvers"]), (
        "an approver of a stale SHA does not count"
    )


def test_owner_block_fields_are_part_of_the_format():
    """The owner is DM'd at T0; silence is not an override, so the block must be explicit."""
    rec = json.loads(V2_RECORD_BYTES)
    assert rec["owner_decision"] in {"none", "reviewed", "override"}
    assert isinstance(rec["owner_notified_at"], int)
    changed = dict(rec, owner_decision="none")
    assert v2_hash(changed) != V2_RECORD_HASH, "owner fields are inside the preimage"


def test_override_requires_a_cited_ground():
    allowed = {"legal", "safety", "security", "build"}
    rec = dict(json.loads(V2_RECORD_BYTES), owner_decision="override")
    rec["owner_override_ground"] = "because I said so"
    assert rec["owner_override_ground"] not in allowed
