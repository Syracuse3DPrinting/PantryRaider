"""Server-side weather forecast parsing (FoodAssistant-afqd)."""
from __future__ import annotations

import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE))

from app.services import weather  # noqa: E402


_SAMPLE = {
    "current_condition": [{
        "temp_F": "72", "temp_C": "22", "FeelsLikeF": "75", "FeelsLikeC": "24",
        "humidity": "40", "windspeedMiles": "8", "windspeedKmph": "13",
        "weatherCode": "116", "weatherDesc": [{"value": "Partly cloudy"}],
    }],
    "weather": [
        {"date": "2026-06-30", "maxtempF": "80", "mintempF": "60",
         "maxtempC": "27", "mintempC": "16",
         "hourly": [{"weatherCode": "113"}, {"weatherCode": "113"}, {"weatherCode": "113"}]},
        {"date": "2026-07-01", "maxtempF": "78", "mintempF": "58",
         "maxtempC": "25", "mintempC": "14", "hourly": []},
    ],
}


def test_parse_forecast_fahrenheit():
    fc = weather.parse_forecast(_SAMPLE, "f")
    assert fc["units"] == "f"
    assert fc["current"]["temp"] == "72"
    assert fc["current"]["feels"] == "75"
    assert fc["current"]["wind"] == "8" and fc["current"]["wind_unit"] == "mph"
    assert fc["current"]["desc"] == "Partly cloudy"
    assert fc["current"]["unit"] == "F"
    assert fc["days"][0]["label"] == "Today" and fc["days"][0]["hi"] == "80"
    assert fc["days"][0]["desc"] == "Sunny"   # from the midday hourly code 113
    assert fc["days"][1]["label"] == "Tomorrow"


def test_parse_forecast_celsius_uses_metric_fields():
    fc = weather.parse_forecast(_SAMPLE, "c")
    assert fc["units"] == "c"
    assert fc["current"]["temp"] == "22"
    assert fc["current"]["wind"] == "13" and fc["current"]["wind_unit"] == "kph"
    assert fc["days"][0]["hi"] == "27" and fc["days"][0]["unit"] == "C"


def test_parse_forecast_rejects_garbage():
    assert weather.parse_forecast(None) is None
    assert weather.parse_forecast({}, "f") is None  # no current_condition
    assert weather.parse_forecast("nope") is None


def test_fetch_forecast_retries_city_when_region_fails(monkeypatch):
    import asyncio
    calls = []

    async def fake_one(client, loc, units):
        calls.append(loc)
        if loc == "Syracuse":
            return ({"units": units, "current": {"temp": "70"}, "days": []}, "")
        return (None, "wttr.in returned HTTP 404")

    monkeypatch.setattr(weather, "_fetch_one", fake_one)
    fc, err = asyncio.run(weather.fetch_forecast("Syracuse, NY", "f"))
    assert fc is not None and err == ""
    assert fc["location"] == "Syracuse, NY"     # original label preserved
    assert calls == ["Syracuse,+NY", "Syracuse"]  # tried precise, then city only


def test_fetch_forecast_reports_error(monkeypatch):
    import asyncio

    async def fake_one(client, loc, units):
        return (None, "could not reach wttr.in (ConnectError)")

    monkeypatch.setattr(weather, "_fetch_one", fake_one)
    fc, err = asyncio.run(weather.fetch_forecast("Nowhere", "f"))
    assert fc is None
    assert "could not reach wttr.in" in err


def test_unknown_weather_code_falls_back_to_desc():
    data = {"current_condition": [{"temp_F": "50", "weatherCode": "99999",
                                   "weatherDesc": [{"value": "Weird sky"}]}],
            "weather": []}
    fc = weather.parse_forecast(data, "f")
    assert fc["current"]["desc"] == "Weird sky"
