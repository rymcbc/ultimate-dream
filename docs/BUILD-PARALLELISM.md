# Building in parallel, and building without each other

Two builders, one repository. JARVIS works from SERVER-PC, Merlin from Ryans_Desktop. The rule below exists so
that either of us going offline slows the project down without stopping it.

## 1. The repository is the queue

The board on each machine is private SQLite — Merlin cannot see JARVIS's board and JARVIS cannot see Merlin's.
Anything that must be coordinated lives in the repository:

- **Claim** = a comment on the issue `claiming: <name>` **and** a pushed branch within two hours. A claim with no
  branch is a wish, not work, and expires.
- **Branch prefix** is the claimant: `jarvis/<slug>` or `merlin/<slug>`.
- **One branch, one PR, one card.** The PR body carries the card id, what changed, the proof command and its real
  exit code.
- **Stale claim**: no push for `CLAIM_STALE_HOURS` (default 12) while a claim is open and the work is unstarted or
  abandoned ⇒ any other builder may claim it. The comment says so on the issue, in public, at the time it happens.

## 2. Nothing is owned by a person

Every card has an **owner** and a **failover owner**, and the failover owner is always the other builder. A card
whose owner is unreachable for `CLAIM_STALE_HOURS` is picked up rather than waited on. Waiting on a specific
agent is the failure mode this document exists to prevent; the project ran for a night with four cards parked
behind someone else's inbox.

## 3. First green wins

If both builders end up with branches for the same card (a race after a stale claim), the first PR that goes
green is merged and the other is closed with the reason. Duplicated effort is cheaper than a stalled project, and
it is bounded to one card.

## 4. What must never depend on the other machine

- **Merges**: only Merlin merges, but a merge is a review + a script — it survives either builder being away.
- **The gate**: CI runs on GitHub, not on a laptop. Neither machine has to be awake.
- **The registry of record**: the hash-chained ledger is a git branch, verified offline. No service has to be
  running for a decision to be checkable.
- **The board**: local, deliberately. It is a convenience, never a system of record.

## 5. Failover is mechanical, not a judgement call

`scripts/failover_check.py` runs hourly. It asks GitHub whether the JARVIS lane has produced anything within the
stale window. If it has not, it comments on the affected issues and reports which cards are now unowned, so they
can be picked up by whoever is awake. It never edits another agent's work and it never merges.

A failover notice is not an accusation — a builder being offline is normal. It is the mechanism that keeps the
project's critical path off any single machine.
