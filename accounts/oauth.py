"""OAuth provider interface and implementations."""

from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass
from typing import Protocol, TypedDict


class Identity(TypedDict):
    """GitHub user identity. gh_id is the stable identity; email is just an address."""

    gh_id: int
    login: str
    email: str | None


class MissingCredentials(Exception):
    """Raised when required OAuth credentials are not configured."""

    pass


class OAuthProvider(Protocol):
    """Protocol for OAuth providers."""

    def authorize_url(self, state: str) -> str:
        """Return the authorization URL for the given state."""
        ...

    def exchange_code(self, code: str) -> Identity:
        """Exchange an authorization code for an identity."""
        ...


@dataclass(frozen=True)
class GithubOAuthProvider:
    """GitHub OAuth provider. Reads credentials from environment at init."""

    def __init__(self) -> None:
        client_id = os.getenv("GITHUB_OAUTH_CLIENT_ID")
        client_secret = os.getenv("GITHUB_OAUTH_CLIENT_SECRET")
        callback_url = os.getenv("GITHUB_OAUTH_CALLBACK_URL")

        if not client_id or not client_secret or not callback_url:
            raise MissingCredentials(
                "GITHUB_OAUTH_CLIENT_ID, GITHUB_OAUTH_CLIENT_SECRET, "
                "and GITHUB_OAUTH_CALLBACK_URL must all be set"
            )

        object.__setattr__(self, "_client_id", client_id)
        object.__setattr__(self, "_client_secret", client_secret)
        object.__setattr__(self, "_callback_url", callback_url)

    def authorize_url(self, state: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._callback_url,
            "scope": "read:user user:email",
            "state": state,
        }
        return "https://github.com/login/oauth/authorize?" + urllib.parse.urlencode(params)

    def exchange_code(self, code: str) -> Identity:
        import urllib.request
        import json

        # Exchange code for access token
        token_url = "https://github.com/login/oauth/access_token"
        data = urllib.parse.urlencode({
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code": code,
            "redirect_uri": self._callback_url,
        }).encode()

        req = urllib.request.Request(
            token_url,
            data=data,
            headers={"Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            token_data = json.loads(resp.read().decode())

        access_token = token_data.get("access_token")
        if not access_token:
            raise ValueError("No access token in response")

        # Fetch user info
        user_url = "https://api.github.com/user"
        req = urllib.request.Request(
            user_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req) as resp:
            user_data = json.loads(resp.read().decode())

        # Fetch emails
        emails_url = "https://api.github.com/user/emails"
        req = urllib.request.Request(
            emails_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req) as resp:
            emails_data = json.loads(resp.read().decode())

        primary_email = None
        for email in emails_data:
            if email.get("primary") and email.get("verified"):
                primary_email = email.get("email")
                break

        return Identity(
            gh_id=user_data["id"],
            login=user_data["login"],
            email=primary_email,
        )


class FakeProvider:
    """Fake OAuth provider for testing. Returns a fixed identity."""

    def __init__(self, identity: Identity | None = None) -> None:
        self._identity = identity or Identity(gh_id=12345, login="testuser", email="test@example.com")

    def authorize_url(self, state: str) -> str:
        # Local import: session.py imports this module at import time, so a
        # module-level import of store_state here would be circular.
        from accounts.session import store_state

        # Store state in DB for validation
        store_state(state)
        return f"https://fake.example.com/authorize?state={urllib.parse.quote(state)}"

    def exchange_code(self, code: str) -> Identity:
        # In fake mode, any code is accepted since state was already validated
        return self._identity