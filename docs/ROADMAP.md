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

## Operating constraint: one game at a time

**This project builds exactly one game at a time** (owner directive, 2026-11-26). There is one active
game, one board lane, and one engine in play at any moment — not a portfolio. A second game may be
_proposed_, but it cannot be balloted into an active state until the current game is either shipped or
formally abandoned by an approved decision. The governance service enforces this: a game proposal that
would create a second active game is rejected at intake, not queued.

**The engine is a field on each game proposal, not a global choice.** The project will use Unreal,
UEFN and Godot across its lifetime, each where it fits the game being built; the ballot that approves a
game also approves the engine named in it. There is no separate "engine selection" decision — that
framing is retired.

## Phase 1: First game — proposal and engine

- [ ] Game proposal filed with a named engine (Godot 4.x / Unreal 5.8 / UEFN / Unity 6 / other) and its
      justification drawn from `docs/research/engine-selection-dossier.md`
- [ ] Ballot per Constitution Article VII — the vote approves the _game and its engine together_
- [ ] Result → `DECISIONS/UD-###.md`
- [ ] Integration PR for the chosen engine with a boot smoke test that proves it runs headless in CI
- [ ] Engine-specific research landed before the first content card: `ue58-agent-pipeline.md` (Unreal),
      `uefn-limits.md` (UEFN), or the Godot pipeline notes

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

- UD-001: First game — title, scope and engine (pending)
- UD-002: License Ballot (auto-triggers)
- UD-003: Multiplayer Architecture (after the first game's engine is approved)

## Completed Decisions

_None yet — first ballot will create UD-001._
