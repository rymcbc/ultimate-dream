# crew 0.10.9 — local patches applied on the gaming PC

Base: `macd2/Crew` @ `674366b` (v0.10.9). Three files differ from upstream; all three fix
behaviour that only shows up on a Windows board.

| file | change | why |
|---|---|---|
| `scripts/crew_card.py` | new `_proof_cwd(card)`; `run_verdict` passes it to `crew_safety.run_proof` | a proof must run in the **card's workspace** (falling back to the board's `default_workdir`), not the caller's cwd — otherwise a verifier runs the proof somewhere the work isn't |
| `scripts/crew_coordinator.py` | `apply_close` retries via `specify` when the card is stuck in triage; `audit_proof` writes `AUDIT FAIL …` into the card's `--result` | a card parked in triage cannot be `complete`d; and a `done` card cannot be blocked, so a post-completion proof failure would otherwise leave the board showing a clean `done` |
| `scripts/crew_safety.py` | `run_proof` spawns with `stdin=DEVNULL`, `close_fds=True`, `start_new_session=True`, `CREATE_NO_WINDOW` on Windows | a proof that inherits the agent's stdin can hang forever, and a console window per proof is noise |

Apply with `git apply` on a clean `674366b`, or copy the three files over the extracted tree.
The patched files themselves are in `scripts/` beside this README, so no patching is required at all.

No secrets in here.
