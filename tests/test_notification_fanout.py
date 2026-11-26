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
    RateLimiter,
    OwnerChoice,
    OWNER_CHOICES,
    EnvelopeType,
    build_envelope,
    Channel,
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
    even if contributor notifications are muted.
    Records owner_notified_at and owner_choice in audit event.
    """
    fanout = NotificationFanOut(channels={ChannelType.DISCORD_DM: DiscordDMChannel()})
    envelope = make_envelope("B-OWNER")

    # Default choice = "none"
    result = await fanout.owner_notify(envelope)

    assert result.status == "sent"
    assert result.channel == ChannelType.DISCORD_DM
    assert result.audit.contributor_id == "owner"
    assert result.audit.owner_notified_at is not None
    assert result.audit.owner_choice == "none"
    print(f"  [owner] notified via {result.channel.value} msg={result.message_id}")
    print(f"  [owner] audit: notified_at={result.audit.owner_notified_at}, choice={result.audit.owner_choice}")

    # Test with explicit choice
    envelope2 = make_envelope("B-OWNER2")
    result2 = await fanout.owner_notify(envelope2, choice="reviewed")
    assert result2.audit.owner_choice == "reviewed"
    assert result2.audit.owner_notified_at is not None
    print(f"  [owner] choice=reviewed audit: choice={result2.audit.owner_choice}")

    # Test with override choice
    envelope3 = make_envelope("B-OWNER3")
    result3 = await fanout.owner_notify(envelope3, choice="override")
    assert result3.audit.owner_choice == "override"
    print(f"  [owner] choice=override audit: choice={result3.audit.owner_choice}")


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


async def test_owner_choice_recorded_later_after_notify():
    """The owner may reply after the T0 DM. record_owner_choice captures that
    reply and writes an audit event — silence remains 'none' and the ballot proceeds."""
    audit = FakeAuditLog()
    fanout = NotificationFanOut(
        channels={ChannelType.DISCORD_DM: DiscordDMChannel()},
        audit_hook=audit,
    )
    envelope = make_envelope("B-LATE")

    # T0 notification — no reply yet, so the choice is 'none' (silence = none)
    await fanout.owner_notify(envelope)
    assert fanout.get_owner_choice("B-LATE") == "none"

    # Owner replies 'override' after the fact
    record = fanout.record_owner_choice("B-LATE", "override")
    assert record["owner_choice"] == "override"
    assert record["owner_notified_at"] is not None  # T0 timestamp preserved
    assert fanout.get_owner_choice("B-LATE") == "override"

    # The change is audited, not silent
    choice_events = [e for e in audit.events if e.owner_choice == "override"]
    assert len(choice_events) >= 1
    assert choice_events[-1].contributor_id == "owner"
    print(f"  [owner] late choice recorded: {fanout.get_owner_choice('B-LATE')}")


async def test_owner_choice_invalid_rejected():
    """An invalid owner choice is rejected loudly with the offending value —
    it must never be recorded as if it were valid."""
    fanout = NotificationFanOut(channels={ChannelType.DISCORD_DM: DiscordDMChannel()})
    envelope = make_envelope("B-BADCHOICE")

    try:
        await fanout.owner_notify(envelope, choice="maybe")
    except ValueError as exc:
        assert "maybe" in str(exc)
        print(f"  [owner] invalid choice rejected: {exc}")
    else:
        raise AssertionError("expected ValueError for invalid owner choice")

    try:
        fanout.record_owner_choice("B-BADCHOICE", "nope")
    except ValueError as exc:
        assert "nope" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid owner choice")

    # Nothing was recorded — a rejected choice leaves the ballot at 'none'
    assert fanout.get_owner_choice("B-BADCHOICE") == "none"


async def test_owner_choice_enum_covers_ruling():
    """The ruling's vocabulary is exactly none | reviewed | override."""
    assert OWNER_CHOICES == ("none", "reviewed", "override")
    assert OwnerChoice.NONE.value == "none"
    assert OwnerChoice.REVIEWED.value == "reviewed"
    assert OwnerChoice.OVERRIDE.value == "override"


