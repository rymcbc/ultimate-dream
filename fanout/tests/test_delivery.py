"""Tests for fanout delivery implementation.

Proof command: uv run --with pytest python -m pytest fanout/tests/test_delivery.py -q

Required cases:
- idempotent double-send sends once
- all three channels dispatched
- transport error -> failed not sent
- suppressed recipient skipped
- invalid status transition refused
"""

import asyncio
import pytest
from fanout.delivery import (
    fan_out,
    NotificationStore,
    make_idempotency_key,
    recipient_hash,
    STATUS_TRANSITIONS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store():
    """In-memory notification store for tests."""
    return NotificationStore(":memory:")


@pytest.fixture
def decision():
    """Sample decision dict."""
    return {
        "decision_id": "dec-2026-0001",
        "proposal_id": "prop-2026-0001",
        "ballot_id": "bal-2026-0001",
        "kind": "ratify",
        "result": "ratified",
        "scope_paths": ["game/content/props/**", "game/content/items/**"],
    }


@pytest.fixture
def recipients():
    """Sample recipients with addresses for all channels."""
    return [
        {
            "gh_id": 122483695,
            "addresses": {
                "discord_dm": "123456789",
                "webhook": "https://webhook.example.com/abc",
                "rss": "https://rss.example.com/feed",
            },
        },
        {
            "gh_id": 987654321,
            "addresses": {
                "discord_dm": "987654321",
                "webhook": "https://webhook.example.com/xyz",
                "rss": "https://rss.example.com/feed2",
            },
        },
    ]


@pytest.fixture
def transports():
    """Mock transports that return delivered_refs."""
    async def mock_discord_dm(decision, address):
        return f"dm-{decision['decision_id']}-{address}"
    
    async def mock_webhook(decision, address):
        return f"wh-{decision['decision_id']}-{address}"
    
    async def mock_rss(decision, address):
        return f"rss-{decision['decision_id']}-{address}"
    
    return {
        "discord_dm": mock_discord_dm,
        "webhook": mock_webhook,
        "rss": mock_rss,
    }


# ---------------------------------------------------------------------------
# Idempotency tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_idempotent_double_send_sends_once(decision, recipients, transports, store):
    """A second call for the same idempotency key returns existing, never re-sends."""
    # First call
    results1 = await fan_out(decision, recipients, transports, store)
    
    # Count sent notifications
    sent_count_1 = sum(1 for r in results1 if r["status"] == "sent")
    assert sent_count_1 == 6  # 2 recipients * 3 channels
    
    # Second call - should skip all
    results2 = await fan_out(decision, recipients, transports, store)
    
    # All should be marked as skipped
    skipped_count = sum(1 for r in results2 if r.get("skipped", False))
    assert skipped_count == 6
    
    # No new deliveries should have happened (same delivered_refs)
    for r1, r2 in zip(results1, results2):
        if r1["status"] == "sent":
            assert r2["status"] == "sent"
            assert r2["delivered_ref"] == r1["delivered_ref"]
            assert r2["skipped"] is True


@pytest.mark.asyncio
async def test_idempotency_key_format(decision, recipients, transports, store):
    """Idempotency key format: decision_id:recipient_hash:channel."""
    results = await fan_out(decision, recipients, transports, store)
    
    for r in results:
        assert r["idempotency_key"] is not None
        parts = r["idempotency_key"].split(":")
        assert len(parts) == 3
        assert parts[0] == decision["decision_id"]
        assert parts[2] in ("discord_dm", "webhook", "rss")


# ---------------------------------------------------------------------------
# Channel dispatch tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_three_channels_dispatched(decision, recipients, transports, store):
    """All three shipping channels (discord_dm, webhook, rss) are dispatched."""
    results = await fan_out(decision, recipients, transports, store)
    
    channels = {r["channel"] for r in results}
    assert channels == {"discord_dm", "webhook", "rss"}
    
    # Each recipient gets all three channels
    for recipient in recipients:
        gh_id = recipient["gh_id"]
        recipient_results = [r for r in results if r["gh_id"] == gh_id]
        recipient_channels = {r["channel"] for r in recipient_results}
        assert recipient_channels == {"discord_dm", "webhook", "rss"}


# ---------------------------------------------------------------------------
# Transport error tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transport_error_marks_failed_not_sent(decision, recipients, store):
    """Transport error results in failed status, not sent."""
    async def failing_transport(decision, address):
        raise RuntimeError("Network error")
    
    transports = {
        "discord_dm": failing_transport,
        "webhook": failing_transport,
        "rss": failing_transport,
    }
    
    results = await fan_out(decision, recipients, transports, store)
    
    for r in results:
        assert r["status"] == "failed"
        assert r["error"] is not None
        assert "Network error" in r["error"]
        assert r["delivered_ref"] is None


# ---------------------------------------------------------------------------
# Suppressed recipient tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_suppressed_recipient_skipped(decision, store):
    """Recipient with no address for a channel gets suppressed status."""
    recipients = [
        {
            "gh_id": 122483695,
            "addresses": {
                "discord_dm": "123456789",
                # webhook and rss missing -> suppressed
            },
        },
    ]
    
    async def mock_transport(decision, address):
        return f"ref-{address}"
    
    transports = {
        "discord_dm": mock_transport,
        "webhook": mock_transport,
        "rss": mock_transport,
    }
    
    results = await fan_out(decision, recipients, transports, store)
    
    # discord_dm should be sent
    dm_result = next(r for r in results if r["channel"] == "discord_dm")
    assert dm_result["status"] == "sent"
    
    # webhook and rss should be suppressed
    for channel in ("webhook", "rss"):
        r = next(r for r in results if r["channel"] == channel)
        assert r["status"] == "suppressed"
        assert r["delivered_ref"] is None
        assert r["error"] == "No address configured for channel"


# ---------------------------------------------------------------------------
# Status transition tests
# ---------------------------------------------------------------------------

def test_invalid_status_transition_refused(store):
    """Invalid status transitions are refused with ValueError."""
    # Insert a notification in 'sent' status
    notification_id = "not-test-001"
    idempotency_key = "dec-001:abc123:discord_dm"
    
    store.insert_queued(
        notification_id=notification_id,
        idempotency_key=idempotency_key,
        decision_id="dec-001",
        gh_id=123,
        channel="discord_dm",
        payload_ref="votes/dec-001.json",
        address="test",
        status="sent",  # Start at sent
    )
    
    # Try to transition sent -> failed (invalid)
    with pytest.raises(ValueError, match="Invalid status transition"):
        store.update_status(idempotency_key, "failed")
    
    # Try to transition sent -> queued (invalid)
    with pytest.raises(ValueError, match="Invalid status transition"):
        store.update_status(idempotency_key, "queued")


def test_valid_status_transitions(store):
    """Valid status transitions are allowed."""
    notification_id = "not-test-002"
    idempotency_key = "dec-002:abc123:webhook"
    
    store.insert_queued(
        notification_id=notification_id,
        idempotency_key=idempotency_key,
        decision_id="dec-002",
        gh_id=123,
        channel="webhook",
        payload_ref="votes/dec-002.json",
        address="test",
        status="queued",
    )
    
    # queued -> sending
    assert store.update_status(idempotency_key, "sending", attempt=1)
    
    # sending -> sent
    assert store.update_status(
        idempotency_key, "sent", attempt=1,
        sent_at="2026-11-26T10:00:00.000Z",
        delivered_ref="msg-123",
    )
    
    # sent -> (nothing allowed)
    with pytest.raises(ValueError):
        store.update_status(idempotency_key, "failed")


def test_failed_can_retry(store):
    """Failed status can transition back to sending for retry."""
    notification_id = "not-test-003"
    idempotency_key = "dec-003:abc123:rss"
    
    store.insert_queued(
        notification_id=notification_id,
        idempotency_key=idempotency_key,
        decision_id="dec-003",
        gh_id=123,
        channel="rss",
        payload_ref="votes/dec-003.json",
        address="test",
        status="failed",
    )
    
    # failed -> sending (retry)
    assert store.update_status(idempotency_key, "sending", attempt=2)


# ---------------------------------------------------------------------------
# Private log and public chain tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_private_log_holds_addresses(store, decision, recipients, transports):
    """Private delivery log holds real addresses."""
    await fan_out(decision, recipients, transports, store)
    
    log = store.get_private_log(decision["decision_id"])
    assert len(log) == 6  # 2 recipients * 3 channels
    
    for entry in log:
        assert entry.address != ""  # Real address stored
        assert entry.gh_id in (122483695, 987654321)
        assert entry.channel in ("discord_dm", "webhook", "rss")


@pytest.mark.asyncio
async def test_public_chain_holds_only_hashes(store, decision, recipients, transports):
    """Public chain holds only hashes, no PII."""
    await fan_out(decision, recipients, transports, store)
    
    chain = store.get_public_chain(decision["decision_id"])
    assert len(chain) == 6
    
    for entry in chain:
        # No real addresses
        assert not hasattr(entry, "address")
        assert not hasattr(entry, "gh_id")
        
        # Has hashes
        assert entry.recipient_hash is not None
        assert len(entry.recipient_hash) == 16  # sha256 truncated
        assert entry.idempotency_key is not None
        assert entry.channel in ("discord_dm", "webhook", "rss")
        
        # delivered_ref is hashed if present
        if entry.status == "sent":
            assert entry.delivered_ref_hash is not None
            assert len(entry.delivered_ref_hash) == 16


# ---------------------------------------------------------------------------
# Recipient hash tests
# ---------------------------------------------------------------------------

def test_recipient_hash_deterministic():
    """recipient_hash is deterministic for same gh_id."""
    h1 = recipient_hash(122483695)
    h2 = recipient_hash(122483695)
    assert h1 == h2
    assert len(h1) == 16


def test_recipient_hash_different_ids():
    """Different gh_ids produce different hashes."""
    h1 = recipient_hash(122483695)
    h2 = recipient_hash(987654321)
    assert h1 != h2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_recipients_list(decision, transports, store):
    """Empty recipients list returns empty results."""
    results = await fan_out(decision, [], transports, store)
    assert results == []


@pytest.mark.asyncio
async def test_missing_transport_for_channel(decision, recipients, store):
    """Missing transport for a channel marks that channel failed."""
    transports = {
        "discord_dm": lambda d, a: "dm-ref",
        # webhook and rss missing
    }
    
    results = await fan_out(decision, recipients, transports, store)
    
    # discord_dm should succeed
    dm_results = [r for r in results if r["channel"] == "discord_dm"]
    assert all(r["status"] == "sent" for r in dm_results)
    
    # webhook and rss should fail
    for channel in ("webhook", "rss"):
        ch_results = [r for r in results if r["channel"] == channel]
        assert all(r["status"] == "failed" for r in ch_results)
        assert "No transport" in ch_results[0]["error"]


if __name__ == "__main__":
    pytest.main([__file__, "-q"])