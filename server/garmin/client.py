"""Garmin Connect client/session management and safe-call helpers."""

import os
import threading
from datetime import date, timedelta

import garminconnect

TOKEN_DIR = os.environ.get("GARMIN_TOKEN_DIR", os.path.expanduser("~/.garminconnect"))

_client_lock = threading.Lock()
_cached_client: garminconnect.Garmin | None = None


def _login() -> garminconnect.Garmin:
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    client = garminconnect.Garmin(email=email, password=password, is_cn=False)
    try:
        client.login(TOKEN_DIR)
    except Exception:
        client.login()
        client.client.dump(TOKEN_DIR)
    return client


def get_client() -> garminconnect.Garmin:
    """Returns a cached, already-authenticated client, logging in only once per
    process. Concurrent requests share this client instead of each doing their own
    login and racing to write TOKEN_DIR."""
    global _cached_client
    with _client_lock:
        if _cached_client is None:
            _cached_client = _login()
        return _cached_client


def invalidate_client() -> None:
    global _cached_client
    with _client_lock:
        _cached_client = None


def today_str() -> str:
    return date.today().isoformat()


def days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


_SPEED_TO_PACE_KEYS = {
    "averageSpeed": "averagePaceMinPerKm",
    "maxSpeed": "maxPaceMinPerKm",
    "averageMovingSpeed": "averageMovingPaceMinPerKm",
    "avgGradeAdjustedSpeed": "gradeAdjustedPaceMinPerKm",
}


def speed_to_pace_str(speed_mps) -> str | None:
    """Converts m/s to a "M:SS" pace-per-km string. Not meaningful at zero/near-zero
    speed (stopped/paused), so those return None rather than a nonsensical huge pace."""
    if not isinstance(speed_mps, (int, float)) or speed_mps < 0.1:
        return None
    sec_per_km = 1000 / speed_mps
    minutes, seconds = divmod(round(sec_per_km), 60)
    return f"{minutes}:{seconds:02d}"


def convert_speeds_to_pace(obj):
    """Recursively replaces known m/s speed fields (averageSpeed, maxSpeed,
    averageMovingSpeed, avgGradeAdjustedSpeed) with M:SS/km pace fields, anywhere they
    appear in a nested dict/list Garmin response. Leaves vertical-speed fields
    (maxVerticalSpeed etc.) untouched since "pace" isn't meaningful for those."""
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if key in _SPEED_TO_PACE_KEYS and isinstance(value, (int, float)):
                result[_SPEED_TO_PACE_KEYS[key]] = speed_to_pace_str(value)
            else:
                result[key] = convert_speeds_to_pace(value)
        return result
    if isinstance(obj, list):
        return [convert_speeds_to_pace(item) for item in obj]
    return obj


def safe_call(fn, *args, **kwargs) -> dict:
    try:
        result = fn(*args, **kwargs)
        return {"ok": True, "data": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def safe_get_client() -> tuple[garminconnect.Garmin | None, dict | None]:
    """get_client() logs in over the network and can fail (bad creds, MFA
    challenge, Garmin outage). Callers must go through this instead of calling
    get_client() directly so a login failure returns the same {"ok": False,
    "error": ...} shape as any other tool error, instead of an unhandled
    exception - get_client() raising inside a bare `safe_call(get_client().x, ...)`
    argument list happens before safe_call's own try/except is entered."""
    try:
        return get_client(), None
    except Exception as e:
        return None, {"ok": False, "error": str(e)}


_AUTH_ERROR_MARKERS = ("401", "403", "unauthorized", "authentication")


def _looks_like_auth_error(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _AUTH_ERROR_MARKERS)


def client_call(method_name: str, *args, **kwargs) -> dict:
    client, err = safe_get_client()
    if err:
        return err
    result = safe_call(getattr(client, method_name), *args, **kwargs)
    if not result["ok"] and _looks_like_auth_error(result["error"]):
        # Cached client's session likely expired - invalidate and retry once
        # with a fresh login rather than returning a stale auth error forever.
        invalidate_client()
        client, err = safe_get_client()
        if err:
            return err
        result = safe_call(getattr(client, method_name), *args, **kwargs)
    return result
