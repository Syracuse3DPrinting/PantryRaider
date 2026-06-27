"""Tests for the barcode scanner mode (FoodAssistant-8jbk).

Covers the in-memory mode store (cycle/set/reset) and the scan endpoint
dispatch: the default "inventory" mode is unchanged, while "consume" and
"shopping" route the barcode to Grocy/Mealie and never hard-fail.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SERVICE = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE))

from app.services import scanner_mode  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_mode():
    scanner_mode.reset()
    yield
    scanner_mode.reset()


def test_mode_defaults_to_inventory():
    assert scanner_mode.get_mode() == "inventory"
    assert scanner_mode.get_state()["label"] == "Stock"


def test_cycle_wraps_through_all_modes():
    seen = [scanner_mode.get_mode()]
    for _ in range(len(scanner_mode.SCANNER_MODES)):
        seen.append(scanner_mode.cycle_mode()["mode"])
    # Cycled through every mode and wrapped back to the start.
    assert seen[0] == "inventory"
    assert set(seen) == set(scanner_mode.SCANNER_MODES)
    assert seen[-1] == "inventory"


def test_set_unknown_mode_falls_back():
    assert scanner_mode.set_mode("nonsense")["mode"] == "inventory"
    assert scanner_mode.set_mode("consume")["mode"] == "consume"


# Scan dispatch -------------------------------------------------------------

@pytest.fixture
def client(monkeypatch, tmp_path):
    cwd = os.getcwd()
    os.chdir(SERVICE)
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "auth_password", "", raising=False)
    monkeypatch.setattr(settings, "auth_required", False, raising=False)
    monkeypatch.setattr(settings, "deployment_mode", "server", raising=False)
    # Make is_configured() true so the setup-redirect middleware is a no-op.
    monkeypatch.setattr(settings, "grocy_base_url", "http://grocy.test", raising=False)
    monkeypatch.setattr(settings, "grocy_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "vision_provider", "gemini", raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", "k", raising=False)
    from fastapi.testclient import TestClient
    from app.main import app
    try:
        yield TestClient(app)
    finally:
        os.chdir(cwd)


def test_consume_mode_calls_grocy(client, monkeypatch):
    scanner_mode.set_mode("consume")
    called = {}

    async def _consume(self, barcode, amount=1.0):
        called["barcode"] = barcode
        called["amount"] = amount
        return {"ok": True}

    from app.services.grocy import GrocyClient
    monkeypatch.setattr(GrocyClient, "consume_by_barcode", _consume)
    r = client.post("/pending/scan", json={"barcode": "12345", "quantity": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "consumed"
    assert called == {"barcode": "12345", "amount": 2}


def test_consume_failure_returns_status_not_500(client, monkeypatch):
    scanner_mode.set_mode("consume")

    async def _boom(self, barcode, amount=1.0):
        raise RuntimeError("unknown barcode")

    from app.services.grocy import GrocyClient
    monkeypatch.setattr(GrocyClient, "consume_by_barcode", _boom)
    r = client.post("/pending/scan", json={"barcode": "999"})
    assert r.status_code == 200
    assert r.json()["status"] == "consume_failed"


def test_scanner_mode_endpoints(client):
    assert client.get("/pending/scanner-mode").json()["mode"] == "inventory"
    cycled = client.post("/pending/scanner-mode/cycle").json()
    assert cycled["mode"] == "consume"
    set_back = client.post("/pending/scanner-mode", json={"mode": "shopping"}).json()
    assert set_back["mode"] == "shopping"
