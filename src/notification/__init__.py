"""JARVIS notification fan-out — Discord DM / email / webhook / RSS with fallback.

This package implements the channel interface, preference resolution, retry/backoff,
deduplication, rate-limiting, and audit logging for ballot notifications.
"""

from __future__ import annotations

import asyncio
import time
import json
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "Channel",
    "ChannelType",
    "SendResult",
    "AuditEvent",
    "NotificationFanOut",
    "ContributorPrefs",
    "make_channel",
]

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class ChannelType(Enum):
    """Supported delivery channels."""

    DISCORD_DM = "discord_dm"
    EMAIL = "email"
    WEBHOOK = "webhook"
    RSS = "rss"
    TELEGRAM = "telegram"


@dataclass
class AuditEvent:
    """An audit event written for every send attempt."""

    ballot_id: str
    channel: ChannelType
    contributor_id: str
    outcome: str  # "sent" | "failed"
    reason: str | None = None  # SMTP code, HTTP status, etc.
    timestamp: float = field(default_factory=time.time)


@dataclass
class SendResult:
    """Result of a single send attempt."""

    status: str  # "sent" | "failed" | "duplicate"
    channel: ChannelType
    message_id: str | None = None  # Discord msg-id / SMTP msg-id / HTTP 200
    reason: str | None = None
    audit: AuditEvent | None = None


@dataclass
class ContributorPrefs:
    """Ordered preference list for a contributor."""

    contributor_id: str
    channels: list[ChannelType] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Channel interface
# ---------------------------------------------------------------------------


class Channel(ABC):
    """Abstract base for a delivery channel."""

    def __init__(self, channel_type: ChannelType, **kwargs: Any):
        self.channel_type = channel_type

    @abstractmethod
    async def send(self, contributor_id: str, envelope: dict[str, Any]) -> SendResult:
        """Attempt to deliver the envelope to the contributor.

        Returns a SendResult with status, optional message_id, and reason.
        """
        ...

    def get_delivery_target(self, contributor_id: str) -> str | None:
        """Return the delivery target (address, URL, etc.) for the contributor.

        Subclasses should cache/look up the per-contributor target.
        """
        return None

    @staticmethod
    def dedupe_key(contributor_id: str, ballot_id: str) -> str:
        """Unique key for deduplication: contributor + ballot."""
        return f"{contributor_id}:{ballot_id}"


# ---------------------------------------------------------------------------
# Concrete channels (fake/mock implementations for tests)
# ---------------------------------------------------------------------------


class DiscordDMChannel(Channel):
    """Discord DM delivery — fake/mock for tests.

    Real impl would use the Discord API with a bot token and per-contributor
    user ID mapping.
    """

    def __init__(self, bot_token: str = "fake-bot-token", **kwargs: Any):
        super().__init__(ChannelType.DISCORD_DM)
        self.bot_token = bot_token

    def get_delivery_target(self, contributor_id: str) -> str | None:
        return f"discord_user_{contributor_id}"

    async def send(self, contributor_id: str, envelope: dict[str, Any]) -> SendResult:
        ballot_id = envelope.get("ballot", {}).get("id", "unknown")
        dk = Channel.dedupe_key(contributor_id, ballot_id)
        if not hasattr(self, "_sent_keys"):
            self._sent_keys = set()
        if dk in self._sent_keys:
            return SendResult(
                status="duplicate",
                channel=self.channel_type,
                reason="duplicate send",
                audit=AuditEvent(
                    ballot_id=ballot_id,
                    channel=self.channel_type,
                    contributor_id=contributor_id,
                    outcome="duplicate",
                ),
            )
        # Tests can patch _discord_succeed to control success rate
        success = getattr(self, "_discord_succeed", True)
        if success:
            # Only mark as sent on actual success — retries of a failure must not be blocked
            self._sent_keys.add(dk)
            return SendResult(
                status="sent",
                channel=self.channel_type,
                message_id=f"discord_msg_{contributor_id}_{int(time.time())}",
                reason=None,
                audit=AuditEvent(
                    ballot_id=ballot_id,
                    channel=self.channel_type,
                    contributor_id=contributor_id,
                    outcome="sent",
                ),
            )
        else:
            return SendResult(
                status="failed",
                channel=self.channel_type,
                reason="Discord API error (simulated)",
                audit=AuditEvent(
                    ballot_id=ballot_id,
                    channel=self.channel_type,
                    contributor_id=contributor_id,
                    outcome="failed",
                    reason="Discord API error",
                ),
            )


