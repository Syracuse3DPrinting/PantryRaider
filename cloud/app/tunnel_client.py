"""The cloud app's client for the VPS tunnel agent.

The agent (cloud/vps/forager-tunnel-agent) is a root helper on the VPS that
programs wg0 and rewrites Caddy's kitchens include. The cloud app never
touches wg or Caddy itself; it asks the agent over a token-authenticated
loopback (or Docker-network) HTTP call. Kept small and monkeypatchable so
the router's enable/disable flow tests run without a live agent.
"""
from __future__ import annotations

import httpx

from .config import settings


class TunnelAgentError(Exception):
    """The agent could not be reached or refused the change.

    The router turns this into a 503 so nothing is left half-committed: the
    database row is written only after the agent confirms the peer.
    """


def _headers() -> dict:
    return {"X-Tunnel-Token": settings.tunnel_agent_token}


def add_peer(public_key: str, tunnel_ip: str, domain: str) -> None:
    """Add (or update) a WireGuard peer and its Caddy route on the VPS.

    ``domain`` is the kitchen's full public hostname (e.g.
    kitchen-pi.forager.pantryraider.app); the agent needs it to render the
    Caddy reverse-proxy block, so it rides along with the peer add."""
    try:
        resp = httpx.post(
            f"{settings.tunnel_agent_url.rstrip('/')}/peer",
            json={"public_key": public_key, "tunnel_ip": tunnel_ip,
                  "domain": domain},
            headers=_headers(),
            timeout=settings.tunnel_agent_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise TunnelAgentError(f"tunnel agent unreachable: {exc}") from exc
    if resp.status_code != 200:
        raise TunnelAgentError(
            f"tunnel agent rejected peer add ({resp.status_code})")


def remove_peer(public_key: str) -> None:
    """Remove a WireGuard peer and its Caddy route on the VPS."""
    try:
        resp = httpx.request(
            "DELETE",
            f"{settings.tunnel_agent_url.rstrip('/')}/peer",
            json={"public_key": public_key},
            headers=_headers(),
            timeout=settings.tunnel_agent_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise TunnelAgentError(f"tunnel agent unreachable: {exc}") from exc
    if resp.status_code != 200:
        raise TunnelAgentError(
            f"tunnel agent rejected peer remove ({resp.status_code})")
