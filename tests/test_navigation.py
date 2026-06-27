"""Tests for the navigation tab registry (service/app/navigation.py).

Covers the Camera tab gating: it appears only when at least one camera is
configured, and an unconfigured Camera tab does NOT raise a service "unlock"
hint (cameras are set in Interface, not a backend service).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVICE = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE))

from app.config import settings  # noqa: E402
from app import navigation  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_nav(monkeypatch):
    # A predictable nav: nothing hidden, default order, no cameras, Mealie off.
    monkeypatch.setattr(settings, "nav_order", "", raising=False)
    monkeypatch.setattr(settings, "nav_hidden", "", raising=False)
    monkeypatch.setattr(settings, "streamdeck_cameras", [], raising=False)
    yield


def test_camera_tab_hidden_without_cameras():
    keys = [t["key"] for t in navigation.visible_tabs()]
    assert "camera" not in keys


def test_camera_tab_shown_with_cameras(monkeypatch):
    monkeypatch.setattr(settings, "streamdeck_cameras",
                        [{"name": "Door", "snapshot_url": "http://x/s.jpg"}], raising=False)
    keys = [t["key"] for t in navigation.visible_tabs()]
    assert "camera" in keys


def test_unconfigured_camera_raises_no_unlock_hint():
    # Mealie is unconfigured here, so it should be the only unlock group; cameras
    # must never produce a lock badge even though their requirement is unmet.
    services = {g["service"] for g in navigation.auto_hidden_groups()}
    assert "cameras" not in services


def test_camera_tab_appears_in_all_tabs_editor(monkeypatch):
    # The Settings tab editor lists every registered tab regardless of state.
    monkeypatch.setattr(settings, "streamdeck_cameras", [], raising=False)
    keys = [t["key"] for t in navigation.all_tabs()]
    assert "camera" in keys
    cam = next(t for t in navigation.all_tabs() if t["key"] == "camera")
    assert cam["shown"] is False and cam["available"] is False
