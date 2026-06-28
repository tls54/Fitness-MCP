"""Combined Garmin + Strava MCP server, hosted over streamable HTTP.

Tools are namespaced with garmin_ / strava_ prefixes since both APIs define
overlapping tool names (get_activity_detail, get_activity_streams, etc).
"""

import os

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

import garmin_tools
import strava_tools

AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if AUTH_TOKEN:
            header = request.headers.get("authorization", "")
            if header != f"Bearer {AUTH_TOKEN}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def build_app() -> Starlette:
    mcp = FastMCP("fitness")
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = int(os.environ.get("PORT", 8000))
    # DNS-rebinding protection assumes a localhost-bound dev server; Railway
    # fronts this with its own domain, so disable it and rely on the bearer
    # token above as the actual access control.
    mcp.settings.transport_security.enable_dns_rebinding_protection = False

    garmin_tools.register(mcp)
    strava_tools.register(mcp)

    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuthMiddleware)
    return app


app = build_app()

if __name__ == "__main__":
    if not AUTH_TOKEN:
        print("WARNING: MCP_AUTH_TOKEN is not set — the server is reachable without authentication.")
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
