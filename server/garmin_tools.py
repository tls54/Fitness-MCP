"""Garmin Connect tools, ported from garmin/garmin_server.py onto FastMCP with a garmin_ prefix."""

import os
from datetime import date, timedelta

import garminconnect
from mcp.server.fastmcp import FastMCP

TOKEN_DIR = os.environ.get("GARMIN_TOKEN_DIR", os.path.expanduser("~/.garminconnect"))


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


_STEP_KIND_TO_TYPE_ID = {
    "warmup": 1,
    "cooldown": 2,
    "interval": 3,
    "recovery": 4,
    "rest": 5,
}


def _build_workout_step(step: dict, order: list[int]) -> "object":
    """Recursively build an ExecutableStep or RepeatGroup from a plain-dict step spec.

    step kinds: "warmup", "interval", "recovery", "cooldown", "rest" (each takes
    "distance_km" or "seconds" as the end condition, exactly one of the two),
    or "repeat" (takes "repeat_count" and a nested "steps" list).
    """
    from garminconnect.workout import ExecutableStep, RepeatGroup

    kind = step["kind"]
    order[0] += 1
    this_order = order[0]

    if kind == "repeat":
        child_steps = [_build_workout_step(s, order) for s in step["steps"]]
        return RepeatGroup(
            stepOrder=this_order,
            stepType={"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
            numberOfIterations=step["repeat_count"],
            workoutSteps=child_steps,
            endCondition={
                "conditionTypeId": 7,
                "conditionTypeKey": "iterations",
                "displayOrder": 7,
                "displayable": False,
            },
            endConditionValue=float(step["repeat_count"]),
        )

    if kind not in _STEP_KIND_TO_TYPE_ID:
        raise ValueError(f"Unknown step kind: {kind!r}")

    distance_km = step.get("distance_km")
    seconds = step.get("seconds")
    if (distance_km is None) == (seconds is None):
        raise ValueError(f"Step {step!r} must set exactly one of distance_km or seconds")

    if distance_km is not None:
        end_condition = {"conditionTypeId": 1, "conditionTypeKey": "distance", "displayOrder": 2, "displayable": True}
        end_condition_value = float(distance_km) * 1000.0
    else:
        end_condition = {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True}
        end_condition_value = float(seconds)

    type_id = _STEP_KIND_TO_TYPE_ID[kind]
    return ExecutableStep(
        stepOrder=this_order,
        stepType={"stepTypeId": type_id, "stepTypeKey": kind, "displayOrder": type_id},
        endCondition=end_condition,
        endConditionValue=end_condition_value,
        targetType={"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1},
    )


def _estimate_step_duration_seconds(step: dict, pace_sec_per_km: float) -> float:
    if step["kind"] == "repeat":
        return step["repeat_count"] * sum(
            _estimate_step_duration_seconds(s, pace_sec_per_km) for s in step["steps"]
        )
    if step.get("seconds") is not None:
        return float(step["seconds"])
    return float(step["distance_km"]) * pace_sec_per_km


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


def _lifestyle_log(client: garminconnect.Garmin, d: str) -> str:
    data = client.get_lifestyle_logging_data(d)
    logs = data.get("dailyLogsReport") or []
    return format_lifestyle_log(logs, d)


def _lifestyle_log_history(client: garminconnect.Garmin, start: str, end: str) -> str:
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


def register(mcp: FastMCP) -> None:
    # ── Daily health ─────────────────────────────────────────────────────────
    @mcp.tool(name="garmin_get_sleep")
    def get_sleep(date: str = "") -> dict:
        """Get detailed sleep data for a given date: sleep stages (deep, light, REM, awake), total sleep duration, sleep score, respiration, SpO2, and sleep start/end times. date: YYYY-MM-DD, defaults to today."""
        return safe_call(get_client().get_sleep_data, date or today_str())

    @mcp.tool(name="garmin_get_hrv")
    def get_hrv(date: str = "") -> dict:
        """Get Heart Rate Variability (HRV) data for a date: overnight HRV summary, 5-minute readings, baseline, and status (Balanced / Unbalanced / Low). date: YYYY-MM-DD, defaults to today."""
        return safe_call(get_client().get_hrv_data, date or today_str())

    @mcp.tool(name="garmin_get_body_battery")
    def get_body_battery(date: str = "") -> dict:
        """Get Body Battery levels for a date: charging/draining events, start/end levels, and the impact of sleep and activities. date: YYYY-MM-DD, defaults to today."""
        d = date or today_str()
        return safe_call(get_client().get_body_battery, d, d)

    @mcp.tool(name="garmin_get_stress")
    def get_stress(date: str = "") -> dict:
        """Get stress data for a date: average stress, max stress, rest stress, and time in low/medium/high/rest stress categories. date: YYYY-MM-DD, defaults to today."""
        return safe_call(get_client().get_stress_data, date or today_str())

    @mcp.tool(name="garmin_get_heart_rate")
    def get_heart_rate(date: str = "") -> dict:
        """Get resting heart rate and heart rate timeline for a date: min HR, max HR, resting HR, and timestamped readings throughout the day. date: YYYY-MM-DD, defaults to today."""
        return safe_call(get_client().get_heart_rates, date or today_str())

    @mcp.tool(name="garmin_get_spo2")
    def get_spo2(date: str = "") -> dict:
        """Get SpO2 (blood oxygen saturation) readings for a date: average, min, max, and overnight continuous readings. date: YYYY-MM-DD, defaults to today."""
        return safe_call(get_client().get_spo2_data, date or today_str())

    @mcp.tool(name="garmin_get_respiration")
    def get_respiration(date: str = "") -> dict:
        """Get breathing rate (respiration) data for a date: average, min, max breaths per minute throughout the day and overnight. date: YYYY-MM-DD, defaults to today."""
        return safe_call(get_client().get_respiration_data, date or today_str())

    @mcp.tool(name="garmin_get_steps_and_activity")
    def get_steps_and_activity(date: str = "") -> dict:
        """Get daily steps, floors climbed, distance, calories (active + resting), and intensity minutes for a date. date: YYYY-MM-DD, defaults to today."""
        d = date or today_str()
        client = get_client()
        steps = safe_call(client.get_steps_data, d)
        stats = safe_call(client.get_stats, d)
        return {"ok": True, "data": {"steps": steps.get("data"), "stats": stats.get("data")}}

    @mcp.tool(name="garmin_get_hydration")
    def get_hydration(date: str = "") -> dict:
        """Get daily hydration data: fluid intake in ml and goal for a date. date: YYYY-MM-DD, defaults to today."""
        return safe_call(get_client().get_hydration_data, date or today_str())

    @mcp.tool(name="garmin_get_daily_summary")
    def get_daily_summary(date: str = "") -> dict:
        """Get a comprehensive daily summary including steps, calories, HR, stress, Body Battery, intensity minutes, and floors for a date. Good all-in-one snapshot. date: YYYY-MM-DD, defaults to today."""
        return safe_call(get_client().get_user_summary, date or today_str())

    # ── Training & fitness ───────────────────────────────────────────────────
    @mcp.tool(name="garmin_get_training_readiness")
    def get_training_readiness(date: str = "") -> dict:
        """Get Garmin's Training Readiness score (0-100) for a date, with component scores for sleep, recovery, HRV, and training load. date: YYYY-MM-DD, defaults to today."""
        return safe_call(get_client().get_training_readiness, date or today_str())

    @mcp.tool(name="garmin_get_training_status")
    def get_training_status(date: str = "") -> dict:
        """Get Garmin's training status: status label (Maintaining/Productive/Unproductive/Detraining/Overreaching), acute/chronic load, load focus, and VO2 max trend. date: YYYY-MM-DD, defaults to today."""
        return safe_call(get_client().get_training_status, date or today_str())

    @mcp.tool(name="garmin_get_vo2max_and_fitness_metrics")
    def get_vo2max_and_fitness_metrics(date: str = "") -> dict:
        """Get VO2 max estimate and fitness age. Includes running VO2 max and cycling VO2 max if available. date: YYYY-MM-DD, defaults to today."""
        return safe_call(get_client().get_max_metrics, date or today_str())

    @mcp.tool(name="garmin_get_lactate_threshold")
    def get_lactate_threshold() -> dict:
        """Get Garmin's lactate threshold estimate: threshold heart rate, threshold pace, and the associated training zone."""
        return safe_call(get_client().get_lactate_threshold)

    @mcp.tool(name="garmin_get_race_predictions")
    def get_race_predictions() -> dict:
        """Get Garmin's predicted race finish times for 5K, 10K, half marathon, and marathon based on current fitness."""
        return safe_call(get_client().get_race_predictions)

    @mcp.tool(name="garmin_get_endurance_score")
    def get_endurance_score(start_date: str = "", end_date: str = "") -> dict:
        """Get Garmin's Endurance Score for a date range - measures aerobic fitness capacity built up over time. start_date/end_date: YYYY-MM-DD, default to 30 days ago / today."""
        start = start_date or days_ago(30)
        end = end_date or today_str()
        return safe_call(get_client().get_endurance_score, start, end)

    @mcp.tool(name="garmin_get_hill_score")
    def get_hill_score(start_date: str = "", end_date: str = "") -> dict:
        """Get Garmin's Hill Score for a date range - measures ability to handle elevation gain in runs. start_date/end_date: YYYY-MM-DD, default to 30 days ago / today."""
        start = start_date or days_ago(30)
        end = end_date or today_str()
        return safe_call(get_client().get_hill_score, start, end)

    @mcp.tool(name="garmin_get_running_tolerance")
    def get_running_tolerance(start_date: str = "", end_date: str = "", aggregation: str = "weekly") -> dict:
        """Get Garmin's running tolerance/load data over a date range (weekly aggregation by default). Shows acute load, chronic load, and injury risk signals. start_date/end_date: YYYY-MM-DD, default to 28 days ago / today. aggregation: 'weekly' or 'daily'."""
        start = start_date or days_ago(28)
        end = end_date or today_str()
        return safe_call(get_client().get_running_tolerance, start, end, aggregation)

    @mcp.tool(name="garmin_get_personal_records")
    def get_personal_records() -> dict:
        """Get personal records (PRs) for running and other activities: fastest mile, 5K, 10K, half marathon, longest run, etc."""
        return safe_call(get_client().get_personal_record)

    @mcp.tool(name="garmin_get_progress_summary")
    def get_progress_summary(start_date: str = "", end_date: str = "", metric: str = "distance") -> dict:
        """Get training progress summary between two dates, grouped by activity type. Shows distance, time, and effort trends. start_date/end_date: YYYY-MM-DD, default to 28 days ago / today. metric: 'distance', 'duration', or 'calories'."""
        start = start_date or days_ago(28)
        end = end_date or today_str()
        return safe_call(get_client().get_progress_summary_between_dates, start, end, metric)

    # ── Activities ───────────────────────────────────────────────────────────
    @mcp.tool(name="garmin_get_activities")
    def get_activities(start_date: str = "", end_date: str = "", activity_type: str = "") -> dict:
        """Get a list of recent Garmin activities with summary stats: type, date, distance, duration, avg HR, calories, Training Effect, aerobic/anaerobic load. start_date/end_date: YYYY-MM-DD, default to 14 days ago / today. activity_type: e.g. 'running', 'cycling', 'hiking' (optional)."""
        start = start_date or days_ago(14)
        end = end_date or today_str()
        return safe_call(get_client().get_activities_by_date, start, end, activity_type or None)

    @mcp.tool(name="garmin_get_activity_detail")
    def get_activity_detail(activity_id: str) -> dict:
        """Get full detail for a single Garmin activity by ID: splits, HR zones, Training Effect, aerobic/anaerobic load, pace, elevation, cadence. activity_id: Garmin activity ID (from garmin_get_activities)."""
        return safe_call(get_client().get_activity, activity_id)

    @mcp.tool(name="garmin_get_activity_splits")
    def get_activity_splits(activity_id: str) -> dict:
        """Get per-kilometre or per-mile splits for a Garmin activity: pace, HR, elevation for each split. activity_id: Garmin activity ID (from garmin_get_activities)."""
        return safe_call(get_client().get_activity_splits, activity_id)

    @mcp.tool(name="garmin_get_activity_hr_zones")
    def get_activity_hr_zones(activity_id: str) -> dict:
        """Get time spent in each HR zone for a Garmin activity. activity_id: Garmin activity ID (from garmin_get_activities)."""
        return safe_call(get_client().get_activity_hr_in_timezones, activity_id)

    @mcp.tool(name="garmin_get_activity_streams")
    def get_activity_streams(activity_id: str, max_points: int = 2000) -> dict:
        """Get time-series chart data for a Garmin activity: cadence, HR, speed, power, elevation, and other metrics sampled throughout the activity. Up to 2000 data points. Use this for detailed analysis of effort, cadence consistency, HR drift, or power curves. activity_id: Garmin activity ID. max_points: max chart points to return (default/max 2000)."""
        return safe_call(get_client().get_activity_details, activity_id, maxchart=max_points)

    @mcp.tool(name="garmin_get_activity_power_zones")
    def get_activity_power_zones(activity_id: str) -> dict:
        """Get time spent in each power zone for a Garmin activity. Only meaningful for activities with actual power data (e.g. BikeErg with ERG Logbook connected). activity_id: Garmin activity ID."""
        return safe_call(get_client().get_activity_power_in_timezones, activity_id)

    @mcp.tool(name="garmin_get_last_activity")
    def get_last_activity() -> dict:
        """Get the most recent Garmin activity with full summary stats."""
        return safe_call(get_client().get_last_activity)

    # ── Trends / history ─────────────────────────────────────────────────────
    @mcp.tool(name="garmin_get_sleep_history")
    def get_sleep_history(days: int = 14) -> dict:
        """Get sleep scores and stage breakdown for the past N days to identify trends. days: number of past days (default 14, max 28)."""
        client = get_client()
        n = min(days, 28)
        history = []
        for i in range(n):
            day = days_ago(i)
            r = safe_call(client.get_sleep_data, day)
            if r["ok"] and r["data"]:
                history.append({"date": day, "data": r["data"]})
        return {"ok": True, "data": history}

    @mcp.tool(name="garmin_get_hrv_history")
    def get_hrv_history(days: int = 14) -> dict:
        """Get overnight HRV values for the past N days to track recovery trends. days: number of past days (default 14, max 28)."""
        client = get_client()
        n = min(days, 28)
        history = []
        for i in range(n):
            day = days_ago(i)
            r = safe_call(client.get_hrv_data, day)
            if r["ok"] and r["data"]:
                history.append({"date": day, "data": r["data"]})
        return {"ok": True, "data": history}

    @mcp.tool(name="garmin_get_body_battery_history")
    def get_body_battery_history(days: int = 14) -> dict:
        """Get end-of-day Body Battery levels for the past N days to track energy trends. days: number of past days (default 14)."""
        client = get_client()
        history = []
        for i in range(days):
            day = days_ago(i)
            r = safe_call(client.get_body_battery, day, day)
            if r["ok"] and r["data"]:
                history.append({"date": day, "data": r["data"]})
        return {"ok": True, "data": history}

    @mcp.tool(name="garmin_get_weekly_summary")
    def get_weekly_summary(end_date: str = "") -> dict:
        """Get a weekly health and activity summary: total steps, active calories, intensity minutes, stress average, and sleep averages for the past 7 days. end_date: YYYY-MM-DD, defaults to today."""
        return safe_call(get_client().get_weekly_stress, end_date or today_str())

    # ── Lifestyle / habits ───────────────────────────────────────────────────
    @mcp.tool(name="garmin_get_lifestyle_log")
    def get_lifestyle_log(date: str = "") -> dict:
        """Get the lifestyle/habit log for a date: which manually-tracked habits (e.g. healthy meals, morning caffeine, moderate exercise, ankle exercises) were logged that day and whether each was completed. date: YYYY-MM-DD, defaults to today."""
        return safe_call(_lifestyle_log, get_client(), date or today_str())

    @mcp.tool(name="garmin_get_lifestyle_log_history")
    def get_lifestyle_log_history(start_date: str, end_date: str = "") -> dict:
        """Get lifestyle/habit log compliance across a date range, as a day-by-day table showing whether each tracked habit was done, missed, or not logged. start_date: YYYY-MM-DD, required. end_date: YYYY-MM-DD, defaults to today."""
        return safe_call(_lifestyle_log_history, get_client(), start_date, end_date or today_str())

    # ── Body & weight ────────────────────────────────────────────────────────
    @mcp.tool(name="garmin_get_weight")
    def get_weight(start_date: str = "", end_date: str = "") -> dict:
        """Get body weight and composition data for a date range. Returns weight, BMI, body fat % if measured. start_date/end_date: YYYY-MM-DD, default to 14 days ago / today."""
        start = start_date or days_ago(14)
        end = end_date or today_str()
        return safe_call(get_client().get_body_composition, start, end)

    # ── Workouts (write) ─────────────────────────────────────────────────────
    @mcp.tool(name="garmin_create_running_workout")
    def create_running_workout(name: str, steps: list[dict], pace_sec_per_km: float = 360.0) -> dict:
        """Create a structured running workout in Garmin Connect and return its workout_id. Does NOT schedule it on a date - call garmin_schedule_workout afterwards to put it on the calendar so it syncs to the watch.

        steps: an ordered list of step dicts, each one of:
          - {"kind": "warmup"|"cooldown"|"interval"|"recovery"|"rest", "distance_km": float} - a step ending after a distance
          - {"kind": "warmup"|"cooldown"|"interval"|"recovery"|"rest", "seconds": float} - a step ending after a duration
          - {"kind": "repeat", "repeat_count": int, "steps": [...]} - repeats a nested list of steps N times

        Example for "4km, then 6x(20s stride + 60s recovery), then 1km":
        [
          {"kind": "interval", "distance_km": 4},
          {"kind": "repeat", "repeat_count": 6, "steps": [
            {"kind": "interval", "seconds": 20},
            {"kind": "recovery", "seconds": 60}
          ]},
          {"kind": "interval", "distance_km": 1}
        ]

        pace_sec_per_km: rough pace estimate (seconds per km) used only to compute the
        workout's estimated duration metadata; defaults to 6:00/km. Does not affect pacing.
        """
        from garminconnect.workout import RunningWorkout

        order = [0]
        workout_steps = [_build_workout_step(s, order) for s in steps]
        segment = {
            "segmentOrder": 1,
            "sportType": {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1},
            "workoutSteps": workout_steps,
        }
        estimated_duration = int(
            sum(_estimate_step_duration_seconds(s, pace_sec_per_km) for s in steps)
        )
        workout = RunningWorkout(
            workoutName=name,
            estimatedDurationInSecs=estimated_duration,
            workoutSegments=[segment],
        )
        result = safe_call(get_client().upload_running_workout, workout)
        if result["ok"] and isinstance(result["data"], dict):
            result["data"]["workout_id"] = result["data"].get("workoutId")
        return result

    @mcp.tool(name="garmin_schedule_workout")
    def schedule_workout(workout_id: str, date: str) -> dict:
        """Schedule a previously-created Garmin workout onto a specific calendar date so it syncs to the watch. workout_id: from garmin_create_running_workout. date: YYYY-MM-DD."""
        return safe_call(get_client().schedule_workout, workout_id, date)

    @mcp.tool(name="garmin_list_workouts")
    def list_workouts(limit: int = 20) -> dict:
        """List workouts stored in Garmin Connect (most recently created first). limit: max results (default 20)."""
        return safe_call(get_client().get_workouts, 0, limit)

    @mcp.tool(name="garmin_delete_workout")
    def delete_workout(workout_id: str) -> dict:
        """Delete a workout from Garmin Connect by its workout_id."""
        return safe_call(get_client().delete_workout, workout_id)
