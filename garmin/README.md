# Garmin Connect MCP Server

A local stdio MCP server that gives Claude direct access to your Garmin Connect data. Built on the [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) library (garth-backed OAuth). Read-only — no data is written back to Garmin.

---

## Tools (34)

### Daily Health

| Tool | Data |
|------|------|
| `get_sleep` | Sleep stages (deep/light/REM/awake), score, duration, respiration, SpO2 |
| `get_hrv` | Overnight HRV, 5-min readings, baseline, status (Balanced/Unbalanced/Low) |
| `get_body_battery` | Charge/drain events, start/end levels throughout the day |
| `get_stress` | Average stress, max stress, time in each stress band |
| `get_heart_rate` | Resting HR, min/max, timestamped HR timeline |
| `get_spo2` | Blood oxygen average, min, max, overnight continuous readings |
| `get_respiration` | Breathing rate average, min, max throughout day and overnight |
| `get_steps_and_activity` | Steps, floors, distance, calories, intensity minutes |
| `get_hydration` | Fluid intake vs daily goal |
| `get_daily_summary` | All-in-one snapshot: steps, calories, HR, stress, Body Battery, intensity |

### Training & Fitness

| Tool | Data |
|------|------|
| `get_training_readiness` | Readiness score (0–100) with component breakdown (sleep, HRV, load, recovery) |
| `get_training_status` | Status label, acute/chronic load, load focus, VO2 max trend |
| `get_vo2max_and_fitness_metrics` | VO2 max estimate, fitness age |
| `get_lactate_threshold` | Threshold HR and pace |
| `get_race_predictions` | Predicted finish times: 5K / 10K / half marathon / marathon |
| `get_endurance_score` | Garmin's aerobic capacity score over a date range |
| `get_hill_score` | Elevation handling ability over a date range |
| `get_running_tolerance` | Acute/chronic load ratio and injury risk signals over a date range |
| `get_personal_records` | PRs across all activity types |
| `get_progress_summary` | Training volume trends between two dates, grouped by activity type |

### Activities

| Tool | Data |
|------|------|
| `get_activities` | List of recent activities: type, date, distance, duration, avg HR, calories, Training Effect, load |
| `get_last_activity` | Most recent activity with full summary stats |
| `get_activity_detail` | Full detail for a single activity by ID: Training Effect, aerobic/anaerobic load, pace, cadence |
| `get_activity_splits` | Per-km splits with pace, HR, and elevation |
| `get_activity_hr_zones` | Time spent in each HR zone for an activity |
| `get_activity_streams` | Time-series chart data (up to 2000 points): cadence, HR, speed, power, elevation |
| `get_activity_power_zones` | Time in each power zone (meaningful once real power data is available) |

### Trends & History

| Tool | Data |
|------|------|
| `get_sleep_history` | Sleep scores and stage breakdown over past N days (default 14, max 28) |
| `get_hrv_history` | Overnight HRV values over past N days |
| `get_body_battery_history` | End-of-day Body Battery levels over past N days |
| `get_weekly_summary` | 7-day rollup: steps, calories, intensity minutes, stress, sleep averages |

### Body

| Tool | Data |
|------|------|
| `get_weight` | Weight and body composition over a date range |

### Lifestyle

| Tool | Data |
|------|------|
| `get_lifestyle_log` | Daily habit log (e.g. healthy meals, morning caffeine, exercise) and completion status |
| `get_lifestyle_log_history` | Day-by-day habit compliance table over a date range |

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone <repo-url>
cd Garmin-MCP
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Authenticate (first time only)

```bash
python setup_auth.py
```

Enter your Garmin Connect email and password when prompted. If you have MFA enabled you'll be asked for your authenticator code. OAuth tokens are saved to `~/.garminconnect/` — your password is never stored.

Tokens auto-refresh indefinitely. Re-run only if you revoke the session or change your password.

> **Note on rate limiting:** Garmin aggressively rate-limits login attempts from non-mobile IPs. If you see 429 errors, wait 5–10 minutes before retrying. Logging into Garmin Connect in your browser immediately beforehand can help.

### 3. Add to Claude Desktop config

Open your Claude Desktop config file:

```
~/Library/Application Support/Claude/claude_desktop_config.json
```

Add the garmin entry under `mcpServers`:

```json
{
  "mcpServers": {
    "garmin": {
      "command": "/absolute/path/to/Garmin-MCP/.venv/bin/python",
      "args": ["/absolute/path/to/Garmin-MCP/garmin_server.py"]
    }
  }
}
```

Use absolute paths. Find them by running `echo $(pwd)/.venv/bin/python` from inside the project folder.

Fully quit Claude Desktop (Cmd+Q) and reopen it.

### 4. Verify

Ask Claude: *"What was my sleep score last night?"* or *"Show me my training status."*

---

## Notes

**No credentials in the config** — authentication is handled entirely via the saved token file in `~/.garminconnect/`. Nothing sensitive lives in the Claude Desktop config.

**Race predictions and training status context** — Garmin's algorithm needs sustained threshold efforts to calibrate well. During injury recovery or low-volume phases, labels like "Unproductive" and inflated race predictions are common artefacts of limited signal, not accurate assessments of fitness. Use these numbers alongside context rather than at face value.

**Power data** — `get_activity_power_zones` and power fields in `get_activity_streams` are only meaningful for activities with real power data recorded (e.g. BikeErg sessions via ERG Logbook). Garmin's estimated FTP is extrapolated from VO2 max and is unreliable without actual power measurements.

**Activity streams and cadence** — `get_activity_streams` returns Garmin's raw chart data. Note that Garmin records running cadence as single-foot steps per minute; multiply by 2 for total cadence (steps/min).

---

## Troubleshooting

**Token expired errors** — run `python setup_auth.py` again to re-authenticate.

**429 Too Many Requests** — Garmin rate-limits login attempts heavily. Wait 5–10 minutes and try again.

**MFA prompt not appearing** — try logging out of all active Garmin Connect sessions in your browser first, then re-run `setup_auth.py`.

**Tools not showing in Claude** — make sure you fully quit Claude Desktop (Cmd+Q, not just closing the window) before restarting. Check that the paths in the config are absolute and correct.

**Empty results from some tools** — some endpoints (endurance score, hill score, running tolerance) require a minimum activity history to return data. If you've recently set up your device, these may return empty until Garmin has enough data to compute them.

---

## Dependencies

- [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) >= 0.2.22
- [`mcp`](https://github.com/modelcontextprotocol/python-sdk) >= 1.0.0
