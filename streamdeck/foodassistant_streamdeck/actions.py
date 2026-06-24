"""Action registry for the Stream Deck controller.

Each key on the deck is bound to an action. An action carries enough metadata
to render its key (label, colour, whether it shows a live count) and a kind
that tells the controller what to do when the key is pressed. The functions
here are pure: they describe actions and run the HTTP side effects, but they
never touch the deck hardware directly. The controller passes in a small
context object for the few effects that reach back to the device (brightness,
paging, kiosk navigation).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

# Preset durations (minutes) cycled through on each timer key press.
TIMER_PRESETS: tuple[int, ...] = (5, 10, 15, 30, 60)


class TimerState:
    """Mutable per-key countdown timer.

    Pressing cycles: idle -> 5 min -> 10 min -> 15 min -> 30 min -> 60 min -> idle.
    While counting down, ``label()`` returns MM:SS remaining. When expired,
    ``alerting`` flips to True; the next press dismisses it.
    """

    def __init__(self) -> None:
        self._preset_idx: int = -1   # -1 = idle
        self._deadline: float = 0.0  # monotonic clock target
        self.alerting: bool = False

    def is_running(self) -> bool:
        return self._preset_idx >= 0 and not self.alerting

    def remaining_seconds(self) -> int:
        if not self.is_running():
            return 0
        return max(0, int(self._deadline - time.monotonic()))

    def label(self, base_label: str) -> str:
        if self.alerting:
            return "Done!"
        if self._preset_idx < 0:
            return base_label
        secs = self.remaining_seconds()
        if secs <= 0:
            return "Done!"
        return f"{secs // 60}:{secs % 60:02d}"

    def color(self, base_color: str) -> str:
        if self.alerting:
            return "#ef4444"
        if self._preset_idx < 0:
            return base_color
        secs = self.remaining_seconds()
        return "#f59e0b" if secs < 60 else "#0d9488"

    def alert_active(self) -> bool:
        return self.alerting

    def press(self) -> None:
        if self.alerting:
            self.alerting = False
            self._preset_idx = -1
            return
        self._preset_idx += 1
        if self._preset_idx >= len(TIMER_PRESETS):
            self._preset_idx = -1
            self._deadline = 0.0
        else:
            self._deadline = time.monotonic() + TIMER_PRESETS[self._preset_idx] * 60

    def tick(self) -> bool:
        """Return True (and set alerting) if the timer just expired."""
        if self.is_running() and self.remaining_seconds() <= 0:
            self.alerting = True
            self._preset_idx = -1
            return True
        return False


# Largest PIN the buffer will hold. Generous enough for any reasonable unlock
# code; extra presses past this are ignored rather than silently truncating a
# longer code into a different one.
PIN_MAX_LEN: int = 12


class PinBuffer:
    """Accumulates a numeric PIN entered on the deck keypad.

    The buffer never exposes the entered digits for rendering; callers ask for
    ``masked()`` (a row of dots) or ``length()`` so the actual code is never
    drawn on a key face. ``digit`` appends, ``backspace`` removes the last
    digit, and ``clear`` empties the whole buffer. ``value`` is only read when
    the controller submits the code over HTTP.
    """

    def __init__(self, max_len: int = PIN_MAX_LEN) -> None:
        self._digits: list[str] = []
        self._max_len = max(1, int(max_len))

    def digit(self, ch: str) -> None:
        """Append a single digit. Non-digits and overflow are ignored."""
        if len(ch) == 1 and ch.isdigit() and len(self._digits) < self._max_len:
            self._digits.append(ch)

    def backspace(self) -> None:
        if self._digits:
            self._digits.pop()

    def clear(self) -> None:
        self._digits.clear()

    def length(self) -> int:
        return len(self._digits)

    def is_empty(self) -> bool:
        return not self._digits

    @property
    def value(self) -> str:
        """The raw entered PIN. Only the submit path should read this."""
        return "".join(self._digits)

    def masked(self) -> str:
        """A face-safe representation: one dot per entered digit."""
        return "•" * len(self._digits)


# Logical keys on the on-deck keypad. Digit keys carry the digit itself; the two
# editing keys use these sentinel names.
KEYPAD_CLEAR = "clear"
KEYPAD_ENTER = "enter"
KEYPAD_CANCEL = "cancel"


def keypad_specs() -> dict[str, ActionSpec]:
    """Build the ActionSpecs used on the keypad page.

    Digits 0-9 plus a clear/backspace, an enter/submit, and a cancel that drops
    back to the normal layout. These are generated rather than stored in the
    static ACTIONS registry so the keypad never appears as a bindable key in a
    user's config.
    """
    specs: dict[str, ActionSpec] = {}
    for d in "0123456789":
        specs[f"keypad_{d}"] = ActionSpec(
            name=f"keypad_{d}", label=d, color="#1e293b",
            kind="keypad", keypad_key=d,
        )
    specs[f"keypad_{KEYPAD_CLEAR}"] = ActionSpec(
        name=f"keypad_{KEYPAD_CLEAR}", label="Clear", color="#7f1d1d",
        kind="keypad", keypad_key=KEYPAD_CLEAR,
    )
    specs[f"keypad_{KEYPAD_ENTER}"] = ActionSpec(
        name=f"keypad_{KEYPAD_ENTER}", label="Enter", color="#166534",
        kind="keypad", keypad_key=KEYPAD_ENTER,
    )
    specs[f"keypad_{KEYPAD_CANCEL}"] = ActionSpec(
        name=f"keypad_{KEYPAD_CANCEL}", label="Cancel", color="#334155",
        kind="keypad", keypad_key=KEYPAD_CANCEL,
    )
    return specs


async def submit_pin(client: Any, base_url: str, pin: str) -> bool:
    """Submit a PIN to the app's login endpoint. Returns True on success.

    The app authenticates with a password (which may be a numeric PIN) posted
    to ``/ui/login`` as a form field. A successful login answers with a redirect
    to the dashboard (status < 400 without following it); a wrong code answers
    401. Network or service errors return False so the deck shows an error state
    rather than crashing.
    """
    base = base_url.rstrip("/")
    try:
        r = await client.post(
            f"{base}/ui/login",
            data={"password": pin},
            follow_redirects=False,
        )
        return r.status_code < 400
    except Exception:  # noqa: BLE001 - surface as failure, never crash
        return False


_WEATHER_CONDITION_CODES: dict[int, str] = {
    113: "Sunny", 116: "Partly\nCloudy", 119: "Cloudy", 122: "Overcast",
    143: "Mist", 176: "Patchy\nRain", 179: "Patchy\nSnow",
    182: "Sleet", 185: "Drizzle", 200: "Thunder", 227: "Blowing\nSnow",
    230: "Blizzard", 248: "Fog", 260: "Ice Fog", 263: "Drizzle",
    266: "Drizzle", 281: "Drizzle", 284: "Ice Drizzle",
    293: "Light\nRain", 296: "Light\nRain", 299: "Rain", 302: "Rain",
    305: "Heavy\nRain", 308: "Heavy\nRain", 311: "Sleet", 314: "Sleet",
    317: "Light\nSleet", 320: "Mod.\nSleet", 323: "Light\nSnow",
    326: "Light\nSnow", 329: "Snow", 332: "Snow", 335: "Heavy\nSnow",
    338: "Heavy\nSnow", 350: "Ice", 353: "Showers", 356: "Showers",
    359: "Heavy\nRain", 362: "Sleet", 365: "Sleet", 368: "Snow\nShowers",
    371: "Snow\nShowers", 374: "Ice", 377: "Ice", 386: "Thunder",
    389: "Thunder", 392: "T-Storm", 395: "Blizzard",
}


class WeatherState:
    """Fetches and caches current weather from wttr.in (no API key required).

    ``location`` is any city name, zip code, or lat,lon string. When empty,
    wttr.in auto-detects the location from the requester's IP address.
    ``units`` is 'f' (Fahrenheit) or 'c' (Celsius).
    """

    def __init__(self, location: str = "", units: str = "f") -> None:
        self.location = location
        self.units = units.lower()
        self._label: str = "Weather"
        self._color: str = "#1e40af"
        self._fetched_at: float = 0.0
        self._error: bool = False

    def age_seconds(self) -> float:
        return time.monotonic() - self._fetched_at

    def label(self, base_label: str) -> str:
        return self._label if self._fetched_at else base_label

    def color(self, base_color: str) -> str:
        return self._color

    async def refresh(self) -> None:
        try:
            import httpx
            loc = self.location.strip().replace(" ", "+") if self.location.strip() else ""
            url = f"https://wttr.in/{loc}?format=j1"
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, headers={"User-Agent": "foodassistant-streamdeck/1.0"})
            if r.status_code != 200:
                self._label = "No signal"
                self._color = "#6b7280"
                self._error = True
                return
            data = r.json()
            cond = data["current_condition"][0]
            temp_key = "temp_F" if self.units == "f" else "temp_C"
            temp = cond.get(temp_key, "?")
            unit_sym = "F" if self.units == "f" else "C"
            code = int(cond.get("weatherCode", 113))
            desc = _WEATHER_CONDITION_CODES.get(code, cond.get("weatherDesc", [{}])[0].get("value", ""))
            self._label = f"{temp}°{unit_sym} {desc}"
            self._color = "#1e40af"
            self._error = False
        except Exception:
            self._label = "No signal"
            self._color = "#6b7280"
            self._error = True
        finally:
            self._fetched_at = time.monotonic()


_HA_STATE_COLOR_ON = "#15803d"
_HA_STATE_COLOR_OFF = "#475569"
_HA_STATE_COLOR_ERROR = "#6b7280"

_HA_ON_STATES = frozenset({"on", "home", "open", "playing", "active", "locked"})


class HaEntityState:
    """Caches Home Assistant entity state for a single key.

    Refreshed from the HA REST API. The key shows a green background when
    the entity is in an "on-like" state and gray otherwise. Unavailable or
    error states fall back to a neutral gray so the key is never misleading.
    """

    def __init__(self, entity_id: str, color_on: str = _HA_STATE_COLOR_ON,
                 color_off: str = _HA_STATE_COLOR_OFF) -> None:
        self.entity_id = entity_id
        self.color_on = color_on
        self.color_off = color_off
        self._state: str = ""   # raw HA state string
        self._fetched_at: float = 0.0

    def age_seconds(self) -> float:
        return time.monotonic() - self._fetched_at

    def is_on(self) -> bool:
        return self._state.lower() in _HA_ON_STATES

    def label(self, base_label: str) -> str:
        if not self._fetched_at:
            return base_label
        suffix = "On" if self.is_on() else "Off"
        return f"{base_label}\n{suffix}"

    def color(self, base_color: str) -> str:
        if not self._fetched_at:
            return base_color
        if self._state in ("unavailable", "unknown", ""):
            return _HA_STATE_COLOR_ERROR
        return self.color_on if self.is_on() else self.color_off

    async def refresh(self, ha_base_url: str, ha_token: str) -> None:
        try:
            import httpx
            url = f"{ha_base_url.rstrip('/')}/api/states/{self.entity_id}"
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {ha_token}",
                             "Content-Type": "application/json"},
                )
            if r.status_code == 200:
                self._state = r.json().get("state", "unknown")
            else:
                self._state = "unavailable"
        except Exception:
            self._state = "unavailable"
        finally:
            self._fetched_at = time.monotonic()


@dataclass(frozen=True)
class ActionSpec:
    """Static description of one bindable action."""

    name: str
    label: str
    color: str            # key background, "#rrggbb"
    kind: str             # "status" | "trigger" | "nav" | "system"
    status_field: str = ""   # for kind=="status": which polled count to show
    target_path: str = ""    # for kind=="nav": app path to open in the kiosk
    ha_entity_id: str = ""   # for kind=="ha_entity": HA entity to show/toggle
    ha_service: str = ""     # for kind=="ha_entity": HA service to call on press
    keypad_key: str = ""     # for kind=="keypad": digit or clear/enter/cancel
    description: str = ""


# The actions a key can be bound to. status_field names must match the keys
# produced by poll_status() below.
ACTIONS: dict[str, ActionSpec] = {
    "expiring": ActionSpec(
        name="expiring",
        label="Expiring",
        color="#b54708",
        kind="status",
        status_field="expiring",
        description="Count of items expired or expiring within the soon window. "
        "Press to refresh now.",
    ),
    "pending": ActionSpec(
        name="pending",
        label="Pending",
        color="#1d4ed8",
        kind="status",
        status_field="pending",
        description="Count of scanned items waiting to be committed. "
        "Press to refresh now.",
    ),
    "commit": ActionSpec(
        name="commit",
        label="Commit",
        color="#15803d",
        kind="trigger",
        description="Commit every pending scan into the inventory.",
    ),
    "add": ActionSpec(
        name="add",
        label="Add",
        color="#b45309",
        kind="nav",
        target_path="ui/add",
        description="Open the add-item page on the attached display.",
    ),
    "inventory": ActionSpec(
        name="inventory",
        label="Stock",
        color="#0f766e",
        kind="nav",
        target_path="ui/",
        description="Open the inventory dashboard on the attached display.",
    ),
    "cook": ActionSpec(
        name="cook",
        label="Cook",
        color="#7e22ce",
        kind="nav",
        target_path="ui/cook",
        description="Open the recipe suggestions page on the attached display.",
    ),
    "brightness": ActionSpec(
        name="brightness",
        label="Bright",
        color="#475569",
        kind="system",
        description="Cycle the deck brightness.",
    ),
    "page_next": ActionSpec(
        name="page_next",
        label="More",
        color="#334155",
        kind="system",
        description="Show the next page of keys.",
    ),
    "page_prev": ActionSpec(
        name="page_prev",
        label="Back",
        color="#334155",
        kind="system",
        description="Show the previous page of keys.",
    ),
    "pin": ActionSpec(
        name="pin",
        label="Unlock",
        color="#1d4ed8",
        kind="pin",
        description="Switch the deck into a numeric keypad to unlock the "
        "PIN-locked app, then return to the normal layout.",
    ),
    "timer_1": ActionSpec(
        name="timer_1",
        label="Timer 1",
        color="#0d9488",
        kind="timer",
        description="Countdown timer (press to cycle: 5/10/15/30/60 min or stop).",
    ),
    "timer_2": ActionSpec(
        name="timer_2",
        label="Timer 2",
        color="#0d9488",
        kind="timer",
        description="Second independent countdown timer.",
    ),
    "timer_3": ActionSpec(
        name="timer_3",
        label="Timer 3",
        color="#0d9488",
        kind="timer",
        description="Third independent countdown timer.",
    ),
    "weather": ActionSpec(
        name="weather",
        label="Weather",
        color="#1e40af",
        kind="weather",
        description="Current weather from wttr.in. Configure location and units in config.toml. "
        "Press to refresh. No API key required.",
    ),
    "ha_1": ActionSpec(name="ha_1", label="HA 1", color=_HA_STATE_COLOR_OFF, kind="ha_entity",
                       description="Home Assistant entity slot 1. Configure in config.toml."),
    "ha_2": ActionSpec(name="ha_2", label="HA 2", color=_HA_STATE_COLOR_OFF, kind="ha_entity",
                       description="Home Assistant entity slot 2. Configure in config.toml."),
    "ha_3": ActionSpec(name="ha_3", label="HA 3", color=_HA_STATE_COLOR_OFF, kind="ha_entity",
                       description="Home Assistant entity slot 3. Configure in config.toml."),
    "ha_4": ActionSpec(name="ha_4", label="HA 4", color=_HA_STATE_COLOR_OFF, kind="ha_entity",
                       description="Home Assistant entity slot 4. Configure in config.toml."),
    "ha_5": ActionSpec(name="ha_5", label="HA 5", color=_HA_STATE_COLOR_OFF, kind="ha_entity",
                       description="Home Assistant entity slot 5. Configure in config.toml."),
}

# Order used when no explicit key list is configured. The controller trims or
# paginates this to fit the connected deck.
DEFAULT_ORDER: list[str] = [
    "expiring",
    "pending",
    "commit",
    "add",
    "inventory",
    "cook",
    "brightness",
]


def resolve(name: str) -> Optional[ActionSpec]:
    """Look up an action by name, or None if it is not known."""
    return ACTIONS.get(name)


async def poll_status(client: Any, base_url: str, soon_days: int = 7) -> dict[str, int]:
    """Fetch the live counts shown on status keys.

    Returns a flat mapping of status_field -> integer. Network or service
    errors collapse to zeros so a key never shows a stale or crashing value.
    """
    out = {"expiring": 0, "pending": 0}
    base = base_url.rstrip("/")
    try:
        r = await client.get(f"{base}/expiring/summary")
        if r.status_code == 200:
            s = r.json()
            out["expiring"] = (
                int(s.get("expired", 0))
                + int(s.get("today", 0))
                + int(s.get("within_3_days", 0))
                + (int(s.get("within_7_days", 0)) if soon_days >= 7 else 0)
            )
    except Exception:
        pass
    try:
        r = await client.get(f"{base}/pending/count")
        if r.status_code == 200:
            out["pending"] = int(r.json().get("count", 0))
    except Exception:
        pass
    return out


@dataclass
class ActionContext:
    """Effects the controller exposes to action handlers."""

    client: Any                                   # httpx.AsyncClient
    base_url: str
    refresh: Callable[[], Awaitable[None]]        # re-poll and redraw
    navigate: Callable[[str], Awaitable[bool]]    # open an app path in the kiosk
    cycle_brightness: Callable[[], int]           # returns the new percent
    page_next: Callable[[], None]
    page_prev: Callable[[], None]
    timer_press: Callable[[str], None] = field(default=lambda _name: None)
    weather_refresh: Callable[[], Awaitable[None]] = field(
        default=lambda: __import__("asyncio").sleep(0)
    )
    ha_base_url: str = ""
    ha_token: str = ""
    ha_entity_refresh: Callable[[], Awaitable[None]] = field(
        default=lambda: __import__("asyncio").sleep(0)
    )
    # Enter the on-deck PIN keypad (kind=="pin").
    keypad_enter: Callable[[], None] = field(default=lambda: None)
    # Handle a keypad key press (kind=="keypad"); arg is the keypad_key value.
    keypad_press: Callable[[str], Awaitable[None]] = field(
        default=lambda _k: __import__("asyncio").sleep(0)
    )


async def run_action(spec: ActionSpec, ctx: ActionContext) -> str:
    """Perform the side effect for a pressed key. Returns a short status line.

    Handlers are intentionally forgiving: a failed HTTP call returns a readable
    message rather than raising, so one bad press cannot take the daemon down.
    """
    base = ctx.base_url.rstrip("/")

    if spec.kind == "status":
        await ctx.refresh()
        return "refreshed"

    if spec.kind == "trigger" and spec.name == "commit":
        try:
            r = await ctx.client.post(f"{base}/pending/commit", json={})
            if r.status_code == 200:
                imported = int(r.json().get("imported", 0))
                await ctx.refresh()
                return f"committed {imported}"
            return f"commit failed ({r.status_code})"
        except Exception as e:  # noqa: BLE001 - surface, never crash
            return f"commit error: {e}"

    if spec.kind == "nav":
        ok = await ctx.navigate(spec.target_path)
        return "opened" if ok else "no display"

    if spec.kind == "system" and spec.name == "brightness":
        pct = ctx.cycle_brightness()
        return f"brightness {pct}%"

    if spec.kind == "system" and spec.name == "page_next":
        ctx.page_next()
        return "next page"

    if spec.kind == "system" and spec.name == "page_prev":
        ctx.page_prev()
        return "prev page"

    if spec.kind == "timer":
        ctx.timer_press(spec.name)
        return f"{spec.name} pressed"

    if spec.kind == "pin":
        ctx.keypad_enter()
        return "keypad"

    if spec.kind == "keypad":
        await ctx.keypad_press(spec.keypad_key)
        return f"keypad {spec.keypad_key}"

    if spec.kind == "weather":
        await ctx.weather_refresh()
        return "weather refreshed"

    if spec.kind == "ha_entity":
        entity_id = spec.ha_entity_id
        service = spec.ha_service
        if not entity_id or not service or not ctx.ha_base_url or not ctx.ha_token:
            return "ha_entity: not configured"
        domain, svc = (service.split(".", 1) + ["turn_on"])[:2]
        try:
            import httpx
            url = f"{ctx.ha_base_url.rstrip('/')}/api/services/{domain}/{svc}"
            async with httpx.AsyncClient(timeout=5.0) as ha:
                r = await ha.post(
                    url,
                    json={"entity_id": entity_id},
                    headers={"Authorization": f"Bearer {ctx.ha_token}",
                             "Content-Type": "application/json"},
                )
            await ctx.ha_entity_refresh()
            return f"{entity_id} -> {service} ({r.status_code})"
        except Exception as e:  # noqa: BLE001
            return f"ha error: {e}"

    return ""
