"""Pull-side of satellite config federation.

On a satellite (deployment_mode=pi_remote) this fetches the shareable backend
config from the main server and applies it to the live settings object, then
mirrors the expiry-defaults table into the local DB. The pulled fields are
recorded in ``settings.server_sourced_fields`` so the UI can show them
read-only: a satellite mirrors its server, it does not edit backend config.

The pull is best-effort: if the server is unreachable the satellite keeps
whatever it last had (or runs unconfigured) rather than crashing.
"""
from __future__ import annotations

import logging
import socket
from datetime import datetime, timezone

import httpx

from ..config import settings, SATELLITE_PULL_FIELDS, APP_VERSION

logger = logging.getLogger("foodassistant.satellite")


def _record_last_sync(result: dict) -> None:
    """Persist a compact summary of a pull so the setup page can show its health.

    Stored under the ``satellite_last_sync`` setting (a small dict). Best-effort:
    a failure to persist must not turn an otherwise-successful sync into a crash.
    """
    summary = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ok": bool(result.get("ok")),
        "applied": list(result.get("applied", [])),
        "defaults": int(result.get("defaults", 0)),
        "error": result.get("error"),
    }
    try:
        settings.save({"satellite_last_sync": summary})
    except Exception as exc:
        logger.warning("satellite sync: could not record last-sync status: %s", exc)


