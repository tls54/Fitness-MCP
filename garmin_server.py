#!/usr/bin/env python3
"""
Garmin Connect MCP Server
Exposes Garmin health, training, and performance data via the Model Context Protocol.
"""

import json
import os
from datetime import date, timedelta
from typing import Any

import garminconnect
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

# ── Auth ──────────────────────────────────────────────────────────────────────

TOKEN_DIR = os.path.expanduser("~/.garminconnect")


def get_client() -> garminconnect.Garmin:
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    client = garminconnect.Garmin(email=email, password=password, is_cn=False)
    try:
        client.login(TOKEN_DIR)
    except Exception:
        client.login()
        client.client.dump(TOKEN_DIR)
    return client


server = Server("garmin-connect")


def today_str() -> str:
    return date.today().isoformat()


def days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def safe_call(fn, *args, **kwargs) -> dict:
    try:
        result = fn(*args, **kwargs)
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def date_range(start: str, end: str) -> list[str]:
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    return [(s + timedelta(days=i)).isoformat() for i in range((e - s).days + 1)]


def format_lifestyle_log(logs: list[dict], d: str) -> str:
    if not logs:
        return f"No lifestyle log entries for {d}."
    lines = [f"Lifestyle log for {d}:"]
    for entry in logs:
        status = "Completed" if entry.get("logStatus") == "YES" else "Not completed"
        lines.append(f"- {entry.get('name')}: {status}")
    return "\n".join(lines)


def get_lifestyle_log(client: garminconnect.Garmin, d: str) -> str:
    data = client.get_lifestyle_logging_data(d)
    logs = data.get("dailyLogsReport") or []
    return format_lifestyle_log(logs, d)


def get_lifestyle_log_history(client: garminconnect.Garmin, start: str, end: str) -> str:
    days = date_range(start, end)
    daily_logs: dict[str, list[dict]] = {}
    habit_names: list[str] = []
    for d in days:
        try:
            data = client.get_lifestyle_logging_data(d)
            logs = data.get("dailyLogsReport") or []
        except Exception:
            logs = []
        daily_logs[d] = logs
        for entry in logs:
            if entry.get("name") not in habit_names:
                habit_names.append(entry.get("name"))

    if not habit_names:
        return f"No lifestyle log entries found between {start} and {end}."

    header = "Date       | " + " | ".join(habit_names)
    lines = [header, "-" * len(header)]
    for d in days:
        status_by_name = {e.get("name"): e.get("logStatus") == "YES" for e in daily_logs[d]}
        row = [d]
        for h in habit_names:
            if h not in status_by_name:
                row.append("not logged")
            else:
                row.append("done" if status_by_name[h] else "missed")
        lines.append(" | ".join(row))
    return "\n".join(lines)


# ── Tools ─────────────────────────────────────────────────────────────────────

