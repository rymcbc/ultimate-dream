# Constitution of the Ultimate Dream Project

## Preamble
We, the contributors to Ultimate Dream, establish this Constitution to govern our collaboration, protect contributor rights, and ensure the project remains open, playable, and community-directed.

## Article I — Purpose
Ultimate Dream exists to create a game through open, democratic collaboration. The game itself is the product; the process is the point.

## Article II — Governance Model
- **Decisions by ballot**: Major directions (engine, license, scope, monetisation) are decided by ranked-choice vote of all contributors with ≥1 merged PR.
- **Day-to-day by consent**: Routine work flows through proposals → PRs → code-owner review. No BDFL, no veto.
- **Forks welcome**: This Constitution applies to the `main` branch of `rymcbc/ultimate-dream`. Forks may adopt, amend, or discard it.

## Article III — Contributor Rights
- **Attribution**: Every merged commit carries its author's name. No squash-merge erasure.
- **DCO, not CLA**: `git commit -s` is the only legal gate. No external agreements.
- **License ballot**: The project license is chosen by ballot (Article VII). Until then, MIT applies as a placeholder.

## Article IV — Asset Policy
- Every asset folder under `assets/` **must** contain a `LICENSE.txt` declaring its terms.
- No binary > 5 MB without a Git LFS pointer. No single file > 20 MB.
- AI-generated assets are permitted if their generator's license allows redistribution.

## Article V — Code Policy
- `main` is protected: no direct pushes, 2 code-owner reviews, stale-review dismissal.
- Required CI checks: `ci` (lint + tests + boot smoke) and `proposal-check`.
- All code must pass `cargo fmt` / `black` / `prettier` as appropriate per language.

## Article VI — Proposal Process
1. Open a **Proposal** issue (template: `.github/ISSUE_TEMPLATE/proposal.yml`).
2. Discussion period: 7 days minimum.
3. Ballot if contested (≥3 objectors), otherwise lazy consensus (7 days, no objection).
4. Passed proposals → `DECISIONS/UD-###.md` + implementation tasks.

## Article VII — License Ballot
- Trigger: 10 contributors with ≥1 merged PR, or 6 months after first commit, whichever comes first.
- Options: MIT, Apache-2.0, GPL-3.0, LGPL-3.0, BSD-3-Clause, "Keep MIT".
- Ranked-choice, instant-runoff. Winner binds `main` and all future forks of `main`.

## Article VIII — Amendment
- This Constitution can be amended by the same ballot process as Article VII.
- Amendments require 60% supermajority of voting contributors.

## Article IX — Dissolution
- If `main` has 0 commits for 365 days, the project is dormant. Any contributor may petition GitHub to transfer ownership.

---

*Signed by the founding contributors via DCO on their first commit.*