def _local_ip() -> str:
    """Best-effort local IP for this device, '' if it cannot be determined.

    Opening a UDP socket toward a public address sends nothing but lets the OS
    pick the outbound interface, whose address we read back.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return ""


def _apply_config(config: dict) -> list[str]:
    """Overlay pulled backend config onto the live settings object.

    Returns the list of field names that were applied (server-sourced).
    """
    applied: list[str] = []
    for field in SATELLITE_PULL_FIELDS:
        if field not in config:
            continue
        object.__setattr__(settings, field, config[field])
        applied.append(field)
    # Record provenance so the UI can render these read-only.
    object.__setattr__(settings, "server_sourced_fields", set(applied))
    return applied


# The Pi host bridge, same address setup.py proxies to. Used to push synced
# Stream Deck weather into the local config.toml (FoodAssistant-bra).
_HOST_BRIDGE = "http://127.0.0.1:9299"

# Settings fields that the Stream Deck controller mirrors from its config.toml.
# A subset of SATELLITE_PULL_FIELDS; when any are pulled we push them into the
# controller config so the deck matches the server: weather (bra) and the UI
# theme that recolours the keys (gxl).
_STREAMDECK_SYNCED_FIELDS = (
    "streamdeck_weather_location", "streamdeck_weather_units", "ui_theme",
)


def _merge_streamdeck_settings(config: dict, location: str, units: str, theme: str) -> dict:
    """Return config with the synced weather and theme overlaid.

    The bridge rewrites the whole config.toml from the posted dict, so a caller
    must read the current config, overlay just these keys, and post the whole
    thing back. Kept pure so the read-modify-write is unit-testable.
    """
    merged = dict(config)
    merged["weather_location"] = location
    merged["weather_units"] = units
    merged["theme"] = theme
    return merged


def _push_streamdeck_settings(timeout: float = 4.0) -> bool:
    """Mirror the synced weather + theme into the local Stream Deck config.toml.

    Best-effort and only meaningful on a Pi appliance with a deck: reads the
    current bridge config, overlays the weather and theme fields from settings,
    and posts the merged config back so the running controller (which watches
    config.toml) picks up the server's values without a manual save. Returns
    True on a successful write, False on any error or when not applicable.
    Never raises.
    """
    try:
        from ..hardware import is_raspberry_pi
        if not (is_raspberry_pi() and settings.has_streamdeck):
            return False
        cur = httpx.get(f"{_HOST_BRIDGE}/streamdeck/config", timeout=timeout)
        config = (cur.json() or {}).get("config", {}) if cur.status_code == 200 else {}
        merged = _merge_streamdeck_settings(
            config,
            settings.streamdeck_weather_location,
            settings.streamdeck_weather_units,
            settings.ui_theme,
        )
        resp = httpx.post(
            f"{_HOST_BRIDGE}/streamdeck/config", json={"config": merged}, timeout=timeout
        )
        return resp.status_code == 200
    except Exception as exc:  # bridge down, not a Pi, etc.: leave the deck as-is
        logger.warning("satellite sync: could not push Stream Deck settings: %s", exc)
        return False


def _apply_defaults(rows: list[dict]) -> int:
    """Replace the local expiry-defaults table with the server's copy.

    Deferred imports keep this module importable without a DB in tests that
    only exercise _apply_config.
    """
    from ..database import SessionLocal
    from ..models.db_models import ExpiryDefault

    db = SessionLocal()
    try:
        db.query(ExpiryDefault).delete()
        for r in rows:
            db.add(ExpiryDefault(
                category=r.get("category", ""),
                name_pattern=r.get("name_pattern", ""),
                storage_type=r.get("storage_type", ""),
                default_days=int(r.get("default_days", 0)),
                notes=r.get("notes"),
                priority=int(r.get("priority", 0)),
            ))
        db.commit()
        return len(rows)
    finally:
        db.close()


def _apply_profiles(rows: list[dict]) -> int:
    """Replace the local Stream Deck profiles table with the server's copy.

    Deferred imports keep this module importable without a DB in tests.
    """
    import json as _json
    from datetime import datetime, timezone
    from ..database import SessionLocal
    from ..models.db_models import StreamDeckProfile

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db = SessionLocal()
    try:
        db.query(StreamDeckProfile).delete()
        for r in rows:
            db.add(StreamDeckProfile(
                name=r.get("name", ""),
                deck_size=int(r.get("deck_size", 0)),
                key_overrides=_json.dumps(r.get("key_overrides", [])),
                created_at=r.get("updated_at", now),
                updated_at=r.get("updated_at", now),
            ))
        db.commit()
        return len(rows)
    finally:
        db.close()


def sync_from_upstream(timeout: float = 8.0) -> dict:
    """Pull backend config + defaults from the main server and apply them.

    Returns a small status dict: {"ok": bool, "applied": [...], "defaults": N,
    "command": str|None, "error": str|None}. Never raises on a network/HTTP
    failure. Each genuine pull attempt is recorded in the persisted
    ``satellite_last_sync`` setting so the setup page can show sync health.
    """
    result = _do_sync_from_upstream(timeout)
    # Skip the "not a satellite" guard: it is not a real pull attempt and only
    # fires in non-satellite or test contexts, so it should not overwrite the
    # last genuine sync status shown in the UI.
    if result.get("error") != "not a satellite":
        _record_last_sync(result)
    return result


def _do_sync_from_upstream(timeout: float = 8.0) -> dict:
    if not settings.is_satellite():
        return {"ok": False, "error": "not a satellite", "applied": [], "defaults": 0, "command": None}
    base = (settings.remote_server_url or "").rstrip("/")
    if not base or not settings.upstream_api_key:
        return {"ok": False, "error": "missing server URL or API key", "applied": [], "defaults": 0, "command": None}

    url = f"{base}/api/config/satellite"
    # Identity headers turn this pull into a heartbeat: the server records us in
    # its remotes list and may hand back a queued command in the response.
    headers = {
        "X-API-Key": settings.upstream_api_key,
        "X-Device-Id": settings.device_id,
        "X-Device-Hostname": socket.gethostname(),
        "X-Device-Mode": settings.deployment_mode,
        "X-Device-Version": APP_VERSION,
        "X-Device-Ip": _local_ip(),
    }
    try:
        resp = httpx.get(url, headers=headers, timeout=timeout)
    except Exception as exc:  # network error: keep prior config
        logger.warning("satellite sync: cannot reach %s: %s", url, exc)
        return {"ok": False, "error": f"cannot reach server: {exc}", "applied": [], "defaults": 0, "command": None}

    if resp.status_code != 200:
        detail = ""
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            detail = resp.text[:200]
        logger.warning("satellite sync: server returned %s: %s", resp.status_code, detail)
        return {"ok": False, "error": f"server {resp.status_code}: {detail}", "applied": [], "defaults": 0, "command": None}

    data = resp.json()
    applied = _apply_config(data.get("config", {}))
    defaults_n = 0
    try:
        defaults_n = _apply_defaults(data.get("expiry_defaults", []))
    except Exception as exc:  # DB not ready or bad row: config still applied
        logger.warning("satellite sync: applied config but defaults failed: %s", exc)
    try:
        _apply_profiles(data.get("streamdeck_profiles", []))
    except Exception as exc:
        logger.warning("satellite sync: could not mirror Stream Deck profiles: %s", exc)

    # Pulling new provider keys/models must invalidate the cached provider.
    try:
        from ..dependencies import reset_providers
        reset_providers()
    except Exception:
        pass

    # If the pull changed the Stream Deck weather or the UI theme, mirror it
    # into the local controller config.toml so the deck matches the server
    # (bra: weather, gxl: theme colours).
    if any(f in applied for f in _STREAMDECK_SYNCED_FIELDS):
        _push_streamdeck_settings()

    command = data.get("command")
    if command == "resync":
        # The heartbeat already re-pulled config in this same request, so a
        # queued resync is satisfied just by us getting here. Nothing more to do.
        logger.info("satellite sync: server requested resync (already fulfilled by this pull)")
    elif command:
        # Unknown command from a newer server: ignore so old satellites keep working.
        logger.info("satellite sync: ignoring unknown command %r", command)

    logger.info("satellite sync: applied %d fields, %d defaults from %s",
                len(applied), defaults_n, base)
    return {"ok": True, "applied": applied, "defaults": defaults_n, "command": command, "error": None}