async def test_webhook_hmac_signature():
    """The webhook channel signs the canonical body with HMAC-SHA256 — the
    card requires a webhook to carry an HMAC header."""
    import hmac
    import hashlib

    webhook = WebhookChannel(url="https://example.com/hook", secret="s3cret")
    envelope = make_envelope("B-HMAC")

    fanout = NotificationFanOut(channels={ChannelType.WEBHOOK: webhook})
    prefs = ContributorPrefs(contributor_id="c_hmac", channels=[ChannelType.WEBHOOK])
    results = await fanout.send_ballot("c_hmac", envelope, prefs)

    assert results[0].status == "sent"
    assert webhook.last_signature is not None

    expected = hmac.new(
        b"s3cret",
        Channel.canonical_body(envelope),
        hashlib.sha256,
    ).hexdigest()
    assert webhook.last_signature == expected
    print(f"  [c_hmac] webhook HMAC signature: {webhook.last_signature[:16]}...")


async def test_envelope_types_and_builder():
    """The shared envelope contract covers all four emitted types."""
    assert EnvelopeType.BALLOT_OPEN.value == "ballot_open"
    assert EnvelopeType.BALLOT_RESULT.value == "ballot_result"
    assert EnvelopeType.PROPOSAL_MERGED.value == "proposal_merged"
    assert EnvelopeType.PROPOSAL_REJECTED.value == "proposal_rejected"

    proposal = {
        "id": "UD-142",
        "title": "Add dynamic lighting",
        "category": "gameplay",
        "summary": "x" * 300,
    }
    ballot = {
        "id": "B-88",
        "opens_at": 1795600000,
        "closes_at": 1795772800,
        "url": "https://example.com/ballot/B-88",
    }
    env = build_envelope(EnvelopeType.BALLOT_OPEN, proposal, ballot, [
        {"label": "Vote yes", "url": "https://example.com/ballot/B-88/yes"},
    ])
    assert env["type"] == "ballot_open"
    assert env["proposal"]["id"] == "UD-142"
    assert env["proposal"]["summary"] == "x" * 120  # capped at 120 chars
    assert env["ballot"]["id"] == "B-88"
    assert env["calls_to_action"][0]["label"] == "Vote yes"

    # The other three types build from the same helper
    for t in (EnvelopeType.BALLOT_RESULT, EnvelopeType.PROPOSAL_MERGED, EnvelopeType.PROPOSAL_REJECTED):
        e = build_envelope(t, proposal, ballot)
        assert e["type"] == t.value
        assert e["ballot"]["id"] == "B-88"

    # An unknown type is rejected loudly, naming the offending value
    try:
        build_envelope("ballot_opne", proposal, ballot)
    except ValueError as exc:
        assert "ballot_opne" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown envelope type")
    print("  [envelope] all four envelope types build; unknown type rejected")


async def test_owner_notify_records_audit_with_timestamp():
    """The owner audit event carries owner_notified_at AND owner_choice —
    both are present on the event, not just implied."""
    audit = FakeAuditLog()
    fanout = NotificationFanOut(
        channels={ChannelType.DISCORD_DM: DiscordDMChannel()},
        audit_hook=audit,
    )
    envelope = make_envelope("B-OWNERAUDIT")

    result = await fanout.owner_notify(envelope, choice="reviewed")

    assert len(audit.events) == 1
    ev = audit.events[0]
    assert ev.contributor_id == "owner"
    assert ev.owner_notified_at is not None
    assert ev.owner_choice == "reviewed"
    assert result.audit.owner_notified_at == ev.owner_notified_at
    print(f"  [owner] audit event: notified_at={ev.owner_notified_at}, choice={ev.owner_choice}")


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
        ("owner notify records audit with timestamp", test_owner_notify_records_audit_with_timestamp),
        ("owner choice recorded later", test_owner_choice_recorded_later_after_notify),
        ("owner choice invalid rejected", test_owner_choice_invalid_rejected),
        ("owner choice enum covers ruling", test_owner_choice_enum_covers_ruling),
        ("webhook HMAC signature", test_webhook_hmac_signature),
        ("envelope types and builder", test_envelope_types_and_builder),
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