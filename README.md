# Fitness MCP

A collection of local MCP servers that give Claude access to your health and fitness data for training analysis, log reviews, and coaching conversations.

```
fitness-mcp/
├── strava/    Strava MCP server — activities, splits, HR, GPS, elevation
└── garmin/    Garmin Connect MCP server — sleep, HRV, body battery, training status, and more
```

Each subdirectory is a standalone MCP server with its own setup, dependencies, and Claude Desktop registration. See the README in each for full setup instructions:

- [strava/README.md](strava/README.md)
- [garmin/README.md](garmin/README.md)

## Quick start

Both servers run independently and can be registered with Claude Desktop side by side:

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

Each server is read-only against its respective API and keeps credentials/tokens local — never committed (see each subdirectory's `.gitignore`). No data leaves your machine except requests to the Strava/Garmin APIs.
