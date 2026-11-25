# D-002 — Email transport: Gmail SMTP now, scale later

**Decided by Ryan, 2026-11-25:** _"if we get to a place where we have alot of people we will decide how to deal with it then."_

## Ruling

Ship the email transport as **plain SMTP config** — host, port, user, app password, from address — behind a
single sender interface. No provider selection now, no queue, no rate-limit engineering, no dedicated
subdomain, no SPF/DKIM/DMARC work while the roster is empty.

## Why it is safe to defer

The only thing that has to be true today is that swapping providers later is a **config change, not a code
change**. That property costs one small interface and is the whole design. Everything else about scale
(deliverability, batching, bounce handling, reputation) is decided when a roster actually exists, against
real numbers instead of guesses.

## Trigger to revisit

When the roster is real — the point where a ballot notice to every member would exceed a consumer mailbox's
daily cap (~500/day on free Gmail) or a first notice lands in spam. At that point Ryan picks the provider;
the SMTP config block changes and nothing else moves.

## What this explicitly does NOT change

- One 48-hour window (`voting_hours: 48`); `window_hours` stays deleted.
- Owner block at T+0 (`owner_notified_at`, `owner_decision`, `owner_override_ground`).
- Transports offered: Discord DM (guild members who allow it), Telegram (verified `telegram_chat_id`),
  email (SMTP config). Per contributor preference, not per system default.
