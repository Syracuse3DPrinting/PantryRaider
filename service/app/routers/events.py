"""On-screen Home Assistant event channel (notifications + camera pop-ups).

Home Assistant pushes events here with an automation's ``rest_command`` (sending
the X-API-Key), and the kiosk / web UI polls ``/events/poll`` and shows them.

  POST /events/notify         {message, title?, level?, timeout?}
  POST /events/camera-popup   {camera?, seconds?}   (camera by name; default first)
  POST /events/test           queue a sample notification (used by the setup UI)
  GET  /events/poll?since=<id> events newer than <id>, plus the current last id

Notifications and pop-ups target the screen of the instance HA posts to. On a
satellite point the HA automation at the satellite (the device with the display).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ..config import settings
from ..services import ha_events
from ..services.cameras import resolve_ha_entity

router = APIRouter(prefix="/events", tags=["events"])


class NotifyPayload(BaseModel):
    message: str = ""
    title: str = ""
    level: str = "info"          # info | success | warning | error
    timeout: int = 0             # seconds on screen; 0 = the client default


class CameraPopupPayload(BaseModel):
    camera: str = ""             # camera name; empty = the first configured camera
    seconds: int = 0             # 0 = the configured default


def _camera_src(name: str) -> tuple[str, str]:
    """Return (resolved_name, proxy_snapshot_src) for a camera by name, or ("","").

    Matches by camera name (case-insensitive); an empty/unknown name falls back
    to the first configured camera so a pop-up always shows something. The src is
    the same-origin proxy path the kiosk already uses, so HA cameras work without
    the kiosk handling the bearer token.
    """
    cams = settings.streamdeck_cameras or []
    want = (name or "").strip().lower()
    idx = -1
    if want:
        for i, cam in enumerate(cams):
            if isinstance(cam, dict) and str(cam.get("name", "")).strip().lower() == want:
                idx = i
                break
    if idx < 0:
        for i, cam in enumerate(cams):
            if isinstance(cam, dict) and (cam.get("snapshot_url") or cam.get("ha_entity") or resolve_ha_entity(cam)[0]):
                idx = i
                break
    if idx < 0:
        return "", ""
    cam = cams[idx]
    return (cam.get("name", "") if isinstance(cam, dict) else ""), f"ui/camera/{idx}/snapshot"


@router.post("/notify")
async def notify(payload: NotifyPayload):
    """Queue a notification toast for the display."""
    if not payload.message.strip() and not payload.title.strip():
        return {"ok": False, "error": "message or title is required"}
    eid = ha_events.add_notification(
        payload.message, title=payload.title, level=payload.level, timeout=payload.timeout
    )
    return {"ok": True, "id": eid}


@router.post("/camera-popup")
async def camera_popup(payload: CameraPopupPayload):
    """Queue a camera pop-up for the display (for example on person detected)."""
    name, src = _camera_src(payload.camera)
    if not src:
        return {"ok": False, "error": "No matching camera is configured."}
    seconds = payload.seconds or int(settings.ha_camera_popup_seconds or 20)
    eid = ha_events.add_camera(name=name, src=src, seconds=seconds)
    return {"ok": True, "id": eid, "camera": name}


@router.post("/test")
async def test_event():
    """Queue a sample notification so the user can confirm the channel works."""
    eid = ha_events.add_notification(
        "If you can read this, Home Assistant notifications are wired up.",
        title="FoodAssistant test", level="success",
    )
    return {"ok": True, "id": eid}


@router.get("/poll")
async def poll(since: int = 0):
    return ha_events.poll(since)
