"""Tests for advanced Stream Deck per-key overrides (FoodAssistant-a99).

These cover parsing the override list into ActionSpec entries, stamping them
onto a built page layout, the streamdeck Config field round-trip through
config.toml, and the app Settings round-trip through settings.json. All are
pure logic: no deck, no network, no Docker.

Run: python -m pytest tests/test_streamdeck_overrides.py -q
"""
from __future__ import annotations

import json


from foodassistant_streamdeck import actions, config, layout


# -- override_to_spec / overrides_to_specs ---------------------------------


def test_ha_action_entity_builds_ha_entity_spec():
    spec = actions.override_to_spec(
        2, {"slot": 2, "type": "ha_action", "entity_id": "light.kitchen",
            "label": "Kitchen"}
    )
    assert spec is not None
    assert spec.kind == "ha_entity"
    assert spec.ha_entity_id == "light.kitchen"
    # No explicit service: defaults to a toggle.
    assert spec.ha_service == "homeassistant.toggle"
    assert spec.label == "Kitchen"
    assert spec.name == "override_2"


def test_ha_action_bare_service_implies_entity():
    spec = actions.override_to_spec(
        0, {"slot": 0, "type": "ha_action", "service": "script.goodnight"}
    )
    assert spec is not None
    assert spec.kind == "ha_entity"
    assert spec.ha_service == "script.goodnight"
    # A bare service like script.goodnight implies its own entity target.
    assert spec.ha_entity_id == "script.goodnight"
    # Label derived from the service tail when none supplied.
    assert spec.label == "Goodnight"


def test_ha_action_without_entity_or_service_is_skipped():
    assert actions.override_to_spec(1, {"type": "ha_action", "label": "x"}) is None


def test_timer_override_carries_preset_minutes():
    spec = actions.override_to_spec(
        3, {"slot": 3, "type": "timer", "minutes": 10, "label": "Pasta"}
    )
    assert spec is not None
    assert spec.kind == "timer"
    assert spec.timer_minutes == 10
    assert spec.label == "Pasta"


def test_timer_override_bad_minutes_falls_back_to_zero():
    spec = actions.override_to_spec(3, {"type": "timer", "minutes": "abc"})
    assert spec is not None
    assert spec.timer_minutes == 0
    assert spec.label == "Timer"


def test_weather_override_carries_location():
    spec = actions.override_to_spec(
        4, {"slot": 4, "type": "weather", "location": "Boston", "label": "Home"}
    )
    assert spec is not None
    assert spec.kind == "weather"
    assert spec.weather_location == "Boston"
    assert spec.label == "Home"


def test_weather_override_accepts_source_alias():
    spec = actions.override_to_spec(4, {"type": "weather", "source": "90210"})
    assert spec is not None
    assert spec.weather_location == "90210"


def test_default_and_unknown_types_return_none():
    assert actions.override_to_spec(0, {"type": "default"}) is None
    assert actions.override_to_spec(0, {"type": "nonsense"}) is None
    assert actions.override_to_spec(0, {}) is None
    assert actions.override_to_spec(0, "not a dict") is None


def test_overrides_to_specs_maps_by_slot():
    overrides = [
        {"slot": 0, "type": "timer", "minutes": 5},
        {"slot": 2, "type": "weather", "location": "NYC"},
        {"slot": 4, "type": "ha_action", "entity_id": "switch.fan"},
    ]
    specs = actions.overrides_to_specs(overrides, key_count=15)
    assert set(specs) == {0, 2, 4}
    assert specs[0].kind == "timer"
    assert specs[2].kind == "weather"
    assert specs[4].kind == "ha_entity"


def test_overrides_to_specs_ignores_out_of_range_slots():
    overrides = [
        {"slot": -1, "type": "timer", "minutes": 5},
        {"slot": 99, "type": "timer", "minutes": 5},
        {"slot": 1, "type": "timer", "minutes": 5},
    ]
    specs = actions.overrides_to_specs(overrides, key_count=6)
    assert set(specs) == {1}


