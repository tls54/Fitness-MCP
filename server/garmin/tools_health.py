"""Daily health, lifestyle/habits, and body/weight Garmin tools."""

from mcp.server.fastmcp import FastMCP

from .client import client_call, days_ago, safe_call, safe_get_client, today_str
from .workout_builders import _lifestyle_log, _lifestyle_log_history


def register(mcp: FastMCP) -> None:
    # ── Daily health ─────────────────────────────────────────────────────────
    @mcp.tool(name="garmin_get_sleep")
    def get_sleep(date: str = "") -> dict:
        """Get detailed sleep data for a given date: sleep stages (deep, light, REM, awake), total sleep duration, sleep score, respiration, SpO2, and sleep start/end times. date: YYYY-MM-DD, defaults to today."""
        return client_call("get_sleep_data", date or today_str())

    @mcp.tool(name="garmin_get_hrv")
    def get_hrv(date: str = "") -> dict:
        """Get Heart Rate Variability (HRV) data for a date: overnight HRV summary, 5-minute readings, baseline, and status (Balanced / Unbalanced / Low). date: YYYY-MM-DD, defaults to today."""
        return client_call("get_hrv_data", date or today_str())

    @mcp.tool(name="garmin_get_body_battery")
    def get_body_battery(date: str = "") -> dict:
        """Get Body Battery levels for a date: charging/draining events, start/end levels, and the impact of sleep and activities. date: YYYY-MM-DD, defaults to today."""
        d = date or today_str()
        return client_call("get_body_battery", d, d)

    @mcp.tool(name="garmin_get_stress")
    def get_stress(date: str = "") -> dict:
        """Get stress data for a date: average stress, max stress, rest stress, and time in low/medium/high/rest stress categories. date: YYYY-MM-DD, defaults to today."""
        return client_call("get_stress_data", date or today_str())

    @mcp.tool(name="garmin_get_heart_rate")
    def get_heart_rate(date: str = "") -> dict:
        """Get resting heart rate and heart rate timeline for a date: min HR, max HR, resting HR, and timestamped readings throughout the day. date: YYYY-MM-DD, defaults to today."""
        return client_call("get_heart_rates", date or today_str())

    @mcp.tool(name="garmin_get_spo2")
    def get_spo2(date: str = "") -> dict:
        """Get SpO2 (blood oxygen saturation) readings for a date: average, min, max, and overnight continuous readings. date: YYYY-MM-DD, defaults to today."""
        return client_call("get_spo2_data", date or today_str())

    @mcp.tool(name="garmin_get_respiration")
    def get_respiration(date: str = "") -> dict:
        """Get breathing rate (respiration) data for a date: average, min, max breaths per minute throughout the day and overnight. date: YYYY-MM-DD, defaults to today."""
        return client_call("get_respiration_data", date or today_str())

    @mcp.tool(name="garmin_get_steps_and_activity")
    def get_steps_and_activity(date: str = "") -> dict:
        """Get daily steps, floors climbed, distance, calories (active + resting), and intensity minutes for a date. date: YYYY-MM-DD, defaults to today."""
        d = date or today_str()
        client, err = safe_get_client()
        if err:
            return err
        steps = safe_call(client.get_steps_data, d)
        stats = safe_call(client.get_stats, d)
        return {"ok": True, "data": {"steps": steps.get("data"), "stats": stats.get("data")}}

    @mcp.tool(name="garmin_get_hydration")
    def get_hydration(date: str = "") -> dict:
        """Get daily hydration data: fluid intake in ml and goal for a date. date: YYYY-MM-DD, defaults to today."""
        return client_call("get_hydration_data", date or today_str())

    @mcp.tool(name="garmin_get_daily_summary")
    def get_daily_summary(date: str = "") -> dict:
        """Get a comprehensive daily summary including steps, calories, HR, stress, Body Battery, intensity minutes, and floors for a date. Good all-in-one snapshot. date: YYYY-MM-DD, defaults to today."""
        return client_call("get_user_summary", date or today_str())

    @mcp.tool(name="garmin_get_weekly_summary")
    def get_weekly_summary(end_date: str = "") -> dict:
        """Get a weekly health and activity summary for the 7 days ending on end_date: total steps, active calories, total intensity minutes, average stress, average resting HR, and average sleep hours. end_date: YYYY-MM-DD, defaults to today."""
        from datetime import date, timedelta

        client, err = safe_get_client()
        if err:
            return err

        end = date.fromisoformat(end_date) if end_date else date.today()
        days = [(end - timedelta(days=i)).isoformat() for i in range(7)]

        total_steps = 0
        active_calories = 0.0
        moderate_minutes = 0
        vigorous_minutes = 0
        stress_values = []
        resting_hr_values = []
        sleep_hours_values = []

        for day in days:
            summary = safe_call(client.get_user_summary, day)
            if summary["ok"] and summary["data"]:
                d = summary["data"]
                total_steps += d.get("totalSteps") or 0
                active_calories += d.get("activeKilocalories") or 0
                moderate_minutes += d.get("moderateIntensityMinutes") or 0
                vigorous_minutes += d.get("vigorousIntensityMinutes") or 0
                if d.get("averageStressLevel") is not None and d["averageStressLevel"] >= 0:
                    stress_values.append(d["averageStressLevel"])
                if d.get("restingHeartRate"):
                    resting_hr_values.append(d["restingHeartRate"])

            sleep = safe_call(client.get_sleep_data, day)
            if sleep["ok"] and sleep["data"]:
                seconds = (sleep["data"].get("dailySleepDTO") or {}).get("sleepTimeSeconds")
                if seconds:
                    sleep_hours_values.append(seconds / 3600)

        def avg(values):
            return round(sum(values) / len(values), 1) if values else None

        return {
            "ok": True,
            "data": {
                "start_date": days[-1],
                "end_date": days[0],
                "total_steps": total_steps,
                "total_active_calories": round(active_calories),
                "total_moderate_intensity_minutes": moderate_minutes,
                "total_vigorous_intensity_minutes": vigorous_minutes,
                "avg_stress_level": avg(stress_values),
                "avg_resting_heart_rate": avg(resting_hr_values),
                "avg_sleep_hours": avg(sleep_hours_values),
            },
        }

    # ── Trends / history ─────────────────────────────────────────────────────
    @mcp.tool(name="garmin_get_sleep_history")
    def get_sleep_history(days: int = 14) -> dict:
        """Get sleep scores and stage breakdown for the past N days to identify trends. Returns per-day summary stats only (durations, sleep score, avg HR/respiration) - not minute-by-minute sleep movement/HR/stress/HRV arrays; use garmin_get_sleep for one night's full detail. days: number of past days (default 14, max 28)."""
        client, err = safe_get_client()
        if err:
            return err
        n = min(days, 28)
        history = []
        for i in range(n):
            day = days_ago(i)
            r = safe_call(client.get_sleep_data, day)
            if r["ok"] and r["data"]:
                dto = r["data"].get("dailySleepDTO") or {}
                history.append(
                    {
                        "date": day,
                        "data": {
                            "sleepTimeSeconds": dto.get("sleepTimeSeconds"),
                            "deepSleepSeconds": dto.get("deepSleepSeconds"),
                            "lightSleepSeconds": dto.get("lightSleepSeconds"),
                            "remSleepSeconds": dto.get("remSleepSeconds"),
                            "awakeSleepSeconds": dto.get("awakeSleepSeconds"),
                            "sleepScores": dto.get("sleepScores"),
                            "avgHeartRate": dto.get("avgHeartRate"),
                            "averageRespirationValue": dto.get("averageRespirationValue"),
                            "avgSleepStress": dto.get("avgSleepStress"),
                            "avgOvernightHrv": r["data"].get("avgOvernightHrv"),
                            "restingHeartRate": r["data"].get("restingHeartRate"),
                            "bodyBatteryChange": r["data"].get("bodyBatteryChange"),
                        },
                    }
                )
        return {"ok": True, "data": history}

    @mcp.tool(name="garmin_get_hrv_history")
    def get_hrv_history(days: int = 14) -> dict:
        """Get overnight HRV values for the past N days to track recovery trends. Returns per-night summary (weekly avg, last-night avg, baseline, status) - not the raw 5-minute HRV readings; use garmin_get_hrv for one night's full detail. days: number of past days (default 14, max 28)."""
        client, err = safe_get_client()
        if err:
            return err
        n = min(days, 28)
        history = []
        for i in range(n):
            day = days_ago(i)
            r = safe_call(client.get_hrv_data, day)
            if r["ok"] and r["data"]:
                history.append({"date": day, "data": r["data"].get("hrvSummary")})
        return {"ok": True, "data": history}

    @mcp.tool(name="garmin_get_body_battery_history")
    def get_body_battery_history(days: int = 14) -> dict:
        """Get end-of-day Body Battery levels for the past N days to track energy trends. days: number of past days (default 14, max 28)."""
        client, err = safe_get_client()
        if err:
            return err
        n = min(days, 28)
        history = []
        for i in range(n):
            day = days_ago(i)
            r = safe_call(client.get_body_battery, day, day)
            if r["ok"] and r["data"]:
                history.append({"date": day, "data": r["data"]})
        return {"ok": True, "data": history}

    # ── Lifestyle / habits ───────────────────────────────────────────────────
    @mcp.tool(name="garmin_get_lifestyle_log")
    def get_lifestyle_log(date: str = "") -> dict:
        """Get the lifestyle/habit log for a date: which manually-tracked habits (e.g. healthy meals, morning caffeine, moderate exercise, ankle exercises) were logged that day and whether each was completed. date: YYYY-MM-DD, defaults to today."""
        client, err = safe_get_client()
        if err:
            return err
        return safe_call(_lifestyle_log, client, date or today_str())

    @mcp.tool(name="garmin_get_lifestyle_log_history")
    def get_lifestyle_log_history(start_date: str, end_date: str = "") -> dict:
        """Get lifestyle/habit log compliance across a date range, as a day-by-day table showing whether each tracked habit was done, missed, or not logged. start_date: YYYY-MM-DD, required. end_date: YYYY-MM-DD, defaults to today."""
        client, err = safe_get_client()
        if err:
            return err
        return safe_call(_lifestyle_log_history, client, start_date, end_date or today_str())

    # ── Body & weight ────────────────────────────────────────────────────────
    @mcp.tool(name="garmin_get_weight")
    def get_weight(start_date: str = "", end_date: str = "") -> dict:
        """Get body weight and composition data for a date range. Returns weight, BMI, body fat % if measured. start_date/end_date: YYYY-MM-DD, default to 14 days ago / today."""
        start = start_date or days_ago(14)
        end = end_date or today_str()
        return client_call("get_body_composition", start, end)
