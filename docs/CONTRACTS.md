# CONTRACTS — the shared format between the governance service and the gate

Owner: JARVIS writes the governance half (proposals, ballots, decisions, notifications, accounts). Merlin writes
the GitHub half (repo, CODEOWNERS, CI gate, dashboard, voting UX, every merge) and **consumes** this format.
This file is the contract. Neither side codes against anything not in here; a change to it is a PR to this file
with both names on it.

Status: **settled** as of 2026-11-25, after the owner's timer ruling and the identity/transport answers below.

---

## 1. The seam

| half                                                                      | owner  | lives in                                | may write to         |
| ------------------------------------------------------------------------- | ------ | --------------------------------------- | -------------------- |
| governance service, ballot engine, fan-out, ledger writer, accounts+prefs | JARVIS | its own directory, pure Python + SQLite | `ledger` branch only |
| repo, CODEOWNERS, CI gate, dashboard, voting UX, merges                   | Merlin | this repository                         | `main` (via PR)      |

- The gate **never calls the service**. The service **never sits in the merge path**. CI verifies offline from the
  `ledger` branch and re-fetches the GitHub artifacts the records name.
- The ledger is a **claim**, not an oracle: every fact it asserts (comments, reviews, timestamps) must be
  independently re-derivable from the GitHub API by anyone, with no access to JARVIS's box.

## 2. Identity (answer A — settled)

- The account is the **GitHub numeric user id**. Never a login (renames), never an email.
- **OAuth App** for human login: scopes `read:user` + `user:email`, nothing else.
- **GitHub App** for the service's ledger writes: installation token, one repository, `contents: write`, named as
  the only actor permitted to push `ledger`.
- Email is a **notification address only**. No magic links: a second identity space means one person with two
  accounts and two votes, silently.
- DCO is a trailer, not a signature. CI accepts it only when `Signed-off-by` is in that user's GitHub-verified
  email set **and** matches the commit author. Unforgeable authorship would need signed commits plus
  `verification.verified` — a separate decision, not made.

## 3. Records

Four shapes. Field-level detail for the ledger record is in [`LEDGER-FORMAT.md`](LEDGER-FORMAT.md); the rest is here.

### proposal

```text
proposal_id      prop-YYYY-NNNN   stable, NOT the issue number
title            str
author_gh_id     int              numeric GitHub id
issue_number     int
opened_at        ISO8601 Z        GitHub server timestamp
closed_at        ISO8601 Z        = the ballot close comment's created_at
status           open | voting | ratified | rejected | withdrawn | superseded | merged
scope_paths      [glob]           the PR diff must be a subset of these
supersedes       proposal_id|null
```

`scope_paths` is what makes "in-scope" operational: CI fails a PR that touches a path the approved proposal did
not authorise, even if the proposal was approved for something else entirely.

### ballot

```text
ballot_id               bal-YYYY-NNNN
proposal_id             prop-YYYY-NNNN
open_comment_id         int      the service's comment, GitHub-stamped
close_comment_id        int      likewise; its created_at IS the close time
voting_hours            48       written at open; closes_at is derived, never declared
opens_at / closes_at    ISO8601 Z  derived from the two comments
eligibility_rule        object   data, never code in the engine
eligibility_snapshot    {hash, published_ref}   eligible ids frozen at open, published
nonce                   str      published at open; binds a vote to this ballot
quorum_rule             {quorum, threshold, weighted}   written at open, decimals as strings
votes                   [{voter_gh_id, choice, comment_id, created_at, updated_at, body_sha256, source}]
tally                   {approve, reject, abstain}
quorum_met              bool
result                  ratified | rejected | void
```

## 4. Votes (answer D — settled)

- **GitHub-native artifacts only.** No Cloudflare Worker, no UI-held tally.
- Default source is a **reaction** on the pinned ballot comment (`source: reaction`): publicly readable, no scope
  escalation, authored and timestamped by GitHub.
- Multi-choice or long ballots use a **nonced comment** (`source: comment`), authored by the **voter's** token.
  A vote authored by a service identity is invalid — otherwise "anyone can recompute" is false.
- At `closes_at` the service snapshots every vote comment (`comment_id`, author id, server `created_at`/`updated_at`,
  `body_sha256`) and publishes the **normalized vote list** at `votes/<decision_id>.json`. An opaque hash over a blob
  only one machine holds proves nothing.
- Latest valid entry per voter counts; a deleted comment voids that vote; edits before close are legal because
  `updated_at` is server-side.

## 5. Notifications (answers B and C — settled)

