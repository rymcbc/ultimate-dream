# Roadmap

> **Hand-written during bootstrap.** `docs/CONTRIBUTING.md` promises this file is generated from approved
> proposals; the ballot engine that would do that is in build. Until the first `DECISIONS/UD-###.md` exists this
> file is maintained by hand and is the only place phase promises live. The moment generation is live, this note
> and the hand-editing both stop.

## Phase 0: Scaffold (Current)

- [x] Repository initialised with MIT placeholder license
- [x] Constitution, Governance, Contributing docs
- [x] GitHub templates, CODEOWNERS, CI workflows
- [x] Branch protection (pending `gh` config)
- [x] Asset gates (license + size) in CI
- [x] Ledger format v2, offline verifier, ledger writer (22 tests)
- [ ] License ballot (trigger: 10 contributors or 6 months)

## Phase 1: Engine Ballot

- [ ] Proposal: Engine selection (Godot / Unreal / Unity / Custom / Other)
- [ ] Ballot per Constitution Article VII
- [ ] Winning engine → `DECISIONS/UD-###.md`
- [ ] Engine integration PR with boot smoke test

## Phase 2: Vertical Slice

- [ ] Core gameplay loop prototype
- [ ] Minimal art pipeline (placeholder → final)
- [ ] Networking skeleton (if multiplayer)
- [ ] Playable build shipped to contributors

## Phase 3: Content & Polish

- [ ] Level/asset production
- [ ] Audio integration
- [ ] QA / bug bash
- [ ] 1.0 release candidate

## Open Proposals (track in Issues)

- UD-001: Engine Selection (pending)
- UD-002: License Ballot (auto-triggers)
- UD-003: Multiplayer Architecture (pending engine)

## Completed Decisions

_None yet — first ballot will create UD-001._
