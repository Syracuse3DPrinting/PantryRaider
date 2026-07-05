"""Per-account monthly token accounting over the usage ledger.

The per-account counterpart of the app's local usage tracker
(service/app/services/usage.py); the month-key and quota semantics match it
on purpose so the app can surface cloud quota errors exactly like its local
budget gate. Duplicated rather than imported: cloud/ shares nothing at
import time with service/.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import EXPIRED_PLAN, PLAN_QUOTAS, TRIAL_DAYS, TRIAL_PLAN
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


def entitlement_active(ent, now_iso: str | None = None) -> bool:
    """Whether an entitlement row counts right now. Status must be active,
    and a row with a hard expiry (trials and comped plans) must not be
    past it."""
    if not ent or ent.status != "active":
        return False
    if ent.expires_at:
        if now_iso is None:
            now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if ent.expires_at < now_iso:
            return False
    return True


# Resolution order when an account holds more than one entitlement row: an
# active paid plan wins over an active comp, which wins over the signup
# trial. Rows written before the source column exists ("") are Stripe rows.
_SOURCE_PRIORITY = {"stripe": 0, "": 0, "comp": 1, "trial": 2}
_PAID_SOURCES = {"stripe", ""}


def resolve_entitlement(rows, now_iso: str | None = None):
    """The entitlement row that governs the account right now, or None."""
    active = [e for e in rows if entitlement_active(e, now_iso)]
    if not active:
        return None
    return min(active, key=lambda e: _SOURCE_PRIORITY.get(e.source, 0))


def grant_trial(db: Session, account_id: int, created_at: str) -> None:
    """The automatic signup trial: 30 days of the premium quota, expiry
    derived at creation time so no cron job is needed. Reuses the same
    expires_at machinery as comped plans."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=TRIAL_DAYS)
    db.add(Entitlement(account_id=account_id, plan=TRIAL_PLAN,
                       status="active",
                       monthly_token_quota=PLAN_QUOTAS[TRIAL_PLAN],
                       source="trial",
                       expires_at=expires.isoformat(timespec="seconds"),
                       updated_at=created_at))
    db.commit()


def trial_days_left(ent, now=None) -> int:
    """Whole days until a trial entitlement expires (counting a partial
    day as a day, so a fresh trial reads 30 and expiry day reads 1)."""
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        expires = datetime.fromisoformat(ent.expires_at)
    except (TypeError, ValueError):
        return 0
    remaining = expires - now
    return max(0, remaining.days + (1 if remaining.seconds or remaining.microseconds else 0))


def quota_state(db: Session, account_id: int, mk: str) -> dict:
    """Entitlement + usage snapshot for gates and the status endpoints.

    Resolution order: active paid plan > active comp > active trial >
    nothing. With nothing active the plan reads "expired" and the quota is
    zero: Forager is trial-then-paid, there is no free tier underneath.
    "active" keeps its original meaning (an active paid entitlement
    exists); "entitled" says whether anything, trial included, is active,
    and is what the remote-access flags will read too.
    """
    rows = db.query(Entitlement).filter_by(account_id=account_id).all()
    ent = resolve_entitlement(rows)
    used = month_total(db, account_id, mk)
    if ent:
        plan = ent.plan
        quota = int(ent.monthly_token_quota)
    else:
        plan = EXPIRED_PLAN
        quota = 0
    days_left = trial_days_left(ent) if ent and ent.source == "trial" else None
    return {
        "active": ent is not None and ent.source in _PAID_SOURCES,
        "entitled": ent is not None,
        "plan": plan,
        "trial_days_left": days_left,
        "quota": quota,
        "used": used,
        "remaining": max(0, quota - used),
        "over_quota": quota > 0 and used >= quota,
        "month": mk,
    }
