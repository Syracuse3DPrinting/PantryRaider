"""The managed AI proxy.

Gate order per request: instance token, rate limit, active entitlement,
monthly quota, then forward. Over-quota answers 402 with a structured body
the app can surface exactly like its local token-budget gate
(service/app/routers/analyze.py). Image bytes pass through in memory only;
nothing image-shaped is ever persisted here.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import ratelimit, usage
from ..config import settings
from ..deps import current_instance, get_db, utc_now_iso
from ..forwarder import get_forwarder
from ..models import Instance

router = APIRouter(prefix="/v1/ai", tags=["ai"])

_KINDS = {"food", "receipt", "enrich"}
_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/heic"}


def _quota_gate(db: Session, account_id: int) -> dict:
    """The account's quota state, raising the 402 the app maps to its
    budget-gate message when the entitlement is missing or spent."""
    state = usage.quota_state(db, account_id, usage.month_key())
    if not state["active"]:
        raise HTTPException(402, detail={
            "error": "no_subscription",
            "message": "This install is linked, but the account has no active "
                       "subscription.",
        })
    if state["over_quota"]:
        raise HTTPException(402, detail={
            "error": "quota_exceeded",
            "used": state["used"],
            "quota": state["quota"],
            "month": state["month"],
            "message": "Monthly AI quota reached. It resets at the start of "
                       "next month.",
        })
    return state


@router.post("/analyze")
async def analyze(
    kind: str = Form(...),
    text: str = Form(""),
    image: UploadFile | None = File(None),
    inst: Instance = Depends(current_instance),
    db: Session = Depends(get_db),
):
    if kind not in _KINDS:
        raise HTTPException(400, detail=f"Unknown task kind: {kind}")
    if not ratelimit.allow(f"proxy:{inst.id}", settings.proxy_rate_per_minute):
        raise HTTPException(429, detail="Too many requests, slow down")
    _quota_gate(db, inst.account_id)

    image_data: bytes | None = None
    mime = ""
    if kind in ("food", "receipt"):
        if image is None:
            raise HTTPException(400, detail="Image tasks need an image upload")
        mime = image.content_type or ""
        if mime not in _ALLOWED_MIME:
            raise HTTPException(400, detail=f"Unsupported image type: {mime}")
        image_data = await image.read()

    fwd = get_forwarder()
    result = await fwd.forward(kind, image_data, mime, text)
    del image_data  # transit only: the bytes never outlive the request

    usage.record(db, inst.account_id, inst.id, result.tokens, kind,
                 usage.month_key(), utc_now_iso())
    state = usage.quota_state(db, inst.account_id, usage.month_key())
    return {
        "result": result.result,
        "tokens": result.tokens,
        "quota": {"used": state["used"], "quota": state["quota"],
                  "remaining": state["remaining"], "month": state["month"]},
    }
