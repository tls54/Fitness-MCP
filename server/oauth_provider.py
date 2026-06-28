"""Minimal single-user OAuth 2.1 authorization server.

Claude's hosted "custom connector" UI (used for cross-device access, e.g. phone)
only supports OAuth — there's no field for a static bearer header like the
desktop JSON config accepts. This wraps our one shared secret (MCP_AUTH_TOKEN)
in just enough OAuth (dynamic client registration, authorization code + PKCE,
refresh tokens) to satisfy that flow. The "login" step is a single password
field that checks against MCP_AUTH_TOKEN — there's only one user.
"""

import html
import json
import os
import secrets
import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

CODE_TTL_SECONDS = 300
ACCESS_TOKEN_TTL_SECONDS = 3600

STORE_PATH = os.environ.get("OAUTH_STORE_PATH", "/data/oauth_store.json")


def _load_store() -> dict:
    if os.path.exists(STORE_PATH):
        with open(STORE_PATH) as f:
            return json.load(f)
    return {"clients": {}, "refresh_tokens": {}}


def _save_store(store: dict) -> None:
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    with open(STORE_PATH, "w") as f:
        json.dump(store, f)


class SingleUserOAuthProvider(OAuthAuthorizationServerProvider):
    """Clients and refresh tokens persist to disk (survive redeploys); auth
    codes and access tokens are short-lived and kept in memory only."""

    def __init__(self, shared_secret: str):
        self.shared_secret = shared_secret
        self._store = _load_store()
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        self._pending: dict[str, tuple[str, AuthorizationParams]] = {}

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        data = self._store["clients"].get(client_id)
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._store["clients"][client_info.client_id] = client_info.model_dump(mode="json")
        _save_store(self._store)

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        login_id = secrets.token_urlsafe(16)
        self._pending[login_id] = (client.client_id, params)
        return f"/login?login_id={login_id}"

    def render_login_page(self, login_id: str, error: str | None = None) -> str:
        error_html = f'<p style="color:#c00">{html.escape(error)}</p>' if error else ""
        return f"""<!doctype html>
<html><body style="font-family: sans-serif; max-width: 28rem; margin: 4rem auto;">
<h2>Fitness MCP</h2>
<p>Enter your access token to connect this client.</p>
{error_html}
<form method="POST" action="/login">
  <input type="hidden" name="login_id" value="{html.escape(login_id)}">
  <input type="password" name="token" placeholder="Access token" autofocus
         style="width: 100%; padding: 0.5rem; font-size: 1rem;">
  <button type="submit" style="margin-top: 1rem; padding: 0.5rem 1rem;">Connect</button>
</form>
</body></html>"""

    def complete_login(self, login_id: str, submitted_token: str) -> str | None:
        """Returns the redirect URL on success, or None if login_id is unknown/expired."""
        entry = self._pending.get(login_id)
        if entry is None:
            return None
        if not secrets.compare_digest(submitted_token, self.shared_secret):
            raise ValueError("Incorrect token")

        client_id, params = self._pending.pop(login_id)
        code = secrets.token_urlsafe(32)
        self._auth_codes[code] = AuthorizationCode(
            code=code,
            scopes=params.scopes or [],
            expires_at=time.time() + CODE_TTL_SECONDS,
            client_id=client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code = self._auth_codes.get(authorization_code)
        if code and code.client_id == client.client_id and code.expires_at > time.time():
            return code
        return None

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        self._auth_codes.pop(authorization_code.code, None)
        return self._issue_tokens(client.client_id, authorization_code.scopes)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        data = self._store["refresh_tokens"].get(refresh_token)
        if data and data["client_id"] == client.client_id:
            return RefreshToken(token=refresh_token, client_id=client.client_id, scopes=data["scopes"])
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        self._store["refresh_tokens"].pop(refresh_token.token, None)
        _save_store(self._store)
        return self._issue_tokens(client.client_id, scopes or refresh_token.scopes)

    async def load_access_token(self, token: str) -> AccessToken | None:
        at = self._access_tokens.get(token)
        if at and (at.expires_at is None or at.expires_at > time.time()):
            return at
        return None

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        self._access_tokens.pop(token.token, None)
        if self._store["refresh_tokens"].pop(token.token, None) is not None:
            _save_store(self._store)

    def _issue_tokens(self, client_id: str, scopes: list[str]) -> OAuthToken:
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + ACCESS_TOKEN_TTL_SECONDS
        self._access_tokens[access_token] = AccessToken(
            token=access_token, client_id=client_id, scopes=scopes, expires_at=expires_at
        )
        self._store["refresh_tokens"][refresh_token] = {"client_id": client_id, "scopes": scopes}
        _save_store(self._store)
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            refresh_token=refresh_token,
            scope=" ".join(scopes) if scopes else None,
        )