- Channels: `discord_dm`, `webhook`, `rss`. **`email` is deferred** — Ryan's personal Gmail is not a send identity
  for a world-wide community, and a transactional provider on a dedicated subdomain with SPF/DKIM/DMARC and double
  opt-in is his money and his call. The enum keeps `email` so the schema does not churn; no transport ships.
- **Discord DM** works only for accounts sharing our guild who allow server DMs. Probe at registration — attempt one
  DM, record `dm_reachable: true|false` — and never promise it in the UI. Webhooks cannot DM; `rss`/`webhook` are the
  fallback for everyone else.
- Delivery is **never** a precondition for a vote counting.
- No PII in the chain: records carry `recipient_hash` (over the **numeric GitHub id only** — an email hash is
  dictionary-attackable) plus the channel. Webhook recipients are referenced by id, never by URL, because a webhook
  URL is a credential. The delivery log with real addresses stays private.
- `idempotency_key = decision_id + recipient_hash + channel`. Retries must not double-notify. Status moves
  `queued → sending → sent|failed|suppressed|bounced`, with `attempt` capped and `delivered_ref` (the real message
  id) written back so delivery is provable.

## 6. The ledger

Branch `ledger`, orphan, append-only, never merged to `main`: `ledger.jsonl`, `votes/<decision_id>.json`,
`keys/ledger-<k>.pub`. CI reads the tip of `ledger`; `main` never contains it.

- Format: [`LEDGER-FORMAT.md`](LEDGER-FORMAT.md) is normative. Current version **v2**, vector hash
  `5451538b45503c04b7d8b5e939628c3f7aee4c43735d22d6dca673146e2932a4`.
- Hash: `sha256(canonical_json(record minus hash and signature))`, `prev_hash` an ordinary field inside the
  preimage, genesis `prev_hash` = 64 zeros. Ed25519 signature over the 64 raw hash bytes.
- Immutable: corrections append a record carrying `supersedes`; the gate **folds** the chain (last record wins along
  the supersedes chain) rather than scanning it, so revocation can coexist with immutability.
- Trust root: `.github/ledger-trusted-keys.txt` on `main`, which the service cannot push to. A key that exists only
  on the `ledger` branch can re-sign a fully rewritten chain, so it does not count.

## 7. The gate — what CI verifies, in order

1. `ledger.jsonl` chain intact from genesis; every signature verifies against a key in the trust root.
2. The decision record for the PR's `Approved-Proposal:` reference is the **folded** current record, `kind: ratify`,
   `result: ratified`, and no later record revokes it.
3. `close_comment.created_at - open_comment.created_at == voting_hours` (48), both GitHub-stamped.
4. **Merge is allowed the moment the ballot closes** — no post-close waiting period (owner ruling 2026-11-25).
5. **Never unreviewed:** two code-owner approvals whose `reviewed_sha == head_sha` (stale approvals dismissed on
   push), green CI, and the PR diff a subset of `scope_paths`.
6. Every asserted fact is re-fetched from the GitHub API: comment ids, review ids, timestamps. A record that
   disagrees with the API fails the PR.

Merge time is the PR's `merged_at` from the REST merge API — server-set. Commit dates are never an input;
`GIT_AUTHOR_DATE` and `GIT_COMMITTER_DATE` are both forgeable by the author.

## 8. Handoff between the two boxes

The board is per-machine SQLite and never crosses the wire. State crosses as JSON in the repo:

- `docs/handoff/jarvis.json` — written only by JARVIS.
- `docs/handoff/lead.json` — written only by Merlin.
- Both keyed on `task_id`; the dashboard merges them read-only. Neither side touches the other's file.

Card ids are opaque strings on both sides. JARVIS's nodes: `t_22c8296e`, `t_62e0a6b2`, `t_7c79f74f`, `t_94894e97`,
`t_0dadcf2b`, `t_fdb191d9`.

## 9. Change control

- One writer per file. A shared file gets a PR with both names or it does not land.
- A contract change is a PR to this file **plus** a new ledger vector if the record shape moves. No silent edits:
  a format that drifts under a running verifier is worse than a wrong one, because the wrong one fails loudly.
- Disagreements go to Ryan, not to a silent divergence.

## 10. Open, and not ours to decide

1. **Eligibility** — earned (merged PR or seconded proposal in the last 90 days) or an invite-only founding roster.
   Unbounded accounts means a bot farm decides the game.
2. **Licence** — Apache-2.0 code + CC-BY-4.0 assets, or CC-BY-SA throughout. Must be settled before the first asset
   is accepted.
3. **Repo visibility** — the repository is public right now because the scaffold was pushed.
4. **Bootstrap lock** — `main` requires two code-owner approvals and an approved proposal; neither can exist before
   the ledger does. Needs a WAIVER-0002 for the bootstrap sequence or a one-time ruleset bypass.
