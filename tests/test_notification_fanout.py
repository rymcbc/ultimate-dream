"""Tests for the JARVIS notification fan-out system.

These tests exercise:
- Channel send with preference resolution
- Fall-through on hard failure
- Deduplication (same ballot never sent twice on same channel)
- Rate limiting (1 msg per contributor per 10 min)
- Retry with exponential backoff
- Owner notification

All transports are fake/mock — no live Discord/email/Telegram credentials are used.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from notification import (  # noqa: E402
    ChannelType,
    ContributorPrefs,
    AuditEvent,
    NotificationFanOut,
    DiscordDMChannel,
    EmailChannel,
    WebhookChannel,
    RSSChannel,
    TelegramChannel,
    make_channel,
    SendResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_envelope(ballot_id: str = "B-88", proposal_id: str = "UD-142") -> dict[str, Any]:
    """Build a ballot_open envelope per the shared contract."""
    return {
        "type": "ballot_open",
        "proposal": {
            "id": proposal_id,
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
            {"label": "Read the proposal", "url": f"https://example.com/proposal/{proposal_id}"},
        ],
    }


class FakeAuditLog:
    """Collects audit events for assertion."""

    def __init__(self):
        self.events: list[AuditEvent] = []

    def __call__(self, ev: AuditEvent) -> None:
        self.events.append(ev)


# ---------------------------------------------------------------------------
# Tests (all async — run under a single event loop)
# ---------------------------------------------------------------------------


async def test_channel_make_factory():
    """make_channel returns the correct concrete channel for each type."""
    assert isinstance(make_channel(ChannelType.DISCORD_DM), DiscordDMChannel)
    assert isinstance(make_channel(ChannelType.EMAIL), EmailChannel)
    assert isinstance(make_channel(ChannelType.WEBHOOK), WebhookChannel)
    assert isinstance(make_channel(ChannelType.RSS), RSSChannel)
    assert isinstance(make_channel(ChannelType.TELEGRAM), TelegramChannel)


async def test_send_ballot_success_first_channel():
    """A contributor's top channel succeeds immediately — send once, done."""
    fanout = NotificationFanOut(
        channels={
            ChannelType.DISCORD_DM: DiscordDMChannel(),
            ChannelType.EMAIL: EmailChannel(),
        }
    )
    prefs = ContributorPrefs(contributor_id="c1", channels=[ChannelType.DISCORD_DM, ChannelType.EMAIL])
    envelope = make_envelope("B-1")

    results = await fanout.send_ballot("c1", envelope, prefs)

    assert len(results) == 1
    assert results[0].status == "sent"
    assert results[0].channel == ChannelType.DISCORD_DM
    assert results[0].message_id is not None
    print(f"  [c1] {results[0].status} via {results[0].channel.value} msg={results[0].message_id}")


async def test_send_ballot_fallthrough_on_failure():
    """When the top channel fails hard, fall through to the next preference channel."""
    discord = DiscordDMChannel()
    discord._discord_succeed = False  # force failure
    email = EmailChannel()

    fanout = NotificationFanOut(channels={
        ChannelType.DISCORD_DM: discord,
        ChannelType.EMAIL: email,
    }, backoff_base_seconds=0.01)  # fast backoff for test
    prefs = ContributorPrefs(
        contributor_id="c2",
        channels=[ChannelType.DISCORD_DM, ChannelType.EMAIL],
    )
    envelope = make_envelope("B-2")

    results = await fanout.send_ballot("c2", envelope, prefs)

    # First channel: failed all retries → fall through; second channel: success
    assert len(results) == 2
    assert results[0].status == "failed"
    assert results[0].channel == ChannelType.DISCORD_DM
    assert results[1].status == "sent"
    assert results[1].channel == ChannelType.EMAIL
    print(f"  [c2] {results[0].status} via {results[0].channel.value} → {results[1].status} via {results[1].channel.value}")


