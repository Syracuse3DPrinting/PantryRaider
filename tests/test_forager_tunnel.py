"""Forager remote-access tunnel, device side (FoodAssistant-uczr).

Two layers, both without network or WireGuard:

- The host bridge's pure helpers: the wg-quick config renderer and the
  `wg show ... latest-handshakes` parser, loaded from the extensionless bridge
  script the same way test_host_bridge does.
- The app's /setup/tunnel/* routes: the enable happy path and rollback, the
  three safety gates, the 402 upgrade path, the disable qr_public_url rule, and
  the status merge, with the bridge client and the cloud httpx client faked.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
_SERVICE = REPO / "service"
sys.path.insert(0, str(_SERVICE))

from app.config import settings, _SAVEABLE, SATELLITE_PULL_FIELDS, SECRET_SETTING_KEYS  # noqa: E402
from app.passwords import hash_secret  # noqa: E402

_ADMIN_PW = "admin-secret"


# --- bridge pure helpers ----------------------------------------------------

def _load_bridge():
    path = REPO / "scripts" / "image-build" / "foodassistant-host-bridge"
    spec = importlib.util.spec_from_loader(
        "foodassistant_host_bridge",
        importlib.machinery.SourceFileLoader("foodassistant_host_bridge", str(path)),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bridge = _load_bridge()


def test_wg_config_renders_split_tunnel():
    text = bridge._render_wg_config(
        private_key="PRIVKEY", address="10.99.4.7",
        server_public_key="SRVPUB", endpoint="vps.example:51820",
        allowed_ips="10.99.0.1/32", dns="", keepalive=25,
    )
    assert "[Interface]" in text and "[Peer]" in text
    assert "PrivateKey = PRIVKEY" in text
    # A bare tunnel IP is normalized to a /32 host address.
    assert "Address = 10.99.4.7/32" in text
    assert "PublicKey = SRVPUB" in text
    assert "Endpoint = vps.example:51820" in text
    # Split tunnel: only the server /32 is routed, never a 0.0.0.0/0 catch-all.
    assert "AllowedIPs = 10.99.0.1/32" in text
    assert "0.0.0.0/0" not in text
    assert "PersistentKeepalive = 25" in text
    # No resolver was given, so no DNS line is emitted (wg-quick would need
    # resolvconf on the device otherwise).
    assert "DNS" not in text


def test_wg_config_keeps_prefix_and_adds_dns_when_given():
    text = bridge._render_wg_config(
        private_key="k", address="10.99.4.7/32", server_public_key="s",
        endpoint="h:51820", allowed_ips="10.99.0.1/32", dns="10.99.0.1",
    )
    assert "Address = 10.99.4.7/32" in text
    assert "DNS = 10.99.0.1" in text


def test_wg_handshake_parser_picks_latest_epoch():
    dump = (
        "PEERONEKEY\t0\n"
        "PEERTWOKEY\t1720000000\n"
    )
    assert bridge._parse_wg_handshakes(dump) == 1720000000


def test_wg_handshake_parser_zero_when_never():
    assert bridge._parse_wg_handshakes("SOMEKEY\t0\n") == 0
    assert bridge._parse_wg_handshakes("") == 0
    assert bridge._parse_wg_handshakes("garbage line") == 0


def test_wg_tools_present_needs_both():
    assert bridge._wg_tools_present(which=lambda n: "/usr/bin/" + n) is True
    assert bridge._wg_tools_present(which=lambda n: None) is False
    assert bridge._wg_tools_present(
        which=lambda n: "/usr/bin/wg" if n == "wg" else None) is False


# --- settings plumbing ------------------------------------------------------

def test_tunnel_enabled_saveable_device_local_not_secret():
    assert "tunnel_enabled" in _SAVEABLE
    assert "tunnel_enabled" not in SATELLITE_PULL_FIELDS
    assert "tunnel_enabled" not in SECRET_SETTING_KEYS


# --- app router fakes -------------------------------------------------------

class _Resp:
    def __init__(self, status, data=None):
        self.status_code = status
        self._data = data or {}

    def json(self):
        return self._data


class _FakeClient:
    """Async-context httpx stand-in dispatching by (method, url-suffix).

    routes maps a URL suffix to a _Resp (or a callable taking the json body).
    calls records every (method, suffix, body) for assertions.
    """

    def __init__(self, routes, calls):
        self._routes = routes
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def _match(self, method, url, kw):
        self._calls.append((method, url, kw.get("json")))
        for suffix, resp in self._routes.items():
            if url.endswith(suffix):
                return resp(kw.get("json")) if callable(resp) else resp
        return _Resp(404)

    async def post(self, url, **kw):
        return self._match("POST", url, kw)

    async def get(self, url, **kw):
        return self._match("GET", url, kw)


@pytest.fixture
def client(tmp_path):
    cwd = os.getcwd()
    os.chdir(_SERVICE)
    from app.main import app
    settings.data_dir = str(tmp_path)
    # Mark configured so the setup-redirect middleware serves the route rather
    # than the wizard page, and drop the auth wall for the test client.
    settings.grocy_base_url = "http://grocy.test"
    settings.grocy_api_key = "test-grocy-key"
    settings.vision_provider = "gemini"
    settings.gemini_api_key = "test-gemini-key"
    settings.auth_required = False
    assert settings.is_configured()
    try:
        with TestClient(app) as c:
            yield c
    finally:
        os.chdir(cwd)


def _login(client):
    """Open an admin session so the /setup auth wall lets the request through."""
    return client.post("/ui/login", data={"password": _ADMIN_PW},
                       follow_redirects=False)


def _linked_pi(monkeypatch, client=None):
    monkeypatch.setattr(settings, "cloud_instance_token", "prc_token")
    monkeypatch.setattr(settings, "cloud_base_url", "https://cloud.test")
    monkeypatch.setattr(settings, "auth_password", hash_secret(_ADMIN_PW))
    monkeypatch.setattr(settings, "deployment_mode", "pi_hosted")
    if client is not None:
        _login(client)


def _patch_clients(bridge_routes, cloud_routes, calls):
    """Patch the router's bridge client and cloud httpx client with fakes."""
    def bridge_factory(*a, **kw):
        return _FakeClient(bridge_routes, calls)

    def cloud_factory(*a, **kw):
        return _FakeClient(cloud_routes, calls)

    return (
        patch("app.routers.setup.bridge_client", side_effect=bridge_factory),
        patch("app.routers.setup.httpx.AsyncClient", side_effect=cloud_factory),
    )


