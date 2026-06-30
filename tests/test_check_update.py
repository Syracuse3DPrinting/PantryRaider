"""Update check reads APP_VERSION from main, not just tags (FoodAssistant-jhug)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVICE = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE))

from app.routers import admin  # noqa: E402
from app.config import APP_VERSION  # noqa: E402


class _Resp:
    def __init__(self, status_code, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload or []

    def json(self):
        return self._payload


class _FakeClient:
    """Stand-in for httpx.AsyncClient: serves a canned config.py for the raw URL."""
    def __init__(self, raw_text=None, raw_status=200):
        self._raw_text = raw_text
        self._raw_status = raw_status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        if "raw.githubusercontent.com" in url:
            if self._raw_text is None:
                return _Resp(404)
            return _Resp(self._raw_status, text=self._raw_text)
        # tags fallback
        return _Resp(200, payload=[{"name": "v0.0.1"}])


def _patch_client(monkeypatch, **kw):
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _FakeClient(**kw))


def test_detects_newer_version_on_main(monkeypatch):
    import asyncio
    _patch_client(monkeypatch, raw_text='APP_VERSION = "99.0.0"\n')
    out = asyncio.run(admin.check_update())
    assert out["ok"] is True
    assert out["latest"] == "99.0.0"
    assert out["update_available"] is True
    assert out["current"] == APP_VERSION


def test_same_version_is_not_an_update(monkeypatch):
    import asyncio
    _patch_client(monkeypatch, raw_text=f'APP_VERSION = "{APP_VERSION}"\n')
    out = asyncio.run(admin.check_update())
    assert out["ok"] is True
    assert out["latest"] == APP_VERSION
    assert out["update_available"] is False


def test_falls_back_to_tags_when_raw_unavailable(monkeypatch):
    import asyncio
    _patch_client(monkeypatch, raw_text=None)  # raw 404 -> tag fallback
    out = asyncio.run(admin.check_update())
    # The fake tag is v0.0.1, older than the running version: not an update,
    # but the call still succeeds via the fallback path.
    assert out["ok"] is True
    assert out["latest"] == "v0.0.1"
    assert out["update_available"] is False
