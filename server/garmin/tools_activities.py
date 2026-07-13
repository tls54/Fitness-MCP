"""Activity list/detail/streams Garmin tools."""

from mcp.server.fastmcp import FastMCP

from .client import client_call, days_ago, today_str


def register(mcp: FastMCP) -> None:
    @mcp.tool(name="garmin_get_activities")
    def get_activities(start_date: str = "", end_date: str = "", activity_type: str = "") -> dict:
        """Get a list of recent Garmin activities with summary stats: type, date, distance, duration, avg HR, calories, Training Effect, aerobic/anaerobic load. start_date/end_date: YYYY-MM-DD, default to 14 days ago / today. activity_type: e.g. 'running', 'cycling', 'hiking' (optional)."""
        start = start_date or days_ago(14)
        end = end_date or today_str()
        return client_call("get_activities_by_date", start, end, activity_type or None)

    @mcp.tool(name="garmin_get_activity_detail")
    def get_activity_detail(activity_id: str) -> dict:
        """Get full detail for a single Garmin activity by ID: splits, HR zones, Training Effect, aerobic/anaerobic load, pace, elevation, cadence. activity_id: Garmin activity ID (from garmin_get_activities)."""
        return client_call("get_activity", activity_id)

    @mcp.tool(name="garmin_get_activity_splits")
    def get_activity_splits(activity_id: str) -> dict:
        """Get per-kilometre or per-mile splits for a Garmin activity: pace, HR, elevation for each split. activity_id: Garmin activity ID (from garmin_get_activities)."""
        return client_call("get_activity_splits", activity_id)

    @mcp.tool(name="garmin_get_activity_hr_zones")
    def get_activity_hr_zones(activity_id: str) -> dict:
        """Get time spent in each HR zone for a Garmin activity. activity_id: Garmin activity ID (from garmin_get_activities)."""
        return client_call("get_activity_hr_in_timezones", activity_id)

    @mcp.tool(name="garmin_get_activity_streams")
    def get_activity_streams(activity_id: str, max_points: int = 2000) -> dict:
        """Get time-series chart data for a Garmin activity: cadence, HR, speed, power, elevation, and other metrics sampled throughout the activity. Up to 2000 data points. Use this for detailed analysis of effort, cadence consistency, HR drift, or power curves. activity_id: Garmin activity ID. max_points: max chart points to return (default/max 2000)."""
        return client_call("get_activity_details", activity_id, maxchart=max_points)

    @mcp.tool(name="garmin_get_activity_power_zones")
    def get_activity_power_zones(activity_id: str) -> dict:
        """Get time spent in each power zone for a Garmin activity. Only meaningful for activities with actual power data (e.g. BikeErg with ERG Logbook connected). activity_id: Garmin activity ID."""
        return client_call("get_activity_power_in_timezones", activity_id)

    @mcp.tool(name="garmin_get_last_activity")
    def get_last_activity() -> dict:
        """Get the most recent Garmin activity with full summary stats."""
        return client_call("get_last_activity")

    @mcp.tool(name="garmin_get_activity_exercise_sets")
    def get_activity_exercise_sets(activity_id: str) -> dict:
        """Get per-set detail (reps, weight, rest, exercise category) for a completed Garmin strength activity, where the watch/app populated it. activity_id: Garmin activity ID (from garmin_get_activities)."""
        return client_call("get_activity_exercise_sets", activity_id)
