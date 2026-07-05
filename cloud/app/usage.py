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

from .config import FREE_PLAN, PLAN_QUOTAS
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
    """Entitlement + usage snapshot for gates and the status endpoints.

    Quota resolution: an active entitlement grants its plan quota;
    everything else (no entitlement, or an expired/canceled one) falls back
    to the free trial tier, so every paired account can use the proxy up to
    the free quota. "active" means an active paid entitlement exists.
    """
    ent = db.query(Entitlement).filter_by(account_id=account_id).first()
    used = month_total(db, account_id, mk)
    active = bool(ent and ent.status == "active")
    if active:
        plan = ent.plan
        quota = int(ent.monthly_token_quota)
    else:
        plan = FREE_PLAN
        quota = PLAN_QUOTAS[FREE_PLAN]
    return {
        "active": active,
        "plan": plan,
        "quota": quota,
        "used": used,
        "remaining": max(0, quota - used),
        "over_quota": quota > 0 and used >= quota,
        "month": mk,
    }
