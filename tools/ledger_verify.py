#!/usr/bin/env python3
"""Ledger verifier (gate side) - ledger-hash-chain-v2.

Normative fixture: tools/ledger_vectors.json. The governance service must emit
byte-identical canonical bytes, or CI refuses the merge.

Construction (v2):
    preimage = canonical_json(record minus `hash` and `signature`)
    hash     = sha256(preimage).hexdigest()
    canonical_json = json.dumps(record, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False).encode("utf-8")

`prev_hash` is an ORDINARY field inside the preimage. No prefixing, no
double-count. The genesis record carries prev_hash = "0" * 64. The signature
covers the 64 raw bytes of `hash`, not the record.

Verify order: recompute hash -> verify signature -> walk prev_hash.

v1 (prefix rule: sha256(prev_hex + canonical(record))) is RETIRED. It produced
different bytes, and therefore different hashes, for the same records.

Usage:
    python3 tools/ledger_verify.py --self-test
    python3 tools/ledger_verify.py [--keys-dir DIR] [--trusted-keys FILE] ledger.jsonl
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

GENESIS_PREV_HASH = "0" * 64
EXCLUDED_FROM_PREIMAGE = ("hash", "signature")
HEX = set("0123456789abcdef")


# --------------------------------------------------------------------------- #
# canonical form
# --------------------------------------------------------------------------- #
def canonical_bytes(record: dict) -> bytes:
    """Canonical UTF-8 bytes of a record body (JCS-equivalent for int/str)."""
    return json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def body_of(record: dict) -> dict:
    return {k: v for k, v in record.items() if k not in EXCLUDED_FROM_PREIMAGE}


def record_hash(record: dict) -> str:
    return hashlib.sha256(canonical_bytes(body_of(record))).hexdigest()


def find_floats(value, path="record"):
    """Floats break canonicality across languages, so they are refused."""
    if isinstance(value, float):
        yield path
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from find_floats(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from find_floats(item, f"{path}[{index}]")


# --------------------------------------------------------------------------- #
# signatures
# --------------------------------------------------------------------------- #
def load_public_key(keys_dir: Path, signer_key_id: str):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    path = keys_dir / f"{signer_key_id}.pub"
    if not path.is_file():
        raise ValueError(f"signer key not found: {path}")
    raw = base64.b64decode(path.read_text(encoding="utf-8").strip(), validate=True)
    if len(raw) != 32:
        raise ValueError(f"{path}: ed25519 public key must be 32 raw bytes, got {len(raw)}")
    return Ed25519PublicKey.from_public_bytes(raw)


def verify_signature(record: dict, keys_dir: Path, trusted_key_ids) -> None:
    from cryptography.exceptions import InvalidSignature

    signer = record.get("signer_key_id")
    signature_b64 = record.get("signature")
    if not signer or not signature_b64:
        raise ValueError(f"{record.get('decision_id')}: missing signer_key_id or signature")
    if trusted_key_ids is not None and signer not in trusted_key_ids:
        raise ValueError(
            f"{record.get('decision_id')}: signer key {signer} is NOT in the trust root "
            f"(.github/ledger-trusted-keys.txt) - a key that lives only on the ledger "
            f"branch can re-sign a fully rewritten chain"
        )
    key = load_public_key(keys_dir, signer)
    signature = base64.b64decode(signature_b64, validate=True)
    try:
        key.verify(signature, bytes.fromhex(record["hash"]))
    except InvalidSignature as exc:
        raise ValueError(
            f"{record.get('decision_id')}: signature does not verify over hash {record['hash']}"
        ) from exc


# --------------------------------------------------------------------------- #
# chain
# --------------------------------------------------------------------------- #
def verify_chain(records, keys_dir: Path | None = None, trusted_key_ids=None) -> str:
    prev = GENESIS_PREV_HASH
    for index, record in enumerate(records):
        where = f"entry {index} ({record.get('decision_id', 'no decision_id')})"

        floats = list(find_floats(record))
        if floats:
            raise ValueError(f"{where}: floats are not allowed: {floats}")

        if "prev_hash" not in record:
            raise ValueError(f"{where}: missing prev_hash (genesis carries 64 zeros)")
        if record["prev_hash"] != prev:
            raise ValueError(
                f"{where}: broken link, prev_hash {record['prev_hash']} != expected {prev}"
            )

        claimed = record.get("hash")
        if not isinstance(claimed, str) or len(claimed) != 64 or not set(claimed) <= HEX:
            raise ValueError(f"{where}: hash must be 64 lowercase hex chars")
        actual = record_hash(record)
        if actual != claimed:
            raise ValueError(f"{where}: hash mismatch, stored {claimed} != computed {actual}")

        if keys_dir is not None:
            verify_signature(record, keys_dir, trusted_key_ids)

        prev = claimed
    return prev


def load_jsonl(path: Path) -> list:
    records = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"{path}:{line_no}: blank line (ledger is one record per line)")
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: not JSON: {exc}") from exc
    if not records:
        raise ValueError(f"{path}: empty ledger")
    return records


# --------------------------------------------------------------------------- #
# self-test (pinned fixtures)
# --------------------------------------------------------------------------- #
def self_test(vectors_path: Path) -> None:
    vectors = json.loads(vectors_path.read_text(encoding="utf-8"))
    if vectors.get("spec") != "ledger-hash-chain-v2":
        raise SystemExit(
            f"FAIL fixture spec is {vectors.get('spec')!r}, expected ledger-hash-chain-v2"
        )
    if vectors["genesis_prev_hash"] != GENESIS_PREV_HASH:
        raise SystemExit("FAIL fixture genesis is not 64 zeros")

    fixture_signer = vectors["fixture_signer"]

    records = []
    for case in vectors["cases"]:
        name = case["name"]
        record = dict(case["record"])
        record["hash"] = case["hash"]
        record["signer_key_id"] = fixture_signer["key_id"]
        record["signature"] = case["signature"]

        actual_canonical = canonical_bytes(body_of(record)).decode("utf-8")
        if actual_canonical != case["canonical_bytes"]:
            raise SystemExit(
                f"FAIL {name}: canonical bytes differ\n"
                f"  got      {actual_canonical}\n  expected {case['canonical_bytes']}"
            )
        print(f"  ok   {name}: canonical bytes match ({len(actual_canonical)} bytes)")

        if record_hash(record) != case["hash"]:
            raise SystemExit(f"FAIL {name}: hash {record_hash(record)} != {case['hash']}")
        print(f"  ok   {name}: hash {case['hash']}")
        records.append(record)

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        keys_dir = Path(tmp)
        (keys_dir / f"{fixture_signer['key_id']}.pub").write_text(
            fixture_signer["public_key_b64"] + "\n", encoding="utf-8"
        )

        verify_chain(records, keys_dir=keys_dir, trusted_key_ids={fixture_signer["key_id"]})
        print(f"  ok   signatures verify against fixture key {fixture_signer['key_id']}")

        try:
            verify_chain(records, keys_dir=keys_dir, trusted_key_ids={"ledger-other"})
        except ValueError:
            print("  ok   untrusted signer key refused")
        else:
            raise SystemExit("FAIL an untrusted signer key was accepted")

        tampered = [dict(r) for r in records]
        tampered[0]["result"] = "rejected"
        try:
            verify_chain(tampered)
        except ValueError:
            print("  ok   tampered record refused")
        else:
            raise SystemExit("FAIL a tampered record passed")

    head = verify_chain(records)
    if head != records[-1]["hash"]:
        raise SystemExit(f"FAIL chain head {head} != {records[-1]['hash']}")
    print(f"  ok   chain of {len(records)}: head {head}")


def main(argv) -> int:
    args = argv[1:]
    if not args:
        print(
            "usage: ledger_verify.py --self-test | [--keys-dir DIR] [--trusted-keys FILE] <ledger.jsonl>",
            file=sys.stderr,
        )
        return 2
    try:
        if args[0] == "--self-test":
            self_test(Path(__file__).with_name("ledger_vectors.json"))
            print("PASS ledger-hash-chain-v2 self-test")
            return 0

        keys_dir = None
        trusted = None
        target = None
        rest = list(args)
        while rest:
            flag = rest.pop(0)
            if flag == "--keys-dir":
                keys_dir = Path(rest.pop(0))
            elif flag == "--trusted-keys":
                trusted = {
                    line.strip()
                    for line in Path(rest.pop(0)).read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.strip().startswith("#")
                }
            else:
                target = Path(flag)
        if target is None:
            print("error: no ledger file given", file=sys.stderr)
            return 2

        records = load_jsonl(target)
        head = verify_chain(records, keys_dir=keys_dir, trusted_key_ids=trusted)
        print(f"ok {target}: {len(records)} records, head {head}")
        return 0
    except ImportError as exc:
        print(f"FAIL missing dependency ({exc}); signatures need `pip install cryptography`",
              file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"FAIL cannot read file: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
