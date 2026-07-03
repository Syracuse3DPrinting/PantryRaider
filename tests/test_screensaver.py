"""Kiosk screensaver setting: soft on-screen idle layer (FoodAssistant-y65x)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SERVICE = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE))

from app.config import settings, _SAVEABLE, SATELLITE_PULL_FIELDS  # noqa: E402


def test_screensaver_minutes_is_device_local_and_off_by_default():
    assert type(settings)().screensaver_minutes == 0      # off by default
    assert "screensaver_minutes" in _SAVEABLE             # persisted
    # A wall panel and a countertop screen want different idle behaviour, so
    # the value never syncs from the main server.
    assert "screensaver_minutes" not in SATELLITE_PULL_FIELDS


def test_setup_payload_accepts_screensaver_minutes():
    from app.routers.setup import SetupPayload

    p = SetupPayload(screensaver_minutes=10)
    assert p.screensaver_minutes == 10
    # Absent from the request = absent from the applied fields, so a partial
    # save never clobbers the stored value.
    assert "screensaver_minutes" not in SetupPayload().model_dump(exclude_unset=True)


def test_grocy_is_a_known_install_log_name():
    # The wizard's Grocy install window polls setup/logs/grocy
    # (FoodAssistant-n5ky), so the proxy must accept the name.
    from app.routers.setup import _LOG_NAMES

    assert "grocy" in _LOG_NAMES


@pytest.fixture
def client(monkeypatch, tmp_path):
    cwd = os.getcwd()
    os.chdir(SERVICE)
    monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "auth_required", False, raising=False)
    from fastapi.testclient import TestClient
    from app.main import app
    try:
        yield TestClient(app)
    finally:
        os.chdir(cwd)


def test_screensaver_config_rendered_on_pages(client, monkeypatch):
    with patch.object(type(settings), "is_configured", lambda self: True):
        monkeypatch.setattr(settings, "screensaver_minutes", 7, raising=False)
        r = client.get("/ui/timers")
        assert r.status_code == 200
        assert 'id="screensaver-config"' in r.text
        assert 'data-minutes="7"' in r.text
        assert "screensaver.js" in r.text
