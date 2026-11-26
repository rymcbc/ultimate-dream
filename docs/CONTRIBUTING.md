# Contributing to Ultimate Dream

Welcome! This project runs on **proposals → PRs → reviews**. No drive-by merges.

## Quick Start

1. **Read**: `CONSTITUTION.md`, `GOVERNANCE.md`, this file.
2. **Propose**: File a **Proposal** issue (Issues → New → Proposal) for any non-trivial change.
3. **Claim**: Pick a task from the Project board or the proposal's task list.
4. **Develop**: Branch from `main`, commit with `-s` (DCO), push.
5. **PR**: Open a PR with `Approved-Proposal: UD-###` in the description.
6. **Review**: green CI plus a maintainer merge. During bootstrap the maintainer merge is the lead's, under
   `ledger/WAIVER-0001.md`.

## Commit Hygiene

- **Sign every commit**: `git commit -s`. Advisory during bootstrap (we squash-merge, so the merge commit
  carries the signer); required once the ballot engine is ratifying.
- **Conventional commits**: `feat:`, `fix:`, `refactor:`, `docs:`, `assets:`, `ci:`, `chore:`.
- **One logical change per PR**. Split if needed.

## Worked example — a change that actually goes through

This is the shape, not a hypothetical:

```text
1. Idea      "The repo needs a ledger format two machines can verify offline."
2. Proposal  Issue: "Ledger v2 - hash-chained decision records"     -> becomes UD-001
3. Ballot    48h window, quorum 20% of roster, majority of yes+no
4. Ratified  record written to the ledger branch, hash published
5. Build     branch ledger/format-v2, commits signed, tests added
6. PR        title "[UD-001] ledger: hash-chained records"
             body: what changed, the proof command, its real exit code,
             and the line: Approved-Proposal: UD-001
7. Merge     ci green, proposal-check green, maintainer squash-merge
```

The proof line matters more than the prose. A PR that says "all tests pass" without the command and its real
exit code is sent back — paste the output, not a promise.

## Code Style

- Formatter runs in CI (Prettier for md/yaml/json). Run locally: `npx prettier --write .`
- Language-specific formatters when we pick an engine (rustfmt, black, gdformat, etc.).

## Asset Policy

- Every asset folder under `assets/` **must** have `LICENSE.txt`.
- Binary > 5 MB → Git LFS (`git lfs track "path"`).
- No file > 20 MB.
- AI-generated assets allowed if generator license permits redistribution.

## Testing

- CI runs: lint + DCO + asset license + size gate + headless boot smoke.
- When an engine is chosen, its test suite runs here.

## Questions?

- Ask in the proposal issue or Discord #general.
- No question is too small — unclear process wastes more time than asking.
