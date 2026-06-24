"""Pure-logic tests for the Stream Deck controller.

These cover config loading, layout/paging, the action registry, status
polling, the commit handler, and key rendering. None of them need a deck
attached or the StreamDeck device library installed, so they import only the
hardware-free modules (config, layout, actions, render), never controller.

Run: python -m pytest tests/test_streamdeck.py -q
"""
from __future__ import annotations

import asyncio

import pytest

from foodassistant_streamdeck import actions, config, layout, render


# -- config ----------------------------------------------------------------


def test_defaults_have_known_actions():
    cfg = config.Config().validated()
    assert cfg.keys, "default key list should not be empty"
    assert all(name in actions.ACTIONS for name in cfg.keys)


def test_load_keys_as_plain_list(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('keys = ["pending", "commit"]\n')
    cfg = config.load(f)
    assert cfg.keys == ["pending", "commit"]


def test_load_keys_as_table_array(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text(
        "[[keys]]\naction = 'expiring'\n[[keys]]\naction = 'add'\n"
    )
    cfg = config.load(f)
    assert cfg.keys == ["expiring", "add"]


def test_unknown_keys_dropped_and_fallback(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('keys = ["bogus", "nope"]\n')
    cfg = config.load(f)
    # Nothing valid was given, so it falls back to the default order.
    assert cfg.keys == list(actions.DEFAULT_ORDER)


def test_numbers_are_clamped(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text("brightness = 999\npoll_seconds = 1\nsoon_days = -4\n")
    cfg = config.load(f)
    assert cfg.brightness == 100
    assert cfg.poll_seconds == 5
    assert cfg.soon_days == 0


def test_env_overrides_file(tmp_path, monkeypatch):
    f = tmp_path / "config.toml"
    f.write_text('base_url = "http://fromfile:1"\napi_key = "fromfile"\n')
    monkeypatch.setenv(config.ENV_BASE_URL, "http://fromenv:2")
    monkeypatch.setenv(config.ENV_API_KEY, "fromenv")
    cfg = config.load(f)
    assert cfg.base_url == "http://fromenv:2"
    assert cfg.api_key == "fromenv"


# -- layout / paging -------------------------------------------------------


def test_supported_sizes():
    assert layout.supported_key_counts() == (6, 15, 32)


def test_single_page_pads_to_key_count():
    pages = layout.build_pages(["pending", "commit"], 15)
    assert len(pages) == 1
    assert len(pages[0]) == 15
    assert pages[0][0].name == "pending"
    assert pages[0][2] is None  # padded blank


def test_no_paging_key_when_everything_fits():
    pages = layout.build_pages(list(actions.DEFAULT_ORDER), 15)
    names = [s.name for s in pages[0] if s is not None]
    assert "page_next" not in names


def test_mini_paginates_overflow():
    names = ["expiring", "pending", "commit", "add", "inventory", "cook", "brightness"]
    pages = layout.build_pages(names, 6)
    assert len(pages) == 2
    # Each page is exactly the deck size and ends with the page-cycle key.
    for page in pages:
        assert len(page) == 6
        assert page[-1].name == "page_next"
    # Five real actions fit before the More key on page one.
    first = [s.name for s in pages[0][:-1] if s is not None]
    assert first == ["expiring", "pending", "commit", "add", "inventory"]


def test_build_pages_rejects_bad_size():
    with pytest.raises(ValueError):
        layout.build_pages(["pending"], 0)


# -- action registry -------------------------------------------------------


def test_default_order_resolves():
    for name in actions.DEFAULT_ORDER:
        assert actions.resolve(name) is not None


def test_status_fields_match_poll_output():
    poll_keys = {"expiring", "pending"}
    for spec in actions.ACTIONS.values():
        if spec.kind == "status":
            assert spec.status_field in poll_keys


# -- polling ---------------------------------------------------------------


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    """Minimal async stand-in for httpx.AsyncClient."""

    def __init__(self, get_map=None, post_map=None):
        self.get_map = get_map or {}
        self.post_map = post_map or {}
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url))
        for suffix, resp in self.get_map.items():
            if url.endswith(suffix):
                return resp
        return _Resp(404, {})

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url))
        for suffix, resp in self.post_map.items():
            if url.endswith(suffix):
                return resp
        return _Resp(404, {})


