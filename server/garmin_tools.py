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


def _build_step_target(step: dict) -> dict:
    """Build the targetType (+ target value fields) for a step from optional pace/HR keys.

    Supported keys (at most one group):
      - pace_min_per_km / pace_max_per_km: seconds-per-km bounds (slower/faster) -> pace zone target.
      - hr_zone: int 1-5 -> heart rate zone target.
      - hr_min / hr_max: bpm bounds -> heart rate target.
      - cadence_min / cadence_max: steps-per-minute bounds -> cadence target. UNVERIFIED -
        workoutTargetTypeId 3 is a guess by analogy (library's TargetType.CADENCE=3), not yet
        confirmed live the way pace/distance/reps were. Test before relying on it.
    """
    pace_min = step.get("pace_min_per_km")
    pace_max = step.get("pace_max_per_km")
    hr_zone = step.get("hr_zone")
    hr_min = step.get("hr_min")
    hr_max = step.get("hr_max")
    cadence_min = step.get("cadence_min")
    cadence_max = step.get("cadence_max")

    if pace_min is not None or pace_max is not None:
        if pace_min is None or pace_max is None:
            raise ValueError("pace_min_per_km and pace_max_per_km must be set together")
        # pace_min_per_km is the faster (smaller sec/km) bound, pace_max_per_km the slower one.
        # Garmin targets are in speed (m/s), where higher = faster, so they invert vs. pace:
        # targetValueOne = min speed (from the slower pace bound), targetValueTwo = max speed (from the faster one).
        #
        # CORRECTED: workoutTargetTypeId 5 ("speed.zone") is NOT the real pace target - it's
        # what the garminconnect library's TargetType constants claim, but Garmin's own app
        # displayed it as a generic speed target, not pace. Confirmed correct value (id 6,
        # "pace.zone") by reading back a workout via garmin_get_workout_by_id after manually
        # fixing the target type for it in Garmin Connect's own UI.
        return {
            "targetType": {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6},
            "targetValueOne": 1000.0 / float(pace_max),
            "targetValueTwo": 1000.0 / float(pace_min),
        }

    if hr_zone is not None:
        return {
            "targetType": {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4},
            "zoneNumber": int(hr_zone),
        }

    if hr_min is not None or hr_max is not None:
        if hr_min is None or hr_max is None:
            raise ValueError("hr_min and hr_max must be set together")
        return {
            "targetType": {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4},
            "targetValueOne": float(hr_min),
            "targetValueTwo": float(hr_max),
        }

    if cadence_min is not None or cadence_max is not None:
        if cadence_min is None or cadence_max is None:
            raise ValueError("cadence_min and cadence_max must be set together")
        return {
            "targetType": {"workoutTargetTypeId": 3, "workoutTargetTypeKey": "cadence.zone", "displayOrder": 3},
            "targetValueOne": float(cadence_min),
            "targetValueTwo": float(cadence_max),
        }

    return {"targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}}


def _build_workout_step(step: dict, order: list[int]) -> "object":
    """Recursively build an ExecutableStep or RepeatGroup from a plain-dict step spec.

    step kinds: "warmup", "interval", "recovery", "cooldown", "rest" (each takes
    "distance_km" or "seconds" as the end condition, exactly one of the two, plus
    optional pace/HR target keys - see _build_step_target), or "repeat" (takes
    "repeat_count" and a nested "steps" list).
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
    calories = step.get("calories")
    if sum(v is not None for v in (distance_km, seconds, calories)) != 1:
        raise ValueError(f"Step {step!r} must set exactly one of distance_km, seconds, or calories")

    if distance_km is not None:
        # Garmin's own schema uses conditionTypeId 3 for distance; 1 is "lap.button" (confirmed
        # empirically - Garmin's upload response echoed conditionTypeId=1 back as "lap.button").
        end_condition = {"conditionTypeId": 3, "conditionTypeKey": "distance", "displayOrder": 2, "displayable": True}
        end_condition_value = float(distance_km) * 1000.0
    elif seconds is not None:
        end_condition = {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True}
        end_condition_value = float(seconds)
    else:
        # UNVERIFIED - id 4 is a guess by analogy with the library's ConditionType.CALORIES=4,
        # the same source that was wrong for distance/lap.button. Test before relying on it.
        end_condition = {"conditionTypeId": 4, "conditionTypeKey": "calories", "displayOrder": 2, "displayable": True}
        end_condition_value = float(calories)

    type_id = _STEP_KIND_TO_TYPE_ID[kind]
    target = _build_step_target(step)
    return ExecutableStep(
        stepOrder=this_order,
        stepType={"stepTypeId": type_id, "stepTypeKey": kind, "displayOrder": type_id},
        endCondition=end_condition,
        endConditionValue=end_condition_value,
        **target,
    )


# CORRECTED: id 9 ("fixed.repetition") is NOT the real reps condition - it round-tripped
# fine through the upload API (accepted, echoed back unchanged), which is why it was
# originally marked "confirmed", but the API accepting/echoing a value only proves the
# API stores what you send - it doesn't prove the watch/app renders it as a rep target.
# id 9 steps showed no target at all in Garmin Connect's app. The real value, confirmed
# by inspecting a workout built via Garmin's own exercise picker (garmin_get_workout_by_id),
# is id 10, conditionTypeKey "reps".
_STRENGTH_REPS_CONDITION_TYPE_ID = 10


def _build_strength_round(exercise: dict, order: list[int], fallbacks: list[dict]) -> "object":
    """Build a RepeatGroup of (exercise step, rest step) x sets for one strength exercise.

    exercise: {"exercise_name": str, "category": str (optional, disambiguates when the
               same name exists in multiple Garmin categories), "sets": int,
               "rest_seconds": float, and exactly one of "reps": int or "seconds": float}

    Looks up exercise_name (+ optional category) in exercises.db (see exercise_db.py).
    If no match is found, or the match's enum_confidence is 'todo' (no trustworthy
    category/exerciseName enum), falls back to a generic "Total Body" category step
    with the intended exercise name and target written into the step's free-text
    "description" field - the watch will show that text but won't auto-count reps for
    it, so the athlete has to manually advance with the lap button on that step. Any
    such fallback is appended to `fallbacks` so the caller can surface it clearly.
    """
    from garminconnect.workout import ExecutableStep, RepeatGroup

    import exercise_db

    name = exercise["exercise_name"]
    category_hint = exercise.get("category")
    match = exercise_db.get_garmin_enums(name, category_hint)

    reps = exercise.get("reps")
    seconds = exercise.get("seconds")
    if (reps is None) == (seconds is None):
        raise ValueError(f"Exercise {exercise!r} must set exactly one of reps or seconds")

    sets = exercise["sets"]
    rest_seconds = exercise["rest_seconds"]
    target_desc = f"{reps} reps" if reps is not None else f"{seconds}s"

    weight_kg = exercise.get("weight_kg")
    # Confirmed live via garmin_get_workout_by_id on a workout hand-built with Garmin's own
    # weight picker: weightValue is a plain float in kilograms, weightUnit is this exact dict.
    weight_kwargs = (
        {"weightValue": float(weight_kg), "weightUnit": {"unitId": 8, "unitKey": "kilogram", "factor": 1000.0}}
        if weight_kg is not None
        else {}
    )
    if weight_kg is not None:
        target_desc += f" @ {weight_kg}kg"

    order[0] += 1
    exercise_step_order = order[0]
    if reps is not None:
        end_condition = {
            "conditionTypeId": _STRENGTH_REPS_CONDITION_TYPE_ID,
            "conditionTypeKey": "reps",
            "displayOrder": 2,
            "displayable": True,
        }
        end_condition_value = float(reps)
    else:
        end_condition = {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True}
        end_condition_value = float(seconds)

    if match is not None and match["enum_confidence"] != "todo":
        exercise_step = ExecutableStep(
            stepOrder=exercise_step_order,
            stepType={"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
            endCondition=end_condition,
            endConditionValue=end_condition_value,
            targetType={"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1},
            category=match["garmin_category_enum"],
            exerciseName=match["garmin_name_enum"],
            **weight_kwargs,
        )
    else:
        fallbacks.append(
            {
                "exercise_name": name,
                "reason": "no confident enum match in exercises.db"
                if match is None
                else f"only a {match['enum_confidence']} match (category={match['category']!r})",
                "note": "watch will display the name/target as text but won't auto-count reps; "
                "advance this step manually with the lap button",
            }
        )
        exercise_step = ExecutableStep(
            stepOrder=exercise_step_order,
            stepType={"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
            endCondition=end_condition,
            endConditionValue=end_condition_value,
            targetType={"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1},
            description=f"{name} - {target_desc}",
            **weight_kwargs,
        )

    order[0] += 1
    rest_step_order = order[0]
    rest_step = ExecutableStep(
        stepOrder=rest_step_order,
        stepType={"stepTypeId": 5, "stepTypeKey": "rest", "displayOrder": 5},
        endCondition={"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True},
        endConditionValue=float(rest_seconds),
        targetType={"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1},
    )

    order[0] += 1
    round_order = order[0]
    return RepeatGroup(
        stepOrder=round_order,
        stepType={"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
        numberOfIterations=sets,
        workoutSteps=[exercise_step, rest_step],
        endCondition={"conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7, "displayable": False},
        endConditionValue=float(sets),
    )


def _estimate_strength_duration_seconds(exercise: dict) -> float:
    work_seconds = exercise["seconds"] if exercise.get("seconds") is not None else exercise.get("reps", 0) * 3.0
    return exercise["sets"] * (work_seconds + exercise["rest_seconds"])


def _estimate_step_duration_seconds(step: dict, pace_sec_per_km: float) -> float:
    if step["kind"] == "repeat":
        return step["repeat_count"] * sum(
            _estimate_step_duration_seconds(s, pace_sec_per_km) for s in step["steps"]
        )
    if step.get("seconds") is not None:
        return float(step["seconds"])
    if step.get("distance_km") is not None:
        return float(step["distance_km"]) * pace_sec_per_km
    # calorie-based steps: no principled way to estimate duration from calories alone
    # without pace/HR/weight data, so just contribute a rough placeholder to the total.
    return 300.0


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
          - {"kind": "warmup"|"cooldown"|"interval"|"recovery"|"rest", "distance_km": float, ...} - a step ending after a distance
          - {"kind": "warmup"|"cooldown"|"interval"|"recovery"|"rest", "seconds": float, ...} - a step ending after a duration
          - {"kind": "warmup"|"cooldown"|"interval"|"recovery"|"rest", "calories": float, ...} - a step ending after burning N calories (UNVERIFIED - untested on a live device, see code comments)
          - {"kind": "repeat", "repeat_count": int, "steps": [...]} - repeats a nested list of steps N times

        Any non-repeat step can also carry an on-watch target (shown live during the step,
        alongside its distance/time/calorie countdown) via one of:
          - "pace_min_per_km" + "pace_max_per_km": seconds-per-km bounds, e.g. 330 (5:30) to 360 (6:00)
          - "hr_zone": int 1-5, referencing the athlete's predefined Garmin HR zones
          - "hr_min" + "hr_max": explicit bpm bounds
          - "cadence_min" + "cadence_max": steps-per-minute bounds (UNVERIFIED - untested on a live device)
        Omit all of these for an unconstrained "just run/rest" step.

        Example for "4km easy, then 6x(20s stride + 60s easy jog recovery), then 1km easy cooldown",
        assuming the athlete's easy pace is roughly 5:30-6:00/km:
        [
          {"kind": "warmup", "distance_km": 4, "pace_min_per_km": 330, "pace_max_per_km": 360},
          {"kind": "repeat", "repeat_count": 6, "steps": [
            {"kind": "interval", "seconds": 20},
            {"kind": "recovery", "seconds": 60, "pace_min_per_km": 330, "pace_max_per_km": 360}
          ]},
          {"kind": "cooldown", "distance_km": 1, "pace_min_per_km": 330, "pace_max_per_km": 360}
        ]
        Strides themselves are intentionally left with no pace target (effort naturally builds to
        near-max over the 20s) - only the easy running/recovery sections should carry the easy-pace target.

        pace_sec_per_km: rough overall pace estimate (seconds per km) used only to compute the
        workout's estimated duration metadata; defaults to 6:00/km. Does not affect on-watch targets.
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

    @mcp.tool(name="garmin_create_strength_workout")
    def create_strength_workout(name: str, exercises: list[dict]) -> dict:
        """Create a structured strength workout in Garmin Connect and return its workout_id. Does NOT schedule it - call garmin_schedule_workout afterwards to put it on the calendar so it syncs to the watch.

        exercise_name is looked up against exercises.db, a ~1500-exercise database built from
        Garmin's own exercise catalog (see build_exercise_db.py/exercise_db.py). Use
        garmin_find_exercise first to check what a name resolves to and its confidence
        ('confirmed': round-trip tested against a live Garmin upload; 'guessed': same naming
        pattern as a confirmed exercise but not tested; 'todo': no trustworthy Garmin enum
        found). If a name has no confident match (or isn't found at all), this tool
        automatically falls back to a generic step with the exercise name and target written
        as free text (returned in the response's "fallbacks" list) - the watch will show that
        text but can't auto-count reps for it, so the athlete advances that step manually with
        the lap button. This never raises for an unmatched name; check the response's
        "fallbacks" list to see which steps, if any, need manual lap-button advancing.

        exercises: an ordered list of exercise dicts, each:
          {"exercise_name": str (free text, e.g. "cable fly", "goblet squat"),
           "category": str (optional - disambiguates when the same name exists in multiple
                       Garmin categories, e.g. "Squat" vs "Banded Exercises"),
           "sets": int,
           "rest_seconds": float,
           "reps": int,   # OR "seconds": float instead of "reps", for timed holds like planks
           "weight_kg": float}  # optional - shows a fixed weight target for the exercise

        Each exercise becomes one repeating round of (exercise, rest) x sets - e.g. sets=3,
        reps=12, rest_seconds=60 becomes 3 rounds of "12 reps" then "rest 60s".

        Known limitation: a single exercise entry uses the same reps/seconds for every set.
        Varying reps or weight across sets of the same exercise (e.g. 12/10/8) is not supported -
        this will raise an error rather than silently build something wrong. If you need that,
        list the exercise multiple times with sets=1 each instead, though it won't render as
        cleanly on the watch as a proper repeat round.

        Example for "3 sets of 12 squats, 60s rest; 3 sets of 30s plank, 45s rest":
        [
          {"exercise_name": "squat", "sets": 3, "reps": 12, "rest_seconds": 60},
          {"exercise_name": "plank", "sets": 3, "seconds": 30, "rest_seconds": 45}
        ]
        """
        from garminconnect.workout import FitnessEquipmentWorkout

        for exercise in exercises:
            if "sets" not in exercise or "rest_seconds" not in exercise:
                raise ValueError(f"Exercise {exercise!r} must set 'sets' and 'rest_seconds'")

        # sportTypeId 5 / "strength_training" - confirmed live: garminconnect's
        # FitnessEquipmentWorkout class defaults to {6, "fitness_equipment"}, which Garmin's
        # own backend actually echoes back as "cardio_training", not a strength workout at
        # all (same class of bug as the earlier distance/lap.button mismatch). The correct
        # sportType was confirmed by inspecting a workout hand-built via Garmin Connect's own
        # UI with garmin_list_workouts, which showed {5, "strength_training"}.
        STRENGTH_SPORT_TYPE = {"sportTypeId": 5, "sportTypeKey": "strength_training", "displayOrder": 5}

        order = [0]
        fallbacks: list[dict] = []
        workout_steps = [_build_strength_round(e, order, fallbacks) for e in exercises]
        segment = {
            "segmentOrder": 1,
            "sportType": STRENGTH_SPORT_TYPE,
            "workoutSteps": workout_steps,
        }
        estimated_duration = int(sum(_estimate_strength_duration_seconds(e) for e in exercises))
        workout = FitnessEquipmentWorkout(
            workoutName=name,
            sportType=STRENGTH_SPORT_TYPE,
            estimatedDurationInSecs=estimated_duration,
            workoutSegments=[segment],
        )
        result = safe_call(get_client().upload_workout, workout.to_dict())
        if result["ok"] and isinstance(result["data"], dict):
            result["data"]["workout_id"] = result["data"].get("workoutId")
        result["fallbacks"] = fallbacks
        return result

    @mcp.tool(name="garmin_find_exercise")
    def find_exercise(query: str = "", category: str = "", equipment: str = "", muscle: str = "") -> dict:
        """Look up exercises before building a strength workout, to check what a name resolves to and its Garmin-enum confidence. Provide at least one of query/category/(equipment+muscle).

        query: free-text fuzzy search, e.g. "cable fly" or "goblet squat" (fuzzy_search).
        category: exact category name to browse, e.g. "Plyo", "Calf Raise" (browse_category).
        equipment: comma-separated equipment tags to filter by, e.g. "band" (filter_by).
        muscle: comma-separated target muscles to filter by, e.g. "CALVES,ABDUCTORS" (filter_by).

        Each result includes enum_confidence: 'confirmed' (round-trip tested live), 'guessed'
        (same pattern as a confirmed exercise, untested), or 'todo' (no trustworthy enum -
        garmin_create_strength_workout will use the free-text Notes fallback for these).
        """
        import exercise_db

        if query:
            return safe_call(exercise_db.fuzzy_search, query)
        if category:
            return safe_call(exercise_db.browse_category, category)
        if equipment or muscle:
            return safe_call(
                exercise_db.filter_by,
                equipment=[e.strip() for e in equipment.split(",") if e.strip()] or None,
                muscles=[m.strip() for m in muscle.split(",") if m.strip()] or None,
            )
        return {"ok": False, "error": "Provide at least one of query, category, or equipment/muscle"}

    @mcp.tool(name="garmin_get_activity_exercise_sets")
    def get_activity_exercise_sets(activity_id: str) -> dict:
        """Get per-set detail (reps, weight, rest, exercise category) for a completed Garmin strength activity, where the watch/app populated it. activity_id: Garmin activity ID (from garmin_get_activities)."""
        return safe_call(get_client().get_activity_exercise_sets, activity_id)

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

    @mcp.tool(name="garmin_get_workout_by_id")
    def get_workout_by_id(workout_id: str) -> dict:
        """Fetch a workout's full raw structure exactly as Garmin stored it, including each step's real endCondition/category/exerciseName. Use this to discover the correct Garmin enums for an exercise: build the workout using Garmin Connect's own exercise picker (app or web - guaranteed valid, unlike our free-text lookup), find its workout_id with garmin_list_workouts, fetch it here, read off the category/exerciseName Garmin actually assigned to each step, then call garmin_record_exercise_enum to save that mapping for future use. workout_id: from garmin_list_workouts or the result of garmin_create_strength_workout/garmin_create_running_workout."""
        return safe_call(get_client().get_workout_by_id, workout_id)

    @mcp.tool(name="garmin_record_exercise_enum")
    def record_exercise_enum(
        exercise_name: str, garmin_category_enum: str, garmin_name_enum: str, category: str = ""
    ) -> dict:
        """Record a confirmed Garmin category/exerciseName enum mapping for a free-text exercise name, so future garmin_create_strength_workout calls use the real enum instead of the free-text Notes fallback.

        Use this after reading back a workout with garmin_get_workout_by_id: if a step you
        built via Garmin's own exercise picker shows e.g. category="FLYE", exerciseName="CABLE_CROSSOVER"
        for what you think of as "cable fly", call:
          garmin_record_exercise_enum(exercise_name="cable fly", garmin_category_enum="FLYE", garmin_name_enum="CABLE_CROSSOVER")

        exercise_name: the free-text name you'll use in garmin_create_strength_workout going forward.
        category: optional - only needed if exercise_name is ambiguous across multiple Garmin
                  categories (matches the "category" field you'd pass to garmin_create_strength_workout).
        This persists to a small store separate from the bundled exercise database, so it
        survives redeploys without needing exercises.db itself to be rebuilt.
        """
        import exercise_db

        return safe_call(
            exercise_db.save_confirmed_enum, exercise_name, garmin_category_enum, garmin_name_enum, category or None
        )

    @mcp.tool(name="garmin_list_confirmed_exercise_enums")
    def list_confirmed_exercise_enums() -> dict:
        """List all operator-confirmed exercise_name -> Garmin enum mappings recorded so far via garmin_record_exercise_enum."""
        import exercise_db

        return safe_call(exercise_db.list_confirmed_enums)