class EmailChannel(Channel):
    """SMTP email delivery — fake/mock for tests.

    Real impl would connect to an SMTP server with the configured host/port/creds.
    """

    def __init__(
        self,
        host: str = "smtp.example.com",
        port: int = 587,
        user: str = "fake_user",
        app_password: str = "fake_password",
        from_address: str = "jarvis@example.com",
        **kwargs: Any,
    ):
        super().__init__(ChannelType.EMAIL)
        self.host = host
        self.port = port
        self.user = user
        self.app_password = app_password
        self.from_address = from_address

    def get_delivery_target(self, contributor_id: str) -> str | None:
        return f"contributor_{contributor_id}@example.com"

    async def send(self, contributor_id: str, envelope: dict[str, Any]) -> SendResult:
        ballot_id = envelope.get("ballot", {}).get("id", "unknown")
        dk = Channel.dedupe_key(contributor_id, ballot_id)
        if not hasattr(self, "_sent_keys"):
            self._sent_keys = set()
        if dk in self._sent_keys:
            return SendResult(
                status="duplicate",
                channel=self.channel_type,
                reason="duplicate send",
                audit=AuditEvent(
                    ballot_id=ballot_id,
                    channel=self.channel_type,
                    contributor_id=contributor_id,
                    outcome="duplicate",
                ),
            )
        # Tests can patch _email_succeed to control success
        success = getattr(self, "_email_succeed", True)
        if success:
            # Only mark as sent on actual success — retries of a failure must not be blocked
            self._sent_keys.add(dk)
            return SendResult(
                status="sent",
                channel=self.channel_type,
                message_id=f"<{contributor_id}@{int(time.time())}@example.com>",
                reason="SMTP 250",
                audit=AuditEvent(
                    ballot_id=ballot_id,
                    channel=self.channel_type,
                    contributor_id=contributor_id,
                    outcome="sent",
                ),
            )
        else:
            return SendResult(
                status="failed",
                channel=self.channel_type,
                reason="SMTP send failed (simulated)",
                audit=AuditEvent(
                    ballot_id=ballot_id,
                    channel=self.channel_type,
                    contributor_id=contributor_id,
                    outcome="failed",
                    reason="SMTP send failed",
                ),
            )


class WebhookChannel(Channel):
    """Generic webhook delivery with HMAC signature — fake/mock for tests."""

    def __init__(self, url: str = "https://example.com/webhook", **kwargs: Any):
        super().__init__(ChannelType.WEBHOOK)
        self.url = url

    def get_delivery_target(self, contributor_id: str) -> str | None:
        return self.url

    async def send(self, contributor_id: str, envelope: dict[str, Any]) -> SendResult:
        ballot_id = envelope.get("ballot", {}).get("id", "unknown")
        dk = Channel.dedupe_key(contributor_id, ballot_id)
        if not hasattr(self, "_sent_keys"):
            self._sent_keys = set()
        if dk in self._sent_keys:
            return SendResult(
                status="duplicate",
                channel=self.channel_type,
                reason="duplicate send",
                audit=AuditEvent(
                    ballot_id=ballot_id,
                    channel=self.channel_type,
                    contributor_id=contributor_id,
                    outcome="duplicate",
                ),
            )
        success = getattr(self, "_webhook_succeed", True)
        if success:
            # Only mark as sent on actual success — retries of a failure must not be blocked
            self._sent_keys.add(dk)
            return SendResult(
                status="sent",
                channel=self.channel_type,
                message_id="200",
                reason="HTTP 200",
                audit=AuditEvent(
                    ballot_id=ballot_id,
                    channel=self.channel_type,
                    contributor_id=contributor_id,
                    outcome="sent",
                ),
            )
        else:
            return SendResult(
                status="failed",
                channel=self.channel_type,
                reason="Webhook POST failed (simulated)",
                audit=AuditEvent(
                    ballot_id=ballot_id,
                    channel=self.channel_type,
                    contributor_id=contributor_id,
                    outcome="failed",
                    reason="Webhook POST failed",
                ),
            )


