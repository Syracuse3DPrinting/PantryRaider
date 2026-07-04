"""Per-account monthly token accounting over the usage ledger.

The per-account counterpart of the app's local usage tracker
(service/app/services/usage.py); the month-key and quota semantics match it
on purpose so the app can surface cloud quota errors exactly like its local
budget gate. Duplicated rather than imported: cloud/ shares nothing at
import time with service/.
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import Entitlement, UsageLedger


def month_key(now=None) -> str:
    """Current 'YYYY-MM' key in UTC. ``now`` injectable for tests."""
    if now is None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


def month_total(db: Session, account_id: int, mk: str) -> int:
    total = (
        db.query(func.coalesce(func.sum(UsageLedger.tokens), 0))
        .filter(UsageLedger.account_id == account_id,
                UsageLedger.month_key == mk)
        .scalar()
    )
    return int(total or 0)


def record(db: Session, account_id: int, instance_id: int, tokens: int,
           kind: str, mk: str, created_at: str) -> None:
    """Append a ledger row. No-op for zero or negative counts."""
    if not tokens or tokens < 0:
        return
    db.add(UsageLedger(account_id=account_id, instance_id=instance_id,
                       month_key=mk, tokens=int(tokens), kind=kind,
                       created_at=created_at))
    db.commit()


def quota_state(db: Session, account_id: int, mk: str) -> dict:
    """Entitlement + usage snapshot for gates and the status endpoints."""
    ent = db.query(Entitlement).filter_by(account_id=account_id).first()
    used = month_total(db, account_id, mk)
    quota = int(ent.monthly_token_quota) if ent else 0
    active = bool(ent and ent.status == "active")
    return {
        "active": active,
        "plan": ent.plan if ent else "",
        "quota": quota,
        "used": used,
        "remaining": max(0, quota - used) if quota else 0,
        "over_quota": active and quota > 0 and used >= quota,
        "month": mk,
    }