# --- enable: happy path + rollback -----------------------------------------

def test_enable_happy_path_brings_up_and_sets_qr(client, monkeypatch):
    _linked_pi(monkeypatch, client)
    monkeypatch.setattr(settings, "qr_public_url", "")
    monkeypatch.setattr(settings, "tunnel_enabled", False)
    calls = []
    cloud_data = {
        "server_public_key": "SRVPUB", "server_endpoint": "vps.test:51820",
        "tunnel_ip": "10.99.4.7", "allowed_ips": "10.99.0.1/32",
        "public_url": "https://home.forager.pantryraider.app", "keepalive": 25,
    }
    bridge_routes = {
        "/tunnel/keygen": _Resp(200, {"ok": True, "public_key": "DEVPUB"}),
        "/tunnel/up": _Resp(200, {"ok": True, "interface": "fa-forager"}),
    }
    cloud_routes = {"/v1/tunnel/enable": _Resp(200, cloud_data)}
    p1, p2 = _patch_clients(bridge_routes, cloud_routes, calls)
    saved = {}
    with p1, p2, patch.object(type(settings), "save", side_effect=lambda d: saved.update(d)):
        r = client.post("/setup/tunnel/enable")
    body = r.json()
    assert body["ok"] is True
    assert body["public_url"] == "https://home.forager.pantryraider.app"
    # The keygen public key was forwarded to the cloud, and the cloud's
    # parameters reached the bridge up call.
    enable_call = next(c for c in calls if c[1].endswith("/v1/tunnel/enable"))
    assert enable_call[2]["public_key"] == "DEVPUB"
    up_call = next(c for c in calls if c[1].endswith("/tunnel/up"))
    assert up_call[2]["server_public_key"] == "SRVPUB"
    assert up_call[2]["allowed_ips"] == "10.99.0.1/32"
    assert saved.get("tunnel_enabled") is True
    assert saved.get("qr_public_url") == "https://home.forager.pantryraider.app"


def test_enable_rolls_back_when_bridge_up_fails(client, monkeypatch):
    _linked_pi(monkeypatch, client)
    calls = []
    bridge_routes = {
        "/tunnel/keygen": _Resp(200, {"ok": True, "public_key": "DEVPUB"}),
        "/tunnel/up": _Resp(500, {"ok": False, "error": "wg-quick failed"}),
        "/tunnel/down": _Resp(200, {"ok": True}),
    }
    cloud_routes = {
        "/v1/tunnel/enable": _Resp(200, {"public_url": "https://x", "tunnel_ip": "10.99.4.7"}),
        "/v1/tunnel/disable": _Resp(200, {"disabled": True}),
    }
    p1, p2 = _patch_clients(bridge_routes, cloud_routes, calls)
    with p1, p2, patch.object(type(settings), "save") as save:
        r = client.post("/setup/tunnel/enable")
    assert r.json()["ok"] is False
    # Rollback: the interface was taken down and the cloud was told to disable.
    assert any(c[1].endswith("/tunnel/down") for c in calls)
    assert any(c[1].endswith("/v1/tunnel/disable") for c in calls)
    # Nothing was persisted (the tunnel never came up).
    save.assert_not_called()


# --- enable: safety gates ---------------------------------------------------

def test_enable_gate_requires_link(client, monkeypatch):
    monkeypatch.setattr(settings, "cloud_instance_token", "")
    monkeypatch.setattr(settings, "auth_password", hash_secret(_ADMIN_PW))
    monkeypatch.setattr(settings, "deployment_mode", "pi_hosted")
    _login(client)
    r = client.post("/setup/tunnel/enable")
    body = r.json()
    assert body["ok"] is False
    assert "Connect" in body["error"]