def test_poll_status_sums_urgency_buckets():
    client = _FakeClient(
        get_map={
            "/expiring/summary": _Resp(
                200,
                {
                    "expired": 1,
                    "today": 2,
                    "within_3_days": 3,
                    "within_7_days": 4,
                    "within_30_days": 99,
                },
            ),
            "/pending/count": _Resp(200, {"count": 5}),
        }
    )
    out = asyncio.run(actions.poll_status(client, "http://x", soon_days=7))
    assert out == {"expiring": 1 + 2 + 3 + 4, "pending": 5}


def test_poll_status_excludes_week_bucket_for_short_window():
    client = _FakeClient(
        get_map={
            "/expiring/summary": _Resp(
                200,
                {"expired": 0, "today": 1, "within_3_days": 2, "within_7_days": 4},
            ),
            "/pending/count": _Resp(200, {"count": 0}),
        }
    )
    out = asyncio.run(actions.poll_status(client, "http://x", soon_days=3))
    assert out["expiring"] == 3  # week bucket dropped


def test_poll_status_tolerates_errors():
    out = asyncio.run(actions.poll_status(_FakeClient(), "http://x"))
    assert out == {"expiring": 0, "pending": 0}


# -- action handlers -------------------------------------------------------


def _ctx(client):
    refreshed = {"n": 0}

    async def refresh():
        refreshed["n"] += 1

    async def navigate(path):
        return True

    ctx = actions.ActionContext(
        client=client,
        base_url="http://x",
        refresh=refresh,
        navigate=navigate,
        cycle_brightness=lambda: 80,
        page_next=lambda: None,
        page_prev=lambda: None,
    )
    return ctx, refreshed


def test_commit_action_reports_count_and_refreshes():
    client = _FakeClient(post_map={"/pending/commit": _Resp(200, {"imported": 4})})
    ctx, refreshed = _ctx(client)
    msg = asyncio.run(actions.run_action(actions.ACTIONS["commit"], ctx))
    assert msg == "committed 4"
    assert refreshed["n"] == 1


def test_commit_action_handles_failure():
    client = _FakeClient(post_map={"/pending/commit": _Resp(500, {})})
    ctx, _ = _ctx(client)
    msg = asyncio.run(actions.run_action(actions.ACTIONS["commit"], ctx))
    assert "failed" in msg


def test_status_press_triggers_refresh():
    ctx, refreshed = _ctx(_FakeClient())
    msg = asyncio.run(actions.run_action(actions.ACTIONS["pending"], ctx))
    assert msg == "refreshed"
    assert refreshed["n"] == 1


def test_brightness_action_returns_percent():
    ctx, _ = _ctx(_FakeClient())
    msg = asyncio.run(actions.run_action(actions.ACTIONS["brightness"], ctx))
    assert msg == "brightness 80%"


# -- rendering -------------------------------------------------------------


def test_render_key_size_and_mode():
    img = render.render_key(72, 72, label="Cook", color="#7e22ce")
    assert img.size == (72, 72)
    assert img.mode == "RGB"


def test_render_status_key_with_count():
    img = render.render_key(96, 96, label="Pending", color="#1d4ed8", count=3, alert=True)
    assert img.size == (96, 96)


def test_blank_key():
    img = render.blank_key(80, 80)
    assert img.size == (80, 80)
    assert img.mode == "RGB"


