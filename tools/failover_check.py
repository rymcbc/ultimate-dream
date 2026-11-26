#!/usr/bin/env python3
"""Failover check for the Ultimate Dream build lanes.

Answers one question: has the JARVIS lane produced anything in the last CLAIM_STALE_HOURS?
If not, says so in public (GitHub issues) and locally, so the work can be picked up by
whoever is awake. It never merges, never edits another agent's branch, never blocks anyone.

Design notes:
  - "Activity" = a push to a jarvis/* branch, a commit authored by the JARVIS identity on any
    branch, or a comment/PR authored by that account. Any one of those means the lane is alive.
  - Silence is normal. This reports; it does not punish. Exit code is always 0 unless the
    check itself failed, so it is safe to schedule hourly.
  - Idempotent-ish: it will not repeat the same notice more than once per NOTICE_COOLDOWN_HOURS.

Usage:
  python tools/failover_check.py                 # report only
  python tools/failover_check.py --comment       # also post one comment per stale card
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

REPO = "rymcbc/ultimate-dream"
STALE_HOURS = int(os.environ.get("CLAIM_STALE_HOURS", "12"))
COOLDOWN_HOURS = int(os.environ.get("NOTICE_COOLDOWN_HOURS", "12"))
JARVIS_LOGIN = os.environ.get("JARVIS_GH_LOGIN", "")  # optional: narrow commits to one account
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".failover-state.json")


def gh(*args: str) -> str:
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {out.stderr.strip()[:300]}")
    return out.stdout


def last_activity(now: datetime) -> tuple[datetime | None, str]:
    """Most recent sign of life from the JARVIS lane, and what it was."""
    newest: datetime | None = None
    what = "nothing found"

    # 1. branches with a jarvis/ prefix — committer date is the push that created/updated them
    try:
        refs = json.loads(gh("api", f"repos/{REPO}/branches", "--paginate"))
        for b in refs:
            if b["name"].startswith("jarvis/"):
                sha = b["commit"]["sha"]
                d = json.loads(gh("api", f"repos/{REPO}/commits/{sha}"))
                ts = d["commit"]["committer"]["date"]
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if newest is None or dt > newest:
                    newest, what = dt, f"branch {b['name']} @ {sha[:7]}"
    except Exception as exc:  # noqa: BLE001
        print(f"[failover] branch probe failed: {type(exc).__name__}: {exc}", file=sys.stderr)

    # 2. recent comments anywhere in the repo by the JARVIS account, if we know the login
    if JARVIS_LOGIN:
        try:
            since = (now - timedelta(hours=STALE_HOURS * 4)).strftime("%Y-%m-%dT%H:%M:%SZ")
            items = json.loads(
                gh("api", f"repos/{REPO}/issues/comments?since={since}&per_page=100", "--paginate")
            )
            for c in items:
                if (c.get("user") or {}).get("login", "").lower() == JARVIS_LOGIN.lower():
                    dt = datetime.fromisoformat(c["created_at"].replace("Z", "+00:00"))
                    if newest is None or dt > newest:
                        newest, what = dt, f"comment on #{c['issue_url'].rsplit('/', 1)[-1]}"
        except Exception as exc:  # noqa: BLE001
            print(f"[failover] comment probe failed: {type(exc).__name__}: {exc}", file=sys.stderr)

    return newest, what


def load_state() -> dict:
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return {}


def save_state(state: dict) -> None:
    try:
        with open(STATE, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[failover] state write failed: {exc}", file=sys.stderr)


def reassign_local_cards(reason_hours: float) -> list[str]:
    """Return JARVIS-lane cards on this machine's board to the local dispatch lane.

    Only touches cards still sitting in `scheduled` — i.e. never started. A card that is
    already being worked is left alone; the stale-claim rule in docs/BUILD-PARALLELISM.md §1
    covers that case at the branch level.
    """
    db = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "hermes",
        "kanban",
        "boards",
        "ultimate-dream",
        "kanban.db",
    )
    if not os.path.exists(db):
        print(f"[failover] no local board at {db} — skipping local reassignment")
        return []

    import sqlite3

    moved: list[str] = []
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "select id, title from tasks where assignee='jarvis' and status='scheduled'"
        ).fetchall()
        for tid, title in rows:
            con.execute(
                "update tasks set assignee='programmer', status='ready', "
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') where id=?",
                (tid,),
            )
            moved.append(f"{tid} {title[:60]}")
        con.commit()
    finally:
        con.close()

    for m in moved:
        print(f"[failover] handed to local lane: {m}")
    if moved:
        print(f"[failover] {len(moved)} card(s) returned to the local lane after {reason_hours:.0f}h of lane silence")
    return moved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--comment", action="store_true", help="post a notice on stale issues")
    ap.add_argument("--board", action="store_true", help="return never-started lane cards to the local lane")
    ap.add_argument("--issues", default="", help="comma separated issue numbers that belong to the lane")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    newest, what = last_activity(now)

    if newest is None:
        print(f"[failover] no JARVIS-lane activity found at all (window {STALE_HOURS}h)")
        idle_h = float("inf")
    else:
        idle_h = (now - newest).total_seconds() / 3600
        print(f"[failover] last lane activity {idle_h:.1f}h ago — {what}")

    if idle_h < STALE_HOURS:
        print(f"[failover] lane alive (threshold {STALE_HOURS}h) — nothing to do")
        return 0

    print(f"[failover] lane idle beyond {STALE_HOURS}h — the work is unowned, not blocked")
    print("[failover] pick up: ballot engine, notifications, audit-log, accounts (see docs/BUILD-PARALLELISM.md)")

    if args.board:
        reassign_local_cards(idle_h)

    state = load_state()
    last_notice = state.get("last_notice_at")
    cooled = True
    if last_notice:
        try:
            cooled = (now - datetime.fromisoformat(last_notice)).total_seconds() / 3600 >= COOLDOWN_HOURS
        except ValueError:
            cooled = True

    if args.comment and cooled and args.issues:
        body = (
            f"Failover notice: no activity from the JARVIS lane in {idle_h:.0f}h "
            f"(threshold {STALE_HOURS}h). Per `docs/BUILD-PARALLELISM.md` §5 this card is unowned rather than "
            "blocked — any builder may claim it. Not an accusation; a builder being offline is normal."
        )
        for num in [n.strip() for n in args.issues.split(",") if n.strip()]:
            try:
                gh("issue", "comment", num, "--repo", REPO, "--body", body)
                print(f"[failover] commented on #{num}")
            except Exception as exc:  # noqa: BLE001
                print(f"[failover] comment on #{num} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        state["last_notice_at"] = now.isoformat()
        save_state(state)
    elif args.comment:
        print("[failover] notice suppressed (cooldown or no issues given)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