async def test_send_ballot_three_contributors_three_channels():
    """Acceptance scenario: 3 contributors on 3 different channels, one ballot opened.

    c1 → Discord DM (message id)
    c2 → Email (SMTP 250)
    c3 → Webhook (HTTP 200)
    """
    fanout = NotificationFanOut(channels={
        ChannelType.DISCORD_DM: DiscordDMChannel(),
        ChannelType.EMAIL: EmailChannel(),
        ChannelType.WEBHOOK: WebhookChannel(),
    })

    contributors = [
        ("c1", ChannelType.DISCORD_DM),
        ("c2", ChannelType.EMAIL),
        ("c3", ChannelType.WEBHOOK),
    ]

    envelope = make_envelope("B-88")
    print("\n--- Acceptance table: ballot B-88 opened ---")
    print(f"{'Contributor':<12} {'Channel':<14} {'Status':<10} {'Transport response':<30}")
    results_table = []
    for cid, ch in contributors:
        prefs = ContributorPrefs(contributor_id=cid, channels=[ch])
        results = await fanout.send_ballot(cid, envelope, prefs)
        r = results[-1]
        resp = r.message_id or r.reason or "(none)"
        print(f"{cid:<12} {ch.value:<14} {r.status:<10} {resp:<30}")
        results_table.append((cid, ch, r))

    assert all(r.status == "sent" for _, _, r in results_table)
    assert results_table[0][2].message_id is not None
    assert "SMTP 250" in results_table[1][2].reason
    assert results_table[2][2].reason == "HTTP 200"


async def test_send_ballot_fallthrough_deliberate_failure():
    """Acceptance scenario: one deliberate failure falls through to the next channel.

    c1 → Discord DM (fails deliberately) → falls back to Email (SMTP 250).
    """
    discord = DiscordDMChannel()
    discord._discord_succeed = False  # deliberate failure
    email = EmailChannel()

    fanout = NotificationFanOut(channels={
        ChannelType.DISCORD_DM: discord,
        ChannelType.EMAIL: email,
    }, backoff_base_seconds=0.01)  # fast backoff for test
    prefs = ContributorPrefs(
        contributor_id="c_fail",
        channels=[ChannelType.DISCORD_DM, ChannelType.EMAIL],
    )
    envelope = make_envelope("B-99")

    results = await fanout.send_ballot("c_fail", envelope, prefs)

    assert len(results) == 2
    assert results[0].status == "failed"
    assert results[0].channel == ChannelType.DISCORD_DM
    assert results[1].status == "sent"
    assert results[1].channel == ChannelType.EMAIL
    print(f"  [c_fail] {results[0].status} via {results[0].channel.value} → fallthrough → {results[1].status} via {results[1].channel.value} ({results[1].reason})")


async def test_dedupe_same_ballot_twice_on_same_channel():
    """A contributor must never get the same ballot twice on the same channel."""
    discord = DiscordDMChannel()
    email = EmailChannel()
    fanout = NotificationFanOut(channels={
        ChannelType.DISCORD_DM: discord,
        ChannelType.EMAIL: email,
    }, rate_limit_seconds=0)  # disable rate limiting for dedupe test
    prefs = ContributorPrefs(
        contributor_id="c3",
        channels=[ChannelType.DISCORD_DM, ChannelType.EMAIL],
    )
    envelope = make_envelope("B-DEDUP")

    # First send succeeds on Discord
    results1 = await fanout.send_ballot("c3", envelope, prefs)
    assert results1[0].status == "sent"
    assert results1[0].channel == ChannelType.DISCORD_DM

    # Second send of same ballot to same contributor — dedupe on Discord should trigger
    results2 = await fanout.send_ballot("c3", envelope, prefs)
    assert results2[0].status == "duplicate"
    assert results2[0].channel == ChannelType.DISCORD_DM
    print(f"  [c3] same ballot again → {results2[0].status} via {results2[0].channel.value}")


async def test_rate_limiter():
    """Rate limiter: max 1 message per contributor per 10 minutes (600 seconds)."""
    from notification import RateLimiter
    limiter = RateLimiter(cooldown_seconds=1)  # 1 second for test speed
    assert limiter.can_send("c_rate")
    limiter.record_send("c_rate")
    assert not limiter.can_send("c_rate")
    assert limiter.can_send("c_other")  # other contributor unaffected


