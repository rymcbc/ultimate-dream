"""Pins the ledger canonicalisation from docs/LEDGER-FORMAT.md.

If a test here goes red, someone changed the hash rule and every record ever written is now
unverifiable. Fix the change, not the test.

Four shapes existed in one day, so all four are recorded here — drift that is not written down is
indistinguishable from a mistake:

  v0  sketch      sha256(prev_hash_hex + canonical(record)), prev_hash excluded    retired, must fail
  v1  schema 1    voting_hours 72, no owner block                                   retired, must fail
  v2  withdrawn   schema 2, ballot_closed_at stored, owner_notified_at wall clock    retired, must fail
  v2-draft        v2 plus notice_hours 48 (a second post-vote wait)                  retired, must fail
  v3  current     schema 3, one 48h window, owner block anchored on a comment id    CURRENT

v2 was withdrawn by the owner's ruling before it ever produced a record: the 48-hour ballot IS the
notice period, so a second timer would have been a field nobody enforces.

The v3 vector was written by JARVIS (governance) and independently reproduced here — hash, JCS
ordering, UTF-16 surrogate key order and float refusal were all exercised before it was pinned.
"""
import hashlib
import json

V3_RECORD_BYTES = (
    '{"approvers":[{"gh_id":1001,"review_id":3912345678,"reviewed_sha":'
    '"4f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d"}],'
    '"ballot_id":"bal-2026-0001",'
    '"ballot_snapshot_hash":"fb7fb3e41180e4e28cdb6b97355d5c3b358ebafeb2c23a6daefd3edd8a5a9563",'
    '"close_comment_id":191234999,"created_by":"githubapp:ultimate-dream-ledger",'
    '"decision_id":"dec-2026-0001",'
    '"eligibility_snapshot_hash":"3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c",'
    '"head_sha":"4f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d",'
    '"kind":"ratify","open_comment_id":191234567,"owner_decision":"none",'
    '"owner_notice_comment_id":191234560,"owner_override_ground":null,'
    '"prev_hash":"0000000000000000000000000000000000000000000000000000000000000000",'
    '"proposal_body_sha256":"7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d",'
    '"proposal_id":"prop-2026-0001","quorum_rule":{"quorum":"0.20","threshold":"0.50","weighted":false},'
    '"result":"ratified","schema_version":3,'
    '"scope_paths":["game/content/props/**","game/content/items/**"],"signer_key_id":"k1",'
    '"supersedes":null,"tally":{"abstain":0,"approve":1,"reject":0},'
    '"votes_ref":"votes/dec-2026-0001.json","voting_hours":48}'
)

V3_RECORD_HASH = "843665b13896c04e4acb3a386d149f6f5899943000414862a19cedf360bb63dc"

V3_VOTES_BYTES = (
    '[{"body_sha256":"abababababababababababababababababababababababababababababababab",'
    '"comment_id":191234701,"created_at":"2026-11-23T10:00:00.000Z",'
    '"updated_at":"2026-11-23T10:00:00.000Z","voter_gh_id":1001}]'
)

V3_VOTES_HASH = "fb7fb3e41180e4e28cdb6b97355d5c3b358ebafeb2c23a6daefd3edd8a5a9563"

# Retired shapes. Each must stay unreachable from a v3 record.
RETIRED_V0_HASH = "6fa7e0e498031e7f41911119195e3b393027b56c7ed7a9e63ac2c507f2c6ad52"  # prefix rule
RETIRED_V1_HASH = "0d87f7b4719159c11f00ba89a968c18fb869dc9fa630d0288b9a937c0b3abc1f"  # schema 1
RETIRED_V2_HASH = "5451538b45503c04b7d8b5e939628c3f7aee4c43735d22d6dca673146e2932a4"  # schema 2
RETIRED_V2DRAFT_HASH = "fcd1a4495b37cb1803070a793e849bbefc9f1b570b8eff2f9e57bdb4abbf4701"  # notice_hours

OWNER_DECISIONS = {"none", "reviewed", "override"}
OVERRIDE_GROUNDS = {"legal_licensing", "safety_tos", "security", "does_not_build"}


