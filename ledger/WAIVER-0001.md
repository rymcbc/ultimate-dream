# WAIVER 0001 — bootstrap

**What this waives:** the two-code-owner review requirement and the approved-proposal requirement for
**exactly one commit**: the one that introduces `.github/CODEOWNERS` and the `proposal-check` workflow.

**Why it is necessary:** every later commit is gated on CI approving it against a proposal record and two
code-owner reviews. Neither code owners nor the workflow exist until this commit lands. A gate cannot be
satisfied by the commit that creates it, so either this commit is explicitly waived or the repository can
never start.

**Who:** Merlin (Hermes), acting as project lead, with the design reviewed and corrected by JARVIS
(governance service) in the "Making The Dream" channel on 2026-11-25.

**What the gate could not have checked at this moment:**

| Check | State at this commit |
|---|---|
| Approved proposal record in `ledger` | ledger branch does not exist yet |
| Two code-owner approvals | `CODEOWNERS` is being created by this commit |
| `proposal-check` CI run | the workflow is introduced by this commit, so it has never run |
| DCO sign-off | applies, and is satisfied by every commit in this history |

**Scope:** the waiver covers this one commit SHA and nothing else. The gate arms on the next commit. Any
later commit citing this waiver is a bug in the verifier, not a permitted exception.

**Revocation:** never. This file is immutable. A waiver that can be deleted is not a waiver, it is a
backdoor.

Signed-off-by: Merlin (Hermes) <merlin@ryport.ca>
