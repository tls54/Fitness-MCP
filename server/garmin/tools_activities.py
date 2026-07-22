"""Activity list/detail/streams Garmin tools."""

from mcp.server.fastmcp import FastMCP

from .client import client_call, convert_speeds_to_pace, days_ago, speed_to_pace_str, today_str


def register(mcp: FastMCP) -> None:
    @mcp.tool(name="garmin_get_activities")
    def get_activities(start_date: str = "", end_date: str = "", activity_type: str = "") -> dict:
        """Get a list of recent Garmin activities with summary stats: type, date, distance, duration, avg HR, calories, Training Effect, aerobic/anaerobic load, pace (M:SS per km). start_date/end_date: YYYY-MM-DD, default to 14 days ago / today. activity_type: e.g. 'running', 'cycling', 'hiking' (optional)."""
        start = start_date or days_ago(14)
        end = end_date or today_str()
        result = client_call("get_activities_by_date", start, end, activity_type or None)
        if result["ok"]:
            result["data"] = convert_speeds_to_pace(result["data"])
        return result

    @mcp.tool(name="garmin_get_activity_detail")
    def get_activity_detail(activity_id: str) -> dict:
        """Get full detail for a single Garmin activity by ID: splits, HR zones, Training Effect, aerobic/anaerobic load, pace (M:SS per km), elevation, cadence. activity_id: Garmin activity ID (from garmin_get_activities)."""
        result = client_call("get_activity", activity_id)
        if result["ok"]:
            result["data"] = convert_speeds_to_pace(result["data"])
        return result

    @mcp.tool(name="garmin_get_activity_splits")
    def get_activity_splits(activity_id: str) -> dict:
        """Get per-kilometre or per-mile splits for a Garmin activity: pace (M:SS per km), HR, elevation for each split. activity_id: Garmin activity ID (from garmin_get_activities)."""
        result = client_call("get_activity_splits", activity_id)
        if result["ok"]:
            result["data"] = convert_speeds_to_pace(result["data"])
        return result

    @mcp.tool(name="garmin_get_activity_hr_zones")
    def get_activity_hr_zones(activity_id: str) -> dict:
        """Get time spent in each HR zone for a Garmin activity. activity_id: Garmin activity ID (from garmin_get_activities)."""
        return client_call("get_activity_hr_in_timezones", activity_id)

    _STREAM_METRICS = {
        "directHeartRate": "heart_rate",
        "directSpeed": "speed_mps",
        "directElevation": "elevation_m",
        "directRunCadence": "run_cadence",
        "directPower": "power",
        "sumDuration": "elapsed_sec",
    }

    @mcp.tool(name="garmin_get_activity_streams")
    def get_activity_streams(activity_id: str, max_points: int = 200) -> dict:
        """Get downsampled time-series chart data for a Garmin activity: heart rate, pace (M:SS per km), elevation, cadence, power, sampled at even intervals throughout the activity. Use this for plotting HR/pace traces or checking effort trends. activity_id: Garmin activity ID. max_points: max points to return after downsampling (default 200, max 2000 - the underlying Garmin data is usually 1 point/second, so raising this rarely adds real detail and can produce very large responses)."""
        max_points = min(max_points, 2000)
        result = client_call("get_activity_details", activity_id, maxchart=max_points)
        if not result["ok"]:
            return result

        raw = result["data"] or {}
        descriptors = raw.get("metricDescriptors") or []
        index_by_key = {d["key"]: d["metricsIndex"] for d in descriptors if d["key"] in _STREAM_METRICS}
        points = raw.get("activityDetailMetrics") or []

        step = max(1, len(points) // max_points)
        series = []
        for p in points[::step]:
            values = p.get("metrics") or []
            point = {
                label: values[idx]
                for key, idx in index_by_key.items()
                for label in [_STREAM_METRICS[key]]
                if idx < len(values)
            }
            if "speed_mps" in point:
                point["pace_min_per_km"] = speed_to_pace_str(point.pop("speed_mps"))
            series.append(point)
        return {"ok": True, "data": {"num_points": len(series), "points": series}}

    @mcp.tool(name="garmin_get_activity_power_zones")
    def get_activity_power_zones(activity_id: str) -> dict:
        """Get time spent in each power zone for a Garmin activity. Only meaningful for activities with actual power data (e.g. BikeErg with ERG Logbook connected). activity_id: Garmin activity ID."""
        return client_call("get_activity_power_in_timezones", activity_id)

    @mcp.tool(name="garmin_get_last_activity")
    def get_last_activity() -> dict:
        """Get the most recent Garmin activity with full summary stats, including pace (M:SS per km)."""
        result = client_call("get_last_activity")
        if result["ok"]:
            result["data"] = convert_speeds_to_pace(result["data"])
        return result

    @mcp.tool(name="garmin_get_activity_exercise_sets")
    def get_activity_exercise_sets(activity_id: str) -> dict:
        """Get per-set detail (reps, weight, rest, exercise category) for a completed Garmin strength activity, where the watch/app populated it. activity_id: Garmin activity ID (from garmin_get_activities)."""
        return client_call("get_activity_exercise_sets", activity_id)
