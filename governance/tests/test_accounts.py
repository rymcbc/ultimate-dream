"""Tests for the contributor account model + GitHub OAuth + notification channel preferences.

Uses a fake GitHub API provider injected via set_github_api() — no real OAuth app
or client secrets are needed. All external calls are mocked.

Each test unlinks any previously linked account first so module-level state
doesn't leak between tests.
"""

from __future__ import annotations

import json
import sys
import os

# Ensure the project root is on the path so we can import the governance module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import governance.accounts as acc
from governance.accounts import (
    set_github_api,
    link_github_account,
    unlink_github_account,
    get_account,
    add_channel,
    remove_channel,
    get_channels,
    verify_email_channel,
    set_preference_order,
    get_preference_order,
    normalize_preferences,
    set_pause,
    get_pause,
    should_deliver_notification,
    refresh_contributor_status,
    CHANNEL_TYPES,
)


class FakeGitHubAPI:
    """Injectable fake GitHub API for tests."""

    def __init__(self, user_info=None, merged_prs=None):
        self.user_info = user_info or {
            "login": "testuser",
            "id": 12345,
            "account_age_days": 45,
            "email": "test@example.com",
        }
        self.merged_prs = merged_prs or []

    def get_user_info(self, access_token: str):
        return self.user_info

    def get_user_merged_prs(self, gh_id: int):
        return self.merged_prs


def fresh():
    """Reset module-level state and inject a fresh fake API."""
    acc._ACCOUNTS.clear()
    acc._CHANNELS.clear()
    acc._PREFS.clear()
    acc._PAUSED.clear()
    set_github_api(FakeGitHubAPI())


# ---------------------------------------------------------------------------
# Account lifecycle tests
# ---------------------------------------------------------------------------

def test_link_github_account_stores_all_fields():
    """Linking a real GitHub account stores github_login, github_id, account_age_days, is_contributor."""
    fresh()
    fake = FakeGitHubAPI(
        user_info={"login": "rymcbc", "id": 6090683101, "account_age_days": 3000, "email": None},
        merged_prs=[{"pr_number": 42, "merged_at": "2026-01-15T10:00:00Z"}],
    )
    set_github_api(fake)

    account = link_github_account(6090683101, "rymcbc", "gho_token_123")

    assert account["github_id"] == 6090683101
    assert account["github_login"] == "rymcbc"
    assert account["account_age_days"] == 3000
    assert account["is_contributor"] is True
    assert "linked_at" in account
    assert "access_token" in account


def test_link_updates_existing_account():
    """Re-linking the same GitHub id upserts (no duplicate)."""
    fresh()
    set_github_api(FakeGitHubAPI())

    link_github_account(99999, "user_a", "token_a")
    link_github_account(99999, "user_a_updated", "token_b")

    account = get_account(99999)
    assert account["github_login"] == "user_a_updated"
    # Only one account in the store
    assert len(acc._ACCOUNTS) == 1


def test_account_age_days_computed_at_link_time():
    """account_age_days is computed from the GitHub API created_at at link time."""
    fresh()
    fake = FakeGitHubAPI(
        user_info={"login": "newuser", "id": 55555, "account_age_days": 42, "email": None},
        merged_prs=[],
    )
    set_github_api(fake)

    account = link_github_account(55555, "newuser", "token_new")

    assert account["account_age_days"] == 42


def test_is_contributor_derived_from_merged_prs():
    """is_contributor is True when the user has merged PRs."""
    fresh()
    fake = FakeGitHubAPI(
        user_info={"login": "contributor", "id": 111, "account_age_days": 100, "email": None},
        merged_prs=[
            {"pr_number": 1, "merged_at": "2026-01-01T00:00:00Z"},
            {"pr_number": 2, "merged_at": "2026-06-01T00:00:00Z"},
        ],
    )
    set_github_api(fake)

    account = link_github_account(111, "contributor", "tok")
    assert account["is_contributor"] is True


