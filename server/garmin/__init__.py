"""Garmin Connect tools, ported from garmin/garmin_server.py onto FastMCP with a garmin_ prefix."""

from mcp.server.fastmcp import FastMCP

from . import tools_activities, tools_health, tools_training, tools_workouts


def register(mcp: FastMCP) -> None:
    tools_health.register(mcp)
    tools_training.register(mcp)
    tools_activities.register(mcp)
    tools_workouts.register(mcp)