def test_long_label_shrinks_to_fit():
    # A wide label must not pick a font wider than the fit fraction of the key.
    from PIL import ImageDraw

    # Start from an oversized font; fit must step it down under the limit while
    # staying above the floor so the result is the shrink path, not the wrap one.
    img = render.render_key(96, 96, label="Inventory", color="#1d4ed8")
    draw = ImageDraw.Draw(img)
    limit = int(96 * 0.90)
    big = render._fit_font(draw, "Inventory", 40, limit, floor=12)
    assert render._text_width(draw, "Inventory", big) <= limit


def test_very_long_word_wraps_at_floor():
    from PIL import ImageDraw

    img = render.render_key(48, 48, label="Refrigeration", color="#1d4ed8")
    draw = ImageDraw.Draw(img)
    floor_font = render._font(render._MIN_FONT_PX)
    lines = render._wrap_single_word(draw, "Refrigeration", floor_font, int(48 * 0.90))
    assert len(lines) >= 2
    assert "".join(lines) == "Refrigeration"


def test_density_factor_clamped_and_inverse():
    # Smaller keys scale up, larger keys scale down, both within the band.
    small = render._density_factor(48, 96)
    large = render._density_factor(120, 96)
    assert 0.80 <= large < 1.0 < small <= 1.25
    assert render._density_factor(96, 96) == 1.0


# -- rotation config -------------------------------------------------------


def test_rotation_defaults_to_zero():
    assert config.Config().validated().rotation == 0


def test_rotation_accepts_allowed_values(tmp_path):
    for deg in (0, 90, 180, 270):
        f = tmp_path / "c.toml"
        f.write_text(f"rotation = {deg}\n")
        assert config.load(f).rotation == deg