def test_enable_gate_requires_password(client, monkeypatch):
    monkeypatch.setattr(settings, "cloud_instance_token", "prc_token")
    monkeypatch.setattr(settings, "auth_password", "")
    monkeypatch.setattr(settings, "deployment_mode", "pi_hosted")
    r = client.post("/setup/tunnel/enable")
    body = r.json()
    assert body["ok"] is False
    assert "password" in body["error"].lower()


def test_enable_gate_requires_pi_appliance(client, monkeypatch):
    monkeypatch.setattr(settings, "cloud_instance_token", "prc_token")
    monkeypatch.setattr(settings, "auth_password", hash_secret(_ADMIN_PW))
    monkeypatch.setattr(settings, "deployment_mode", "server")
    _login(client)
    r = client.post("/setup/tunnel/enable")
    body = r.json()
    assert body["ok"] is False
    assert "Pi appliance" in body["error"]


def test_enable_402_returns_upgrade_message(client, monkeypatch):
    _linked_pi(monkeypatch, client)
    calls = []
    bridge_routes = {"/tunnel/keygen": _Resp(200, {"ok": True, "public_key": "DEVPUB"})}
    cloud_routes = {"/v1/tunnel/enable": _Resp(402, {"error": "no_subscription"})}
    p1, p2 = _patch_clients(bridge_routes, cloud_routes, calls)
    with p1, p2, patch.object(type(settings), "save") as save:
        r = client.post("/setup/tunnel/enable")
    body = r.json()
    assert body["ok"] is False
    assert body.get("needs_plan") is True
    assert "plan" in body["error"].lower()
    # The interface was never brought up, so nothing to persist or roll back.
    assert not any(c[1].endswith("/tunnel/up") for c in calls)
    save.assert_not_called()


# --- disable: qr_public_url clearing rule -----------------------------------

def test_disable_clears_qr_when_it_matches_tunnel(client, monkeypatch):
    _linked_pi(monkeypatch, client)
    monkeypatch.setattr(settings, "qr_public_url", "https://home.forager.pantryraider.app")
    monkeypatch.setattr(settings, "tunnel_enabled", True)
    calls = []
    bridge_routes = {"/tunnel/down": _Resp(200, {"ok": True})}
    cloud_routes = {
        "/v1/tunnel/status": _Resp(200, {"public_url": "https://home.forager.pantryraider.app"}),
        "/v1/tunnel/disable": _Resp(200, {"disabled": True}),
    }
    p1, p2 = _patch_clients(bridge_routes, cloud_routes, calls)
    saved = {}
    with p1, p2, patch.object(type(settings), "save", side_effect=lambda d: saved.update(d)):
        r = client.post("/setup/tunnel/disable")
    assert r.json()["ok"] is True
    assert saved.get("tunnel_enabled") is False
    assert saved.get("qr_public_url") == ""


def test_disable_keeps_qr_when_it_is_a_custom_url(client, monkeypatch):
    _linked_pi(monkeypatch, client)
    monkeypatch.setattr(settings, "qr_public_url", "https://pantry.mydomain.example")
    monkeypatch.setattr(settings, "tunnel_enabled", True)
    calls = []
    bridge_routes = {"/tunnel/down": _Resp(200, {"ok": True})}
    cloud_routes = {
        "/v1/tunnel/status": _Resp(200, {"public_url": "https://home.forager.pantryraider.app"}),
        "/v1/tunnel/disable": _Resp(200, {"disabled": True}),
    }
    p1, p2 = _patch_clients(bridge_routes, cloud_routes, calls)
    saved = {}
    with p1, p2, patch.object(type(settings), "save", side_effect=lambda d: saved.update(d)):
        r = client.post("/setup/tunnel/disable")
    assert r.json()["ok"] is True
    assert saved.get("tunnel_enabled") is False
    assert "qr_public_url" not in saved


# --- status merge -----------------------------------------------------------

def test_status_merges_cloud_and_bridge(client, monkeypatch):
    _linked_pi(monkeypatch, client)
    monkeypatch.setattr(settings, "tunnel_enabled", True)
    monkeypatch.setattr(settings, "qr_public_url", "https://home.forager.pantryraider.app")
    calls = []
    bridge_routes = {"/tunnel/status": _Resp(200, {"up": True, "last_handshake_seconds": 12})}
    cloud_routes = {"/v1/tunnel/status": _Resp(200, {
        "enabled": True, "public_url": "https://home.forager.pantryraider.app",
        "last_handshake": 999,
    })}
    p1, p2 = _patch_clients(bridge_routes, cloud_routes, calls)
    with p1, p2:
        r = client.get("/setup/tunnel/status")
    body = r.json()
    assert body["ok"] is True
    assert body["enabled"] is True
    assert body["reachable"] is True
    assert body["up"] is True
    # The bridge's live handshake wins over the cloud's cached figure.
    assert body["last_handshake_seconds"] == 12
    assert body["public_url"] == "https://home.forager.pantryraider.app"
