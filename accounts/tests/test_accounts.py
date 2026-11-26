"""Tests for accounts package."""

from __future__ import annotations

import os
import tempfile

import pytest

from accounts import (
    DEFAULT_PREFS,
    FakeProvider,
    GithubOAuthProvider,
    Identity,
    InvalidState,
    MissingCredentials,
    UnknownToken,
    get_prefs,
    get_session,
    set_dm_reachable,
    set_prefs,
    sign_in,
    store_state,
)


class TestFakeProvider:
    """Tests for the fake OAuth provider."""

    def test_fake_provider_sign_in_creates_session(self) -> None:
        """Fake provider sign-in creates a session with correct identity."""
        provider = FakeProvider(Identity(gh_id=12345, login="testuser", email="test@example.com"))
        state = "test-state-123"
        store_state(state)

        token = sign_in(provider, state, state)

        assert token is not None
        assert len(token) > 0

        session = get_session(token)
        assert session is not None
        assert session.gh_id == 12345
        assert session.login == "testuser"
        assert session.email == "test@example.com"
        assert session.dm_reachable is False
        assert session.prefs == DEFAULT_PREFS

    def test_fake_provider_rejects_bad_state(self) -> None:
        """Fake provider rejects invalid or missing state."""
        provider = FakeProvider()
        store_state("valid-state")

        with pytest.raises(InvalidState):
            sign_in(provider, "invalid-state", "invalid-state")

        with pytest.raises(InvalidState):
            sign_in(provider, "another-state", "another-state")

    def test_fake_provider_unknown_token_returns_none(self) -> None:
        """Unknown token returns None from get_session and get_prefs."""
        assert get_session("unknown-token") is None
        assert get_prefs("unknown-token") is None


class TestGithubOAuthProvider:
    """Tests for the GitHub OAuth provider."""

    def test_missing_env_var_refuses_sign_in(self) -> None:
        """Missing env var causes MissingCredentials at init."""
        # Ensure env vars are not set
        for var in ["GITHUB_OAUTH_CLIENT_ID", "GITHUB_OAUTH_CLIENT_SECRET", "GITHUB_OAUTH_CALLBACK_URL"]:
            os.environ.pop(var, None)

        with pytest.raises(MissingCredentials):
            GithubOAuthProvider()

    def test_partial_env_vars_also_fail(self) -> None:
        """Partially set env vars also fail."""
        os.environ["GITHUB_OAUTH_CLIENT_ID"] = "test-id"
        os.environ.pop("GITHUB_OAUTH_CLIENT_SECRET", None)
        os.environ.pop("GITHUB_OAUTH_CALLBACK_URL", None)

        with pytest.raises(MissingCredentials):
            GithubOAuthProvider()

        os.environ.pop("GITHUB_OAUTH_CLIENT_ID", None)


class TestPreferences:
    """Tests for preference storage and retrieval."""

    def test_prefs_round_trip_per_session(self) -> None:
        """Preferences round-trip correctly per session."""
        provider = FakeProvider(Identity(gh_id=111, login="user1", email="user1@example.com"))
        store_state("state-1")
        token1 = sign_in(provider, "state-1", "state-1")

        provider2 = FakeProvider(Identity(gh_id=222, login="user2", email="user2@example.com"))
        store_state("state-2")
        token2 = sign_in(provider2, "state-2", "state-2")

        # Set different prefs for each session
        set_prefs(token1, {"discord_dm": True, "webhook": False, "rss": True})
        set_prefs(token2, {"discord_dm": False, "webhook": True, "rss": False})

        # Verify each session has its own prefs
        prefs1 = get_prefs(token1)
        prefs2 = get_prefs(token2)

        assert prefs1 == {"discord_dm": True, "webhook": False, "rss": True}
        assert prefs2 == {"discord_dm": False, "webhook": True, "rss": False}

    def test_prefs_partial_update_preserves_other_keys(self) -> None:
        """Partial prefs update preserves unspecified keys."""
        provider = FakeProvider(Identity(gh_id=333, login="user3", email="user3@example.com"))
        store_state("state-3")
        token = sign_in(provider, "state-3", "state-3")

        # Initial prefs are defaults
        assert get_prefs(token) == DEFAULT_PREFS

        # Update only one key
        set_prefs(token, {"discord_dm": True})

        # Others should remain at defaults
        prefs = get_prefs(token)
        assert prefs["discord_dm"] is True
        assert prefs["webhook"] is False
        assert prefs["rss"] is False

    def test_prefs_ignores_unknown_keys(self) -> None:
        """Unknown preference keys are ignored (no email key allowed)."""
        provider = FakeProvider(Identity(gh_id=444, login="user4", email="user4@example.com"))
        store_state("state-4")
        token = sign_in(provider, "state-4", "state-4")

        set_prefs(token, {"discord_dm": True, "email": True, "unknown": True})

        prefs = get_prefs(token)
        assert prefs["discord_dm"] is True
        assert "email" not in prefs
        assert "unknown" not in prefs
        assert set(prefs.keys()) == {"discord_dm", "webhook", "rss"}

    def test_set_prefs_unknown_token_raises(self) -> None:
        """Setting prefs on unknown token raises UnknownToken."""
        with pytest.raises(UnknownToken):
            set_prefs("unknown-token", {"discord_dm": True})


class TestDMReachable:
    """Tests for DM reachable flag."""

    def test_set_dm_reachable(self) -> None:
        """DM reachable can be set and retrieved."""
        provider = FakeProvider(Identity(gh_id=555, login="user5", email="user5@example.com"))
        store_state("state-5")
        token = sign_in(provider, "state-5", "state-5")

        assert get_session(token).dm_reachable is False

        set_dm_reachable(token, True)
        assert get_session(token).dm_reachable is True

        set_dm_reachable(token, False)
        assert get_session(token).dm_reachable is False

    def test_set_dm_reachable_unknown_token_raises(self) -> None:
        """Setting DM reachable on unknown token raises UnknownToken."""
        with pytest.raises(UnknownToken):
            set_dm_reachable("unknown-token", True)


class TestSessionIsolation:
    """Tests for session isolation with database."""

    def test_multiple_sessions_independent(self) -> None:
        """Multiple sessions are independent."""
        provider = FakeProvider()
        store_state("a")
        store_state("b")
        store_state("c")

        token_a = sign_in(provider, "a", "a")
        token_b = sign_in(provider, "b", "b")
        token_c = sign_in(provider, "c", "c")

        set_prefs(token_a, {"discord_dm": True})
        set_prefs(token_b, {"webhook": True})
        set_prefs(token_c, {"rss": True})

        assert get_prefs(token_a) == {"discord_dm": True, "webhook": False, "rss": False}
        assert get_prefs(token_b) == {"discord_dm": False, "webhook": True, "rss": False}
        assert get_prefs(token_c) == {"discord_dm": False, "webhook": False, "rss": True}


class TestDefaultPrefs:
    """Tests for default preferences constant."""

    def test_default_prefs_has_correct_keys(self) -> None:
        """DEFAULT_PREFS has exactly the three allowed keys, no email."""
        assert set(DEFAULT_PREFS.keys()) == {"discord_dm", "webhook", "rss"}
        assert all(v is False for v in DEFAULT_PREFS.values())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])