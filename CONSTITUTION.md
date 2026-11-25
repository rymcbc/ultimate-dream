# Constitution of the Ultimate Dream

Ratified by ballot. Amending it takes a 2/3 supermajority (§12).

## 1. What this is

A world-wide, community-built game. Anyone may propose, everyone may vote, and nothing enters the game until it
has passed a vote and been reviewed. The game is the product; this document is what stops the product from
belonging to whoever shouts loudest or commits fastest.

## 2. The only way a change enters the game

````text
idea → proposal → 48-hour ballot → ratified → reviewed PR → merged
```text

No step may be skipped, and no one is exempt. A maintainer who wants a change opens a proposal like everyone
else. The single exception is the bootstrap commit that creates this repository's review rules, which lands under
`ledger/WAIVER-0001.md` because a gate cannot approve the commit that creates it.

## 3. The 48-hour ballot

- **Window: exactly 48 hours, hard.** Server-side, UTC, no extensions, no early close, no exceptions for
  holidays, outages or enthusiasm.
- **Every eligible contributor may vote** for the whole window. Voting is `yes`, `no` or `abstain`.
- **Notification at open**: every eligible contributor is told the ballot has opened, on the channel they chose
  in their account — Discord DM, email, or Telegram. A contributor who received no notification has still had
  their chance to vote; delivery is never a condition of a vote counting.
- **Owner review at open**: the project owner receives a Discord DM at T0 naming the ballot, the proposal, the
  window and the close time, and may **review or override** it during the window (§6).
- **Close and result**: at T0+48h the ballot closes and the tally is computed from frozen votes. There is no
  further waiting period — the 48 hours _is_ the notice period, and implementation may begin the moment the
  result is recorded.

## 4. Who may vote

- A linked GitHub account at least **30 days old** with a verified email. One account, one vote — uniqueness is
  enforced by GitHub's numeric user id, never by login (logins get renamed and recycled).
- No contribution requirement. Requiring a merged PR before the first vote would make the first vote impossible.
- **Dormant** after 180 days with no vote and no merged PR; dormant accounts are dropped from the roster so
  quorum tracks a living population instead of a graveyard that voids every ballot.
- **Eligibility is frozen at open.** New signups during a window do not change who was eligible or what quorum
  meant.

## 5. Quorum and majority

- **Quorum: 20% of the eligible roster, with a floor of 5 votes cast.** Abstain counts toward quorum and never
  toward the majority.
- **Below quorum**: the ballot is `void`, one automatic re-run with a fresh 48 hours, then it fails closed.
- **Majority: more than 50% of yes+no.** A tie is **rejected** — a tie is not consent — and may be re-proposed
  after a 14-day cooldown with amendments.
- **Bootstrap**: the first three ballots use the floor of 5 only. This expires permanently on the third
  decision; a percentage of a three-person roster is noise, and pretending otherwise would be theatre.

## 6. Owner review and override

The project owner is **Ryan**. At the start of every 48-hour window he is asked, in his Discord DMs, to review
the ballot or override it.

- An override **stops the ballot** and is recorded as a `revoke` record in the ledger with the owner's GitHub id
  and a cited ground. It is not a quiet deletion; it is on the public record forever.
- An override must cite **one of exactly four grounds**: legal or licensing, safety or terms of service,
  security, or _does not build_. "I don't like it" is not a ground.
- An override may be challenged: a fresh ballot reaching **2/3 of yes+no** sustains the proposal over the
  override. The owner cannot be overridden by a simple majority, and cannot override by silence either — any
  ballot he neither reviews nor overrides simply proceeds.
- The owner has no other special power. He is one voter plus one documented, cited, challengeable stop button.

## 7. Scope rule

A proposal must be implementable in a single milestone. Oversized ideas are split into an epic with child
proposals. Reviewers reject monoliths as "split this" — voting on a monolith is how a community approves
something nobody can build.

## 8. How a change actually merges

Every merge requires **all** of:

1. An approved proposal id cited in the PR.
2. A ratified ledger record that verifies offline: intact hash chain, quorum met, majority reached, and a ballot
   that was open for the full 48 hours between its GitHub-stamped open and close comments.
3. Two code-owner reviews **against the current head commit** — a push after review invalidates it.
4. A DCO `Signed-off-by` matching the commit author.
5. Changed paths inside the proposal's declared scope.
6. Every asset accompanied by a `LICENSE.txt` naming its source.
7. Green CI.

Direct pushes to `main` are forbidden for everyone, maintainers included. If a check is wrong, the check gets
fixed by proposal — not bypassed by a push.

## 9. Assets and licensing

- Code license is chosen by ballot among MIT, Apache-2.0, MPL-2.0, GPL-3.0, AGPL-3.0. MIT applies as a
  placeholder until that ballot closes.
- Assets must be redistributable: CC0, CC-BY, or a license explicitly permitting redistribution. No file enters
  the repository without a `LICENSE.txt` naming its origin.
- AI-generated assets are permitted when the generator's terms allow redistribution; the tool and its license
  are recorded in the sidecar.
- No single file over 20 MB; no binary over 5 MB without a Git LFS pointer.

## 10. Transparency

- Every ballot, vote, tally and override is public and recomputable from GitHub alone, without our servers.
- Financial decisions (if the project ever takes money) require a ballot and a quarterly public report.

## 11. Forks and exit

This document binds `main` of the official repository. Forks may adopt, amend or discard it. If `main` has no
commits for 365 days the project is dormant and the repository is offered to its contributors. Code and
decisions stay public either way — the ledger is designed so that the history outlives the servers.

## 12. Amendment

Changing this document is a proposal like any other, requiring a **2/3 supermajority of yes+no** and the same
48-hour window. No clause is unamendable, including this one.

---

_Signed by the founding contributors via DCO on their first commit._
````
