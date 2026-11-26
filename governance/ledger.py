"""Ledger writer for The Ultimate Dream — v3 format.

Implements docs/LEDGER-FORMAT.md v3 (the settled spec on `gate/fix-ci`) and
nothing else. Two rules matter more than the code:

1. Canonicalisation is RFC 8785 (JCS): keys sorted by UTF-16 code units,
   integers only, no floats, UTF-8 output, no whitespace.
   Python's json.dumps(sort_keys=True) is NOT equivalent — it sorts by code
   point, which disagrees with JCS as soon as a key contains a character
   outside the BMP (an emoji-leading key sorts first under JCS and last
   under Python). Titles will contain emoji. This module never calls
   json.dumps with sort_keys for hashing.
2. `prev_hash` is an ordinary field *inside* the preimage. Only `hash` and
   `signature` are excluded. There is no prefixing and no separator.

Verification order: recompute hash -> verify Ed25519 signature over the
64 raw hash bytes -> walk prev_hash back to genesis. The gate fails closed:
no trust root, no signature, or a bad signature means no verification.

"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Iterable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

GENESIS_PREV_HASH = "0" * 64

KINDS = ("ratify", "revoke", "waive", "supersede")
RESULTS = ("ratified", "rejected", "void", "waived")
OWNER_DECISIONS = ("none", "reviewed", "override")
OVERRIDE_GROUNDS = ("legal_licensing", "safety_tos", "security", "does_not_build")

REQUIRED_FIELDS = (
    "kind",
    "schema_version",
    "decision_id",
    "proposal_id",
    "ballot_id",
    "open_comment_id",
    "close_comment_id",
    "voting_hours",
    "owner_notice_comment_id",
    "owner_decision",
    "owner_override_ground",
    "ballot_snapshot_hash",
    "votes_ref",
    "eligibility_snapshot_hash",
    "quorum_rule",
    "tally",
    "result",
    "scope_paths",
    "proposal_body_sha256",
    "head_sha",
    "approvers",
    "supersedes",
    "created_by",
    "signer_key_id",
    "prev_hash",
)

# --------------------------------------------------------------------------
# RFC 8785 canonicalisation (JCS)
# --------------------------------------------------------------------------

_ESCAPES = {
    chr(34): chr(92) + chr(34),
    chr(92): chr(92) + chr(92),
    chr(8): chr(92) + "b",
    chr(12): chr(92) + "f",
    chr(10): chr(92) + "n",
    chr(13): chr(92) + "r",
    chr(9): chr(92) + "t",
}

def _escape_string(value: str) -> str:
    out = [chr(34)]
    for ch in value:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append(chr(92) + "u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append(chr(34))
    return "".join(out)


def _reject_floats(value: Any) -> None:
    if isinstance(value, float):
        raise LedgerError("floats are banned from ledger records; use an integer or a fixed decimal string")
    if isinstance(value, dict):
        for v in value.values():
            _reject_floats(v)
    elif isinstance(value, list):
        for v in value:
            _reject_floats(v)


def _sort_key(key: str) -> bytes:
    return key.encode("utf-16-be")


def canonical_json(value: Any) -> str:
    """Serialise `value` to RFC 8785 canonical JSON per docs/LEDGER-FORMAT.md v3."""
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
    raise LedgerError("unsupported type in ledger record: " + type(value).__name__)


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


# --------------------------------------------------------------------------
# Hashing
# --------------------------------------------------------------------------


def record_hash(record: dict) -> str:
    """sha256 over the canonical record with `hash` and `signature` removed."""
    preimage = {k: v for k, v in record.items() if k not in ("hash", "signature")}
    return hashlib.sha256(canonical_bytes(preimage)).hexdigest()


def votes_snapshot_hash(votes: list) -> str:
    """sha256 over the canonical frozen vote array (votes/<decision_id>.json)."""
    return hashlib.sha256(canonical_bytes(votes)).hexdigest()


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


class LedgerError(ValueError):
    pass


class SignatureError(LedgerError):
    """Raised when a record signature cannot be verified."""
    pass


def validate(record: dict) -> None:
    missing = [f for f in REQUIRED_FIELDS if f not in record]
    if missing:
        raise LedgerError("record missing required fields: " + ", ".join(missing))

    if record["kind"] not in KINDS:
        raise LedgerError("unknown kind " + repr(record["kind"]))
    if record["result"] not in RESULTS:
        raise LedgerError("unknown result " + repr(record["result"]))
    if record["owner_decision"] not in OWNER_DECISIONS:
        raise LedgerError("unknown owner_decision " + repr(record["owner_decision"]))

    ground = record["owner_override_ground"]
    if record["owner_decision"] == "override":
        if ground not in OVERRIDE_GROUNDS:
            raise LedgerError(
                "override requires a cited ground from " + repr(OVERRIDE_GROUNDS) + ", got " + repr(ground)
            )
    elif ground is not None:
        raise LedgerError("owner_override_ground must be null unless owner_decision is 'override'")

    if record["schema_version"] != 3:
        raise LedgerError("unsupported schema_version " + repr(record["schema_version"]))

    if record["voting_hours"] != 48:
        raise LedgerError("voting_hours must be 48")

    prev = record["prev_hash"]
    if not isinstance(prev, str) or len(prev) != 64 or any(c not in "0123456789abcdef" for c in prev):
        raise LedgerError("prev_hash must be 64 lowercase hex characters")

    tally = record["tally"]
    for field in ("approve", "reject", "abstain"):
        if not isinstance(tally.get(field), int):
            raise LedgerError("tally." + field + " must be an integer")

    for approver in record["approvers"]:
        if approver.get("reviewed_sha") != record["head_sha"]:
            raise LedgerError("every approval must be for the merged head_sha; stale approvals are invalid")


# --------------------------------------------------------------------------
# Chain — fail closed
# --------------------------------------------------------------------------


def seal(record: dict, signature: str | None = None) -> dict:
    """Return a copy of `record` with `hash` (and `signature`) filled in."""
    validate(record)
    sealed = dict(record)
    sealed["hash"] = record_hash(record)
    if signature is not None:
        sealed["signature"] = signature
    return sealed


def _signature_bytes(record: dict) -> bytes:
    """Decode the base64 Ed25519 signature from a sealed record."""
    sig = record.get("signature")
    if not isinstance(sig, str):
        raise SignatureError("unsigned")
    try:
        return base64.b64decode(sig, validate=True)
    except Exception:
        raise SignatureError("bad signature encoding")


def _public_key(public_keys: Mapping[str, bytes], key_id: str) -> Ed25519PublicKey:
    """Load an Ed25519 public key from raw 32-byte key material."""
    key_material = public_keys.get(key_id)
    if key_material is None:
        raise SignatureError("unknown signer key " + repr(key_id))
    try:
        return Ed25519PublicKey.from_public_bytes(key_material)
    except Exception:
        raise SignatureError("bad public key material for " + repr(key_id))


def verify_signature(record: dict, public_keys: Mapping[str, bytes]) -> None:
    """Verify the Ed25519 signature over the 64 raw hash bytes of `record`."""
    sig_bytes = _signature_bytes(record)
    key = _public_key(public_keys, record.get("signer_key_id"))
    hash_bytes = bytes.fromhex(record["hash"])
    try:
        key.verify(sig_bytes, hash_bytes)
    except InvalidSignature:
        raise SignatureError("bad signature")


def verify_record(record: dict, public_keys: Mapping[str, bytes] | None = None) -> tuple[bool, str]:
    """Verify a sealed record.

    `public_keys` maps key_id -> raw 32-byte Ed25519 public key. It is a
    trust root supplied by the verifier, never a key that travels with the
    ledger it is supposed to police.

    Fails closed: no public keys, no signature, or a bad signature means
    verification fails.

    Returns (ok, reason).
    """
    if public_keys is None or len(public_keys) == 0:
        return False, "no trust root configured"

    stored_hash = record.get("hash")
    if not isinstance(stored_hash, str):
        return False, "not sealed"

    if stored_hash != record_hash(record):
        return False, "hash mismatch"

    try:
        verify_signature(record, public_keys)
    except SignatureError as exc:
        return False, str(exc)

    return True, "ok"


def verify_chain(records: Iterable[dict], public_keys: Mapping[str, bytes] | None = None) -> tuple[bool, str]:
    """Walk a chain from genesis, verifying every record.

    `public_keys` is the trust root — without it, verification fails closed.
    Returns (ok, reason).
    """
    if public_keys is None or len(public_keys) == 0:
        return False, "no trust root configured"

    previous = GENESIS_PREV_HASH
    seen = 0
    for index, record in enumerate(records):
        seen += 1
        if record.get("prev_hash") != previous:
            return False, "record " + str(index) + " (" + str(record.get("decision_id")) + ") does not chain: prev_hash mismatch"
        ok, reason = verify_record(record, public_keys)
        if not ok:
            return False, "record " + str(index) + " (" + str(record.get("decision_id")) + "): " + reason
        previous = record["hash"]
    if seen == 0:
        return False, "empty chain"
    return True, "ok"


def dump_line(record: dict) -> str:
    """Serialise a sealed record as one canonical JSONL line."""
    return canonical_json(record) + "\n"


def load_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]
