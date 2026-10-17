"""Google/GitHub OAuth: standard authorization-code flow implemented directly
against each provider's token/userinfo endpoints via httpx (already a
dependency) rather than pulling in a full OAuth client library -- keeps the
flow auditable and matches this project's "thin interface" preference.

Both providers implement the same OAuthProvider protocol so
backend/api/auth/service.py has one code path for "exchange code -> get
profile -> create/link user", not one per provider.
"""

from dataclasses import dataclass
from typing import Optional, Protocol

import httpx


@dataclass
class OAuthProfile:
    provider: str
    provider_account_id: str
    email: str
    full_name: Optional[str] = None


class OAuthProvider(Protocol):
    name: str

    def authorization_url(self, *, state: str) -> str: ...

    def exchange_code_for_profile(self, *, code: str) -> OAuthProfile: ...


class GoogleOAuthProvider:
    name = "google"
    _AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    _TOKEN_URL = "https://oauth2.googleapis.com/token"
    _USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def authorization_url(self, *, state: str) -> str:
        params = httpx.QueryParams(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
            }
        )
        return f"{self._AUTH_URL}?{params}"

    def exchange_code_for_profile(self, *, code: str) -> OAuthProfile:
        with httpx.Client(timeout=10.0) as client:
            token_response = client.post(
                self._TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            token_response.raise_for_status()
            access_token = token_response.json()["access_token"]

            userinfo_response = client.get(
                self._USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
            )
            userinfo_response.raise_for_status()
            profile = userinfo_response.json()

        return OAuthProfile(
            provider=self.name,
            provider_account_id=profile["sub"],
            email=profile["email"],
            full_name=profile.get("name"),
        )


class GithubOAuthProvider:
    name = "github"
    _AUTH_URL = "https://github.com/login/oauth/authorize"
    _TOKEN_URL = "https://github.com/login/oauth/access_token"
    _USER_URL = "https://api.github.com/user"
    _EMAILS_URL = "https://api.github.com/user/emails"

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def authorization_url(self, *, state: str) -> str:
        params = httpx.QueryParams(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "scope": "read:user user:email",
                "state": state,
            }
        )
        return f"{self._AUTH_URL}?{params}"

    def exchange_code_for_profile(self, *, code: str) -> OAuthProfile:
        with httpx.Client(timeout=10.0) as client:
            token_response = client.post(
                self._TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                },
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            access_token = token_response.json()["access_token"]

            headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
            user_response = client.get(self._USER_URL, headers=headers)
            user_response.raise_for_status()
            user = user_response.json()

            email = user.get("email")
            if not email:
                # GitHub omits email from /user if the user's email is private;
                # /user/emails requires the user:email scope (requested above).
                emails_response = client.get(self._EMAILS_URL, headers=headers)
                emails_response.raise_for_status()
                primary = next((e for e in emails_response.json() if e.get("primary")), None)
                email = primary["email"] if primary else emails_response.json()[0]["email"]

        return OAuthProfile(
            provider=self.name,
            provider_account_id=str(user["id"]),
            email=email,
            full_name=user.get("name"),
        )
