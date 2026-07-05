"""Account signup, login, and the portal's own-account view."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import ratelimit, usage
from ..config import settings
from ..deps import (ACCOUNT_DISABLED_MESSAGE, client_ip, current_account,
                    get_db, utc_now_iso)
from ..models import Account, AuthSession, Instance
from ..security import (hash_password, new_token, password_problem,
                        token_hash, verify_password)

router = APIRouter(prefix="/v1/accounts", tags=["accounts"])


class Credentials(BaseModel):
    # A minimal shape check, not full RFC validation (pydantic's EmailStr
    # would pull in email-validator; not worth a dependency to police typos).
    email: str
    password: str


def _valid_email(email: str) -> bool:
    local, _, domain = email.partition("@")
    return bool(local) and "." in domain and " " not in email


def authenticate(db: Session, email: str, password: str) -> Account | None:
    """The account matching these credentials, or None. Shared by login,
    the portal forms, and one-step provisioning."""
    account = db.query(Account).filter_by(email=email.strip().lower()).first()
    if not account or not verify_password(password, account.password_hash):
        return None
    return account


def _issue_session(db: Session, account_id: int) -> str:
    token = new_token("prs")
    expires = datetime.now(timezone.utc) + timedelta(hours=settings.session_ttl_hours)
    db.add(AuthSession(token_hash=token_hash(token), account_id=account_id,
                       expires_at=expires.isoformat(timespec="seconds"),
                       created_at=utc_now_iso()))
    db.commit()
    return token


@router.post("/signup")
def signup(payload: Credentials, request: Request, db: Session = Depends(get_db)):
    client = client_ip(request)
    if not ratelimit.allow(f"signup:{client}", settings.signup_rate_per_minute):
        raise HTTPException(429, detail="Too many signup attempts, try again in a minute")
    email = payload.email.strip().lower()
    problem = password_problem(payload.password, email)
    if problem:
        raise HTTPException(400, detail=problem)
    if not _valid_email(email):
        raise HTTPException(400, detail="Enter a valid email address")
    if db.query(Account).filter_by(email=email).first():
        raise HTTPException(409, detail="An account with that email already exists")
    account = Account(email=email, password_hash=hash_password(payload.password),
                      created_at=utc_now_iso())
    db.add(account)
    db.commit()
    # Every new account starts its 30-day trial immediately; the expiry is
    # written now, so it lapses on its own with no cron job.
    usage.grant_trial(db, account.id, account.created_at)
    return {"session_token": _issue_session(db, account.id)}


@router.post("/login")
def login(payload: Credentials, request: Request, db: Session = Depends(get_db)):
    client = client_ip(request)
    if not ratelimit.allow(f"login:{client}", settings.login_rate_per_minute):
        raise HTTPException(429, detail="Too many login attempts, try again in a minute")
    account = authenticate(db, payload.email, payload.password)
    if not account:
        # One message for both cases, so login does not confirm which emails exist.
        raise HTTPException(401, detail="Invalid email or password")
    if account.disabled:
        raise HTTPException(403, detail=ACCOUNT_DISABLED_MESSAGE)
    return {"session_token": _issue_session(db, account.id)}


@router.get("/me")
def me(account: Account = Depends(current_account), db: Session = Depends(get_db)):
    state = usage.quota_state(db, account.id, usage.month_key())
    instances = db.query(Instance).filter_by(account_id=account.id).all()
    return {
        "email": account.email,
        "entitlement": state,
        "instances": [
            {"id": i.id, "name": i.name, "app_version": i.app_version,
             "deployment_mode": i.deployment_mode, "last_seen_at": i.last_seen_at}
            for i in instances
        ],
    }
