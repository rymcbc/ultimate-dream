# Governance — how the loop actually runs

Companion to `CONSTITUTION.md`. The constitution says what is allowed; this says what happens, in what order,
and who is told.

## The 48-hour loop

| T               | Event                                                                                          | Who acts                     | Where it is recorded                       |
| --------------- | ---------------------------------------------------------------------------------------------- | ---------------------------- | ------------------------------------------ |
| T-∞             | Proposal opened from the issue form                                                            | anyone with a linked account | GitHub issue, `prop-YYYY-NNNN`             |
| T-24h at latest | Triage: scope confirmed, split if oversized                                                    | maintainers                  | issue label + comment                      |
| **T+0**         | **Ballot opens.** Nonce published, eligibility frozen, votes accepted from this second         | system                       | ledger `open_comment_id`                   |
| **T+0**         | **Notifications fan out** — Discord DM, email, Telegram, per each contributor's chosen channel | system                       | audit log, per-recipient delivery result   |
| **T+0**         | **Owner review request** — Discord DM to Ryan: ballot, proposal, close time, Review / Override | system → Ryan                | audit log `owner_notified_at`              |
| T+0…T+48h       | Voting and discussion; owner may override with a cited ground                                  | eligible roster              | each vote is a GitHub-authored artifact    |
| **T+48h**       | **Close.** Votes frozen into a snapshot, tally computed, result recorded                       | system                       | ledger record + `votes/<decision_id>.json` |
| T+48h           | Result announced on the same channels the ballot was announced                                 | system                       | audit log                                  |
| T+48h →         | Implementation PRs may open; gate verifies the ledger record                                   | contributors                 | PR                                         |
| merge           | Requires 2 code-owner reviews on head, DCO, scope match, green CI                              | code owners                  | `main`                                     |
| merge +         | `docs/DECISIONS/<id>.md` written, roadmap regenerated                                          | system                       | repo                                       |

**There is no second waiting period.** The 48 hours covers both the vote and the notice, because every
contributor was told at T+0 and had the whole window to object.

## Roles

- **Contributor** — linked account, may propose, vote, comment, and submit PRs.
- **Code owner** — listed in `CODEOWNERS` for some path; their review is required, and a review of an older
  commit does not count.
- **Maintainer** — triages proposals, merges what the gate allows. Cannot merge what the gate refuses.
- **Owner (Ryan)** — one voter plus the documented, cited, challengeable override in §6 of the constitution.

## Notifications

Three transports, chosen per contributor at signup and changeable any time:

1. **Discord DM** — only for accounts sharing the guild that allow server DMs; the picker hides DM until a probe
   succeeds.
2. **Email** — SMTP from the project's own address. Written as configuration (host, port, user, app password,
   from address) so a provider swap is a config change, not a rewrite. A consumer mailbox is fine for the first
   ballots and stops being fine somewhere in the low hundreds of recipients; that ceiling is a known limit, not a
   surprise.
3. **Telegram** — bot DM to a linked Telegram account, linked by a one-time code.

Rules: retry with backoff, fall through to the next preferred channel on hard failure, never send the same
ballot twice on the same channel, and never make delivery a condition of a vote counting.

## Quorum, including a one-person roster

Quorum is 20% of the eligible roster with a floor of 5 votes cast — except that the floor can never exceed the
roster. While fewer than 5 members are eligible, quorum is **every eligible voter**, so a founding ballot with
one eligible member is decided by that member, is valid, and records the quorum it actually required. The floor
of 5 governs again the moment the roster reaches 5. This is deliberately not a percentage of one dressed up as
democracy: it is the entire electorate, and it is the only rule under which a project can start on day one with
one person and still mean the same thing when there are five hundred.

## Escalation

| Situation                           | Action                                                                                  |
| ----------------------------------- | --------------------------------------------------------------------------------------- |
| Ballot below quorum                 | `void`, one automatic re-run with a fresh 48h, then fail closed                         |
| Ballot tied                         | `rejected`, 14-day cooldown before re-proposal                                          |
| Owner override                      | ballot stops, `revoke` record with cited ground, challengeable by 2/3 of a fresh ballot |
| Owner does not respond              | ballot proceeds — silence is not an override                                            |
| Gate and record disagree            | the gate wins by refusing; a human investigates before anyone touches the rule          |
| Proposer disagrees with a rejection | re-propose after cooldown with amendments, never a direct merge                         |

## What is deliberately absent

- No lazy consensus and no "no objection in 7 days" rule — silence is not consent here.
- No ranked-choice for ordinary proposals. Three choices (`yes`/`no`/`abstain`) keep the tally recomputable by
  anyone with a browser.
- No vote weighting by contribution, reputation or holdings. Reputation weights are how a community hands its
  decisions to its loudest members.
- No override without a cited ground, and no silent removal of a proposal from the queue.
