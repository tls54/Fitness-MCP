# Fitness MCP

MCP servers that give Claude access to your health and fitness data for training analysis, log reviews, and coaching conversations.

```
fitness-mcp/
└── server/    Combined Garmin + Strava MCP server, hosted on Railway (streamable HTTP)
```

## Hosted server (`server/`)

Both sports' tools merged into a single MCP server, namespaced with `garmin_`/`strava_` prefixes (e.g. `garmin_get_activity_detail` vs `strava_get_activity_detail`), running over MCP's streamable-HTTP transport so it can be reached from any device — not just the machine that would otherwise spawn a local subprocess.

- Deployed on [Railway](https://railway.app) via `server/Dockerfile`. Garmin/Strava OAuth tokens persist across redeploys on a mounted Railway Volume (paths configured via `GARMIN_TOKEN_DIR` / `STRAVA_TOKEN_PATH` / `STRAVA_CONFIG_PATH` env vars).
- The endpoint is protected by a static bearer token (`MCP_AUTH_TOKEN` env var) checked on every request — required since the Railway URL is public.
- Required env vars: `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `MCP_AUTH_TOKEN`, `GARMIN_TOKEN_DIR`, `STRAVA_TOKEN_PATH`, `STRAVA_CONFIG_PATH`. `GARMIN_EMAIL`/`GARMIN_PASSWORD` are optional fallbacks if the saved Garmin token ever needs a full re-login.
- Register with an MCP client by pointing it at `https://<railway-app>.up.railway.app/mcp` with header `Authorization: Bearer <MCP_AUTH_TOKEN>`.

Local dev: `cd server && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`, then run `python main.py` with the env vars above pointed at local token paths.

**Note:** Strava now requires a paid API plan for third-party apps. If Strava tools start returning `403 Forbidden` with `{"resource":"Application","field":"Status","code":"Inactive"}`, it means the registered Strava API application has been deactivated — check/reactivate it at [strava.com/settings/api](https://www.strava.com/settings/api).

## Security

The server is read-only against the Garmin/Strava APIs it wraps (aside from creating/scheduling/deleting Garmin workouts, which the user explicitly requests). Credentials/tokens are never committed (see `server/.gitignore`). The endpoint additionally requires a bearer token on every request since it's reachable over the network rather than spawned locally.
