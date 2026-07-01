"""On-screen Home Assistant event channel.

Home Assistant pushes events to Pantry Raider (a rest_command in an automation),
and the kiosk / web UI polls for them and shows them on the display: notification
toasts and camera pop-ups (for example, pop up the doorbell camera when a person
is detected). Events live in a small in-memory ring, like the timers and the
active recipe: they are transient and process-local, which is fine because they
target the screen of the instance HA posts to, and a restart simply clears any
unseen events.

Each event has a monotonically increasing ``id`` so a client can poll for "what
is new since the last id I saw" without missing or replaying events.
"""
from __future__ import annotations

import threading
import time

# Keep only the most recent events, and drop anything older than the TTL, so a
# kiosk that was off does not get flooded with a backlog when it polls.
_MAX_EVENTS = 50
_TTL_SECONDS = 120

_lock = threading.Lock()
_events: list[dict] = []
_next_id = 1


def _prune_locked(now: float) -> None:
    global _events
    cutoff = now - _TTL_SECONDS
    _events = [e for e in _events if e["ts"] >= cutoff][-_MAX_EVENTS:]


def _add(event: dict) -> int:
    global _next_id
    now = time.time()
    with _lock:
        event["id"] = _next_id
        event["ts"] = now
        _next_id += 1
        _events.append(event)
        _prune_locked(now)
        return event["id"]


def add_notification(message: str, title: str = "", level: str = "info",
                     timeout: int = 0) -> int:
    """Queue a notification toast. ``level`` is info/success/warning/error."""
    lvl = level if level in ("info", "success", "warning", "error") else "info"
    return _add({
        "type": "notification",
        "message": str(message),
        "title": str(title),
        "level": lvl,
        "timeout": max(0, int(timeout or 0)),
    })


def add_camera(name: str = "", src: str = "", seconds: int = 0) -> int:
    """Queue a camera pop-up. ``src`` is the proxy snapshot path the kiosk shows."""
    return _add({
        "type": "camera",
        "name": str(name),
        "src": str(src),
        "seconds": max(0, int(seconds or 0)),
    })


def add_navigate(path: str) -> int:
    """Queue a kiosk page-change event. ``path`` is an app-relative path (e.g.
    "ui/cook"), so a Home Assistant automation can drive which page the display
    shows (FoodAssistant-i4rs). The kiosk navigates same-origin only."""
    return _add({"type": "navigate", "path": str(path or "").strip()})


def poll(after_id: int = 0) -> dict:
    """Events newer than ``after_id``, plus the current last id.

    A fresh client should first read ``last_id`` (with after_id huge, or via the
    returned value) so it only sees events that arrive after it connects, rather
    than replaying the recent ring on load.
    """
    now = time.time()
    with _lock:
        _prune_locked(now)
        last = _next_id - 1
        try:
            after = int(after_id)
        except (TypeError, ValueError):
            after = 0
        fresh = [dict(e) for e in _events if e["id"] > after]
    return {"events": fresh, "last_id": last}


def last_id() -> int:
    with _lock:
        return _next_id - 1


def reset() -> None:
    """Clear all events (used by tests)."""
    global _events, _next_id
    with _lock:
        _events = []
        _next_id = 1
