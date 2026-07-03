"""Settings reorganization (docs/design/settings-reorg.md, FoodAssistant-y78w).

The Settings page has one menu of ten intent groups (the old Settings /
Personalization toggle is gone). These tests guard the new structure:

* every group pill renders for the shapes it applies to,
* no form control from the pre-reorg page was lost in the move (the id lists
  below were collected from the old template, per deployment shape),
* old ``#pane-*`` deep links resolve through the ``PANE_HASH_ALIASES`` map,
* the Devices pane keeps the This Device / Start Page / Stream Deck toggle.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SERVICE = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(_SERVICE))

from app.config import settings  # noqa: E402


@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app

    cwd = os.getcwd()
    os.chdir(_SERVICE)
    monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "auth_required", False)
    monkeypatch.setattr(settings, "auth_password", "")
    try:
        yield TestClient(app)
    finally:
        os.chdir(cwd)


def _render(client, monkeypatch, *, mode: str, is_pi: bool) -> str:
    monkeypatch.setattr(settings, "deployment_mode", mode)
    with patch.object(type(settings), "is_configured", lambda self: True), \
         patch("app.routers.setup.is_raspberry_pi", return_value=is_pi), \
         patch("app.templating.is_raspberry_pi", return_value=is_pi):
        r = client.get("/setup")
    assert r.status_code == 200
    return r.text


SHAPES = [("server", False), ("pi_hosted", True), ("pi_remote", True)]

# The ten intent groups and which shapes get a pill for each.
GROUP_PILLS = {
    "pane-appearance": {"server", "pi_hosted", "pi_remote"},
    "pane-screen": {"server", "pi_hosted", "pi_remote"},
    "pane-scanning": {"server", "pi_hosted", "pi_remote"},
    "pane-recipes": {"server", "pi_hosted", "pi_remote"},
    "pane-inventory": {"server", "pi_hosted"},
    "pane-connections": {"server", "pi_hosted", "pi_remote"},
    "pane-devices": {"server", "pi_hosted", "pi_remote"},
    "pane-security": {"server", "pi_hosted", "pi_remote"},
    "pane-backups": {"server", "pi_hosted", "pi_remote"},
    "pane-advanced": {"server", "pi_hosted", "pi_remote"},
}

# Every form-control id the settings side (below the side menu) rendered
# before the reorganization, per deployment shape. The reorganization moves
# markup between panes; it must never drop a control. Collected from the
# pre-reorg template render.
_COMMON = [
    "anthropic_api_key", "anthropic_model", "anthropic_model_sel", "api_key",
    "auth_password", "auth_required", "auto_update",
    "background_file", "background_image_url", "background_opacity",
    "backup_include_secrets", "barcode_autocheck_shopping",
    "barcode_enrichment", "barcode_global_capture", "barcode_llm_fallback",
    "cook_ai_context",
    "custom-heading-icon", "custom-heading-label",
    "custom-tab-icon", "custom-tab-label", "custom-tab-url",
    "custom_theme_accent", "custom_theme_base", "custom_theme_bg",
    "custom_theme_name", "custom_theme_primary", "custom_theme_surface",
    "custom_theme_text",
    "debug_logging", "device_hostname",
    "enrich_model", "enrich_model_sel", "enrich_provider",
    "expiring_soon_days",
    "floating_nav_autohide_streamdeck", "floating_nav_position",
    "gemini_api_key", "gemini_model", "gemini_model_sel",
    "grocy_api_key", "grocy_base_url", "grocy_public_url",
    "ha_camera_popup_seconds", "ha_events_device", "ha_events_enabled",
    "mealie_api_key", "mealie_base_url", "mealie_public_url",
    "nav_visibility",
    "ollama_base_url", "ollama_model", "ollama_model_sel",
    "openai_api_key", "openai_model", "openai_model_sel",
    "perishable_days", "qr_public_url", "qr_url_mode", "quiet_mode",
    "rclone_remote", "rclone_schedule_hours", "recipe_source",
    "restore-file", "scanner-test-input", "scanner_type",
    "settings-search", "spoonacular_api_key", "staple_items",
    "start_icon_color", "start_key_style", "start_page_enabled",
    "start_page_keys",
    "streamdeck_ha_base_url", "streamdeck_ha_token",
    "streamdeck_weather_location", "streamdeck_weather_units",
    "suggest_per_tier", "themealdb_api_key", "totp-code",
    "ui_theme", "usb_backup_interval_hours", "vision_provider",
    "appliance_stand_mixer", "appliance_air_fryer", "appliance_oven",
]
_PI_COMMON = [
    "display_idle_timeout", "display_touch", "display_type",
    "full-restore-source", "has_streamdeck", "kms_rotation", "new_hostname",
    "scheduled_reboot_time", "screensaver_minutes", "screensaver_mode",
    "screensaver_speed", "sd-profile-name-input", "sd-profile-select",
    "streamdeck_brightness", "streamdeck_icon_color",
    "streamdeck_idle_timeout", "streamdeck_key_count",
    "streamdeck_key_style", "streamdeck_rotation",
    "ui_scale", "wake_on_motion", "wifi_password", "wifi_ssid",
]
EXPECTED_IDS = {
    "server": _COMMON + [
        "ai_token_budget",
        "cam-ip-host", "cam-ip-name", "cam-ip-pass", "cam-ip-path",
        "cam-ip-port", "cam-ip-preset", "cam-ip-user", "cam-scan-cidr",
        "scan_cidr", "timezone",
        "tunnel_mode_cloudflare", "tunnel_mode_off",
        "tunnel_mode_subscription", "tunnel_token",
    ],
    "pi_hosted": _COMMON + _PI_COMMON + [
        "ai_token_budget",
        "cam-ip-host", "cam-ip-name", "cam-ip-pass", "cam-ip-path",
        "cam-ip-port", "cam-ip-preset", "cam-ip-user", "cam-scan-cidr",
        "scan_cidr", "timezone",
        "tunnel_mode_cloudflare", "tunnel_mode_off",
        "tunnel_mode_subscription", "tunnel_token",
        "switch_server_url", "switch_upstream_api_key",
    ],
    "pi_remote": _COMMON + _PI_COMMON + [
        "kiosk_pin", "kiosk_readonly_when_locked",
        "remote_server_url", "upstream_api_key",
    ],
}


def test_single_menu_with_ten_groups(client, monkeypatch):
    for mode, is_pi in SHAPES:
        html = _render(client, monkeypatch, mode=mode, is_pi=is_pi)
        for pane, shapes in GROUP_PILLS.items():
            pill = f'data-bs-target="#{pane}"' in html
            assert pill == (mode in shapes), (mode, pane, pill)
        # The Settings / Personalization toggle is gone.
        assert "showSettingsMenu(" not in html
        assert 'data-mgroup="p"' not in html


def test_no_setting_lost_in_reorg(client, monkeypatch):
    """Every form control from the pre-reorg settings page still renders."""
    for mode, is_pi in SHAPES:
        html = _render(client, monkeypatch, mode=mode, is_pi=is_pi)
        region = html.split('<div class="side-menu">', 1)[1]
        found = set(
            m.group(2)
            for m in re.finditer(
                r'<(input|select|textarea)\b[^>]*\bid="([^"]+)"', region
            )
        )
        missing = [i for i in EXPECTED_IDS[mode] if i not in found]
        assert not missing, (mode, missing)


def test_old_pane_hashes_have_aliases(client, monkeypatch):
    html = _render(client, monkeypatch, mode="server", is_pi=False)
    for old, new in {
        "pane-theme": "pane-appearance",
        "pane-navigation": "pane-appearance",
        "pane-display": "pane-screen",
        "pane-ai": "pane-scanning",
        "pane-hardware": "pane-scanning",
        "pane-personalization-recipes": "pane-recipes",
        "pane-personalization-storage": "pane-inventory",
        "pane-homeassistant": "pane-connections",
        "pane-cameras": "pane-connections",
        "pane-tunnel": "pane-connections",
        "pane-start-page": "pane-devices",
        "pane-streamdeck": "pane-devices",
        "pane-network": "pane-devices",
        "pane-upstream": "pane-devices",
        "pane-data": "pane-backups",
    }.items():
        assert f"'{old}': '{new}'," in html, f"missing alias {old} -> {new}"
    # Dissolved panes leave no dead pane divs behind (start-page/streamdeck
    # keep their ids as Devices sub-areas).
    for gone in ("pane-theme", "pane-navigation", "pane-display", "pane-ai",
                 "pane-hardware", "pane-personalization-recipes",
                 "pane-personalization-storage", "pane-homeassistant",
                 "pane-cameras", "pane-tunnel", "pane-network",
                 "pane-upstream", "pane-data"):
        assert f'id="{gone}"' not in html, f"stale pane div: {gone}"


def test_devices_pane_sub_toggle(client, monkeypatch):
    # On a Pi all three sub-areas are offered; off-Pi there is no deck button.
    pi = _render(client, monkeypatch, mode="pi_hosted", is_pi=True)
    assert "showDeckStart('devices')" in pi
    assert "showDeckStart('start')" in pi
    assert "showDeckStart('deck')" in pi
    assert 'id="pane-start-page"' in pi and 'id="pane-streamdeck"' in pi
    srv = _render(client, monkeypatch, mode="server", is_pi=False)
    assert "showDeckStart('devices')" in srv
    assert 'id="pane-start-page"' in srv
    assert 'id="pane-streamdeck"' not in srv


def test_satellite_devices_pane_holds_main_server(client, monkeypatch):
    sat = _render(client, monkeypatch, mode="pi_remote", is_pi=True)
    dev = sat.split('id="pane-devices"', 1)[1].split('id="pane-', 1)[0]
    assert "remote_server_url" in dev
    assert "syncFromUpstream" in dev
    # The kiosk PIN moved to Security & Access.
    sec = sat.split('id="pane-security"', 1)[1].split('id="pane-', 1)[0]
    assert "kiosk_pin" in sec
    assert "kiosk_readonly_when_locked" in sec
