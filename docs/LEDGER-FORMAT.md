# Ledger Format v1 (normative)

The ledger is how a stranger proves a change was approved by real people after a real notice window,
**without trusting our servers**. It lives on an orphan branch `ledger`, never merged to `main`.

Agreed between Merlin (gate side) and JARVIS (governance service, the writer) on 2026-11-25. Both vectors
below were reproduced independently on the gate side from the specification alone, before either side wrote
code against them.

## Branch layout

```
ledger                                  orphan branch, append-only, force-push forbidden
├── ledger.jsonl                        one record per line, UTF-8, LF, no blank lines
├── votes/<decision_id>.json            frozen vote snapshot for that decision
└── keys/ledger-<k>.pub                 Ed25519 public key used to sign records
```

CI reads the tip of `ledger`. `main` never contains it.

## Hash rule (v1 — this is the one that matters)

```
canonical_json = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
hash           = sha256(canonical_json).hexdigest()
```

`prev_hash` is **a field inside the record** and therefore inside the preimage. Only `hash` and `signature`
are excluded.

**Superseded rule — never produced in production, must never verify:** an earlier sketch prepended
`prev_hash_hex` to the canonical bytes and excluded the field. On the v1 sample record that rule yields
`2de74e9d…`; the v1 rule yields `0d87f7b4…`. Both are pinned in `tests/test_ledger_format.py`, where the
legacy rule is asserted to *fail* — so nobody restores it by accident. A format hashed two ways is how an
audit ends up with a decision that was legitimately approved and cannot be proven.

## Record fields (all required)

| field | type | notes |
|---|---|---|
| `kind` | `ratify` \| `revoke` \| `waive` \| `supersede` | how to read the record |
| `schema_version` | int | 1 |
| `decision_id`, `proposal_id`, `ballot_id` | str | stable ids, not issue numbers |
| `open_comment_id`, `close_comment_id` | int | GitHub-stamped comments; the close comment's `created_at` is the only permitted window anchor |
| `voting_hours` | int | **vote window**, written at open so `closes_at` is derivable, never declared |
| `ballot_closed_at` | ISO8601 Z | must equal `close_comment.created_at` exactly |
| `votes_ref` | path | e.g. `votes/dec-2026-0001.json` |
| `ballot_snapshot_hash` | hex | `sha256(JCS(votes array))`, frozen at close |
| `eligibility_snapshot_hash` | hex | `sha256(JCS(eligible ids))`, frozen at open |
| `head_sha` | 40 hex | the tree the approvers reviewed; the merge must match it |
| `approvers` | array | `{gh_id, review_id, reviewed_sha}` — re-fetched from the API, never trusted as claimed |
| `scope_paths` | array | globs the PR must stay inside |
| `proposal_body_sha256` | hex | the pitch that was actually voted on |
| `quorum_rule` | object | `{quorum, threshold, weighted}`, decimals as strings |
| `tally` | object | `{approve, reject, abstain}` |
| `result` | `ratified` \| `rejected` \| `void` \| `waived` | **writer's vocabulary** — the gate adopts it, not the reverse |
| `prev_hash` | 64 hex | genesis = 64 zeros |
| `signer_key_id` | str | which key in `keys/` signed it |
| `supersedes` | id \| null | append-only correction, never an edit |
| `created_by` | str | writer identity, e.g. `githubapp:ultimate-dream-ledger` |

## Two timers — do not merge them

- **Vote window** (`voting_hours`): how long the ballot stays open for voting.
- **Notice window** (`window_hours`, 48): the ratification gap between ballot close and merge. Ryan's
  requirement — "passed, then a 2-day timer, then it goes in the game" — is *this* one.

A record carrying only one of them cannot distinguish "voted for two days" from "approved and merged
instantly", which is precisely the failure the project exists to prevent. The gate enforces:

```
merge_commit_committer_date - ballot_closed_at >= 48h
```

GitHub **committer** timestamps only. Author dates are chosen by the contributor and are trivially backdated.

## Test vectors (normative)

### Vector A — record

Canonical bytes:

```
{"approvers":[{"gh_id":1001,"review_id":3912345678,"reviewed_sha":"4f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d"}],"ballot_closed_at":"2026-11-25T17:00:00.000Z","ballot_id":"bal-2026-0001","ballot_snapshot_hash":"fb7fb3e41180e4e28cdb6b97355d5c3b358ebafeb2c23a6daefd3edd8a5a9563","close_comment_id":191234999,"created_by":"githubapp:ultimate-dream-ledger","decision_id":"dec-2026-0001","eligibility_snapshot_hash":"3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c","head_sha":"4f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d","kind":"ratify","open_comment_id":191234567,"prev_hash":"0000000000000000000000000000000000000000000000000000000000000000","proposal_body_sha256":"7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d","proposal_id":"prop-2026-0001","quorum_rule":{"quorum":"0.20","threshold":"0.50","weighted":false},"result":"ratified","schema_version":1,"scope_paths":["game/content/props/**","game/content/items/**"],"signer_key_id":"k1","supersedes":null,"tally":{"abstain":0,"approve":1,"reject":0},"votes_ref":"votes/dec-2026-0001.json","voting_hours":72}
```

```
H(record) = 0d87f7b4719159c11f00ba89a968c18fb869dc9fa630d0288b9a937c0b3abc1f
```

### Vector B — vote snapshot

Canonical bytes:

```
[{"body_sha256":"abababababababababababababababababababababababababababababababab","comment_id":191234701,"created_at":"2026-11-23T10:00:00.000Z","updated_at":"2026-11-23T10:00:00.000Z","voter_gh_id":1001}]
```

```
ballot_snapshot_hash = fb7fb3e41180e4e28cdb6b97355d5c3b358ebafeb2c23a6daefd3edd8a5a9563
```

### Retired vector

`6fa7e0e498031e7f41911119195e3b393027b56c7ed7a9e63ac2c507f2c6ad52` — the v0 sketch, kept only as a
negative test.

## Bootstrap waiver

The commit that introduces `.github/CODEOWNERS` cannot be approved by two code owners, because none exist
yet. It lands by direct push with `ledger/WAIVER-0001.md` naming who pushed, why, and exactly which checks
were impossible at that moment. The verifier exempts precisely that one SHA. The waiver is never edited.

## Immutability

`ledger` carries a branch ruleset forbidding force-push and deletion for everyone, maintainers included.
Records are append-only; a wrong record is superseded, and the old one stays forever.

## Open items

- `schema_version` stayed `1` while the preimage rule changed from the sketch. The sketch is recorded here as
  superseded; a bump to `2` is pending the writer's decision, so no two records claim the same version under
  different rules.
- `voting_hours: 72` — sample value or decision, pending confirmation.
- Ed25519 signature verification (over the 64 raw hash bytes) and the `LEDGER_HEAD` anchor are specified but
  not yet wired.
