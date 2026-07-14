"""Workout creation/scheduling/management and exercise-lookup Garmin tools."""

from datetime import date
from datetime import date as date_cls

from mcp.server.fastmcp import FastMCP

from .client import client_call, safe_call
from .workout_builders import (
    _build_strength_round,
    _build_workout_step,
    _estimate_step_duration_seconds,
    _estimate_strength_duration_seconds,
)


def register(mcp: FastMCP) -> None:
    @mcp.tool(name="garmin_create_running_workout")
    def create_running_workout(name: str, steps: list[dict], pace_sec_per_km: float = 360.0) -> dict:
        """Create a structured running workout in Garmin Connect and return its workout_id. Does NOT schedule it on a date - call garmin_schedule_workout afterwards to put it on the calendar so it syncs to the watch.

        steps: an ordered list of step dicts, each one of:
          - {"kind": "warmup"|"cooldown"|"interval"|"recovery"|"rest", "distance_km": float, ...} - a step ending after a distance
          - {"kind": "warmup"|"cooldown"|"interval"|"recovery"|"rest", "seconds": float, ...} - a step ending after a duration
          - {"kind": "warmup"|"cooldown"|"interval"|"recovery"|"rest", "calories": float, ...} - a step ending after burning N calories
          - {"kind": "repeat", "repeat_count": int, "steps": [...]} - repeats a nested list of steps N times

        Any non-repeat step can also carry an on-watch target (shown live during the step,
        alongside its distance/time/calorie countdown) via one of:
          - "pace_min_per_km" + "pace_max_per_km": seconds-per-km bounds, e.g. 330 (5:30) to 360 (6:00)
          - "hr_zone": int 1-5, referencing the athlete's predefined Garmin HR zones
          - "hr_min" + "hr_max": explicit bpm bounds
          - "cadence_min" + "cadence_max": steps-per-minute bounds
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

        try:
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
        except Exception as e:
            return {"ok": False, "error": str(e)}
        result = client_call("upload_running_workout", workout)
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

        try:
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
        except Exception as e:
            return {"ok": False, "error": str(e)}
        result = client_call("upload_workout", workout.to_dict())
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

    @mcp.tool(name="garmin_schedule_workout")
    def schedule_workout(workout_id: str, date: str) -> dict:
        """Schedule a previously-created Garmin workout onto a specific calendar date so it syncs to the watch. workout_id: from garmin_create_running_workout. date: YYYY-MM-DD."""
        return client_call("schedule_workout", workout_id, date)

    def _scheduled_workouts_for_month(year: int, month: int) -> dict:
        result = client_call("get_scheduled_workouts", year, month)
        if not result["ok"]:
            return result
        items = result["data"].get("calendarItems") or []
        workouts = [
            {
                "scheduled_item_id": item.get("id"),
                "workout_id": item.get("workoutId"),
                "title": item.get("title"),
                "sport": item.get("sportTypeKey"),
                "date": item.get("date"),
            }
            for item in items
            if item.get("itemType") == "workout"
        ]
        return {"ok": True, "data": workouts}

    @mcp.tool(name="garmin_get_scheduled_workouts")
    def get_scheduled_workouts(target_date: str = "", year: str = "", month: str = "") -> dict:
        """Get workout(s) scheduled on the Garmin calendar. Pass target_date to answer "what do I have scheduled today/tomorrow/on X?" (returns just that day's workouts). Omit target_date and optionally pass year/month to get the whole month's schedule instead (defaults to the current month). Each entry has title, sport, workout_id (for garmin_get_workout_by_id), and scheduled_item_id (for garmin_unschedule_workout). Only calendar entries that are actual workouts are included - weigh-ins and other calendar item types are filtered out."""
        if target_date:
            d = date.fromisoformat(target_date)
        else:
            d = date.today()
        y = int(year) if year else d.year
        m = int(month) if month else d.month
        result = _scheduled_workouts_for_month(y, m)
        if not result["ok"] or not target_date:
            return result
        target_str = d.isoformat()
        return {"ok": True, "data": [w for w in result["data"] if w["date"] == target_str]}

    @mcp.tool(name="garmin_list_workouts")
    def list_workouts(limit: int = 20) -> dict:
        """List workouts stored in Garmin Connect (most recently created first). limit: max results (default 20)."""
        return client_call("get_workouts", 0, limit)

    @mcp.tool(name="garmin_delete_workout")
    def delete_workout(workout_id: str) -> dict:
        """Delete a workout from Garmin Connect by its workout_id."""
        return client_call("delete_workout", workout_id)

    @mcp.tool(name="garmin_unschedule_workout")
    def unschedule_workout(workout_id: str, date: str) -> dict:
        """Remove a workout from a specific calendar date without deleting the workout template itself (it stays available to reschedule). workout_id: from garmin_create_running_workout/garmin_create_strength_workout/garmin_list_workouts. date: YYYY-MM-DD, the calendar date it's scheduled on (from garmin_get_scheduled_workouts)."""
        d = date_cls.fromisoformat(date)
        result = _scheduled_workouts_for_month(d.year, d.month)
        if not result["ok"]:
            return result
        match = next((w for w in result["data"] if str(w["workout_id"]) == workout_id and w["date"] == date), None)
        if not match:
            return {"ok": False, "error": f"No workout {workout_id} found scheduled on {date}"}
        return client_call("unschedule_workout", match["scheduled_item_id"])

    @mcp.tool(name="garmin_get_workout_by_id")
    def get_workout_by_id(workout_id: str) -> dict:
        """Fetch a workout's full raw structure exactly as Garmin stored it, including each step's real endCondition/category/exerciseName. Use this to discover the correct Garmin enums for an exercise: build the workout using Garmin Connect's own exercise picker (app or web - guaranteed valid, unlike our free-text lookup), find its workout_id with garmin_list_workouts, fetch it here, read off the category/exerciseName Garmin actually assigned to each step, then call garmin_record_exercise_enum to save that mapping for future use. workout_id: from garmin_list_workouts or the result of garmin_create_strength_workout/garmin_create_running_workout."""
        return client_call("get_workout_by_id", workout_id)

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