TOOLS = [
    # ── Daily health ──────────────────────────────────────────────────────────
    types.Tool(
        name="get_sleep",
        description="Get detailed sleep data for a given date: sleep stages (deep, light, REM, awake), total sleep duration, sleep score, respiration, SpO2, and sleep start/end times.",
        inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."}}},
    ),
    types.Tool(
        name="get_hrv",
        description="Get Heart Rate Variability (HRV) data for a date: overnight HRV summary, 5-minute readings, baseline, and status (Balanced / Unbalanced / Low).",
        inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."}}},
    ),
    types.Tool(
        name="get_body_battery",
        description="Get Body Battery levels for a date: charging/draining events, start/end levels, and the impact of sleep and activities.",
        inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."}}},
    ),
    types.Tool(
        name="get_stress",
        description="Get stress data for a date: average stress, max stress, rest stress, and time in low/medium/high/rest stress categories.",
        inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."}}},
    ),
    types.Tool(
        name="get_heart_rate",
        description="Get resting heart rate and heart rate timeline for a date: min HR, max HR, resting HR, and timestamped readings throughout the day.",
        inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."}}},
    ),
    types.Tool(
        name="get_spo2",
        description="Get SpO2 (blood oxygen saturation) readings for a date: average, min, max, and overnight continuous readings.",
        inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."}}},
    ),
    types.Tool(
        name="get_respiration",
        description="Get breathing rate (respiration) data for a date: average, min, max breaths per minute throughout the day and overnight.",
        inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."}}},
    ),
    types.Tool(
        name="get_steps_and_activity",
        description="Get daily steps, floors climbed, distance, calories (active + resting), and intensity minutes for a date.",
        inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."}}},
    ),
    types.Tool(
        name="get_hydration",
        description="Get daily hydration data: fluid intake in ml and goal for a date.",
        inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."}}},
    ),
    types.Tool(
        name="get_daily_summary",
        description="Get a comprehensive daily summary including steps, calories, HR, stress, Body Battery, intensity minutes, and floors for a date. Good all-in-one snapshot.",
        inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."}}},
    ),

    # ── Training & fitness ────────────────────────────────────────────────────
    types.Tool(
        name="get_training_readiness",
        description="Get Garmin's Training Readiness score (0–100) for a date, with component scores for sleep, recovery, HRV, and training load.",
        inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."}}},
    ),
    types.Tool(
        name="get_training_status",
        description="Get Garmin's training status: status label (Maintaining/Productive/Unproductive/Detraining/Overreaching), acute/chronic load, load focus, and VO2 max trend.",
        inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."}}},
    ),
    types.Tool(
        name="get_vo2max_and_fitness_metrics",
        description="Get VO2 max estimate and fitness age. Includes running VO2 max and cycling VO2 max if available.",
        inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."}}},
    ),
    types.Tool(
        name="get_lactate_threshold",
        description="Get Garmin's lactate threshold estimate: threshold heart rate, threshold pace, and the associated training zone.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="get_race_predictions",
        description="Get Garmin's predicted race finish times for 5K, 10K, half marathon, and marathon based on current fitness.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="get_endurance_score",
        description="Get Garmin's Endurance Score for a date range — measures aerobic fitness capacity built up over time.",
        inputSchema={"type": "object", "properties": {
            "start_date": {"type": "string", "description": "YYYY-MM-DD. Defaults to 30 days ago."},
            "end_date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."},
        }},
    ),
    types.Tool(
        name="get_hill_score",
        description="Get Garmin's Hill Score for a date range — measures ability to handle elevation gain in runs.",
        inputSchema={"type": "object", "properties": {
            "start_date": {"type": "string", "description": "YYYY-MM-DD. Defaults to 30 days ago."},
            "end_date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."},
        }},
    ),
    types.Tool(
        name="get_running_tolerance",
        description="Get Garmin's running tolerance/load data over a date range (weekly aggregation by default). Shows acute load, chronic load, and injury risk signals.",
        inputSchema={"type": "object", "properties": {
            "start_date": {"type": "string", "description": "YYYY-MM-DD. Defaults to 28 days ago."},
            "end_date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."},
            "aggregation": {"type": "string", "description": "'weekly' or 'daily'. Defaults to weekly."},
        }},
    ),
    types.Tool(
        name="get_personal_records",
        description="Get personal records (PRs) for running and other activities: fastest mile, 5K, 10K, half marathon, longest run, etc.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="get_progress_summary",
        description="Get training progress summary between two dates, grouped by activity type. Shows distance, time, and effort trends.",
        inputSchema={"type": "object", "properties": {
            "start_date": {"type": "string", "description": "YYYY-MM-DD. Defaults to 28 days ago."},
            "end_date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."},
            "metric": {"type": "string", "description": "'distance', 'duration', or 'calories'. Defaults to distance."},
        }},
    ),

    # ── Activities ────────────────────────────────────────────────────────────
    types.Tool(
        name="get_activities",
        description="Get a list of recent Garmin activities with summary stats: type, date, distance, duration, avg HR, calories, Training Effect, aerobic/anaerobic load.",
        inputSchema={"type": "object", "properties": {
            "start_date": {"type": "string", "description": "YYYY-MM-DD. Defaults to 14 days ago."},
            "end_date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."},
            "activity_type": {"type": "string", "description": "Filter by type e.g. 'running', 'cycling', 'hiking'. Optional."},
        }},
    ),
    types.Tool(
        name="get_activity_detail",
        description="Get full detail for a single Garmin activity by ID: splits, HR zones, Training Effect, aerobic/anaerobic load, pace, elevation, cadence.",
        inputSchema={"type": "object", "properties": {
            "activity_id": {"type": "string", "description": "Garmin activity ID (from get_activities)."},
        }, "required": ["activity_id"]},
    ),
    types.Tool(
        name="get_activity_splits",
        description="Get per-kilometre or per-mile splits for a Garmin activity: pace, HR, elevation for each split.",
        inputSchema={"type": "object", "properties": {
            "activity_id": {"type": "string", "description": "Garmin activity ID (from get_activities)."},
        }, "required": ["activity_id"]},
    ),
    types.Tool(
        name="get_activity_hr_zones",
        description="Get time spent in each HR zone for a Garmin activity.",
        inputSchema={"type": "object", "properties": {
            "activity_id": {"type": "string", "description": "Garmin activity ID (from get_activities)."},
        }, "required": ["activity_id"]},
    ),
    types.Tool(
        name="get_activity_streams",
        description=(
            "Get time-series chart data for a Garmin activity: cadence, HR, speed, power, elevation, "
            "and other metrics sampled throughout the activity. Up to 2000 data points. "
            "Use this for detailed analysis of effort, cadence consistency, HR drift, or power curves."
        ),
        inputSchema={"type": "object", "properties": {
            "activity_id": {"type": "string", "description": "Garmin activity ID (from get_activities)."},
            "max_points": {"type": "integer", "description": "Max chart points to return (default 2000, max 2000)."},
        }, "required": ["activity_id"]},
    ),
    types.Tool(
        name="get_activity_power_zones",
        description=(
            "Get time spent in each power zone for a Garmin activity. "
            "Only meaningful for activities with actual power data (e.g. BikeErg with ERG Logbook connected)."
        ),
        inputSchema={"type": "object", "properties": {
            "activity_id": {"type": "string", "description": "Garmin activity ID (from get_activities)."},
        }, "required": ["activity_id"]},
    ),
    types.Tool(
        name="get_last_activity",
        description="Get the most recent Garmin activity with full summary stats.",
        inputSchema={"type": "object", "properties": {}},
    ),

    # ── Trends / history ──────────────────────────────────────────────────────
    types.Tool(
        name="get_sleep_history",
        description="Get sleep scores and stage breakdown for the past N days to identify trends.",
        inputSchema={"type": "object", "properties": {"days": {"type": "integer", "description": "Number of past days (default 14, max 28)."}}},
    ),
    types.Tool(
        name="get_hrv_history",
        description="Get overnight HRV values for the past N days to track recovery trends.",
        inputSchema={"type": "object", "properties": {"days": {"type": "integer", "description": "Number of past days (default 14, max 28)."}}},
    ),
    types.Tool(
        name="get_body_battery_history",
        description="Get end-of-day Body Battery levels for the past N days to track energy trends.",
        inputSchema={"type": "object", "properties": {"days": {"type": "integer", "description": "Number of past days (default 14)."}}},
    ),
    types.Tool(
        name="get_weekly_summary",
        description="Get a weekly health and activity summary: total steps, active calories, intensity minutes, stress average, and sleep averages for the past 7 days.",
        inputSchema={"type": "object", "properties": {"end_date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."}}},
    ),

    # ── Lifestyle / habits ────────────────────────────────────────────────────
    types.Tool(
        name="get_lifestyle_log",
        description="Get the lifestyle/habit log for a date: which manually-tracked habits (e.g. healthy meals, morning caffeine, moderate exercise, ankle exercises) were logged that day and whether each was completed.",
        inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."}}},
    ),
    types.Tool(
        name="get_lifestyle_log_history",
        description="Get lifestyle/habit log compliance across a date range, as a day-by-day table showing whether each tracked habit was done, missed, or not logged.",
        inputSchema={"type": "object", "properties": {
            "start_date": {"type": "string", "description": "YYYY-MM-DD. Required."},
            "end_date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."},
        }, "required": ["start_date"]},
    ),

    # ── Body & weight ─────────────────────────────────────────────────────────
    types.Tool(
        name="get_weight",
        description="Get body weight and composition data for a date range. Returns weight, BMI, body fat % if measured.",
        inputSchema={"type": "object", "properties": {
            "start_date": {"type": "string", "description": "YYYY-MM-DD. Defaults to 14 days ago."},
            "end_date": {"type": "string", "description": "YYYY-MM-DD. Defaults to today."},
        }},
    ),
]


