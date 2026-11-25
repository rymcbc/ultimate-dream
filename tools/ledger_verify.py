#!/usr/bin/env python3
"""Ledger hash-chain verifier (gate side).

The canonical byte form and the hash construction are pinned by
tools/ledger_vectors.json. The governance service must emit byte-identical
canonical bytes; this file is the arbiter, and CI fails the PR if it disagrees.

Construction (ledger-hash-chain-v1):
    preimage = prev_hash_hex (64 lowercase hex chars) + canonical_json(record)
    hash     = sha256(preimage).hexdigest()
    canonical_json = json.dumps(record, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False).encode("utf-8")

`prev_hash` is a fixed-width 64-char string, so no separator is needed and the
chain link cannot be confused with record content. Genesis prev_hash = "0"*64.

Fields excluded from the preimage: hash, signature, prev_hash. A record may
carry `prev_hash` for human readers, but hashing it would double-count the link.

Floats are rejected anywhere in a record: JSON number formatting is not
canonical across languages, so the ledger uses integers or decimal strings only.

Usage:
    python3 tools/ledger_verify.py --self-test
    python3 tools/ledger_verify.py path/to/ledger.jsonl
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

GENESIS_PREV_HASH = "0" * 64
EXCLUDED_FROM_PREIMAGE = ("hash", "signature", "prev_hash")
HEX = set("0123456789abcdef")


def canonical_bytes(record: dict) -> bytes:
    """Canonical UTF-8 bytes of a record body."""
    return json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def record_hash(prev_hash: str, record: dict) -> str:
    """sha256(prev_hash_hex + canonical_json(record)) as lowercase hex."""
    if len(prev_hash) != 64 or not set(prev_hash) <= HEX:
        raise ValueError(
            f"prev_hash must be 64 lowercase hex chars, got {prev_hash!r}"
        )
    return hashlib.sha256(prev_hash.encode("utf-8") + canonical_bytes(record)).hexdigest()


def body_of(record: dict) -> dict:
    """Record with the non-hashed fields stripped."""
    return {k: v for k, v in record.items() if k not in EXCLUDED_FROM_PREIMAGE}


def find_floats(value, path="record"):
    """Yield paths of any float in the structure (floats break canonicality)."""
    if isinstance(value, float):
        yield path
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from find_floats(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from find_floats(item, f"{path}[{index}]")


def verify_chain(records: list[dict]) -> str:
    """Verify linkage and hashes. Returns the head hash; raises on any fault."""
    prev = GENESIS_PREV_HASH
    for index, record in enumerate(records):
        where = f"entry {index} ({record.get('decision_id', 'no decision_id')})"
        floats = list(find_floats(record))
        if floats:
            raise ValueError(f"{where}: float values are not allowed: {floats}")
        body = body_of(record)
        stored_prev = record.get("prev_hash")
        if stored_prev is not None and stored_prev != prev:
            raise ValueError(
                f"{where}: broken link, stored prev_hash {stored_prev} != expected {prev}"
            )
        claimed = record.get("hash")
        if not isinstance(claimed, str):
            raise ValueError(f"{where}: missing hash")
        actual = record_hash(prev, body)
        if actual != claimed:
            raise ValueError(f"{where}: hash mismatch, stored {claimed} != computed {actual}")
        prev = claimed
    return prev


def self_test(vectors_path: Path) -> None:
    vectors = json.loads(vectors_path.read_text(encoding="utf-8"))
    cases = vectors["cases"]
    prev = vectors["genesis_prev_hash"]
    if prev != GENESIS_PREV_HASH:
        raise SystemExit(f"FAIL genesis mismatch: {prev}")

    records: list[dict] = []
    for case in cases:
        name = case["name"]
        record = case["record"]
        expected_canonical = case["canonical_bytes"]
        expected_hash = case["hash"]

        actual_canonical = canonical_bytes(record).decode("utf-8")
        if actual_canonical != expected_canonical:
            raise SystemExit(
                f"FAIL {name}: canonical bytes differ\n  got      {actual_canonical}\n  expected {expected_canonical}"
            )
        print(f"  ok   {name}: canonical bytes match ({len(actual_canonical)} bytes)")

        actual_hash = record_hash(prev, record)
        if actual_hash != expected_hash:
            raise SystemExit(
                f"FAIL {name}: hash differs\n  got      {actual_hash}\n  expected {expected_hash}"
            )
        print(f"  ok   {name}: hash {actual_hash}")

        records.append({**record, "prev_hash": prev, "hash": actual_hash})
        prev = actual_hash

    head = verify_chain(records)
    if head != cases[-1]["hash"]:
        raise SystemExit(f"FAIL chain head {head} != {cases[-1]['hash']}")
    print(f"  ok   chain of {len(records)}: head {head}")


def verify_file(path: Path) -> None:
    records = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"FAIL {path}:{line_no}: not JSON: {exc}") from exc
    head = verify_chain(records)
    print(f"ok {path}: {len(records)} records, head {head}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: ledger_verify.py --self-test | <ledger.jsonl>", file=sys.stderr)
        return 2
    target = argv[1]
    try:
        if target == "--self-test":
            self_test(Path(__file__).with_name("ledger_vectors.json"))
            print("PASS ledger-hash-chain-v1 self-test")
        else:
            verify_file(Path(target))
    except ValueError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
