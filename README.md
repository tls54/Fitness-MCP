# Fitness MCP

MCP servers that give Claude access to your health and fitness data for training analysis, log reviews, and coaching conversations.

```
fitness-mcp/
├── server/    Combined Garmin + Strava MCP server, hosted on Railway (streamable HTTP) — primary path
├── strava/    Standalone Strava MCP server (stdio, local-only) — activities, splits, HR, GPS, elevation
└── garmin/    Standalone Garmin Connect MCP server (stdio, local-only) — sleep, HRV, body battery, training status, and more
```

## Hosted server (`server/`)

The primary deployment: both sports' tools merged into a single MCP server, namespaced with `garmin_`/`strava_` prefixes (e.g. `garmin_get_activity_detail` vs `strava_get_activity_detail`), running over MCP's streamable-HTTP transport so it can be reached from any device — not just the machine that would otherwise spawn a local subprocess.

- Built from `server/garmin_tools.py` (ported from `garmin/garmin_server.py`) and `server/strava_tools.py` (ported from `strava/server.py`).
- Deployed on [Railway](https://railway.app) via `server/Dockerfile`. Garmin/Strava OAuth tokens persist across redeploys on a mounted Railway Volume (paths configured via `GARMIN_TOKEN_DIR` / `STRAVA_TOKEN_PATH` / `STRAVA_CONFIG_PATH` env vars).
- The endpoint is protected by a static bearer token (`MCP_AUTH_TOKEN` env var) checked on every request — required since the Railway URL is public.
- Required env vars: `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `MCP_AUTH_TOKEN`, `GARMIN_TOKEN_DIR`, `STRAVA_TOKEN_PATH`, `STRAVA_CONFIG_PATH`. `GARMIN_EMAIL`/`GARMIN_PASSWORD` are optional fallbacks if the saved Garmin token ever needs a full re-login.
- Register with an MCP client by pointing it at `https://<railway-app>.up.railway.app/mcp` with header `Authorization: Bearer <MCP_AUTH_TOKEN>`.

Local dev: `cd server && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`, then run `python main.py` with the env vars above pointed at local token paths.

## Standalone local servers (`strava/`, `garmin/`)

The original per-sport stdio servers, kept for local-only use or as a fallback. Each is a standalone MCP server with its own setup, dependencies, and Claude Desktop registration — see the README in each:

- [strava/README.md](strava/README.md)
- [garmin/README.md](garmin/README.md)

Both can be registered with Claude Desktop side by side:

```json
{
  "mcpServers": {
    "strava": {
      "command": "/path/to/strava/python",
      "args": ["/absolute/path/to/fitness-mcp/strava/server.py"]
    },
    "garmin": {
      "command": "/absolute/path/to/fitness-mcp/garmin/.venv/bin/python",
      "args": ["/absolute/path/to/fitness-mcp/garmin/garmin_server.py"]
    }
  }
}
```

Restart Claude Desktop after editing the config.

## Security

Every server is read-only against its respective API. Credentials/tokens are never committed (see each subdirectory's `.gitignore`). The hosted server additionally requires a bearer token on every request since it's reachable over the network rather than spawned locally.