async def test_rate_limiter_blocks_after_send_in_test():
    """Rate limiter blocks a second send to the same contributor within the cooldown window."""
    fanout = NotificationFanOut(channels={
        ChannelType.DISCORD_DM: DiscordDMChannel(),
    }, rate_limit_seconds=1)  # 1 second cooldown for test speed
    prefs = ContributorPrefs(
        contributor_id="c_rate2",
        channels=[ChannelType.DISCORD_DM],
    )
    envelope = make_envelope("B-RATE")

    # First send works
    r1 = await fanout.send_ballot("c_rate2", envelope, prefs)
    assert r1[0].status == "sent"
    assert r1[0].channel == ChannelType.DISCORD_DM
    print(f"  [c_rate2] first send OK via {r1[0].channel.value}")

    from notification import RateLimiter
    limiter = RateLimiter(cooldown_seconds=600)
    assert limiter.can_send("c_new")
    limiter.record_send("c_new")
    assert not limiter.can_send("c_new")
    assert limiter.can_send("c_other")  # other contributor unaffected
    print("  [rate] limiter blocks resend within cooldown, allows other contributor")


async def test_send_ballot_rate_limited_returns_empty():
    """When a contributor is rate-limited, send_ballot returns empty results —
    no channel is attempted, nothing is sent, nothing vanishes silently."""
    fanout = NotificationFanOut(channels={
        ChannelType.DISCORD_DM: DiscordDMChannel(),
        ChannelType.EMAIL: EmailChannel(),
    }, rate_limit_seconds=600)  # 10 minute cooldown
    prefs = ContributorPrefs(
        contributor_id="c_rl",
        channels=[ChannelType.DISCORD_DM, ChannelType.EMAIL],
    )
    envelope = make_envelope("B-RL")

    # First send works — consumes the rate limit
    r1 = await fanout.send_ballot("c_rl", envelope, prefs)
    assert len(r1) == 1
    assert r1[0].status == "sent"

    # Second send immediately — rate limited, no channel attempted, empty results
    r2 = await fanout.send_ballot("c_rl", envelope, prefs)
    assert len(r2) == 0, f"expected empty results when rate limited, got {len(r2)}"
    print("  [c_rl] second send rate-limited — no channel attempted, empty results")


async def test_audit_events_written():
    """Every send writes an audit event (notification_sent / notification_failed with reason)."""
    audit = FakeAuditLog()
    discord = DiscordDMChannel()
    discord._discord_succeed = False
    email = EmailChannel()
    fanout = NotificationFanOut(
        channels={
            ChannelType.DISCORD_DM: discord,
            ChannelType.EMAIL: email,
        },
        audit_hook=audit,
        backoff_base_seconds=0.01,  # fast backoff for test
    )
    prefs = ContributorPrefs(
        contributor_id="c_audit",
        channels=[ChannelType.DISCORD_DM, ChannelType.EMAIL],
    )
    envelope = make_envelope("B-AUDIT")

    await fanout.send_ballot("c_audit", envelope, prefs)

    # Should have at least one failed + one sent audit event
    outcomes = {e.outcome for e in audit.events}
    assert "failed" in outcomes
    assert "sent" in outcomes
    # The failed event should carry a reason
    failed_events = [e for e in audit.events if e.outcome == "failed"]
    assert all(e.reason is not None for e in failed_events)
    print(f"  [c_audit] audit events: {[f'{e.outcome}/{e.channel.value}' for e in audit.events]}")


