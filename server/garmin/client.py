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
