# The roster — who may vote

`roster/founding.json` is the electorate. Everything that needs to know "who is eligible" reads this file, and
nothing else, until accounts land.

## Why a file and not a database

The project starts with one eligible member and the governance service is still in build. A file that git tracks
is verifiable, diffable, and impossible to change silently: adding a member is a commit with an author. When the
accounts service exists it becomes the writer of this file, not a replacement for it — eligibility keeps a git
history either way.

## Rules the engine must honour

- **Eligibility is read at ballot open and frozen for the window.** A member joining mid-ballot does not change
  the electorate, the quorum, or the tally.
- **Quorum = `min(roster, max(5, ceil(0.20 * roster)))`.** With fewer than five eligible members the floor is
  capped by the roster, so a one-person founding ballot is valid and records the quorum it actually required.
  See `docs/GOVERNANCE.md` §"Quorum, including a one-person roster".
- **Identity is the GitHub numeric id**, never the login. Logins are renameable and are not identities.
- **`eligible: false`** keeps a member on the roster without a vote — dormant accounts are marked, not deleted,
  so the story of a ballot can still be reconstructed later.

## Current state

One member: `rymcbc` (`gh_id 122483695`), role `owner`, source `founding`.

The owner's role does not give extra votes. It gives the override described in `CONSTITUTION.md` §6, which is
recorded as a `revoke` record with a cited ground and is challengeable — not a silent veto.
