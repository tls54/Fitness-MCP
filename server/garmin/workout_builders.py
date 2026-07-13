"""Internals for building Garmin workout step/round structures and estimating durations."""

from datetime import date, timedelta

import garminconnect

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
      - cadence_min / cadence_max: steps-per-minute bounds -> cadence target. workoutTargetTypeId 3
        round-trips correctly (confirmed via garmin_get_workout_by_id); not yet visually confirmed
        rendering a live cadence target on-device the way pace/HR have been.
    """
    pace_min = step.get("pace_min_per_km")
    pace_max = step.get("pace_max_per_km")
    hr_zone = step.get("hr_zone")
    hr_min = step.get("hr_min")
    hr_max = step.get("hr_max")
    cadence_min = step.get("cadence_min")
    cadence_max = step.get("cadence_max")

    groups_set = sum(
        bool(pair)
        for pair in (
            (pace_min is not None or pace_max is not None),
            (hr_zone is not None),
            (hr_min is not None or hr_max is not None),
            (cadence_min is not None or cadence_max is not None),
        )
    )
    if groups_set > 1:
        raise ValueError(
            f"Step {step!r} sets more than one target group (pace/hr_zone/hr_min+max/cadence) - "
            "only one target group is supported per step"
        )

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
        # id 3 confirmed live (round-trips correctly); Garmin's real key is "cadence", not
        # "cadence.zone" as guessed - cosmetic label fix, the id is what Garmin keys off.
        return {
            "targetType": {"workoutTargetTypeId": 3, "workoutTargetTypeKey": "cadence", "displayOrder": 3},
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
        # Confirmed live via garmin_get_workout_by_id: id 4 round-trips exactly as "calories".
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