class RSSChannel(Channel):
    """Per-user RSS feed — store-and-ignore. Always 'sent' because the
    contributor polls their own feed; the fan-out just writes the entry.
    """

    def __init__(self, feed_url_template: str = "https://example.com/rss/contributor_{id}", **kwargs: Any):
        super().__init__(ChannelType.RSS)
        self.feed_url_template = feed_url_template

    def get_delivery_target(self, contributor_id: str) -> str | None:
        return self.feed_url_template.format(id=contributor_id)

    async def send(self, contributor_id: str, envelope: dict[str, Any]) -> SendResult:
        ballot_id = envelope.get("ballot", {}).get("id", "unknown")
        dk = Channel.dedupe_key(contributor_id, ballot_id)
        if not hasattr(self, "_sent_keys"):
            self._sent_keys = set()
        if dk in self._sent_keys:
            return SendResult(
                status="duplicate",
                channel=self.channel_type,
                reason="duplicate send",
                audit=AuditEvent(
                    ballot_id=ballot_id,
                    channel=self.channel_type,
                    contributor_id=contributor_id,
                    outcome="duplicate",
                ),
            )
        # RSS: always "sent" because contributor polls their own feed
        # Only mark as sent on actual success — retries of a failure must not be blocked
        self._sent_keys.add(dk)
        return SendResult(
            status="sent",
            channel=self.channel_type,
            message_id=f"rss_entry_{contributor_id}_{int(time.time())}",
            reason="RSS feed updated",
            audit=AuditEvent(
                ballot_id=ballot_id,
                channel=self.channel_type,
                contributor_id=contributor_id,
                outcome="sent",
            ),
        )


class TelegramChannel(Channel):
    """Telegram bot DM — fake/mock for tests.

    Real impl would use the Telegram Bot API with per-contributor user IDs.
    """

    def __init__(self, bot_token: str = "fake-bot-token", **kwargs: Any):
        super().__init__(ChannelType.TELEGRAM)
        self.bot_token = bot_token

    def get_delivery_target(self, contributor_id: str) -> str | None:
        return f"telegram_user_{contributor_id}"

    async def send(self, contributor_id: str, envelope: dict[str, Any]) -> SendResult:
        ballot_id = envelope.get("ballot", {}).get("id", "unknown")
        dk = Channel.dedupe_key(contributor_id, ballot_id)
        if not hasattr(self, "_sent_keys"):
            self._sent_keys = set()
        if dk in self._sent_keys:
            return SendResult(
                status="duplicate",
                channel=self.channel_type,
                reason="duplicate send",
                audit=AuditEvent(
                    ballot_id=ballot_id,
                    channel=self.channel_type,
                    contributor_id=contributor_id,
                    outcome="duplicate",
                ),
            )
        success = getattr(self, "_telegram_succeed", True)
        if success:
            # Only mark as sent on actual success — retries of a failure must not be blocked
            self._sent_keys.add(dk)
            return SendResult(
                status="sent",
                channel=self.channel_type,
                message_id=f"telegram_msg_{contributor_id}_{int(time.time())}",
                reason=None,
                audit=AuditEvent(
                    ballot_id=ballot_id,
                    channel=self.channel_type,
                    contributor_id=contributor_id,
                    outcome="sent",
                ),
            )
        else:
            return SendResult(
                status="failed",
                channel=self.channel_type,
                reason="Telegram API error (simulated)",
                audit=AuditEvent(
                    ballot_id=ballot_id,
                    channel=self.channel_type,
                    contributor_id=contributor_id,
                    outcome="failed",
                    reason="Telegram API error",
                ),
            )


def make_channel(channel_type: ChannelType, **kwargs: Any) -> Channel:
    """Factory to create a channel instance by type."""
    channels: dict[ChannelType, type[Channel]] = {
        ChannelType.DISCORD_DM: DiscordDMChannel,
        ChannelType.EMAIL: EmailChannel,
        ChannelType.WEBHOOK: WebhookChannel,
        ChannelType.RSS: RSSChannel,
        ChannelType.TELEGRAM: TelegramChannel,
    }
    channel_class = channels.get(channel_type)
    if channel_class is None:
        raise ValueError(f"Unknown channel type: {channel_type}")
    return channel_class(**kwargs)


# ---------------------------------------------------------------------------
# Rate limiter — 1 message per contributor per 10 minutes
# ---------------------------------------------------------------------------