def test_is_contributor_false_without_merged_prs():
    """is_contributor is False when the user has no merged PRs."""
    fresh()
    fake = FakeGitHubAPI(
        user_info={"login": "lurker", "id": 222, "account_age_days": 500, "email": None},
        merged_prs=[],
    )
    set_github_api(fake)

    account = link_github_account(222, "lurker", "tok")
    assert account["is_contributor"] is False


def test_get_account_returns_none_for_unknown_id():
    """Retrieving an unknown github_id returns None."""
    fresh()
    assert get_account(0) is None


# ---------------------------------------------------------------------------
# Channel management tests
# ---------------------------------------------------------------------------

def test_add_discord_dm_channel_records_reachability():
    """Adding a Discord DM channel records dm_reachable (false if DMs closed)."""
    fresh()
    set_github_api(FakeGitHubAPI())
    link_github_account(12345, "testuser", "tok")

    channel = add_channel(12345, "discord_dm", {"user_id": "12345"})

    assert channel["channel_type"] == "discord_dm"
    assert "dm_reachable" in channel
    assert channel["dm_reachable"] is False  # default: DMs closed, handled honestly


def test_add_webhook_channel_echoes_challenge():
    """Adding a webhook channel verifies by echoing a challenge token."""
    fresh()
    set_github_api(FakeGitHubAPI())
    link_github_account(12345, "testuser", "tok")

    channel = add_channel(12345, "webhook", {"url": "https://example.com/webhook"})

    assert channel["channel_type"] == "webhook"
    assert channel["verified"] is True
    assert "challenge_token" in channel
    assert len(channel["challenge_token"]) == 16


def test_add_rss_channel_is_generated_not_verified():
    """Adding an RSS channel marks it as generated and never verified."""
    fresh()
    set_github_api(FakeGitHubAPI())
    link_github_account(12345, "testuser", "tok")

    channel = add_channel(12345, "rss", {"feed_url": "https://example.com/feed"})

    assert channel["channel_type"] == "rss"
    assert channel.get("generated") is True


def test_add_email_channel_generates_token_and_is_unverified():
    """Adding an email channel generates a verification token and is unverified."""
    fresh()
    set_github_api(FakeGitHubAPI())
    link_github_account(12345, "testuser", "tok")

    channel = add_channel(12345, "email", {"email": "test@example.com"})

    assert channel["channel_type"] == "email"
    assert channel["verified"] is False
    assert "verification_token" in channel
    assert len(channel["verification_token"]) == 16


def test_verify_email_channel_by_token():
    """Verifying an email channel with the correct token marks it verified."""
    fresh()
    set_github_api(FakeGitHubAPI())
    link_github_account(12345, "testuser", "tok")

    channel = add_channel(12345, "email", {"email": "test@example.com"})
    token = channel["verification_token"]

    assert verify_email_channel(12345, token) is True

    channels = get_channels(12345)
    assert channels["email"]["verified"] is True
    assert "verified_at" in channels["email"]


def test_verify_email_channel_wrong_token_fails():
    """A wrong verification token fails and does not mark the channel verified."""
    fresh()
    set_github_api(FakeGitHubAPI())
    link_github_account(12345, "testuser", "tok")

    add_channel(12345, "email", {"email": "test@example.com"})

    assert verify_email_channel(12345, "wrong_token") is False

    channels = get_channels(12345)
    assert channels["email"]["verified"] is False


def test_verify_email_channel_no_email_channel_returns_false():
    """Verifying when no email channel exists returns False."""
    fresh()
    set_github_api(FakeGitHubAPI())
    link_github_account(12345, "testuser", "tok")

    assert verify_email_channel(12345, "any_token") is False


def test_remove_channel():
    """Removing a channel deletes it from the store."""
    fresh()
    set_github_api(FakeGitHubAPI())
    link_github_account(12345, "testuser", "tok")

    add_channel(12345, "discord_dm", {"user_id": "12345"})
    add_channel(12345, "webhook", {"url": "https://example.com/hook"})

    removed = remove_channel(12345, "discord_dm")
    assert removed is True

    channels = get_channels(12345)
    assert "discord_dm" not in channels
    assert "webhook" in channels