def test_rotation_rejects_bad_value(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("rotation = 45\n")
    assert config.load(f).rotation == 0


# -- rotation index remap --------------------------------------------------


def test_rotated_index_180_reverses_grid():
    # 15-key deck (5x3): top-left (0) maps to bottom-right (14) and back.
    assert layout.rotated_index(0, 15, 180) == 14
    assert layout.rotated_index(14, 15, 180) == 0
    # 180 is its own inverse for every key.
    for i in range(15):
        assert layout.rotated_index(layout.rotated_index(i, 15, 180), 15, 180) == i


def test_rotated_index_zero_is_identity():
    for i in range(32):
        assert layout.rotated_index(i, 32, 0) == i


def test_rotated_index_unknown_size_passthrough():
    assert layout.rotated_index(3, 7, 180) == 3


# -- timer widget ----------------------------------------------------------


def test_timer_idle_shows_base_label():
    t = actions.TimerState()
    assert t.label("Timer 1") == "Timer 1"
    assert not t.is_running()
    assert not t.alerting


def test_timer_press_cycles_presets():
    t = actions.TimerState()
    t.press()  # -> 5 min
    assert t.is_running()
    assert t.remaining_seconds() > 0


def test_timer_press_through_all_resets_to_idle():
    t = actions.TimerState()
    for _ in range(len(actions.TIMER_PRESETS) + 1):
        t.press()
    assert not t.is_running()
    assert t.label("T") == "T"


def test_timer_label_shows_countdown():
    t = actions.TimerState()
    t.press()  # 5 min
    label = t.label("Timer")
    assert ":" in label  # MM:SS format


def test_timer_alerting_on_expiry():
    t = actions.TimerState()
    t.press()
    # Force expiry by backdating the deadline
    t._deadline = t._deadline - 400
    expired = t.tick()
    assert expired
    assert t.alerting
    assert t.label("T") == "Done!"


def test_timer_dismiss_alert():
    t = actions.TimerState()
    t.press()
    t._deadline = t._deadline - 400
    t.tick()
    assert t.alerting
    t.press()  # dismiss
    assert not t.alerting
    assert t.label("T") == "T"


def test_timer_action_registered():
    for name in ("timer_1", "timer_2", "timer_3"):
        assert name in actions.ACTIONS
        assert actions.ACTIONS[name].kind == "timer"


def test_timer_press_via_action_context():
    pressed = {}

    def fake_timer_press(name):
        pressed["name"] = name

    ctx = actions.ActionContext(
        client=None,
        base_url="http://x",
        refresh=lambda: None,
        navigate=lambda _: None,
        cycle_brightness=lambda: 80,
        page_next=lambda: None,
        page_prev=lambda: None,
        timer_press=fake_timer_press,
    )
    asyncio.run(actions.run_action(actions.ACTIONS["timer_1"], ctx))
    assert pressed.get("name") == "timer_1"


# -- weather widget ---------------------------------------------------------


def test_weather_action_registered():
    assert "weather" in actions.ACTIONS
    spec = actions.ACTIONS["weather"]
    assert spec.kind == "weather"


def test_weather_idle_shows_base_label():
    w = actions.WeatherState(location="", units="f")
    assert w.label("Weather") == "Weather"


def test_weather_label_after_fake_fetch():
    w = actions.WeatherState(location="", units="f")
    # Simulate a successful fetch by poking internal state directly.
    w._label = "72°F Sunny"
    w._fetched_at = __import__("time").monotonic()
    assert w.label("Weather") == "72°F Sunny"


def test_weather_color_default():
    w = actions.WeatherState()
    assert w.color("#123456") == "#1e40af"


def test_weather_config_loaded(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('weather_location = "New York"\nweather_units = "c"\nweather_poll_minutes = 30\n')
    cfg = config.load(f)
    assert cfg.weather_location == "New York"
    assert cfg.weather_units == "c"
    assert cfg.weather_poll_minutes == 30


def test_weather_refresh_via_context():
    refreshed = []

    async def fake_weather_refresh():
        refreshed.append(True)

    async def noop():
        pass

    ctx = actions.ActionContext(
        client=None,
        base_url="http://x",
        refresh=noop,
        navigate=lambda _: noop(),
        cycle_brightness=lambda: 80,
        page_next=lambda: None,
        page_prev=lambda: None,
        weather_refresh=fake_weather_refresh,
    )
    asyncio.run(actions.run_action(actions.ACTIONS["weather"], ctx))
    assert refreshed, "weather_refresh should have been called"


# -- HA entity -------------------------------------------------------------

def test_ha_actions_registered():
    for i in range(1, 6):
        name = f"ha_{i}"
        assert name in actions.ACTIONS
        assert actions.ACTIONS[name].kind == "ha_entity"


def test_ha_entity_state_idle():
    h = actions.HaEntityState("light.kitchen")
    assert h.label("Kitchen") == "Kitchen"
    assert h.color("#000") == "#000"


def test_ha_entity_state_on():
    import time
    h = actions.HaEntityState("light.kitchen", color_on="#f59e0b")
    h._state = "on"
    h._fetched_at = time.monotonic()
    assert h.is_on()
    assert "On" in h.label("Kitchen")
    assert h.color("#000") == "#f59e0b"


def test_ha_entity_state_off():
    import time
    h = actions.HaEntityState("light.kitchen", color_off="#334155")
    h._state = "off"
    h._fetched_at = time.monotonic()
    assert not h.is_on()
    assert "Off" in h.label("Kitchen")
    assert h.color("#000") == "#334155"


def test_ha_entity_state_unavailable():
    import time
    h = actions.HaEntityState("light.kitchen")
    h._state = "unavailable"
    h._fetched_at = time.monotonic()
    assert h.color("#000") == actions._HA_STATE_COLOR_ERROR


def test_ha_config_loaded(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text(
        'ha_base_url = "http://192.168.1.50:8123"\n'
        'ha_token = "abc123"\n'
        'ha_poll_seconds = 15\n'
        '[[ha_slots]]\n'
        'entity_id = "light.kitchen"\n'
        'service = "light.toggle"\n'
        'label = "Kitchen"\n'
    )
    cfg = config.load(f)
    assert cfg.ha_base_url == "http://192.168.1.50:8123"
    assert cfg.ha_token == "abc123"
    assert cfg.ha_poll_seconds == 15
    assert len(cfg.ha_slots) == 1
    assert cfg.ha_slots[0]["entity_id"] == "light.kitchen"


def test_ha_run_action_unconfigured():
    async def noop():
        pass

    ctx = actions.ActionContext(
        client=None,
        base_url="http://x",
        refresh=noop,
        navigate=lambda _: noop(),
        cycle_brightness=lambda: 80,
        page_next=lambda: None,
        page_prev=lambda: None,
    )
    msg = asyncio.run(actions.run_action(actions.ACTIONS["ha_1"], ctx))
    assert "not configured" in msg


# -- PIN keypad ------------------------------------------------------------


def test_pin_buffer_accumulates_digits():
    b = actions.PinBuffer()
    assert b.is_empty()
    for ch in "1234":
        b.digit(ch)
    assert b.length() == 4
    assert b.value == "1234"
    assert not b.is_empty()


def test_pin_buffer_masks_and_never_shows_digits():
    b = actions.PinBuffer()
    for ch in "9173":
        b.digit(ch)
    masked = b.masked()
    assert len(masked) == 4
    # The mask must not leak any actual digit.
    assert not any(c.isdigit() for c in masked)


def test_pin_buffer_backspace_and_clear():
    b = actions.PinBuffer()
    for ch in "555":
        b.digit(ch)
    b.backspace()
    assert b.value == "55"
    b.clear()
    assert b.is_empty()
    assert b.value == ""
    # Backspace on an empty buffer is a no-op, not an error.
    b.backspace()
    assert b.is_empty()


def test_pin_buffer_ignores_non_digits_and_overflow():
    b = actions.PinBuffer(max_len=3)
    b.digit("a")     # not a digit
    b.digit("12")    # not a single char
    assert b.is_empty()
    for ch in "12345":
        b.digit(ch)  # caps at max_len
    assert b.length() == 3
    assert b.value == "123"


def test_pin_action_registered():
    assert "pin" in actions.ACTIONS
    assert actions.ACTIONS["pin"].kind == "pin"


def test_keypad_specs_cover_digits_and_controls():
    specs = actions.keypad_specs()
    for d in "0123456789":
        assert specs[f"keypad_{d}"].keypad_key == d
        assert specs[f"keypad_{d}"].kind == "keypad"
    for ctl in (actions.KEYPAD_CLEAR, actions.KEYPAD_ENTER, actions.KEYPAD_CANCEL):
        assert specs[f"keypad_{ctl}"].keypad_key == ctl


def test_pin_action_enters_keypad_via_context():
    entered = {"n": 0}

    async def noop():
        pass

    ctx = actions.ActionContext(
        client=None,
        base_url="http://x",
        refresh=noop,
        navigate=lambda _: noop(),
        cycle_brightness=lambda: 80,
        page_next=lambda: None,
        page_prev=lambda: None,
        keypad_enter=lambda: entered.__setitem__("n", entered["n"] + 1),
    )
    msg = asyncio.run(actions.run_action(actions.ACTIONS["pin"], ctx))
    assert msg == "keypad"
    assert entered["n"] == 1


def test_keypad_press_dispatched_via_context():
    pressed = []

    async def fake_keypad_press(key):
        pressed.append(key)

    async def noop():
        pass

    ctx = actions.ActionContext(
        client=None,
        base_url="http://x",
        refresh=noop,
        navigate=lambda _: noop(),
        cycle_brightness=lambda: 80,
        page_next=lambda: None,
        page_prev=lambda: None,
        keypad_press=fake_keypad_press,
    )
    spec = actions.keypad_specs()["keypad_7"]
    msg = asyncio.run(actions.run_action(spec, ctx))
    assert msg == "keypad 7"
    assert pressed == ["7"]


def test_submit_pin_success():
    client = _FakeClient(post_map={"/ui/login": _Resp(303, {})})
    ok = asyncio.run(actions.submit_pin(client, "http://x", "1234"))
    assert ok is True
    assert client.calls == [("POST", "http://x/ui/login")]


def test_submit_pin_failure_on_401():
    client = _FakeClient(post_map={"/ui/login": _Resp(401, {})})
    ok = asyncio.run(actions.submit_pin(client, "http://x", "0000"))
    assert ok is False


def test_submit_pin_tolerates_errors():
    class Boom:
        async def post(self, *a, **k):
            raise RuntimeError("network down")

    ok = asyncio.run(actions.submit_pin(Boom(), "http://x", "1234"))
    assert ok is False


# -- keypad layout ---------------------------------------------------------


def test_keypad_pages_cover_all_keys_across_pages():
    for key_count in layout.supported_key_counts():
        pages = layout.build_keypad_pages(key_count)
        assert pages
        for page in pages:
            assert len(page) == key_count
        # Gather every keypad key across all pages: the full pad must be present
        # somewhere, even on a deck that has to paginate.
        keys = {
            s.keypad_key
            for page in pages
            for s in page
            if s is not None and s.kind == "keypad"
        }
        for d in "0123456789":
            assert d in keys
        assert actions.KEYPAD_CLEAR in keys
        assert actions.KEYPAD_ENTER in keys
        assert actions.KEYPAD_CANCEL in keys


def test_keypad_single_page_when_it_fits():
    # The 15-key Original holds the whole pad on one page.
    assert len(layout.build_keypad_pages(15)) == 1
    assert len(layout.build_keypad_pages(32)) == 1


def test_keypad_paginates_on_mini():
    # The 6-key Mini cannot fit the 13-key pad, so it spills onto more pages,
    # each ending in a wrapping page-cycle key.
    pages = layout.build_keypad_pages(6)
    assert len(pages) > 1
    for page in pages:
        assert page[-1].name == "page_next"


def test_keypad_pages_reject_bad_size():
    with pytest.raises(ValueError):
        layout.build_keypad_pages(0)


def test_keypad_xl_phone_block():
    # On the XL (8x4) the first three digits sit in the top-left row.
    page = layout.build_keypad_pages(32)[0]
    assert page[0].keypad_key == "1"
    assert page[1].keypad_key == "2"
    assert page[2].keypad_key == "3"


def test_ha_run_action_calls_service():
    import json
    calls = []

    class FakeResp:
        status_code = 200

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            pass
        async def post(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResp()

    original_spec = actions.ACTIONS["ha_1"]
    actions.ACTIONS["ha_1"] = actions.ActionSpec(
        name="ha_1", label="Kitchen", color="#000",
        kind="ha_entity",
        ha_entity_id="light.kitchen",
        ha_service="light.toggle",
    )

    refreshed = []

    async def fake_ha_refresh():
        refreshed.append(True)

    async def noop():
        pass

    import unittest.mock as mock
    with mock.patch("httpx.AsyncClient", return_value=FakeClient()):
        ctx = actions.ActionContext(
            client=None,
            base_url="http://x",
            refresh=noop,
            navigate=lambda _: noop(),
            cycle_brightness=lambda: 80,
            page_next=lambda: None,
            page_prev=lambda: None,
            ha_base_url="http://192.168.1.50:8123",
            ha_token="tok",
            ha_entity_refresh=fake_ha_refresh,
        )
        msg = asyncio.run(actions.run_action(actions.ACTIONS["ha_1"], ctx))

    actions.ACTIONS["ha_1"] = original_spec
    assert calls, "should have POSTed to HA"
    assert "light/toggle" in calls[0]["url"]
    assert refreshed, "ha_entity_refresh should have been called"
