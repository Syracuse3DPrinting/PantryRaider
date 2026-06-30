"""IP-camera LAN discovery (FoodAssistant-d9rx). Network calls are injected so
the logic is exercised without touching the network."""
from __future__ import annotations

import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE))

from app.services import camera_scan  # noqa: E402


class _Resp:
    def __init__(self, status_code=200, content=b"\xff\xd8\xff", ctype="image/jpeg"):
        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": ctype}


def test_looks_like_image_by_magic_and_ctype():
    assert camera_scan._looks_like_image(_Resp(content=b"\xff\xd8\xff", ctype="application/octet-stream"))
    assert camera_scan._looks_like_image(_Resp(content=b"junk", ctype="image/png"))
    assert not camera_scan._looks_like_image(_Resp(content=b"<html>", ctype="text/html"))


def test_find_snapshot_returns_first_working_path(monkeypatch):
    good = "http://10.0.0.5/snap.jpg"

    def fetch(url):
        if url == good:
            return _Resp(200)
        return _Resp(404, content=b"", ctype="text/html")

    monkeypatch.setattr(camera_scan, "_port_open", lambda ip, p, t: True)
    url = camera_scan._find_snapshot("10.0.0.5", 80, 0.1, fetch=fetch)
    assert url == good


def test_probe_camera_with_http_snapshot(monkeypatch):
    monkeypatch.setattr(camera_scan, "_port_open",
                        lambda ip, p, t: p == 80)  # only HTTP open

    def fetch(url):
        return _Resp(200) if url.endswith("/snapshot.jpg") else _Resp(404, b"", "text/html")

    cam = camera_scan.probe_camera("10.0.0.5", fetch=fetch)
    assert cam and cam["ip"] == "10.0.0.5"
    assert cam["snapshot_url"].endswith("/snapshot.jpg")
    assert cam["rtsp"] is False


def test_probe_camera_rtsp_only(monkeypatch):
    monkeypatch.setattr(camera_scan, "_port_open", lambda ip, p, t: p == 554)
    cam = camera_scan.probe_camera("10.0.0.6", fetch=lambda u: _Resp(404))
    assert cam and cam["rtsp"] is True and cam["snapshot_url"] == ""


def test_probe_camera_plain_http_not_reported(monkeypatch):
    # An HTTP host with no recognised snapshot path is not a camera.
    monkeypatch.setattr(camera_scan, "_port_open", lambda ip, p, t: p == 80)
    cam = camera_scan.probe_camera("10.0.0.7",
                                   fetch=lambda u: _Resp(200, b"<html>", "text/html"))
    assert cam is None


def test_scan_rejects_bad_cidr():
    out = camera_scan.scan_for_cameras("not-a-cidr")
    assert out and out[0].get("error")


def test_looks_dockerish():
    assert camera_scan.looks_dockerish("172.19.0.0/24") is True
    assert camera_scan.looks_dockerish("172.17.0.0/16") is True
    assert camera_scan.looks_dockerish("192.168.1.0/24") is False
    assert camera_scan.looks_dockerish("10.0.0.0/24") is False
    assert camera_scan.looks_dockerish("172.200.0.0/24") is False  # not the private range


def test_best_lan_cidr_prefers_real_lan_over_docker(monkeypatch):
    # With both a Docker 172.x and a real 192.168.x interface visible, pick the LAN.
    monkeypatch.setattr(camera_scan, "_candidate_ips",
                        lambda: {"172.19.0.5", "192.168.1.40"})
    assert camera_scan.best_lan_cidr() == "192.168.1.0/24"
    # 10.x is preferred over 172.x too.
    monkeypatch.setattr(camera_scan, "_candidate_ips", lambda: {"172.19.0.5", "10.1.2.3"})
    assert camera_scan.best_lan_cidr() == "10.1.2.0/24"
    # Only Docker visible (a bridge-networked container): we still return it, and
    # the endpoint flags it as dockerish so the UI tells the user to correct it.
    monkeypatch.setattr(camera_scan, "_candidate_ips", lambda: {"172.19.0.5"})
    assert camera_scan.best_lan_cidr() == "172.19.0.0/24"
