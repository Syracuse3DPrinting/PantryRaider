"""Shared screensaver state for the kiosk panel and the Stream Deck.

When the kiosk screensaver's bouncing logo is on screen and the deck layout
setting says the deck sits next to the panel (FoodAssistant-3fdq), the two act
as one canvas: the kiosk (the animation driver) posts the logo's normalized
position here a few times a second, and the deck controller polls it on its
own slower cadence to render the slice of the logo crossing its keys.

Sharing (FoodAssistant-0fho): the state lives in a small JSON file so a server
running multiple uvicorn workers agrees on it (the kiosk's post may land on a
different worker than the deck's poll). Unlike the other shared state files it
does NOT live under data_dir: the kiosk posts a few times a second while the
saver is up, and on a Pi appliance data_dir sits on the SD card, where several
writes per second is real flash wear for state that is worthless across a
reboot. It defaults to the system temp dir (tmpfs on the Pi image, and wiped
on reboot either way, which matches the state's ephemeral nature); set
SCREENSAVER_STATE_DIR to override. Reads are mtime-cached so the deck's poll
costs one stat call, and an unwritable dir quietly degrades to the old
process-local in-memory behavior.

Freshness is judged with a pure helper so the logic is unit-testable without
sleeping: a state older than the staleness window counts as inactive, so a
kiosk that died mid-saver never leaves the deck showing a frozen logo forever.

The deck can also dismiss the saver: a key press posts a dismiss mark, and the
kiosk's next state post returns it, telling the browser to hide the overlay.
(A dismiss landing in the same instant as a kiosk post can lose to it; the
next key press retries, and the posts are ~300ms apart, so this is accepted.)

Finished timer pills ride the same channel (FoodAssistant-07ee): the kiosk
includes a small "pills" array (id, box in the same panel-normalized space,
done flag, food icon character) so a Done pill drifting into the deck band
shows up on the keys too. The kiosk sends only finished pills, so the payload
stays a handful of numbers.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

# A kiosk posts every few hundred milliseconds while the saver is up, so a
# state this old means the saver ended (or the kiosk went away).
STALE_AFTER_SECONDS = 10.0

# Hard cap on stored pills: the kiosk sends only finished timers (and it
# simulates at most six pills anyway), so anything past this is junk input.
MAX_PILLS = 6

# An icon is one emoji, possibly with a variation selector; anything longer
# is not an icon.
_MAX_ICON_CHARS = 4

_lock = threading.Lock()
_DEFAULT_STATE: dict = {
    "active": False,
    # Logo bounding box in panel-normalized units (panel width and height are
    # each 1.0; the deck band extends past 0..1 on the layout's side).
    "x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0,
    # Deck band size in panel-normalized units and which side it sits on, as
    # computed by the kiosk, so the deck's slice math needs no panel geometry.
    "band": 0.0, "layout": "off",
    # Finished timer pills, sanitized dicts in the same normalized space.
    "pills": [],
    "updated": 0.0,
    # Set by a deck key press; returned (once) to the kiosk so it dismisses.
    "dismissed": 0.0,
}
_state: dict = dict(_DEFAULT_STATE)
# mtime of the state file our in-memory view corresponds to (None = never seen).
_mtime: int | None = None


def _state_file() -> Path:
    # Runtime-local by design (see docstring): temp dir, not the SD-backed
    # data_dir. Resolved per call so an env override applies live.
    base = os.environ.get("SCREENSAVER_STATE_DIR") or tempfile.gettempdir()
    return Path(base) / "foodassistant-screensaver.json"


def _load_locked() -> None:
    """Refresh the in-process state from the file if it changed on disk.
    Caller holds the lock."""
    global _state, _mtime
    try:
        sf = _state_file()
        mtime = sf.stat().st_mtime_ns
    except OSError:
        return  # no file yet (never posted, or unwritable dir)
    if mtime == _mtime:
        return
    try:
        data = json.loads(sf.read_text())
    except (OSError, ValueError):
        return  # a torn or corrupt file never breaks a poll; keep what we have
    if isinstance(data, dict):
        _mtime = mtime
        _state = {**_DEFAULT_STATE, **{k: data[k] for k in _DEFAULT_STATE if k in data}}


def _save_locked() -> None:
    """Write the state to the file (atomic replace, best effort). Caller holds
    the lock."""
    global _mtime
    sf = _state_file()
    try:
        tmp = sf.with_name(sf.name + ".tmp")
        tmp.write_text(json.dumps(_state))
        os.replace(tmp, sf)
        _mtime = sf.stat().st_mtime_ns
    except OSError:
        pass  # dir not writable: fall back to process-local behavior


def sanitize_pills(raw) -> list[dict]:
    """Pure helper: reduce a posted "pills" value to a safe, small list.

    Each entry keeps only the fields the deck needs (id, x, y, w, h, done,
    icon), with types coerced and the icon truncated, capped at MAX_PILLS
    entries. Anything malformed is dropped rather than raised, so a garbage
    post can never break the channel.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if len(out) >= MAX_PILLS:
            break
        if not isinstance(item, dict):
            continue
        def _num(key: str) -> float:
            v = item.get(key, 0.0)
            return float(v) if isinstance(v, (int, float)) else 0.0
        out.append({
            "id": str(item.get("id") or "")[:64],
            "x": _num("x"), "y": _num("y"),
            "w": _num("w"), "h": _num("h"),
            "done": bool(item.get("done")),
            "icon": str(item.get("icon") or "")[:_MAX_ICON_CHARS],
        })
    return out


