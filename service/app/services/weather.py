"""Server-side weather forecast from wttr.in's free JSON API (FoodAssistant-afqd).

The kiosk weather page used to load a panel PNG from v2.wttr.in directly in the
browser, which is unreliable and depends on the kiosk's own internet access. The
Stream Deck weather widget instead uses wttr.in's j1 JSON API server-side, which
is dependable, so the page now uses the same path: the server fetches and parses
the forecast and the page renders plain HTML.

The parse step is a pure function so it is unit-testable without any network.
"""
from __future__ import annotations

from typing import Any

# wttr.in numeric weather codes -> short description, mirroring the Stream Deck
# widget's table so the two surfaces agree.
_CONDITION = {
    113: "Sunny", 116: "Partly cloudy", 119: "Cloudy", 122: "Overcast",
    143: "Mist", 176: "Patchy rain", 179: "Patchy snow", 182: "Sleet",
    185: "Drizzle", 200: "Thundery", 227: "Blowing snow", 230: "Blizzard",
    248: "Fog", 260: "Fog", 263: "Drizzle", 266: "Drizzle", 281: "Drizzle",
    284: "Drizzle", 293: "Light rain", 296: "Light rain", 299: "Rain",
    302: "Rain", 305: "Heavy rain", 308: "Heavy rain", 311: "Sleet",
    314: "Sleet", 317: "Light sleet", 320: "Sleet", 323: "Light snow",
    326: "Light snow", 329: "Snow", 332: "Snow", 335: "Heavy snow",
    338: "Heavy snow", 350: "Ice pellets", 353: "Light showers",
    356: "Showers", 359: "Heavy showers", 362: "Sleet showers",
    365: "Sleet showers", 368: "Snow showers", 371: "Snow showers",
    374: "Ice showers", 377: "Ice showers", 386: "Thundery showers",
    389: "Thundery rain", 392: "Thundery snow", 395: "Heavy snow showers",
}


def _desc(cond: dict) -> str:
    try:
        code = int(cond.get("weatherCode", 0))
    except (TypeError, ValueError):
        code = 0
    if code in _CONDITION:
        return _CONDITION[code]
    try:
        return str(cond.get("weatherDesc", [{}])[0].get("value", "")).strip()
    except Exception:
        return ""


def parse_forecast(data: Any, units: str = "f") -> dict | None:
    """Parse a wttr.in j1 payload into a render-ready forecast dict, or None.

    Shape: ``{location, units, current: {...}, days: [{...}]}``. Pure: it only
    reads the dict it is handed. Returns None when the payload is unusable.
    """
    if not isinstance(data, dict):
        return None
    units = "c" if str(units).lower() == "c" else "f"
    u = "F" if units == "f" else "C"
    cc = data.get("current_condition")
    if not cc or not isinstance(cc, list) or not isinstance(cc[0], dict):
        return None
    cond = cc[0]
    current = {
        "temp": cond.get("temp_F" if units == "f" else "temp_C", "?"),
        "feels": cond.get("FeelsLikeF" if units == "f" else "FeelsLikeC", "?"),
        "humidity": cond.get("humidity", "?"),
        "wind": cond.get("windspeedMiles" if units == "f" else "windspeedKmph", "?"),
        "wind_unit": "mph" if units == "f" else "kph",
        "desc": _desc(cond),
        "unit": u,
    }
    tags = ("Today", "Tomorrow")
    days: list[dict] = []
    for i, day in enumerate(data.get("weather", []) or []):
        if not isinstance(day, dict):
            continue
        # Pick a representative midday condition where the hourly data has one.
        hourly = day.get("hourly") or []
        mid = hourly[len(hourly) // 2] if hourly else {}
        days.append({
            "label": tags[i] if i < len(tags) else str(day.get("date", "")),
            "date": str(day.get("date", "")),
            "hi": day.get("maxtempF" if units == "f" else "maxtempC", "?"),
            "lo": day.get("mintempF" if units == "f" else "mintempC", "?"),
            "desc": _desc(mid) if isinstance(mid, dict) else "",
            "unit": u,
        })
    if not days and not current.get("temp"):
        return None
    return {"units": units, "current": current, "days": days}


async def fetch_forecast(location: str = "", units: str = "f") -> dict | None:
    """Fetch and parse the wttr.in forecast for ``location``. None on any error.

    A blank location lets wttr.in geolocate from the requester (this server's
    egress) IP, matching the Stream Deck widget's behaviour."""
    import httpx
    loc = (location or "").strip().replace(" ", "+")
    url = f"https://wttr.in/{loc}?format=j1"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers={"User-Agent": "foodassistant-weather/1.0"})
        if r.status_code != 200:
            return None
        parsed = parse_forecast(r.json(), units)
    except Exception:  # noqa: BLE001 - any failure is "unavailable", never a crash
        return None
    if parsed is not None:
        parsed["location"] = location
    return parsed
