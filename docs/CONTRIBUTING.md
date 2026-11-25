# Contributing to Ultimate Dream

Welcome! This project runs on **proposals → PRs → reviews**. No drive-by merges.

## Quick Start
1. **Read**: `CONSTITUTION.md`, `GOVERNANCE.md`, this file.
2. **Propose**: File a **Proposal** issue (Issues → New → Proposal) for any non-trivial change.
3. **Claim**: Pick a task from the Project board or the proposal's task list.
4. **Develop**: Branch from `main`, commit with `-s` (DCO), push.
5. **PR**: Open a PR with `Approved-Proposal: UD-###` in the description.
6. **Review**: Two code-owner approvals + green CI = merge.

## Commit Hygiene
- **Sign every commit**: `git commit -s` (DCO enforced by CI).
- **Conventional commits**: `feat:`, `fix:`, `refactor:`, `docs:`, `assets:`, `ci:`, `chore:`.
- **One logical change per PR**. Split if needed.

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