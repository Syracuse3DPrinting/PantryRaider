"""Named custom themes and the Theme/Navigation split (FoodAssistant-nw49,
-py1o, -oret, -37gi, -bbz8).

Covers:
  * config-level resolution of a "custom:<id>" theme to its stored colours,
  * save() accepting a valid custom:<id> and rejecting a dangling one,
  * the /setup/custom-theme save + delete endpoints,
  * the Settings page rendering the split Theme/Navigation panes, the reset
    control, and the moved Display/Stream Deck pills under Personalization.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SERVICE = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(_SERVICE))

from app.config import settings, theme_info, resolve_custom_colors  # noqa: E402


@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app

    cwd = os.getcwd()
    os.chdir(_SERVICE)
    monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "auth_required", False)
    monkeypatch.setattr(settings, "auth_password", "")
    monkeypatch.setattr(settings, "custom_themes", [])
    monkeypatch.setattr(settings, "ui_theme", "dark")
    try:
        yield TestClient(app)
    finally:
        os.chdir(cwd)


_THEME = {
    "name": "My Kitchen", "base": "light",
    "primary": "#ff7700", "accent": "#00ddaa",
    "bg": "#101418", "surface": "#1c2228", "text": "#eef2f6",
}


# -- config resolution ------------------------------------------------------

def test_resolve_custom_colors_for_named_theme(monkeypatch):
    monkeypatch.setattr(settings, "custom_themes", [
        {"id": "my_kitchen", "name": "My Kitchen", "base": "light",
         "primary": "#ff7700", "accent": "#00ddaa", "bg": "#101418",
         "surface": "#1c2228", "text": "#eef2f6"},
    ])
    monkeypatch.setattr(settings, "ui_theme", "custom:my_kitchen")
    colors = resolve_custom_colors("custom:my_kitchen")
    assert colors["primary"] == "#ff7700"
    assert colors["base"] == "light"
    # theme_info follows the named theme's base for data-bs-theme.
    assert theme_info("custom:my_kitchen")["mode"] == "light"
    # A built-in theme is not a custom theme.
    assert resolve_custom_colors("dark") is None


def test_save_accepts_valid_custom_id_and_rejects_dangling(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "custom_themes", [])
    monkeypatch.setattr(settings, "ui_theme", "dark")
    # A custom:<id> with no matching theme is rejected back to the default.
    settings.save({"ui_theme": "custom:ghost"})
    assert settings.ui_theme != "custom:ghost"
    # Saved together with its theme, it sticks.
    settings.save({
        "custom_themes": [{"id": "ghost", "name": "Ghost", "base": "dark",
                           "primary": "#111111", "accent": "#222222",
                           "bg": "#000000", "surface": "#101010", "text": "#ffffff"}],
        "ui_theme": "custom:ghost",
    })
    assert settings.ui_theme == "custom:ghost"


# -- endpoints --------------------------------------------------------------

def test_custom_theme_save_and_delete_endpoints(client):
    with patch.object(type(settings), "is_configured", lambda self: True):
        r = client.post("/setup/custom-theme", json=_THEME)
    assert r.status_code == 200 and r.json()["ok"] is True
    tid = r.json()["id"]
    assert settings.ui_theme == f"custom:{tid}"
    assert any(t["id"] == tid for t in settings.custom_themes)

    # Re-saving the same name updates in place (no duplicate).
    with patch.object(type(settings), "is_configured", lambda self: True):
        client.post("/setup/custom-theme", json={**_THEME, "primary": "#abcdef"})
    matches = [t for t in settings.custom_themes if t["id"] == tid]
    assert len(matches) == 1 and matches[0]["primary"] == "#abcdef"

    # Delete the active theme -> falls back off custom.
    with patch.object(type(settings), "is_configured", lambda self: True):
        d = client.post("/setup/custom-theme/delete", json={})
    assert d.json()["ok"] is True
    assert not settings.ui_theme.startswith("custom:")
    assert all(t["id"] != tid for t in settings.custom_themes)


def test_custom_theme_save_rejects_blank_name_and_bad_hex(client):
    with patch.object(type(settings), "is_configured", lambda self: True):
        assert client.post("/setup/custom-theme", json={**_THEME, "name": "  "}).json()["ok"] is False
        assert client.post("/setup/custom-theme", json={**_THEME, "primary": "red"}).json()["ok"] is False


# -- page structure ---------------------------------------------------------

def _render(client, monkeypatch, *, is_pi: bool) -> str:
    monkeypatch.setattr(settings, "deployment_mode", "pi_hosted" if is_pi else "server")
    with patch.object(type(settings), "is_configured", lambda self: True), \
         patch("app.routers.setup.is_raspberry_pi", return_value=is_pi), \
         patch("app.templating.is_raspberry_pi", return_value=is_pi):
        r = client.get("/setup")
    assert r.status_code == 200
    return r.text


def test_theme_and_navigation_are_separate_panes(client, monkeypatch):
    html = _render(client, monkeypatch, is_pi=False)
    for pane in ("pane-theme", "pane-navigation"):
        assert f'id="{pane}"' in html
        assert f'data-bs-target="#{pane}"' in html
    # The named-theme builder and nav reset controls render.
    assert 'onclick="saveCustomTheme(this)"' in html
    assert 'onclick="resetNavEditor(this)"' in html
    assert "window.TABS_DEFAULT" in html


def test_saved_custom_theme_shows_in_dropdown(client, monkeypatch):
    monkeypatch.setattr(settings, "custom_themes", [
        {"id": "my_kitchen", "name": "My Kitchen", "base": "dark",
         "primary": "#ff7700", "accent": "#00ddaa", "bg": "#101418",
         "surface": "#1c2228", "text": "#eef2f6"},
    ])
    monkeypatch.setattr(settings, "ui_theme", "custom:my_kitchen")
    html = _render(client, monkeypatch, is_pi=False)
    assert 'value="custom:my_kitchen"' in html
    assert "My Kitchen" in html
    # Active custom theme is applied to the standalone Settings page too.
    assert "#ff7700" in html


def test_display_and_streamdeck_moved_to_personalization(client, monkeypatch):
    html = _render(client, monkeypatch, is_pi=True)
    # Both pills now carry the Personalization group marker.
    for target in ("#pane-display", "#pane-streamdeck"):
        seg = html.split(f'data-bs-target="{target}"', 1)
        assert len(seg) == 2, f"{target} pill missing"
        # The button tag around the pill includes the personalization group.
        btn = seg[0].rsplit("<button", 1)[1] + seg[1].split("</button>", 1)[0]
        assert 'data-mgroup="p"' in btn, f"{target} not under Personalization"


def test_attached_hardware_in_hardware_pane_not_streamdeck(client, monkeypatch):
    html = _render(client, monkeypatch, is_pi=True)
    hw = html.split('id="pane-hardware"', 1)[1].split('id="pane-', 1)[0]
    assert "hwdetect-display" in hw
    assert "Attached hardware" in hw
    sd = html.split('id="pane-streamdeck"', 1)[1].split('id="pane-', 1)[0]
    assert "hwdetect-display" not in sd
