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
CAMERA_PORTS = (554, 8554, 80, 81, 88, 8000, 8080, 8081, 443, 8443, 9000, 37777)
_HTTP_PORTS = (80, 81, 88, 8000, 8080, 8081, 9000)
_HTTPS_PORTS = (443, 8443)
_RTSP_PORTS = (554, 8554)

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


def _probe_http(ip: str, port: int, scheme: str, timeout: float,
                fetch=None) -> tuple[str, bool]:
    """Probe snapshot paths on ``scheme://ip:port``.

    Returns (snapshot_url, auth_required). A 200 image wins immediately; a
    401/403 on any path is recorded as auth_required, since password-protected
    cameras are still cameras (the user can add credentials). ``fetch`` is
    injectable for tests."""
    def _default_fetch(url: str):
        return httpx.get(url, timeout=timeout, verify=False, follow_redirects=True)
    fetch = fetch or _default_fetch
    default_port = 80 if scheme == "http" else 443
    base = f"{scheme}://{ip}" if port == default_port else f"{scheme}://{ip}:{port}"
    auth = False
    for path in SNAPSHOT_PATHS:
        url = base + path
        try:
            resp = fetch(url)
        except Exception:
            continue
        code = getattr(resp, "status_code", 0)
        if code == 200 and _looks_like_image(resp):
            return url, False
        if code in (401, 403):
            auth = True
    return "", auth


def probe_camera(ip: str, timeout: float = 0.4, fetch=None) -> dict | None:
    """Probe one host. Returns a dict when ANY camera port is open, else None.

    The dict carries ``report`` (True when this is likely a camera: a snapshot
    was found, it answers RTSP, or a snapshot path needed auth) plus the open
    ports, snapshot_url, rtsp/auth flags, and a ``kind`` for the UI. Returning
    even non-camera responders lets the scan report how many hosts answered on
    camera ports, which distinguishes 'no cameras' from 'cannot reach the LAN'."""
    open_ports = [p for p in CAMERA_PORTS if _port_open(ip, p, timeout)]
    if not open_ports:
        return None
    snapshot_url = ""
    auth = False
    for p in open_ports:
        scheme = "http" if p in _HTTP_PORTS else ("https" if p in _HTTPS_PORTS else "")
        if not scheme:
            continue
        url, a = _probe_http(ip, p, scheme, timeout, fetch=fetch)
        auth = auth or a
        if url:
            snapshot_url = url
            break
    rtsp = any(p in _RTSP_PORTS for p in open_ports)
    report = bool(snapshot_url) or rtsp or auth
    kind = ("snapshot" if snapshot_url else
            "auth" if auth else
            "rtsp" if rtsp else "open")
    return {
        "ip": ip,
        "ports": open_ports,
        "snapshot_url": snapshot_url,
        "rtsp": rtsp,
        "auth_required": auth,
        "report": report,
        "kind": kind,
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


def scan_for_cameras(cidr: str, timeout: float = 0.4, concurrency: int = 128,
                     fetch=None) -> dict:
    """Scan a CIDR for IP cameras.

    Returns ``{"cameras": [...], "responded": int, "scanned": int}`` or
    ``{"error": ...}``. ``responded`` counts hosts that answered on any camera
    port (even non-cameras), so the caller can tell 'no cameras here' from 'this
    container cannot reach the LAN'."""
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError as exc:
        return {"error": f"invalid network: {exc}"}
    if net.num_addresses > MAX_HOSTS:
        return {"error": f"network too large (max {MAX_HOSTS} hosts); use a /22 or smaller"}
    skip = _local_ips()
    hosts = [str(h) for h in net.hosts() if str(h) not in skip]

    def _safe(ip: str) -> dict | None:
        try:
            return probe_camera(ip, timeout, fetch=fetch)
        except Exception:
            return None

    responders: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        for result in pool.map(_safe, hosts):
            if result:
                responders.append(result)
    cameras = [r for r in responders if r.get("report")]
    cameras.sort(key=lambda c: tuple(int(o) for o in c["ip"].split(".")))
    return {"cameras": cameras, "responded": len(responders), "scanned": len(hosts)}
