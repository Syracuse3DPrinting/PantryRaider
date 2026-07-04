"""Instance pairing and the instance status endpoint.

The flow mirrors the app's satellite pairing pattern: the portal mints a
short-lived code, the install redeems it (the code is the credential) and
receives a long-lived instance token, shown once and stored hashed. From
then on the install dials out with the token; the cloud never reaches in.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import usage
from ..config import settings
from ..deps import current_account, current_instance, get_db, utc_now_iso
from ..models import Account, Instance, PairingCode
from ..security import new_pairing_code, new_token, token_hash

router = APIRouter(prefix="/v1", tags=["instances"])


@router.post("/pairing/code")
def create_pairing_code(account: Account = Depends(current_account),
                        db: Session = Depends(get_db)):
    code = new_pairing_code()
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=settings.pairing_code_ttl_minutes)
    expires_at = expires.isoformat(timespec="seconds")
    db.add(PairingCode(code_hash=token_hash(code), account_id=account.id,
                       expires_at=expires_at, created_at=utc_now_iso()))
    db.commit()
    return {"code": code, "expires_at": expires_at}


class RedeemRequest(BaseModel):
    code: str
    name: str = ""


@router.post("/pairing/redeem")
def redeem_pairing_code(payload: RedeemRequest, db: Session = Depends(get_db)):
    row = db.query(PairingCode).filter_by(
        code_hash=token_hash(payload.code.strip().upper())).first()
    if not row or row.redeemed or row.expires_at < utc_now_iso():
        # One message for unknown, used, and expired: a probe learns nothing.
        raise HTTPException(400, detail="Invalid or expired pairing code")
    row.redeemed = 1
    token = new_token("prc")
    inst = Instance(token_hash=token_hash(token), account_id=row.account_id,
                    name=payload.name.strip()[:120], created_at=utc_now_iso())
    db.add(inst)
    db.commit()
    # The only time the token crosses the wire; the database keeps its hash.
    return {"instance_token": token, "instance_id": inst.id}


@router.get("/instance/me")
def instance_me(inst: Instance = Depends(current_instance),
                db: Session = Depends(get_db)):
    """Entitlement status and quota remaining, for the app's settings page."""
    state = usage.quota_state(db, inst.account_id, usage.month_key())
    return {"instance_id": inst.id, "name": inst.name, "entitlement": state}
