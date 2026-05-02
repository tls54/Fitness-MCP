# Strava MCP Server

A local MCP server that connects Claude to the Strava API, giving Claude access to your workout data for training analysis, log reviews, and coaching conversations.

Ask Claude things like:
- "How has my training been this week?"
- "What are my fastest runs ever?"
- "Tell me about my long run last Sunday"
- "How does my YTD mileage compare to all time?"

## How It Works

Claude Desktop launches this server as a subprocess and communicates over stdio using the MCP protocol. The server fetches your Strava data on demand — no manual exports, no hosted infrastructure.

```
Claude Desktop ↕ MCP (stdio) ↕ Python Server ↕ HTTP ↕ Strava API
```

## Prerequisites

- Python 3.10+
- [Claude Desktop](https://claude.ai/download)
- A Strava account with activities

## Setup

### 1. Clone the repo

```bash
git clone <repo-url>
cd strava-mcp
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create a Strava API application

Go to [strava.com/settings/api](https://www.strava.com/settings/api) and create an app. Set **Authorization Callback Domain** to `localhost`. Note your **Client ID** and **Client Secret**.

### 4. Configure credentials

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```
STRAVA_CLIENT_ID=your_client_id
STRAVA_CLIENT_SECRET=your_client_secret
```

### 5. Run the one-time auth flow

```bash
python auth.py
```

This opens Strava in your browser. Approve access and the tokens are saved to `strava_token.json` automatically. You only need to do this once — tokens refresh automatically after that.

### 6. Register with Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "strava": {
      "command": "/path/to/your/python",
      "args": ["/absolute/path/to/strava-mcp/server.py"]
    }
  }
}
```

Use the full path to the Python where you installed the dependencies (e.g. a conda env). Find it with `which python` after activating your environment.

Restart Claude Desktop after saving.

## Available Tools

| Tool | Description |
|---|---|
| `get_athlete_stats` | YTD, all-time, and recent (4-week) running totals |
| `get_recent_activities` | List recent activities, optionally filtered by date range |
| `get_activity_detail` | Full detail for a single activity including km splits and HR |
| `get_best_activities` | Rank activities by pace, distance, time, or elevation |

## Security

- `.env` and `strava_token.json` are gitignored — never commit them
- The server only requests read-only Strava scopes (`activity:read_all`)
- No data leaves your machine except the requests to the Strava API