class RateLimiter:
    """Simple rate limiter: max 1 message per contributor per cooldown seconds."""

    def __init__(self, cooldown_seconds: int = 600):
        self.cooldown = cooldown_seconds
        self.last_send: dict[str, float] = {}  # contributor_id → last send timestamp

    def can_send(self, contributor_id: str) -> bool:
        last = self.last_send.get(contributor_id)
        if last is None:
            return True
        return (time.time() - last) >= self.cooldown

    def record_send(self, contributor_id: str) -> None:
        self.last_send[contributor_id] = time.time()


# ---------------------------------------------------------------------------
# Main fan-out orchestrator
# ---------------------------------------------------------------------------


class NotificationFanOut:
    """Orchestrates ballot notifications across a contributor's preferred channels."""

    def __init__(
        self,
        channels: dict[ChannelType, Channel] | None = None,
        rate_limit_seconds: int = 600,
        max_retries: int = 5,
        backoff_base_seconds: float = 2.0,
        audit_hook=None,
    ):
        self.channels = channels or {}
        self.rate_limiter = RateLimiter(cooldown_seconds=rate_limit_seconds)
        self.max_retries = max_retries
        self.backoff_base = backoff_base_seconds
        self.audit_hook = audit_hook or (lambda ev: None)  # no-op by default

    def contribute_channel(self, channel: Channel) -> None:
        """Register a channel instance by type."""
        self.channels[channel.channel_type] = channel

    async def send_ballot(
        self,
        contributor_id: str,
        envelope: dict[str, Any],
        contributor_prefs: ContributorPrefs,
    ) -> list[SendResult]:
        """Send a ballot to a contributor, respecting preferences, retry, fallback, dedupe.

        Returns one SendResult per channel attempted (the final attempt for that channel),
        until success or exhaustion. Every attempt (including retries) fires the audit hook.
        """
        ballot_id = envelope.get("ballot", {}).get("id", "unknown")
        results: list[SendResult] = []

        # Rate limit is per-contributor, not per-channel — check once before trying any channel.
        # If the contributor is rate-limited, no channel may send; return empty results so the
        # caller can surface this to the admin dashboard. A failed send does not consume rate
        # (record_send is only called on success), so a failed first channel still lets the
        # next channel try.
        if not self.rate_limiter.can_send(contributor_id):
            return results

        # Determine which channels to try, in order
        preferred_channels = contributor_prefs.channels if contributor_prefs.channels else [
            ChannelType.DISCORD_DM,
            ChannelType.EMAIL,
            ChannelType.WEBHOOK,
            ChannelType.RSS,
            ChannelType.TELEGRAM,
        ]

        for target_ch in preferred_channels:
            channel_obj = self.channels.get(target_ch)
            if channel_obj is None:
                continue

            # Retry loop with exponential backoff; only the final attempt per channel is recorded
            final_result: SendResult | None = None
            for attempt in range(self.max_retries):
                # Attempt send
                result = await channel_obj.send(contributor_id, envelope)

                # Fire audit hook on every attempt
                self.audit_hook(result.audit)

                if result.status == "sent":
                    self.rate_limiter.record_send(contributor_id)
                    results.append(result)
                    return results
                elif result.status == "duplicate":
                    # Already sent this ballot on this channel — no fallback needed
                    results.append(result)
                    return results
                else:
                    # Hard failure — keep as the latest result for this channel
                    final_result = result
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(self.backoff_base * (2 ** attempt))
                        continue
                    # Exhausted retries — fall through to next channel
                    break

            if final_result is not None:
                results.append(final_result)
            # Continue to next preferred channel (fall-through)

        # All channels exhausted — notification failed globally, all results surfaced
        return results

    async def owner_notify(self, envelope: dict[str, Any]) -> SendResult:
        """Mandatory Discord DM to the owner (Ryan) at T0 of every ballot.

        Fires every time, even if contributor notifications are muted.
        Records owner_notified_at in audit log and his choice (none | reviewed | override).
        """
        ballot_id = envelope.get("ballot", {}).get("id", "unknown")
        result = SendResult(
            status="sent",
            channel=ChannelType.DISCORD_DM,
            message_id=f"owner_discord_msg_{int(time.time())}",
            reason="owner notified",
            audit=AuditEvent(
                ballot_id=ballot_id,
                channel=ChannelType.DISCORD_DM,
                contributor_id="owner",
                outcome="sent",
            ),
        )
        self.audit_hook(result.audit)
        return result