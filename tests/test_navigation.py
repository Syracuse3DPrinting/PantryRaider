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


# -- custom tab normalization (FoodAssistant-9gdz) --------------------------

def test_normalize_custom_tabs_drops_invalid_and_assigns_keys():
    raw = [
        {"label": "Home Assistant", "url": "https://ha.local", "icon": "bi-house"},
        {"label": "", "url": "https://x"},          # no label, dropped
        {"label": "No URL"},                          # no url, dropped
        "not a dict",                                 # dropped
        {"label": "Docs", "url": "ui/about"},         # default icon
    ]
    out = navigation.normalize_custom_tabs(raw)
    assert [t["label"] for t in out] == ["Home Assistant", "Docs"]
    assert out[0]["key"].startswith(navigation.CUSTOM_PREFIX)
    assert out[0]["icon"] == "bi-house" and out[0]["custom"] is True
    assert out[1]["icon"] == navigation._DEFAULT_CUSTOM_ICON


def test_normalize_custom_tabs_dedupes_keys():
    raw = [
        {"id": "media", "label": "Media", "url": "a"},
        {"id": "media", "label": "Media Two", "url": "b"},
    ]
    out = navigation.normalize_custom_tabs(raw)
    assert out[0]["key"] != out[1]["key"]


def test_custom_tab_shows_in_visible_and_all_tabs(monkeypatch):
    monkeypatch.setattr(settings, "custom_nav_tabs",
                        [{"label": "Wiki", "url": "https://wiki.local", "icon": "bi-book"}],
                        raising=False)
    monkeypatch.setattr(settings, "nav_parents", {}, raising=False)
    vkeys = [t["key"] for t in navigation.visible_tabs()]
    custom = [k for k in vkeys if k.startswith(navigation.CUSTOM_PREFIX)]
    assert custom, "custom tab should be visible"
    editor = {t["key"]: t for t in navigation.all_tabs()}
    assert editor[custom[0]]["custom"] is True
    assert editor[custom[0]]["label"] == "Wiki"


# -- nav tree building ------------------------------------------------------

def _tab(key, parent="", custom=False):
    t = {"key": key, "label": key.title(), "icon": "bi-x", "href": key}
    if custom:
        t["custom"] = True
        t["parent"] = parent
    return t


def test_build_nav_tree_flat_when_no_parents():
    tabs = [_tab("a"), _tab("b"), _tab("c")]
    tree = navigation.build_nav_tree(tabs, parents={})
    assert [n["key"] for n in tree] == ["a", "b", "c"]
    assert all(n["children"] == [] for n in tree)


def test_build_nav_tree_nests_builtin_child_under_parent():
    tabs = [_tab("parent"), _tab("child"), _tab("other")]
    tree = navigation.build_nav_tree(tabs, parents={"child": "parent"})
    keys = [n["key"] for n in tree]
    assert "child" not in keys           # nested, not top-level
    parent = next(n for n in tree if n["key"] == "parent")
    assert [c["key"] for c in parent["children"]] == ["child"]


def test_build_nav_tree_nests_custom_child_via_inline_parent():
    tabs = [_tab("parent"), _tab("custom_x", parent="parent", custom=True)]
    tree = navigation.build_nav_tree(tabs, parents={})
    parent = next(n for n in tree if n["key"] == "parent")
    assert [c["key"] for c in parent["children"]] == ["custom_x"]


def test_build_nav_tree_orphan_parent_falls_back_to_top_level():
    # Parent reference points at a tab that is not present (hidden) -> top level.
    tabs = [_tab("child")]
    tree = navigation.build_nav_tree(tabs, parents={"child": "missing"})
    assert [n["key"] for n in tree] == ["child"]


def test_build_nav_tree_only_one_level_deep():
    # A child of a child should not nest two levels; it stays top-level.
    tabs = [_tab("a"), _tab("b"), _tab("c")]
    tree = navigation.build_nav_tree(tabs, parents={"b": "a", "c": "b"})
    a = next(n for n in tree if n["key"] == "a")
    assert [ch["key"] for ch in a["children"]] == ["b"]
    # c's parent (b) is itself nested, so c falls back to top level.
    assert "c" in [n["key"] for n in tree]


# -- render smoke test: a parent with children produces a dropdown ----------

def test_navbar_renders_dropdown_for_parent_with_children(monkeypatch, tmp_path):
    import os
    cwd = os.getcwd()
    os.chdir(SERVICE)
    try:
        monkeypatch.setattr(settings, "data_dir", str(tmp_path), raising=False)
        monkeypatch.setattr(settings, "auth_required", False, raising=False)
        monkeypatch.setattr(settings, "deployment_mode", "server", raising=False)
        monkeypatch.setattr(settings, "grocy_base_url", "http://grocy.test", raising=False)
        monkeypatch.setattr(settings, "grocy_api_key", "k", raising=False)
        monkeypatch.setattr(settings, "nav_order", "", raising=False)
        monkeypatch.setattr(settings, "nav_hidden", "", raising=False)
        # Nest the Expiring tab under Inventory so Inventory becomes a dropdown.
        monkeypatch.setattr(settings, "nav_parents", {"expiring": "inventory"}, raising=False)
        monkeypatch.setattr(settings, "custom_nav_tabs", [], raising=False)
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        html = client.get("/ui/about").text
        assert 'id="navSub_inventory"' in html
        assert "dropdown-toggle" in html
    finally:
        os.chdir(cwd)