def test_overrides_to_specs_last_wins_on_duplicate_slot():
    overrides = [
        {"slot": 1, "type": "timer", "minutes": 5},
        {"slot": 1, "type": "weather", "location": "NYC"},
    ]
    specs = actions.overrides_to_specs(overrides, key_count=6)
    assert specs[1].kind == "weather"


def test_overrides_to_specs_skips_non_dict_and_bad_slot():
    overrides = ["x", {"type": "timer"}, {"slot": "nan", "type": "timer"}]
    specs = actions.overrides_to_specs(overrides, key_count=6)
    assert specs == {}


# -- layout.apply_overrides ------------------------------------------------


def test_apply_overrides_replaces_correct_slot_single_page():
    pages = layout.build_pages(["expiring", "pending", "commit"], 15)
    specs = actions.overrides_to_specs(
        [{"slot": 1, "type": "timer", "minutes": 5, "label": "T"}], 15
    )
    layout.apply_overrides(pages, specs, 15)
    assert pages[0][0].name == "expiring"
    assert pages[0][1].kind == "timer"
    assert pages[0][1].label == "T"
    assert pages[0][2].name == "commit"


def test_apply_overrides_can_fill_a_blank_slot():
    pages = layout.build_pages(["expiring"], 6)
    # Slot 3 is blank in the default single page; an override fills it.
    specs = actions.overrides_to_specs(
        [{"slot": 3, "type": "weather", "location": "NYC"}], 6
    )
    layout.apply_overrides(pages, specs, 6)
    assert pages[0][3] is not None
    assert pages[0][3].kind == "weather"


def test_apply_overrides_no_overrides_is_noop():
    pages = layout.build_pages(["expiring", "pending"], 15)
    before = [s.name if s else None for s in pages[0]]
    layout.apply_overrides(pages, {}, 15)
    after = [s.name if s else None for s in pages[0]]
    assert before == after


def test_apply_overrides_spans_pages_skipping_cycle_key():
    # On a paginated layout the last key of each page is reserved for paging, so
    # 5 slots per page are usable. A spec at absolute slot 6 lands at page 1,
    # position 1. (apply_overrides indexes by absolute slot directly, so this
    # tests the page-walking math independent of the single-deck slot clamp.)
    pages = layout.build_pages(["expiring"] * 12, 6)
    assert len(pages) > 1
    spec = actions.override_to_spec(6, {"type": "timer", "minutes": 3})
    layout.apply_overrides(pages, {6: spec}, 6)
    assert pages[1][1].kind == "timer"


# -- streamdeck Config round-trip ------------------------------------------


def test_config_loads_key_overrides_from_toml(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text(
        'keys = ["expiring", "pending"]\n\n'
        '[[key_overrides]]\n'
        'slot = 1\n'
        'type = "timer"\n'
        'minutes = 10\n'
        'label = "Pasta"\n'
    )
    cfg = config.load(f)
    assert isinstance(cfg.key_overrides, list)
    assert cfg.key_overrides[0]["slot"] == 1
    assert cfg.key_overrides[0]["type"] == "timer"
    specs = actions.overrides_to_specs(cfg.key_overrides, key_count=15)
    assert specs[1].kind == "timer"
    assert specs[1].timer_minutes == 10


def test_config_default_key_overrides_empty():
    cfg = config.Config().validated()
    assert cfg.key_overrides == []


# -- app Settings round-trip -----------------------------------------------


def test_app_settings_persists_key_overrides(tmp_path):
    from app.config import Settings, _SAVEABLE

    assert "streamdeck_key_overrides" in _SAVEABLE
    overrides = [
        {"slot": 0, "type": "timer", "minutes": 5, "label": "Eggs"},
        {"slot": 2, "type": "weather", "location": "Boston"},
    ]
    s = Settings(data_dir=str(tmp_path))
    s.save({"streamdeck_key_overrides": overrides})

    saved = json.loads((tmp_path / "settings.json").read_text())
    assert saved["streamdeck_key_overrides"] == overrides

    # A freshly-loaded Settings sees the persisted value.
    s2 = Settings(data_dir=str(tmp_path))
    s2.apply(saved)
    assert s2.streamdeck_key_overrides == overrides
