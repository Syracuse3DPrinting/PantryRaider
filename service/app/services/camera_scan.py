"""Scan the local network for IP cameras (FoodAssistant-d9rx).

Mirrors the Home Assistant camera discovery, but for cameras the app reaches
directly: probe each host on the subnet for common camera ports, and for hosts
answering HTTP, try a short list of well-known snapshot paths and keep the first
that returns an actual image. Cameras that only speak RTSP (port 554, no HTTP
snapshot) are still reported so the user knows they exist, with a note that they
need an MJPEG/snapshot path or an RTSP-to-HLS bridge to be usable in a browser.

The per-host probe is factored out and the HTTP fetch is injectable so tests can
exercise the logic without a network. Reuses lan_scan's subnet helpers.
"""
from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor

import httpx

from .lan_scan import _local_ips, default_cidr  # noqa: F401 - re-exported for the router

import ipaddress

# Ports a network camera commonly answers on. 554 is RTSP (not browser-viewable);
# the rest are HTTP(S) front-ends that may expose a JPEG snapshot or MJPEG stream.
CAMERA_PORTS = (554, 80, 8080, 8000, 88, 8081, 81)
_HTTP_PORTS = (80, 8080, 8000, 88, 8081, 81)

# Snapshot paths used across common camera brands. Tried in order; the first that
# returns an image wins. Kept short so a host is probed quickly.
SNAPSHOT_PATHS = (
    "/snapshot.jpg",
    "/snap.jpg",
    "/image.jpg",
    "/jpg/image.jpg",
    "/cgi-bin/snapshot.cgi",
    "/axis-cgi/jpg/image.cgi",                       # Axis
    "/ISAPI/Streaming/channels/101/picture",         # Hikvision
    "/cgi-bin/api.cgi?cmd=Snap&channel=0",           # Reolink
    "/onvif-http/snapshot",                           # generic ONVIF
    "/tmpfs/auto.jpg",                                # Dahua/Amcrest
)

MAX_HOSTS = 1024


def _looks_like_image(resp: httpx.Response) -> bool:
    """True when an HTTP response body is a JPEG/PNG image."""
    ctype = resp.headers.get("content-type", "").lower()
    if ctype.startswith("image/"):
        return True
    body = resp.content[:3]
    return body[:2] == b"\xff\xd8" or body[:3] == b"\x89PN"  # JPEG / PNG magic


def _port_open(ip: str, port: int, timeout: float) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((ip, port)) == 0
    except OSError:
        return False


def _find_snapshot(ip: str, http_port: int, timeout: float,
                   fetch=None) -> str | None:
    """Return the first working snapshot URL on ``ip:http_port``, or None.

    ``fetch`` is injectable for tests; it takes a URL and returns an httpx-like
    response (or raises). Defaults to a plain httpx GET."""
    def _default_fetch(url: str):
        return httpx.get(url, timeout=timeout)
    fetch = fetch or _default_fetch
    host = f"http://{ip}:{http_port}" if http_port != 80 else f"http://{ip}"
    for path in SNAPSHOT_PATHS:
        url = host + path
        try:
            resp = fetch(url)
        except Exception:
            continue
        if getattr(resp, "status_code", 0) == 200 and _looks_like_image(resp):
            return url
    return None


def probe_camera(ip: str, timeout: float = 0.4, fetch=None) -> dict | None:
    """Probe one host for a camera. Returns a candidate dict or None.

    A candidate carries the ip, the open camera ports, a working ``snapshot_url``
    when one was found, and ``rtsp`` True when only port 554 answered (so the UI
    can flag that it needs a snapshot/MJPEG path or a bridge)."""
    open_ports = [p for p in CAMERA_PORTS if _port_open(ip, p, timeout)]
    if not open_ports:
        return None
    snapshot_url = None
    for hp in (p for p in open_ports if p in _HTTP_PORTS):
        snapshot_url = _find_snapshot(ip, hp, timeout, fetch=fetch)
        if snapshot_url:
            break
    rtsp_only = 554 in open_ports and not any(p in _HTTP_PORTS for p in open_ports)
    # A bare HTTP server with no recognised snapshot path is probably not a
    # camera; only report HTTP hosts when we actually found an image.
    if not snapshot_url and not rtsp_only:
        return None
    return {
        "ip": ip,
        "ports": open_ports,
        "snapshot_url": snapshot_url or "",
        "rtsp": 554 in open_ports,
        "name": f"Camera at {ip}",
    }


def _candidate_ips() -> set[str]:
    """All non-loopback IPv4 addresses this host can see (outbound + hostname)."""
    from .lan_scan import _outbound_ip
    ips: set[str] = set()
    out = _outbound_ip()
    if out:
        ips.add(out)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return {ip for ip in ips if not ip.startswith("127.")}


def _rank_ip(ip: str) -> int:
    """Lower rank = more likely to be a real home/office LAN. Docker's default
    bridge lives in 172.16/12, so that range is ranked last."""
    if ip.startswith("192.168."):
        return 0
    if ip.startswith("10."):
        return 1
    if ip.startswith("172."):
        return 3  # Docker default bridge range: least likely the user's LAN
    return 2


def looks_dockerish(cidr: str) -> bool:
    """Heuristic: a 172.16-31.x subnet is most likely a Docker bridge, not the LAN."""
    try:
        first = cidr.split("/", 1)[0]
        a, b = (int(first.split(".")[0]), int(first.split(".")[1]))
    except (ValueError, IndexError):
        return False
    return a == 172 and 16 <= b <= 31


def best_lan_cidr() -> str | None:
    """Best guess at the host's real LAN /24, preferring 192.168/10 over a Docker
    172.x interface (FoodAssistant-d9rx). Returns None when nothing is found."""
    cands = _candidate_ips()
    if not cands:
        return None
    ip = sorted(cands, key=lambda x: (_rank_ip(x), x))[0]
    try:
        return str(ipaddress.ip_network(f"{ip}/24", strict=False))
    except ValueError:
        return None


def scan_for_cameras(cidr: str, timeout: float = 0.4, concurrency: int = 64,
                     fetch=None) -> list[dict]:
    """Scan a CIDR for IP cameras. Returns candidate dicts (or a single
    ``{"error": ...}`` element for a bad/oversized CIDR)."""
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError as exc:
        return [{"error": f"invalid network: {exc}"}]
    if net.num_addresses > MAX_HOSTS:
        return [{"error": f"network too large (max {MAX_HOSTS} hosts); use a /22 or smaller"}]
    skip = _local_ips()
    hosts = [str(h) for h in net.hosts() if str(h) not in skip]

    def _safe(ip: str) -> dict | None:
        try:
            return probe_camera(ip, timeout, fetch=fetch)
        except Exception:
            return None

    found: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        for result in pool.map(_safe, hosts):
            if result:
                found.append(result)
    found.sort(key=lambda c: tuple(int(o) for o in c["ip"].split(".")))
    return found
