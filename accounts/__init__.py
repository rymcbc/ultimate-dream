"""Accounts package - OAuth sign-in, sessions, and channel preferences."""

from accounts.oauth import (
    FakeProvider,
    GithubOAuthProvider,
    Identity,
    MissingCredentials,
    OAuthProvider,
)
from accounts.session import (
    DEFAULT_PREFS,
    InvalidState,
    UnknownToken,
    get_prefs,
    get_session,
    set_dm_reachable,
    set_prefs,
    sign_in,
    store_state,
)

__all__ = [
    # OAuth
    "OAuthProvider",
    "GithubOAuthProvider",
    "FakeProvider",
    "Identity",
    "MissingCredentials",
    # Session
    "sign_in",
    "store_state",
    "get_session",
    "get_prefs",
    "set_prefs",
    "set_dm_reachable",
    "DEFAULT_PREFS",
    "UnknownToken",
    "InvalidState",
]