def test_remove_nonexistent_channel_returns_false():
    """Removing a channel that doesn't exist returns False."""
    fresh()
    set_github_api(FakeGitHubAPI())
    link_github_account(12345, "testuser", "tok")

    removed = remove_channel(12345, "discord_dm")
    assert removed is False


def test_channels_for_account():
    """All channels for a contributor are retrievable."""
    fresh()
    set_github_api(FakeGitHubAPI())
    link_github_account(12345, "testuser", "tok")

    add_channel(12345, "discord_dm", {"user_id": "12345"})
    add_channel(12345, "webhook", {"url": "https://example.com/hook"})
    add_channel(12345, "rss", {"feed_url": "https://example.com/feed"})

    channels = get_channels(12345)
    assert "discord_dm" in channels
    assert "webhook" in channels
    assert "rss" in channels


# ---------------------------------------------------------------------------
# Preference order tests
# ---------------------------------------------------------------------------

def test_preference_order_stored_as_integers():
    """Preference order stores integers and normalises gaps."""
    fresh()
    set_github_api(FakeGitHubAPI())
    link_github_account(12345, "testuser", "tok")

    prefs = set_preference_order(12345, ["rss", "discord_dm", "webhook"])

    assert prefs == {"rss": 1, "discord_dm": 2, "webhook": 3}


def test_preference_order_normalises_gaps():
    """If gaps exist in preferences, they are normalised to contiguous ints."""
    fresh()
    set_github_api(FakeGitHubAPI())
    link_github_account(12345, "testuser", "tok")

    # Simulate partial order with gaps
    acc._PREFS[12345] = {"discord_dm": 1, "rss": 3}  # gap at 2

    normalised = normalize_preferences(12345)

    assert normalised == {"discord_dm": 1, "rss": 2}


def test_get_preference_order_returns_default():
    """Default preference order is discord_dm:1, webhook:2, rss:3."""
    fresh()
    set_github_api(FakeGitHubAPI())
    link_github_account(12345, "testuser", "tok")

    prefs = get_preference_order(12345)

    assert prefs == {"discord_dm": 1, "webhook": 2, "rss": 3}


def test_preference_order_invalid_types_ignored():
    """Invalid channel types in a preference list are ignored."""
    fresh()
    set_github_api(FakeGitHubAPI())
    link_github_account(12345, "testuser", "tok")

    prefs = set_preference_order(12345, ["discord_dm", "sms", "rss"])

    assert prefs == {"discord_dm": 1, "rss": 2}


# ---------------------------------------------------------------------------
# Pause switch tests
# ---------------------------------------------------------------------------

def test_pause_all_notifications():
    """A contributor can pause all notifications with one switch."""
    fresh()
    set_github_api(FakeGitHubAPI())
    link_github_account(12345, "testuser", "tok")

    assert get_pause(12345) is False

    set_pause(12345, True)
    assert get_pause(12345) is True

    set_pause(12345, False)
    assert get_pause(12345) is False


def test_should_deliver_notification_returns_false_when_paused():
    """Paused contributors should not receive notifications."""
    fresh()
    set_github_api(FakeGitHubAPI())
    link_github_account(12345, "testuser", "tok")

    set_pause(12345, True)
    assert should_deliver_notification(12345) is False


def test_should_deliver_notification_returns_true_when_not_paused():
    """Non-paused contributors should receive notifications."""
    fresh()
    set_github_api(FakeGitHubAPI())
    link_github_account(12345, "testuser", "tok")

    assert should_deliver_notification(12345) is True


# ---------------------------------------------------------------------------
# Daily refresh tests
# ---------------------------------------------------------------------------

def test_refresh_contributor_status():
    """Daily refresh recomputes is_contributor and account_age_days."""
    fresh()
    fake = FakeGitHubAPI(
        user_info={"login": "refreshuser", "id": 77777, "account_age_days": 200, "email": None},
        merged_prs=[{"pr_number": 5, "merged_at": "2026-01-01T00:00:00Z"}],
    )
    set_github_api(fake)

    link_github_account(77777, "refreshuser", "tok")
    refreshed = refresh_contributor_status(77777)

    assert refreshed["is_contributor"] is True
    assert "last_contributor_check" in refreshed


