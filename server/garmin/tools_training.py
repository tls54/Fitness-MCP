"""Training-status, fitness-metric, and progress Garmin tools."""

from mcp.server.fastmcp import FastMCP

from .client import client_call, days_ago, today_str


def register(mcp: FastMCP) -> None:
    @mcp.tool(name="garmin_get_training_readiness")
    def get_training_readiness(date: str = "") -> dict:
        """Get Garmin's Training Readiness score (0-100) for a date, with component scores for sleep, recovery, HRV, and training load. date: YYYY-MM-DD, defaults to today."""
        return client_call("get_training_readiness", date or today_str())

    @mcp.tool(name="garmin_get_training_status")
    def get_training_status(date: str = "") -> dict:
        """Get Garmin's training status: status label (Maintaining/Productive/Unproductive/Detraining/Overreaching), acute/chronic load, load focus, and VO2 max trend. date: YYYY-MM-DD, defaults to today."""
        return client_call("get_training_status", date or today_str())

    @mcp.tool(name="garmin_get_vo2max_and_fitness_metrics")
    def get_vo2max_and_fitness_metrics(date: str = "") -> dict:
        """Get VO2 max estimate and fitness age. Includes running VO2 max and cycling VO2 max if available. date: YYYY-MM-DD, defaults to today."""
        return client_call("get_max_metrics", date or today_str())

    @mcp.tool(name="garmin_get_lactate_threshold")
    def get_lactate_threshold() -> dict:
        """Get Garmin's lactate threshold estimate: threshold heart rate, threshold pace, and the associated training zone."""
        return client_call("get_lactate_threshold")

    @mcp.tool(name="garmin_get_race_predictions")
    def get_race_predictions() -> dict:
        """Get Garmin's predicted race finish times for 5K, 10K, half marathon, and marathon based on current fitness."""
        return client_call("get_race_predictions")

    @mcp.tool(name="garmin_get_endurance_score")
    def get_endurance_score(start_date: str = "", end_date: str = "") -> dict:
        """Get Garmin's Endurance Score for a date range - measures aerobic fitness capacity built up over time. start_date/end_date: YYYY-MM-DD, default to 30 days ago / today."""
        start = start_date or days_ago(30)
        end = end_date or today_str()
        return client_call("get_endurance_score", start, end)

    @mcp.tool(name="garmin_get_hill_score")
    def get_hill_score(start_date: str = "", end_date: str = "") -> dict:
        """Get Garmin's Hill Score for a date range - measures ability to handle elevation gain in runs. start_date/end_date: YYYY-MM-DD, default to 30 days ago / today."""
        start = start_date or days_ago(30)
        end = end_date or today_str()
        return client_call("get_hill_score", start, end)

    @mcp.tool(name="garmin_get_running_tolerance")
    def get_running_tolerance(start_date: str = "", end_date: str = "", aggregation: str = "weekly") -> dict:
        """Get Garmin's running tolerance/load data over a date range (weekly aggregation by default). Shows acute load, chronic load, and injury risk signals. start_date/end_date: YYYY-MM-DD, default to 28 days ago / today. aggregation: 'weekly' or 'daily'."""
        start = start_date or days_ago(28)
        end = end_date or today_str()
        return client_call("get_running_tolerance", start, end, aggregation)

    @mcp.tool(name="garmin_get_personal_records")
    def get_personal_records() -> dict:
        """Get personal records (PRs) for running and other activities: fastest mile, 5K, 10K, half marathon, longest run, etc."""
        return client_call("get_personal_record")

    @mcp.tool(name="garmin_get_progress_summary")
    def get_progress_summary(start_date: str = "", end_date: str = "", metric: str = "distance") -> dict:
        """Get training progress summary between two dates, grouped by activity type. Shows distance, time, and effort trends. start_date/end_date: YYYY-MM-DD, default to 28 days ago / today. metric: 'distance', 'duration', or 'calories'."""
        start = start_date or days_ago(28)
        end = end_date or today_str()
        return client_call("get_progress_summary_between_dates", start, end, metric)
