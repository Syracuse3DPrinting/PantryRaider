"""Bluetooth kitchen thermometer endpoints (FoodAssistant-6ivl).

The host-side reader daemon and the Timers page meet here:

  GET  /gadgets/config            what the reader should do (enabled flag +
                                  configured device list), polled by the daemon
  POST /gadgets/readings          probe readings + discovered devices, pushed
                                  by the daemon every few seconds
  GET  /gadgets/state             the UI snapshot the Timers page polls
  POST /gadgets/devices           add a discovered thermometer (turns the
                                  feature on if it was off)
  DELETE /gadgets/devices/{id}    remove a thermometer
  POST /gadgets/target            set or clear a probe's target temperature

Configuration lives in settings (gadgets_enabled, gadget_devices), so it
round-trips through the normal settings persistence and the daemon needs no
file coupling with the app.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..config import settings
from ..services import gadgets

router = APIRouter(prefix="/gadgets", tags=["gadgets"])


class DeviceIn(BaseModel):
    id: str
    name: str = ""
    protocol: str = ""


class TargetIn(BaseModel):
    device_id: str
    probe: int
    temp_c: float | None = None   # None clears the target
    direction: str = "above"      # above | below


def _norm_id(value: str) -> str:
    return str(value or "").strip().upper()


@router.get("/config")
async def reader_config():
    """What the host-side reader should do. Devices are listed even while the
    feature is off so a passive scan can keep the add list warm; the daemon
    only connects to devices when enabled is true."""
    return {
        "enabled": bool(settings.gadgets_enabled),
        "devices": gadgets.configured_devices(),
    }


@router.post("/readings")
async def post_readings(payload: dict):
    """Ingest a reader push: live probe readings plus discovered devices."""
    return gadgets.ingest(payload if isinstance(payload, dict) else {})


@router.get("/state")
async def state():
    """The Timers page snapshot: live probes, targets, and devices to add."""
    return gadgets.get_state()


@router.post("/devices")
async def add_device(payload: DeviceIn):
    """Add a thermometer (usually one the reader discovered). Adding the
    first device is the feature opt-in, so it also flips gadgets_enabled."""
    dev_id = _norm_id(payload.id)
    if not dev_id:
        return {"ok": False, "error": "a device id is required"}
    protocol = payload.protocol if payload.protocol in gadgets.PROTOCOLS else ""
    devices = [dict(d) for d in gadgets.configured_devices()]
    for dev in devices:
        if _norm_id(dev.get("id")) == dev_id:
            if payload.name:
                dev["name"] = payload.name[:60]
            if protocol:
                dev["protocol"] = protocol
            break
    else:
        devices.append({"id": dev_id, "name": payload.name[:60],
                        "protocol": protocol, "targets": {}})
    settings.save({"gadget_devices": devices, "gadgets_enabled": True})
    return {"ok": True, "devices": devices}


@router.delete("/devices/{device_id}")
async def remove_device(device_id: str):
    dev_id = _norm_id(device_id)
    devices = [dict(d) for d in gadgets.configured_devices()
               if _norm_id(d.get("id")) != dev_id]
    settings.save({"gadget_devices": devices})
    return {"ok": True, "devices": devices}


@router.post("/target")
async def set_target(payload: TargetIn):
    """Set or clear one probe's target temperature (stored in Celsius)."""
    dev_id = _norm_id(payload.device_id)
    devices = [dict(d) for d in gadgets.configured_devices()]
    for dev in devices:
        if _norm_id(dev.get("id")) != dev_id:
            continue
        targets = dict(dev.get("targets") or {})
        key = str(int(payload.probe))
        if payload.temp_c is None:
            targets.pop(key, None)
        else:
            direction = "below" if payload.direction == "below" else "above"
            targets[key] = {"temp_c": round(float(payload.temp_c), 1),
                            "direction": direction}
        dev["targets"] = targets
        settings.save({"gadget_devices": devices})
        return {"ok": True, "devices": devices}
    return {"ok": False, "error": "unknown device"}