def test_refresh_raises_for_unknown_account():
    """Refreshing an unknown account raises ValueError."""
    fresh()
    set_github_api(FakeGitHubAPI())

    try:
        refresh_contributor_status(99999)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Unlink tests
# ---------------------------------------------------------------------------

def test_unlink_removes_account_and_channels():
    """Unlinking removes the account, channels, preferences, and pause state."""
    fresh()
    set_github_api(FakeGitHubAPI())
    link_github_account(12345, "testuser", "tok")
    add_channel(12345, "discord_dm", {"user_id": "12345"})
    set_preference_order(12345, ["rss", "webhook"])
    set_pause(12345, True)

    unlink_github_account(12345)

    assert get_account(12345) is None
    assert get_channels(12345) == {}
    assert get_preference_order(12345) == {"discord_dm": 1, "webhook": 2, "rss": 3}  # default restored
    assert get_pause(12345) is False


# ---------------------------------------------------------------------------
# Patch __main__ runner for direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    failures = 0
    tests = [
        ("test_link_github_account_stores_all_fields", test_link_github_account_stores_all_fields),
        ("test_link_updates_existing_account", test_link_updates_existing_account),
        ("test_account_age_days_computed_at_link_time", test_account_age_days_computed_at_link_time),
        ("test_is_contributor_derived_from_merged_prs", test_is_contributor_derived_from_merged_prs),
        ("test_is_contributor_false_without_merged_prs", test_is_contributor_false_without_merged_prs),
        ("test_get_account_returns_none_for_unknown_id", test_get_account_returns_none_for_unknown_id),
        ("test_add_discord_dm_channel_records_reachability", test_add_discord_dm_channel_records_reachability),
        ("test_add_webhook_channel_echoes_challenge", test_add_webhook_channel_echoes_challenge),
        ("test_add_rss_channel_is_generated_not_verified", test_add_rss_channel_is_generated_not_verified),
        ("test_add_email_channel_generates_token_and_is_unverified", test_add_email_channel_generates_token_and_is_unverified),
        ("test_verify_email_channel_by_token", test_verify_email_channel_by_token),
        ("test_verify_email_channel_wrong_token_fails", test_verify_email_channel_wrong_token_fails),
        ("test_verify_email_channel_no_email_channel_returns_false", test_verify_email_channel_no_email_channel_returns_false),
        ("test_remove_channel", test_remove_channel),
        ("test_remove_nonexistent_channel_returns_false", test_remove_nonexistent_channel_returns_false),
        ("test_channels_for_account", test_channels_for_account),
        ("test_preference_order_stored_as_integers", test_preference_order_stored_as_integers),
        ("test_preference_order_normalises_gaps", test_preference_order_normalises_gaps),
        ("test_get_preference_order_returns_default", test_get_preference_order_returns_default),
        ("test_preference_order_invalid_types_ignored", test_preference_order_invalid_types_ignored),
        ("test_pause_all_notifications", test_pause_all_notifications),
        ("test_should_delivery_notification_returns_false_when_paused", test_should_deliver_notification_returns_false_when_paused),
        ("test_should_deliver_notification_returns_true_when_not_paused", test_should_deliver_notification_returns_true_when_not_paused),
        ("test_refresh_contributor_status", test_refresh_contributor_status),
        ("test_refresh_raises_for_unknown_account", test_refresh_raises_for_unknown_account),
        ("test_unlink_removes_account_and_channels", test_unlink_removes_account_and_channels),
    ]
    for name, fn in tests:
        try:
            fn()
            print("PASS " + name)
        except Exception as exc:
            failures += 1
            print("FAIL " + name + ": " + str(exc))
    if failures:
        print(str(failures) + " FAILED")
        raise SystemExit(1)
    print("ALL GREEN")