def is_fresh(updated: float, now: float, stale_after: float = STALE_AFTER_SECONDS) -> bool:
    """Pure helper: True when a state stamped at ``updated`` still counts as
    live at ``now``. A zero/negative timestamp (never posted) is never fresh."""
    if updated <= 0:
        return False
    return 0 <= (now - updated) <= stale_after


def update(active: bool, x: float = 0.0, y: float = 0.0, w: float = 0.0,
           h: float = 0.0, band: float = 0.0, layout: str = "off",
           pills: list | None = None) -> dict:
    """Record the kiosk's saver state and return any pending dismiss.

    The returned dict carries {"dismiss": bool}: True when a deck key press
    asked for the saver to end since the kiosk's previous post. The mark is
    consumed by this read, so it fires exactly once.
    """
    now = time.time()
    clean_pills = sanitize_pills(pills)
    with _lock:
        _load_locked()
        dismissed = _state["dismissed"]
        _state.update({
            "active": bool(active),
            "x": float(x), "y": float(y), "w": float(w), "h": float(h),
            "band": float(band), "layout": str(layout),
            "pills": clean_pills,
            "updated": now,
        })
        _state["dismissed"] = 0.0
        _save_locked()
        if not active:
            return {"dismiss": False}
        return {"dismiss": bool(dismissed)}


def dismiss() -> None:
    """Mark the saver dismissed (a deck key press); the kiosk's next state
    post picks it up and hides the overlay."""
    with _lock:
        _load_locked()
        _state["dismissed"] = time.time()
        _save_locked()


def snapshot(now: float | None = None) -> dict:
    """Current state for the deck's poll, staleness already applied."""
    if now is None:
        now = time.time()
    with _lock:
        _load_locked()
        fresh = is_fresh(_state["updated"], now)
        return {
            "active": bool(_state["active"]) and fresh,
            "x": _state["x"], "y": _state["y"],
            "w": _state["w"], "h": _state["h"],
            "band": _state["band"], "layout": _state["layout"],
            "pills": list(_state["pills"]),
        }


def reset() -> None:
    """Test helper: return to the never-posted state and drop the file."""
    global _state, _mtime
    with _lock:
        _state = dict(_DEFAULT_STATE)
        _state["pills"] = []
        _mtime = None
        try:
            _state_file().unlink(missing_ok=True)
        except OSError:
            pass