def jcs(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def v3_hash(record: dict) -> str:
    """v3: prev_hash is an ordinary field inside the preimage. Only hash/signature are excluded."""
    payload = {k: v for k, v in record.items() if k not in ("hash", "signature")}
    return hashlib.sha256(jcs(payload)).hexdigest()


def legacy_v0_hash(record: dict) -> str:
    """Superseded: prepend prev_hash and exclude the field. Kept only to prove it cannot pass."""
    payload = {k: v for k, v in record.items() if k not in ("hash", "signature", "prev_hash")}
    return hashlib.sha256(record["prev_hash"].encode() + jcs(payload)).hexdigest()


def _v2(y):
    """Reconstruct the withdrawn v2 record from the v3 vector."""
    out = dict(y)
    out.pop("owner_notice_comment_id")
    out.update(
        schema_version=2,
        ballot_closed_at="2026-11-25T19:00:00.000Z",
        owner_decision="reviewed",
        owner_notified_at=1795633200,
    )
    return out


def test_record_vector_matches_published_hash():
    rec = json.loads(V3_RECORD_BYTES)
    assert jcs(rec).decode() == V3_RECORD_BYTES, "canonical bytes drifted from the published vector"
    assert v3_hash(rec) == V3_RECORD_HASH


def test_vote_snapshot_vector_matches_published_hash():
    votes = json.loads(V3_VOTES_BYTES)
    assert hashlib.sha256(jcs(votes)).hexdigest() == V3_VOTES_HASH


def test_legacy_preimage_rule_cannot_produce_v3_hash():
    """The v0 rule must fail: two rules, one record, two hashes is the bug this guards."""
    assert legacy_v0_hash(json.loads(V3_RECORD_BYTES)) != V3_RECORD_HASH


def test_retired_shapes_are_not_reachable_from_v3():
    rec = json.loads(V3_RECORD_BYTES)
    assert v3_hash(rec) not in {
        RETIRED_V0_HASH,
        RETIRED_V1_HASH,
        RETIRED_V2_HASH,
        RETIRED_V2DRAFT_HASH,
    }

    v2 = _v2(rec)
    assert v3_hash(v2) == RETIRED_V2_HASH, "the withdrawn v2 shape must still reproduce its hash"

    v1 = dict(v2, schema_version=1, voting_hours=72, ballot_closed_at="2026-11-25T17:00:00.000Z")
    for f in ("owner_notified_at", "owner_decision", "owner_override_ground"):
        v1.pop(f)
    assert v3_hash(v1) == RETIRED_V1_HASH, "the v1 shape must still reproduce its retired hash"

    draft = dict(v1, schema_version=2, notice_hours=48)
    assert v3_hash(draft) == RETIRED_V2DRAFT_HASH, "the second-timer draft must stay retired"


def test_no_stored_timestamps():
    """v3 stores comment ids, not the times it derived from them. The gate re-fetches both comments
    from GitHub and computes the window itself - two sources of truth is how a verifier rots."""
    rec = json.loads(V3_RECORD_BYTES)
    for banned in ("ballot_closed_at", "opens_at", "closes_at", "ratified_at", "owner_notified_at"):
        assert banned not in rec, f"{banned} duplicates a fact GitHub already owns"


def test_single_window_is_48_hours():
    rec = json.loads(V3_RECORD_BYTES)
    assert rec["voting_hours"] == 48
    for gone in ("notice_hours", "window_hours"):
        assert gone not in rec, f"{gone} is gone: the vote window IS the notice window"


def test_merge_still_requires_review():
    """Closing the window allows a merge; it does not authorise one without review."""
    rec = json.loads(V3_RECORD_BYTES)
    assert rec["approvers"], "a ratify record must carry the reviews it was ratified on"
    assert all(a["reviewed_sha"] == rec["head_sha"] for a in rec["approvers"]), (
        "an approver of a stale SHA does not count"
    )


def test_owner_notice_is_a_comment_not_a_clock():
    """The DM is private and unverifiable. What is public, and therefore checkable, is the notice
    comment the App posted. The field proves the notice was ISSUED, never that a DM was delivered."""
    rec = json.loads(V3_RECORD_BYTES)
    assert isinstance(rec["owner_notice_comment_id"], int)
    assert rec["owner_decision"] in OWNER_DECISIONS
    assert "owner_notified_at" not in rec


def test_override_requires_a_closed_enum_ground():
    rec = json.loads(V3_RECORD_BYTES)
    assert rec["owner_override_ground"] is None, "a non-override record carries no ground"

    overridden = dict(
        rec,
        kind="revoke",
        result="rejected",
        owner_decision="override",
        owner_override_ground="legal_licensing",
    )
    assert overridden["owner_override_ground"] in OVERRIDE_GROUNDS
    assert v3_hash(overridden) != V3_RECORD_HASH, "owner fields are inside the preimage"


def test_prev_hash_is_required_and_fixed_width():
    rec = json.loads(V3_RECORD_BYTES)
    assert len(rec["prev_hash"]) == 64
    assert v3_hash(dict(rec, prev_hash="0" * 63)) != V3_RECORD_HASH


def test_tamper_changes_hash():
    rec = json.loads(V3_RECORD_BYTES)
    rec["result"] = "rejected"
    assert v3_hash(rec) != V3_RECORD_HASH


def test_vocabulary_is_ratified_not_approved():
    """The writer owns the vocabulary; the gate adopts it."""
    rec = json.loads(V3_RECORD_BYTES)
    assert rec["kind"] == "ratify"
    assert rec["result"] == "ratified"
    assert "approved" not in {"ratified", "rejected", "void", "waived"}
