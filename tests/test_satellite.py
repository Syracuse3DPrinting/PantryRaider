"""Satellite config-federation tests.

Exercise the server-side config endpoint (what a main server hands out) and the
pull-side apply logic (how a satellite mirrors it), without real network or a
second running instance. Pure logic + FastAPI TestClient.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SERVICE = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE))

from app.config import settings, SATELLITE_PULL_FIELDS  # noqa: E402


# -- server side: GET /api/config/satellite ----------------------------------

@pytest.fixture
def client():
    # Templates load from the relative path "app/templates", so run from service/.
    from fastapi.testclient import TestClient
    from app.main import app
    cwd = os.getcwd()
    os.chdir(SERVICE)
    try:
        yield TestClient(app)
    finally:
        os.chdir(cwd)


def test_config_endpoint_refuses_without_server_api_key(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "")
    r = client.get("/api/config/satellite")
    assert r.status_code == 503


def test_config_endpoint_rejects_bad_key(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret-key")
    monkeypatch.setattr(settings, "auth_password", "")  # avoid auth middleware
    r = client.get("/api/config/satellite", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_config_endpoint_serves_shareable_fields(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret-key")
    monkeypatch.setattr(settings, "auth_password", "")
    monkeypatch.setattr(settings, "grocy_base_url", "http://server:9383")
    monkeypatch.setattr(settings, "grocy_api_key", "grocy-key")
    r = client.get("/api/config/satellite", headers={"X-API-Key": "secret-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    # Every shareable field is present; no device-local secret leaks.
    assert set(body["config"].keys()) == set(SATELLITE_PULL_FIELDS)
    assert body["config"]["grocy_base_url"] == "http://server:9383"
    assert "secret_key" not in body["config"]
    assert "auth_password" not in body["config"]
    assert "api_key" not in body["config"]
    assert isinstance(body["expiry_defaults"], list)


# -- pull side: apply config onto live settings ------------------------------

def test_apply_config_sets_only_shareable_fields(monkeypatch):
    from app.services.satellite import _apply_config
    monkeypatch.setattr(settings, "grocy_base_url", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    applied = _apply_config({
        "grocy_base_url": "http://server:9383",
        "gemini_api_key": "pulled-key",
        "secret_key": "SHOULD-NOT-APPLY",  # not in SATELLITE_PULL_FIELDS
    })
    assert "grocy_base_url" in applied
    assert "gemini_api_key" in applied
    assert "secret_key" not in applied
    assert settings.grocy_base_url == "http://server:9383"
    assert settings.gemini_api_key == "pulled-key"
    assert getattr(settings, "secret_key") != "SHOULD-NOT-APPLY"
    assert settings.server_sourced_fields >= {"grocy_base_url", "gemini_api_key"}


def test_sync_noops_when_not_satellite(monkeypatch):
    from app.services.satellite import sync_from_upstream
    monkeypatch.setattr(settings, "deployment_mode", "server")
    out = sync_from_upstream()
    assert out["ok"] is False
    assert out["error"] == "not a satellite"


def test_sync_requires_url_and_key(monkeypatch):
    from app.services.satellite import sync_from_upstream
    monkeypatch.setattr(settings, "deployment_mode", "pi_remote")
    monkeypatch.setattr(settings, "remote_server_url", "")
    monkeypatch.setattr(settings, "upstream_api_key", "")
    out = sync_from_upstream()
    assert out["ok"] is False
    assert "missing" in out["error"]


# -- mode semantics ----------------------------------------------------------

def test_satellite_is_configured_needs_url_and_key(monkeypatch):
    monkeypatch.setattr(settings, "deployment_mode", "pi_remote")
    monkeypatch.setattr(settings, "auth_required", False)
    monkeypatch.setattr(settings, "remote_server_url", "http://server:9284")
    monkeypatch.setattr(settings, "upstream_api_key", "")
    assert settings.is_configured() is False
    monkeypatch.setattr(settings, "upstream_api_key", "k")
    assert settings.is_configured() is True


def test_satellite_features_show_backend_panes(monkeypatch):
    monkeypatch.setattr(settings, "deployment_mode", "pi_remote")
    f = settings.features()
    assert f["satellite"] is True
    assert f["manages_stack"] is False
    assert f["ai"] is True
