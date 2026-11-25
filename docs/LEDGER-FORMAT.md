# Ledger Format v1

The ledger is how a stranger proves a change was approved by real people after a real 48-hour window,
**without trusting our servers**. It lives on an orphan branch `ledger`, one canonical JSON record per
line, in `decisions.ndjson`. This document is normative: the writer and the CI verifier both implement it,
and `tests/test_ledger_format.py` pins it with the vector below.

Agreed between Merlin (lead) and JARVIS (governance service) on 2026-11-25.

## Record

```json
{"anchor_comment":"ic_1234567890","approvers":["u_1001","u_1002"],
 "ballot_snapshot_hash":"9f9f…","decision_id":"dec-2026-0001",
 "proposal_id":"prop-2026-0001","result":"approved","window_hours":48}
```

Field notes:
- `anchor_comment` — the GitHub comment id of the result comment posted at ballot close. Its
  `created_at`, read from the GitHub API, is the **only** permitted anchor for the 48-hour window. A
  wall-clock time from any machine is not evidence.
- `ballot_snapshot_hash` — sha256 over the frozen vote snapshot taken at close (voters, choices, reaction
  ids, server timestamps). Freezing is what stops a voter editing or deleting their vote after the fact.
- `approvers` — code owners whose review `reviewed_sha` equals the merged head. The verifier re-fetches
  these from the GitHub API; it never trusts this list on its own.
- `window_hours` — fixed at 48 for ordinary decisions.

## Hash

```
canonical_json = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
hash           = sha256(prev_hash_hex.encode() + canonical_json).hexdigest()
prev_hash      = 64 hex chars; genesis record uses "0" * 64
```

**No separator between `prev_hash` and the canonical bytes.** This is safe *only* because `prev_hash` is
fixed-width at 64 characters, so a record's payload can never be shifted into the hash region. Do not
"tidy" this into a colon-joined or newline-joined string: it would change every hash ever written and break
verification of the whole chain. That is the reason, not a style preference.

## Test vector (normative)

Input record — exactly the seven keys below:

```json
{"anchor_comment":"ic_1234567890","approvers":["u_1001","u_1002"],
 "ballot_snapshot_hash":"9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f",
 "decision_id":"dec-2026-0001","proposal_id":"prop-2026-0001","result":"ratified","window_hours":48}
```

Canonical bytes (byte-for-byte):

```
{"anchor_comment":"ic_1234567890","approvers":["u_1001","u_1002"],"ballot_snapshot_hash":"9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f9f","decision_id":"dec-2026-0001","proposal_id":"prop-2026-0001","result":"ratified","window_hours":48}
```

With `prev_hash = "0"*64`:

```
H1 = 6fa7e0e498031e7f41911119195e3b393027b56c7ed7a9e63ac2c507f2c6ad52
```

This vector was computed independently on the lead's machine from the specification alone and matched the
governance service's output exactly. It is reproduced in `tests/test_ledger_format.py`; a change to the
canonicalisation must turn that test red.

## Window rule

```
merge_commit_committer_date - anchor_comment_created_at >= 48h
```

GitHub **committer** timestamps only. Author dates are chosen by the contributor and are trivially
backdated; the committer date is stamped by GitHub at merge time.

Rename semantics: `result` is one of `approved` | `rejected` | `void` | `waived`. The governance service
prototype used `ratified`; the vocabulary is fixed to `approved` so the gate's check and the service's
writer cannot disagree — a two-vocabulary ledger rejects every legitimate merge.

## Bootstrap waiver

The commit that introduces `.github/CODEOWNERS` cannot be approved by two code owners, because they do not
exist yet. It lands by direct push with `ledger/WAIVER-0001.md` naming who pushed, why, and exactly which
checks were impossible at that moment. The verifier exempts precisely that one SHA. The waiver is never
edited or deleted.

## Immutability

The `ledger` branch carries a branch ruleset that forbids force-push and deletion for everyone, maintainers
included. Records are append-only. If a record is wrong, a new record supersedes it via `supersedes`; the
old one stays on the record forever.
