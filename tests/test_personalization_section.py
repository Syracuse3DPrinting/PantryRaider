"""Personalization section of the Settings page (FoodAssistant-pszk).

The Settings page (setup.html) now groups the commonly-changed, taste-level
settings under a "Personalization" sidebar heading, separate from the
set-and-forget Settings. The moved panes keep their pane ids (so #pane-* hash
nav and any code that clicks a pane still works) and their save wiring. This
suite guards that structure and the stand-mixer attachment toggle
(FoodAssistant-rjdr) on the appliances checklist.
"""
from __future__ import annotations

import os
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


def _render(client, monkeypatch, *, satellite: bool) -> str:
    monkeypatch.setattr(
        settings, "deployment_mode", "pi_remote" if satellite else "server"
    )
    with patch.object(type(settings), "is_configured", lambda self: True):
        r = client.get("/setup")
    assert r.status_code == 200
    return r.text


def test_personalization_heading_and_links(client, monkeypatch):
    html = _render(client, monkeypatch, satellite=False)
    assert "Personalization" in html
    # Interface was split into separate Theme and Navigation panes under
    # Personalization (FoodAssistant-py1o).
    for pane in ("pane-theme", "pane-navigation"):
        assert f'data-bs-target="#{pane}"' in html
        assert f'id="{pane}"' in html
    # New Personalization panes exist with stable ids for hash nav.
    for pane in (
        "pane-personalization-recipes",
        "pane-personalization-storage",
        "pane-personalization-weather",
    ):
        assert f'data-bs-target="#{pane}"' in html
        assert f'id="{pane}"' in html


def test_moved_recipe_prefs_inputs_render_in_personalization(client, monkeypatch):
    """The suggestion-tuning + appliances inputs live in the Personalization
    recipe-prefs pane and are saved by its own button (non-satellite)."""
    html = _render(client, monkeypatch, satellite=False)
    pane = html.split('id="pane-personalization-recipes"', 1)[1].split(
        'id="pane-theme"', 1
    )[0]
    # Suggestion tuning + appliances moved here.
    for field in ("staple_items", "cook_ai_context", "kitchen-appliances",
                  "perishable_days", "suggest_per_tier"):
        assert field in pane
    # Its own save button (not the Settings Recipes one).
    assert 'onclick="savePaneRecipePrefs(this)"' in pane
    # Mealie/TheMealDB stay in the Settings Recipes pane, not here.
    assert "mealie_base_url" not in pane
    assert "themealdb_api_key" not in pane


def test_storage_categories_moved_out_of_inventory(client, monkeypatch):
    html = _render(client, monkeypatch, satellite=False)
    inv = html.split('id="pane-inventory"', 1)[1].split('id="pane-', 1)[0]
    assert "storage-cat-editor" not in inv
    store = html.split('id="pane-personalization-storage"', 1)[1].split(
        'id="pane-', 1
    )[0]
    assert "storage-cat-editor" in store
    assert "saveStorageCategories()" in store


def test_streamdeck_weather_personalization_pane_non_satellite(client, monkeypatch):
    html = _render(client, monkeypatch, satellite=False)
    wx = html.split('id="pane-personalization-weather"', 1)[1].split(
        'id="pane-', 1
    )[0]
    assert "streamdeck_weather_location" in wx
    assert 'onclick="saveStreamDeckWeather(this)"' in wx


def test_satellite_recipe_prefs_pane_is_read_only(client, monkeypatch):
    """On a satellite the recipe-prefs pane still renders, read-only, with the
    managed-on-server note and no editable save button (server-managed)."""
    html = _render(client, monkeypatch, satellite=True)
    assert 'id="pane-personalization-recipes"' in html
    # Satellite-only panes (storage/weather) are gated out.
    assert 'id="pane-personalization-storage"' not in html
    assert 'id="pane-personalization-weather"' not in html
    pane = html.split('id="pane-personalization-recipes"', 1)[1].split(
        'id="pane-theme"', 1
    )[0]
    assert 'onclick="savePaneRecipePrefs(this)"' not in pane
    assert "Recipe settings are managed on the main server" in pane


def test_stand_mixer_attachment_toggle_present(client, monkeypatch):
    """The attachments group is wired to show only when a stand mixer is owned."""
    html = _render(client, monkeypatch, satellite=False)
    assert 'data-group="attachment"' in html
    assert "function syncStandMixerAttachments" in html
    # Wired to the stand_mixer checkbox on load and change.
    assert "appliance_stand_mixer" in html
    assert "syncStandMixerAttachments" in html


def test_settings_personalization_top_toggle_present(client, monkeypatch):
    """The Settings page has a top toggle to switch between Settings and
    Personalization, and the Personalization pills carry the group marker so the
    toggle can show one menu at a time (FoodAssistant)."""
    from app.config import settings
    monkeypatch.setattr(settings, "deployment_mode", "server")
    with patch.object(type(settings), "is_configured", lambda self: True):
        html = client.get("/setup").text
    assert 'onclick="showSettingsMenu(\'p\')"' in html
    assert 'onclick="showSettingsMenu(\'s\')"' in html
    assert 'function showSettingsMenu(' in html
    # The personalization pills are tagged so the toggle can hide them.
    assert 'data-mgroup="p"' in html
