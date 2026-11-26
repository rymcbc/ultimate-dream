# Ultimate Dream

A collaborative game project built in the open. We vote on direction, ship playable builds, and share everything.

**Status**: 🟡 Bootstrap phase. The repository, the governance rules and the ledger gate are live. The ballot
engine is in build, the engine choice is still an open ballot, and there is no playable build yet. This README
says so rather than describing the end state.

![CI](https://github.com/rymcbc/ultimate-dream/actions/workflows/ci.yml/badge.svg)

## What exists today, exactly

| Thing                            | State                                                    |
| -------------------------------- | -------------------------------------------------------- |
| Governance rules                 | live — `CONSTITUTION.md`, `docs/GOVERNANCE.md`           |
| Ledger format + offline verifier | live — `docs/LEDGER-FORMAT.md`, `tools/ledger_verify.py` |
| Ledger writer                    | live — `governance/ledger.py`, 22 tests                  |
| CI gate                          | live — required check `ci` on `main`                     |
| Ballot engine                    | in build                                                 |
| Notifications (Discord/Telegram) | not built — nothing sends anything yet                   |
| Game engine                      | undecided — that is what the first ballot is for         |
| Playable build                   | none                                                     |

If a document here disagrees with this table, the table is right and the document is a bug. Report it.

## A stranger's path to a merged change

1. **Read** `CONSTITUTION.md` (§2 is how anything enters the game) and `docs/CONTRIBUTING.md`.
2. **Propose** — open a Proposal issue. Every non-trivial change starts as one, no exceptions.
3. **Ballot** — once the ballot engine is live, a hard 48-hour window decides it.
4. **Build** — branch from `main`, one logical change, sign your commits, open a PR.
5. **Merge** — green `ci`, the proposal reference in the PR body, and a maintainer merge.

While the ballot engine is still in build, steps 3 and 5 are executed by the project lead under
`ledger/WAIVER-0001.md` and the bootstrap path in `.github/workflows/proposal-check.yml`. That window is
explicit, it is stated in the PR body, and it closes the moment the first `DECISIONS/UD-###.md` exists.

## Where to talk

- Discord: **Making The Dream** (invite from a maintainer). Ballot and build discussion happens there.
- GitHub Issues: proposals, bugs, and anything that must outlive a chat.
- Do not DM a maintainer for a decision that belongs in an issue — it will be asked to move.

## Honest limitations

- One GitHub account currently holds write access, so "two code-owner reviews" cannot yet be satisfied by two
  people. Known bootstrap debt, tracked in the open, not hidden.
- No engine, no build, no screenshots. Anyone claiming otherwise is talking about a private branch.
