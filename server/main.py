"""Combined Garmin + Strava MCP server, hosted over streamable HTTP.

Tools are namespaced with garmin_ / strava_ prefixes since both APIs define
overlapping tool names (get_activity_detail, get_activity_streams, etc).

Auth: Claude's hosted "custom connector" UI (needed for cross-device access,
e.g. phone) only supports OAuth, not a static bearer header. SingleUserOAuthProvider
wraps our one shared secret (MCP_AUTH_TOKEN) in a minimal OAuth 2.1 flow so that
UI works; see oauth_provider.py for details.
"""

import os

import uvicorn
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse

import garmin_tools
import strava_tools
from oauth_provider import SingleUserOAuthProvider

AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN")
SERVER_URL = os.environ.get("SERVER_URL")  # e.g. https://fitness-mcp-production-7ba7.up.railway.app


def build_app() -> Starlette:
    if not AUTH_TOKEN:
        raise RuntimeError("MCP_AUTH_TOKEN must be set")
    if not SERVER_URL:
        raise RuntimeError("SERVER_URL must be set to this server's public https URL")

    provider = SingleUserOAuthProvider(shared_secret=AUTH_TOKEN)

    mcp = FastMCP(
        "fitness",
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(SERVER_URL),
            resource_server_url=AnyHttpUrl(SERVER_URL),
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True),
        ),
    )
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = int(os.environ.get("PORT", 8000))
    # DNS-rebinding protection assumes a localhost-bound dev server; Railway
    # fronts this with its own domain, so disable it. OAuth above is the real
    # access control for /mcp now.
    mcp.settings.transport_security.enable_dns_rebinding_protection = False

    garmin_tools.register(mcp)
    strava_tools.register(mcp)

    @mcp.custom_route("/login", methods=["GET"])
    async def login_form(request: Request):
        login_id = request.query_params.get("login_id", "")
        return HTMLResponse(provider.render_login_page(login_id))

    @mcp.custom_route("/login", methods=["POST"])
    async def login_submit(request: Request):
        form = await request.form()
        login_id = str(form.get("login_id", ""))
        token = str(form.get("token", ""))
        try:
            redirect_url = provider.complete_login(login_id, token)
        except ValueError:
            return HTMLResponse(provider.render_login_page(login_id, error="Incorrect token."), status_code=401)
        if redirect_url is None:
            return PlainTextResponse("Login session expired — restart the connector setup.", status_code=400)
        return RedirectResponse(url=redirect_url, status_code=302)

    return mcp.streamable_http_app()


app = build_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