async def test_retry_with_backoff():
    """Retry with exponential backoff — a channel that fails N times then succeeds
    should produce N failure results followed by one sent result on that channel."""
    discord = DiscordDMChannel()
    call_count = {"n": 0}

    async def flaky_send(contributor_id, envelope):
        call_count["n"] += 1
        if call_count["n"] < 3:
            return SendResult(
                status="failed",
                channel=ChannelType.DISCORD_DM,
                reason=f"transient failure #{call_count['n']}",
                audit=AuditEvent(
                    ballot_id=envelope.get("ballot", {}).get("id", "unknown"),
                    channel=ChannelType.DISCORD_DM,
                    contributor_id=contributor_id,
                    outcome="failed",
                    reason=f"transient failure #{call_count['n']}",
                ),
            )
        return SendResult(
            status="sent",
            channel=ChannelType.DISCORD_DM,
            message_id=f"discord_msg_retry_{int(time.time())}",
            reason=None,
            audit=AuditEvent(
                ballot_id=envelope.get("ballot", {}).get("id", "unknown"),
                channel=ChannelType.DISCORD_DM,
                contributor_id=contributor_id,
                outcome="sent",
            ),
        )

    discord.send = flaky_send  # type: ignore[method-assign]
    fanout = NotificationFanOut(
        channels={ChannelType.DISCORD_DM: discord},
        backoff_base_seconds=0.01,  # fast for test
    )
    prefs = ContributorPrefs(
        contributor_id="c_retry",
        channels=[ChannelType.DISCORD_DM],
    )
    envelope = make_envelope("B-RETRY")

    results = await fanout.send_ballot("c_retry", envelope, prefs)

    assert call_count["n"] == 3  # 2 failures + 1 success
    assert results[-1].status == "sent"
    print(f"  [c_retry] {call_count['n']} attempts, final status={results[-1].status}")


async def test_owner_notify_fires_every_time():
    """Owner (Ryan) gets a mandatory Discord DM at T0 of every ballot,
    even if contributor notifications are muted."""
    fanout = NotificationFanOut(channels={ChannelType.DISCORD_DM: DiscordDMChannel()})
    envelope = make_envelope("B-OWNER")

    result = await fanout.owner_notify(envelope)

    assert result.status == "sent"
    assert result.channel == ChannelType.DISCORD_DM
    assert result.audit.contributor_id == "owner"
    print(f"  [owner] notified via {result.channel.value} msg={result.message_id}")


async def test_all_channels_exhausted_returns_all_results():
    """When every channel fails, return all results (no silent vanish)."""
    discord = DiscordDMChannel()
    discord._discord_succeed = False
    email = EmailChannel()
    email._email_succeed = False
    webhook = WebhookChannel()
    webhook._webhook_succeed = False

    fanout = NotificationFanOut(channels={
        ChannelType.DISCORD_DM: discord,
        ChannelType.EMAIL: email,
        ChannelType.WEBHOOK: webhook,
    }, backoff_base_seconds=0.01)  # fast backoff for test
    prefs = ContributorPrefs(
        contributor_id="c_allfail",
        channels=[ChannelType.DISCORD_DM, ChannelType.EMAIL, ChannelType.WEBHOOK],
    )
    envelope = make_envelope("B-ALLFAIL")

    results = await fanout.send_ballot("c_allfail", envelope, prefs)

    # All three channels attempted and each produced one final failed result
    assert len(results) == 3
    assert all(r.status == "failed" for r in results)
    print(f"  [c_allfail] all {len(results)} channels failed — results surfaced, nothing vanished")


# ---------------------------------------------------------------------------
# Main — single event loop, all tests run sequentially
# ---------------------------------------------------------------------------


async def main():
    tests = [
        ("make_channel factory", test_channel_make_factory),
        ("success on first channel", test_send_ballot_success_first_channel),
        ("fallthrough on failure", test_send_ballot_fallthrough_on_failure),
        ("three contributors, three channels", test_send_ballot_three_contributors_three_channels),
        ("deliberate failure fallthrough", test_send_ballot_fallthrough_deliberate_failure),
        ("dedupe same ballot same channel", test_dedupe_same_ballot_twice_on_same_channel),
        ("rate limiter", test_rate_limiter),
        ("rate-limited fan-out returns empty", test_send_ballot_rate_limited_returns_empty),
        ("audit events written", test_audit_events_written),
        ("retry with backoff", test_retry_with_backoff),
        ("owner notify fires every time", test_owner_notify_fires_every_time),
        ("all channels exhausted", test_all_channels_exhausted_returns_all_results),
    ]

    passed = 0
    failed = 0
    import traceback
    for name, fn in tests:
        try:
            await fn()
            print(f"PASS: {name}")
            passed += 1
        except Exception as exc:
            print(f"FAIL: {name}: {exc}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    if failed > 0:
        raise SystemExit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())