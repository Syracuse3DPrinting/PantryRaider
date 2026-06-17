"""Route + template smoke tests.

Drive the real FastAPI app via TestClient and assert every GET UI page returns
200 and its Jinja template renders. Grocy/Mealie are mocked so no network or
Docker is needed, and the setup-save flow is exercised end to end.
"""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Jinja2Templates is configured with the relative path "app/templates", so the
# app must be imported (and run) with the working directory set to service/.
_SERVICE_DIR = Path(__file__).parent.parent / "service"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    cwd = os.getcwd()
    os.chdir(_SERVICE_DIR)
    try:
        from app.config import settings
        from app.main import app

        # Make the app think it is fully configured so the setup-redirect
        # middleware is a no-op, and leave auth_password empty so the auth
        # middleware is a no-op too.
        data_dir = tmp_path_factory.mktemp("data")
        settings.data_dir = str(data_dir)
        settings.grocy_base_url = "http://grocy.test"
        settings.grocy_api_key = "test-grocy-key"
        settings.vision_provider = "gemini"
        settings.gemini_api_key = "test-gemini-key"
        settings.auth_required = False
        settings.auth_password = ""
        assert settings.is_configured()

        with TestClient(app) as c:
            yield c
    finally:
        os.chdir(cwd)


@pytest.fixture(autouse=True)
def _mock_services(monkeypatch):
    """Stub the Grocy/Mealie network calls used while rendering pages."""
    from app.services.grocy import GrocyClient

    async def _expiring(self, days=7):
        return []

    monkeypatch.setattr(GrocyClient, "get_expiring", _expiring)


GET_PAGES = [
    "/ui/",
    "/ui/inventory",
    "/ui/add",
    "/ui/pending",
    "/ui/recipes",
    "/ui/cook",
    "/ui/mealplan",
    "/ui/shopping",
    "/ui/expiring",
    "/ui/defaults",
    "/setup",
]


@pytest.mark.parametrize("path", GET_PAGES)
def test_get_page_renders(client, path):
    r = client.get(path)
    assert r.status_code == 200, f"{path} -> {r.status_code}"
    assert "text/html" in r.headers["content-type"]
    # A rendered Jinja page, not an error stub.
    assert "<html" in r.text.lower() or "<!doctype" in r.text.lower()


def test_root_redirects_to_ui(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (303, 307)
    assert r.headers["location"].endswith("/ui/")


def test_health_ok_shape(client):
    # When configured, /health calls the provider + Grocy health checks; mock both.
    from app.services.grocy import GrocyClient
    import app.dependencies as deps

    async def _ok(self):
        return True

    GrocyClient.health_check = _ok

    class _Provider:
        async def health_check(self):
            return True

    deps.get_vision_provider.cache_clear()
    deps._build_provider = lambda *a, **k: _Provider()  # noqa: ARG005
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_setup_save_round_trips(client):
    from app.config import settings

    payload = {
        "vision_provider": "gemini",
        "gemini_api_key": "round-trip-key",
        "grocy_base_url": "http://grocy.example",
        "grocy_api_key": "round-trip-grocy",
        "perishable_days": 9,
        "expiring_soon_days": 3,
        "staple_items": "miso, nori",
    }
    r = client.post("/setup/save", json=payload)
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    # Applied to the live settings object...
    assert settings.perishable_days == 9
    assert settings.expiring_soon_days == 3
    assert settings.staple_items == "miso, nori"

    # ...and persisted to settings.json.
    import json
    saved = json.loads((Path(settings.data_dir) / "settings.json").read_text())
    assert saved["perishable_days"] == 9
    assert saved["staple_items"] == "miso, nori"
    assert saved["gemini_api_key"] == "round-trip-key"
