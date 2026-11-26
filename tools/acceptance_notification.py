"""Live acceptance table for the JARVIS notification fan-out card.

3 contributors on 3 different channels, one ballot opened, showing 3 sends
with their transport response (Discord message id / SMTP 250 / webhook HTTP
200), plus one deliberate failure falling through to the next channel.

Run:  python tools/acceptance_notification.py
Transports are fake/mock — no live credentials are wired (gated per scope).
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from notification import (  # noqa: E402
    ChannelType,
    ContributorPrefs,
    DiscordDMChannel,
    EmailChannel,
    WebhookChannel,
    NotificationFanOut,
)


def make_envelope(ballot_id: str = "B-88") -> dict:
    return {
        "type": "ballot_open",
        "proposal": {
            "id": "UD-142",
            "title": "Add dynamic lighting to apartment scenes",
            "category": "gameplay",
            "summary": "120 chars",
        },
        "ballot": {
            "id": ballot_id,
            "opens_at": 1795600000,
            "closes_at": 1795772800,
            "url": f"https://example.com/ballot/{ballot_id}",
        },
        "calls_to_action": [
            {"label": "Vote yes", "url": f"https://example.com/ballot/{ballot_id}/yes"},
            {"label": "Read the proposal", "url": "https://example.com/proposal/UD-142"},
        ],
    }


async def main() -> int:
    discord = DiscordDMChannel()
    email = EmailChannel()
    webhook = WebhookChannel(url="https://example.com/hook")

    fanout = NotificationFanOut(channels={
        ChannelType.DISCORD_DM: discord,
        ChannelType.EMAIL: email,
        ChannelType.WEBHOOK: webhook,
    })

    envelope = make_envelope("B-88")

    print("=" * 84)
    print("ACCEPTANCE TABLE — ballot B-88 opened (3 contributors, 3 channels)")
    print("=" * 84)
    print(f"{'Contributor':<12} {'Channel':<13} {'Status':<8} {'Transport response':<32} {'Delivered ref'}")
    print("-" * 84)

    contributors = [
        ("c1", ChannelType.DISCORD_DM),
        ("c2", ChannelType.EMAIL),
        ("c3", ChannelType.WEBHOOK),
    ]
    ok = True
    for cid, ch in contributors:
        prefs = ContributorPrefs(contributor_id=cid, channels=[ch])
        results = await fanout.send_ballot(cid, envelope, prefs)
        r = results[-1]
        response = r.reason or "(no reason)"
        if ch == ChannelType.DISCORD_DM:
            response = "Discord API accepted"
        print(f"{cid:<12} {ch.value:<13} {r.status:<8} {response:<32} {r.message_id}")
        if r.status != "sent":
            ok = False

    print("-" * 84)
    print("Webhook HMAC-SHA256 signature (canonical body):")
    print(f"  {webhook.last_signature}")
    print()

    # --- Deliberate failure: top channel hard-fails, falls through to next ---
    print("=" * 84)
    print("DELIBERATE FAILURE — top channel hard-fails, must fall through")
    print("=" * 84)
    fail_discord = DiscordDMChannel()
    fail_discord._discord_succeed = False  # type: ignore[attr-defined]  # deliberate hard failure
    fallback_email = EmailChannel()

    fallthrough = NotificationFanOut(channels={
        ChannelType.DISCORD_DM: fail_discord,
        ChannelType.EMAIL: fallback_email,
    }, backoff_base_seconds=0.01)

    prefs = ContributorPrefs(
        contributor_id="c_fail",
        channels=[ChannelType.DISCORD_DM, ChannelType.EMAIL],
    )
    results = await fallthrough.send_ballot("c_fail", make_envelope("B-99"), prefs)

    print(f"{'Contributor':<12} {'Channel':<13} {'Status':<8} {'Transport response':<32} {'Delivered ref'}")
    print("-" * 84)
    for r in results:
        response = r.reason or "(no reason)"
        print(f"{'c_fail':<12} {r.channel.value:<13} {r.status:<8} {response:<32} {r.message_id or '-'}")
    print()

    fallthrough_ok = (
        len(results) == 2
        and results[0].status == "failed"
        and results[0].channel == ChannelType.DISCORD_DM
        and results[1].status == "sent"
        and results[1].channel == ChannelType.EMAIL
    )
    if not fallthrough_ok:
        ok = False

    if ok:
        print("ACCEPTANCE PASS: 3 sends across 3 channels + 1 deliberate failure fell through.")
        return 0
    print("ACCEPTANCE FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
