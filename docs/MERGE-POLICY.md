# Merge policy

Normative for this repo. If a rule here and a chat message disagree, this file wins until it is
changed by a commit.

## Why the review gate is 0

This repo has **one** GitHub identity (`rymcbc`). GitHub refuses to let an account approve its own
pull request, so **any** `required_approving_review_count` ≥ 1 is unsatisfiable — not strict, not
unreachable-by-policy, arithmetically impossible. A gate nobody can pass is a wall, not a gate: it
held #11, #13 and #16 for hours while CI was green and the work was done.

So the gate is:

- `required_status_checks`: `ci`, `proposal-check` — **both mandatory**
- `required_status_checks.strict`: **on** — the branch must be current with `main`
- `required_approving_review_count`: **0**
- `enforce_admins`: **on** — nobody bypasses CI, including the coordinator

`enforce_admins` stays on deliberately. It means every merge is gated by CI and nothing else, so
the protection that remains is the protection that actually measures something.

## Who merges

The **coordinator** (Merlin) merges, and only after the checks on the current head are green.
Workers commit inside their own worktrees; nobody merges on a timer. There are no scheduled
merges — a merge happens in a turn where someone looked at it.

## Dedupe — check before you open

Two agents on one repo collide at the speed of the faster one. Before opening a PR:

1. `gh pr list --state open` — if a PR already touches the same paths, comment there instead.
2. Check the board for a card with the same scope.
3. If the work is genuinely a duplicate of something already in `main`, close it with the reason
   rather than rebasing it into a second implementation.

Measured cost of skipping this: #13 (a fan-out that #14 had already replaced) and #17/#18 (the same
one-line CI change opened twice within 8 seconds). Duplicate code that lands is worse than
duplicate code that doesn't.

## Lane ownership

- **JARVIS** — governance service, ballot engine, notifications/fan-out, ledger writer, accounts
- **Merlin** — repo shape, CI gate, dashboard, voting UX, and **all merges**
- Anything that changes the *machine* (installs, services, config, keys) is Ryan's call, not a
  lane call.

## Changing this file

The coordinator does it, in a commit, with the reason in the message. Branch protection is edited
by the coordinator only — it has already been flipped back to an unsatisfiable value once, which
silently froze every PR until someone noticed.
