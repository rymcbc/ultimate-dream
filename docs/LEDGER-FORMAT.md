# Ledger Format v1 (normative)

The ledger is how a stranger proves a change was approved by real people after a real notice window,
**without trusting our servers**. It lives on an orphan branch `ledger`, never merged to `main`.

Agreed between Merlin (gate side) and JARVIS (governance service, the writer) on 2026-11-25. Both vectors
below were reproduced independently on the gate side from the specification alone, before either side wrote
code against them.

## Branch layout

````text
ledger                                  orphan branch, append-only, force-push forbidden
├── ledger.jsonl                        one record per line, UTF-8, LF, no blank lines
├── votes/<decision_id>.json            frozen vote snapshot for that decision
└── keys/ledger-<k>.pub                 Ed25519 public key used to sign records
```text

CI reads the tip of `ledger`. `main` never contains it.

## Hash rule (v2 — this is the one that matters)

```text
canonical_json = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
hash           = sha256(canonical_json).hexdigest()
```text

`prev_hash` is **a field inside the record** and therefore inside the preimage. Only `hash` and `signature`
are excluded.

**Superseded rules — never produced in production, must never verify:**

| version                | rule                                                                                                             | sample hash of the vector below | status             |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------- | ------------------------------- | ------------------ |
| v0 (sketch)            | `sha256(prev_hash_hex + canonical(record))`, `prev_hash` excluded from the preimage                              | `2de74e9d…`                     | retired, must fail |
| v1                     | same preimage as v2, but `schema_version: 1`, `voting_hours: 72`, no `owner_*` fields                            | `0d87f7b4…`                     | retired, must fail |
| v2-draft               | `schema_version: 2` plus a `notice_hours: 48` field (a second, post-vote waiting period that the owner withdrew) | `fcd1a449…`                     | retired, must fail |
| **v2 (this document)** | `sha256(canonical(record))`, `prev_hash` inside, `schema_version: 2`, one 48-hour window                         | `5451538b…`                     | **current**        |

All four are pinned in `tests/test_ledger_format.py`; the three retired ones are asserted to _fail_, so nobody
restores one by accident. A format hashed two ways is how an audit ends up with a decision that was legitimately
approved and cannot be proven.

## Record fields (all required)

| field                                     | type                                           | notes                                                                                                |
| ----------------------------------------- | ---------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `kind`                                    | `ratify` \| `revoke` \| `waive` \| `supersede` | how to read the record                                                                               |
| `schema_version`                          | int                                            | 2                                                                                                    |
| `decision_id`, `proposal_id`, `ballot_id` | str                                            | stable ids, not issue numbers                                                                        |
| `open_comment_id`, `close_comment_id`     | int                                            | GitHub-stamped comments; the close comment's `created_at` is the only permitted window anchor        |
| `voting_hours`                            | int                                            | **the single window**: 48 in production. Written at open so `closes_at` is derivable, never declared |
| `owner_notified_at`                       | int \| null                                    | when the owner was DM'd at T0 (audit only, never a gate input)                                       |
| `owner_decision`                          | `none` \| `reviewed` \| `override`             | silence is `none` and the ballot proceeds                                                            |
| `owner_override_ground`                   | str \| null                                    | required when `owner_decision` is `override`; one of legal \| safety \| security \| build            |
| `ballot_closed_at`                        | ISO8601 Z                                      | must equal `close_comment.created_at` exactly                                                        |
| `votes_ref`                               | path                                           | e.g. `votes/dec-2026-0001.json`                                                                      |
| `ballot_snapshot_hash`                    | hex                                            | `sha256(JCS(votes array))`, frozen at close                                                          |
| `eligibility_snapshot_hash`               | hex                                            | `sha256(JCS(eligible ids))`, frozen at open                                                          |
| `head_sha`                                | 40 hex                                         | the tree the approvers reviewed; the merge must match it                                             |
| `approvers`                               | array                                          | `{gh_id, review_id, reviewed_sha}` — re-fetched from the API, never trusted as claimed               |
| `scope_paths`                             | array                                          | globs the PR must stay inside                                                                        |
| `proposal_body_sha256`                    | hex                                            | the pitch that was actually voted on                                                                 |
| `quorum_rule`                             | object                                         | `{quorum, threshold, weighted}`, decimals as strings                                                 |
| `tally`                                   | object                                         | `{approve, reject, abstain}`                                                                         |
| `result`                                  | `ratified` \| `rejected` \| `void` \| `waived` | **writer's vocabulary** — the gate adopts it, not the reverse                                        |
| `prev_hash`                               | 64 hex                                         | genesis = 64 zeros                                                                                   |
| `signer_key_id`                           | str                                            | which key in `keys/` signed it                                                                       |
| `supersedes`                              | id \| null                                     | append-only correction, never an edit                                                                |
| `created_by`                              | str                                            | writer identity, e.g. `githubapp:ultimate-dream-ledger`                                              |

## One window: 48 hours (owner ruling, 2026-11-25)

There is **one** timer. It is the vote window _and_ the notice period, and it is 48 hours:

- `voting_hours: 48`, written at open so `closes_at` is derivable, never declared.
- Everyone eligible is notified at T0 and has the full window to object.
- The merge may follow immediately after close. There is **no second waiting period** — an earlier draft in this
  document required `merge_time - close >= 48h`, and that is hereby withdrawn.

Gate rule instead:

```text
close_comment.created_at - open_comment.created_at == 48h   (GitHub-stamped, both of them)
merge is allowed any time after close
```text

GitHub **committer** timestamps only; author dates are chosen by the contributor and are trivially backdated.
`window_hours` is removed rather than left in place meaning nothing.

## Test vectors (normative)

### Vector A — record

Canonical bytes:

```json
{"approvers":[{"gh_id":1001,"review_id":3912345678,"reviewed_sha":"4f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d"}],"ballot_closed_at":"2026-11-25T19:00:00.000Z","ballot_id":"bal-2026-0001","ballot_snapshot_hash":"fb7fb3e41180e4e28cdb6b97355d5c3b358ebafeb2c23a6daefd3edd8a5a9563","close_comment_id":191234999,"created_by":"githubapp:ultimate-dream-ledger","decision_id":"dec-2026-0001","eligibility_snapshot_hash":"3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c","head_sha":"4f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d","kind":"ratify","open_comment_id":191234567,"owner_decision":"reviewed","owner_notified_at":1795633200,"owner_override_ground":null,"prev_hash":"0000000000000000000000000000000000000000000000000000000000000000","proposal_body_sha256":"7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d7d","proposal_id":"prop-2026-0001","quorum_rule":{"quorum":"0.20","threshold":"0.50","weighted":false},"result":"ratified","schema_version":2,"scope_paths":["game/content/props/**","game/content/items/**"],"signer_key_id":"k1","supersedes":null,"tally":{"abstain":0,"approve":1,"reject":0},"votes_ref":"votes/dec-2026-0001.json","voting_hours":48}
```json

```text
H(record) = 5451538b45503c04b7d8b5e939628c3f7aee4c43735d22d6dca673146e2932a4
```text

### Vector B — vote snapshot

Canonical bytes:

```json
[{"body_sha256":"abababababababababababababababababababababababababababababababab","comment_id":191234701,"created_at":"2026-11-23T10:00:00.000Z","updated_at":"2026-11-23T10:00:00.000Z","voter_gh_id":1001}]
```json

```text
ballot_snapshot_hash = fb7fb3e41180e4e28cdb6b97355d5c3b358ebafeb2c23a6daefd3edd8a5a9563
```text

### Retired vectors — must fail

| hash                                                               | what it was                                                                |
| ------------------------------------------------------------------ | -------------------------------------------------------------------------- |
| `6fa7e0e498031e7f41911119195e3b393027b56c7ed7a9e63ac2c507f2c6ad52` | v0 sketch (prefix rule)                                                    |
| `0d87f7b4719159c11f00ba89a968c18fb869dc9fa630d0288b9a937c0b3abc1f` | v1 (`schema_version: 1`, `voting_hours: 72`, no owner fields)              |
| `fcd1a4495b37cb1803070a793e849bbefc9f1b570b8eff2f9e57bdb4abbf4701` | v2-draft (`notice_hours: 48` — a second waiting period the owner withdrew) |

## Bootstrap waiver

The commit that introduces `.github/CODEOWNERS` cannot be approved by two code owners, because none exist
yet. It lands by direct push with `ledger/WAIVER-0001.md` naming who pushed, why, and exactly which checks
were impossible at that moment. The verifier exempts precisely that one SHA. The waiver is never edited.

## Immutability

`ledger` carries a branch ruleset forbidding force-push and deletion for everyone, maintainers included.
Records are append-only; a wrong record is superseded, and the old one stays forever.

## Open items

- `schema_version` is **2** as of 2026-11-25, after the owner's 48-hour ruling. The three earlier shapes (v0 sketch,
  v1, v2-draft) are retired above and none was ever produced in production.
- `voting_hours` — **resolved 2026-11-25 by the owner: 48 hours, one window.** The vector now carries `48`, so the
  pin and the policy finally agree; the earlier note that kept `72` in the vector to protect an agreed hash is
  withdrawn, because that hash belonged to a rule the owner rejected.
- The merge may follow immediately after close **but never unreviewed**: two code-owner approvals on the current
  `head_sha`, green CI, and an approved proposal are still required. The 48 hours is a notice period, not a
  substitute for review.
- Ed25519 signature verification (over the 64 raw hash bytes) and the `LEDGER_HEAD` anchor are specified but
  not yet wired.
````
