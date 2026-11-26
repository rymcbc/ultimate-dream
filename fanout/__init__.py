"""fanout — idempotent notification fan-out for The Ultimate Dream.

Implements delivery of decision notifications via injected transports (Discord DM,
webhook, RSS). Email is not shipped (deferred to owner).

Idempotency: key = f"{decision_id}:{recipient_hash}:{channel}".
A second call for the same key returns the existing notification and never re-sends.

Status flow: queued -> sending -> sent | failed | suppressed | bounced

delivered_ref (real message id) written back on successful send.

Private delivery log holds addresses; public chain holds only hashes
(recipient_hash, idempotency_key, channel, status, delivered_ref_hash).
"""

from .delivery import fan_out, NotificationStore, make_idempotency_key, recipient_hash

__all__ = [
    "fan_out",
    "NotificationStore",
    "make_idempotency_key",
    "recipient_hash",
]