# ── Handlers ──────────────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    client = get_client()
    d = arguments.get("date", today_str())

    # ── Daily health ──────────────────────────────────────────────────────────
    if name == "get_sleep":
        result = safe_call(client.get_sleep_data, d)

    elif name == "get_hrv":
        result = safe_call(client.get_hrv_data, d)

    elif name == "get_body_battery":
        result = safe_call(client.get_body_battery, d, d)

    elif name == "get_stress":
        result = safe_call(client.get_stress_data, d)

    elif name == "get_heart_rate":
        result = safe_call(client.get_heart_rates, d)

    elif name == "get_spo2":
        result = safe_call(client.get_spo2_data, d)

    elif name == "get_respiration":
        result = safe_call(client.get_respiration_data, d)

    elif name == "get_steps_and_activity":
        steps = safe_call(client.get_steps_data, d)
        stats = safe_call(client.get_stats, d)
        result = {"ok": True, "data": {"steps": steps.get("data"), "stats": stats.get("data")}}

    elif name == "get_hydration":
        result = safe_call(client.get_hydration_data, d)

    elif name == "get_daily_summary":
        result = safe_call(client.get_user_summary, d)

    # ── Training & fitness ────────────────────────────────────────────────────
    elif name == "get_training_readiness":
        result = safe_call(client.get_training_readiness, d)

    elif name == "get_training_status":
        result = safe_call(client.get_training_status, d)

    elif name == "get_vo2max_and_fitness_metrics":
        result = safe_call(client.get_max_metrics, d)

    elif name == "get_lactate_threshold":
        result = safe_call(client.get_lactate_threshold)

    elif name == "get_race_predictions":
        result = safe_call(client.get_race_predictions)

    elif name == "get_endurance_score":
        start = arguments.get("start_date", days_ago(30))
        end = arguments.get("end_date", today_str())
        result = safe_call(client.get_endurance_score, start, end)

    elif name == "get_hill_score":
        start = arguments.get("start_date", days_ago(30))
        end = arguments.get("end_date", today_str())
        result = safe_call(client.get_hill_score, start, end)

    elif name == "get_running_tolerance":
        start = arguments.get("start_date", days_ago(28))
        end = arguments.get("end_date", today_str())
        agg = arguments.get("aggregation", "weekly")
        result = safe_call(client.get_running_tolerance, start, end, agg)

    elif name == "get_personal_records":
        result = safe_call(client.get_personal_record)

    elif name == "get_progress_summary":
        start = arguments.get("start_date", days_ago(28))
        end = arguments.get("end_date", today_str())
        metric = arguments.get("metric", "distance")
        result = safe_call(client.get_progress_summary_between_dates, start, end, metric)

    # ── Activities ────────────────────────────────────────────────────────────
    elif name == "get_activities":
        start = arguments.get("start_date", days_ago(14))
        end = arguments.get("end_date", today_str())
        activity_type = arguments.get("activity_type", None)
        result = safe_call(client.get_activities_by_date, start, end, activity_type)

    elif name == "get_activity_detail":
        result = safe_call(client.get_activity, arguments["activity_id"])

    elif name == "get_activity_splits":
        result = safe_call(client.get_activity_splits, arguments["activity_id"])

    elif name == "get_activity_hr_zones":
        result = safe_call(client.get_activity_hr_in_timezones, arguments["activity_id"])

    elif name == "get_activity_streams":
        max_points = int(arguments.get("max_points", 2000))
        result = safe_call(client.get_activity_details, arguments["activity_id"], maxchart=max_points)

    elif name == "get_activity_power_zones":
        result = safe_call(client.get_activity_power_in_timezones, arguments["activity_id"])

    elif name == "get_last_activity":
        result = safe_call(client.get_last_activity)

    # ── Trends / history ──────────────────────────────────────────────────────
    elif name == "get_sleep_history":
        days = min(int(arguments.get("days", 14)), 28)
        history = []
        for i in range(days):
            day = days_ago(i)
            r = safe_call(client.get_sleep_data, day)
            if r["ok"] and r["data"]:
                history.append({"date": day, "data": r["data"]})
        result = {"ok": True, "data": history}

    elif name == "get_hrv_history":
        days = min(int(arguments.get("days", 14)), 28)
        history = []
        for i in range(days):
            day = days_ago(i)
            r = safe_call(client.get_hrv_data, day)
            if r["ok"] and r["data"]:
                history.append({"date": day, "data": r["data"]})
        result = {"ok": True, "data": history}

    elif name == "get_body_battery_history":
        days = min(int(arguments.get("days", 14)), 28)
        history = []
        for i in range(days):
            day = days_ago(i)
            r = safe_call(client.get_body_battery, day, day)
            if r["ok"] and r["data"]:
                history.append({"date": day, "data": r["data"]})
        result = {"ok": True, "data": history}

    elif name == "get_weekly_summary":
        end = arguments.get("end_date", today_str())
        result = safe_call(client.get_weekly_stress, end)

    # ── Lifestyle / habits ────────────────────────────────────────────────────
    elif name == "get_lifestyle_log":
        result = safe_call(get_lifestyle_log, client, d)

    elif name == "get_lifestyle_log_history":
        start = arguments["start_date"]
        end = arguments.get("end_date", today_str())
        result = safe_call(get_lifestyle_log_history, client, start, end)

    # ── Body & weight ─────────────────────────────────────────────────────────
    elif name == "get_weight":
        start = arguments.get("start_date", days_ago(14))
        end = arguments.get("end_date", today_str())
        result = safe_call(client.get_body_composition, start, end)

    else:
        result = {"ok": False, "error": f"Unknown tool: {name}"}

    return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
