"""Stripe webhook: Checkout and subscription events become entitlements.

No Stripe SDK and no outbound Stripe calls in the scaffold; the endpoint
verifies the signature over the raw body (security.verify_stripe_signature)
and reads the documented event shapes. Event ids are recorded so Stripe's
retried deliveries process once.

Wiring expectations for the live Stripe account: the Checkout Session is
created with client_reference_id set to the cloud account id, and the
starter plan's live price id is set in CLOUD_STRIPE_PRICE_STARTER (future
tiers go in CLOUD_STRIPE_PRICE_TO_PLAN). An unrecognised price falls back
to the default paid plan.
"""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import DEFAULT_PLAN, PLAN_QUOTAS, settings
from ..deps import get_db, utc_now_iso
from ..models import Account, Entitlement, StripeEvent, Subscription
from ..security import verify_stripe_signature

router = APIRouter(prefix="/v1/stripe", tags=["stripe"])

# Stripe subscription statuses that count as an active entitlement. Past-due
# stays active through Stripe's retry window; a final failure arrives as a
# status change or deletion event.
_ACTIVE_STATUSES = {"active", "trialing", "past_due"}


def _set_entitlement(db: Session, account_id: int, plan: str, status: str) -> None:
    ent = db.query(Entitlement).filter_by(account_id=account_id).first()
    if not ent:
        ent = Entitlement(account_id=account_id)
        db.add(ent)
    ent.plan = plan
    ent.status = status
    ent.monthly_token_quota = PLAN_QUOTAS.get(plan, 0)
    # A Stripe event owns the entitlement from here on: a real purchase
    # replaces any admin-comped grant, and Stripe rows never carry the
    # comp-style hard expiry (their lifecycle arrives as webhook events).
    ent.source = "stripe"
    ent.expires_at = ""
    ent.updated_at = utc_now_iso()
    db.commit()


def _plan_for_price(price_id: str) -> str:
    """CLOUD_STRIPE_PRICE_STARTER maps the live starter price to its plan;
    the price_to_plan dict covers any future tiers."""
    if price_id and price_id == settings.stripe_price_starter:
        return "starter"
    return settings.stripe_price_to_plan.get(price_id, DEFAULT_PLAN)


def _handle_checkout_completed(db: Session, obj: dict) -> None:
    """checkout.session.completed: the purchase that creates the entitlement."""
    try:
        account_id = int(obj.get("client_reference_id") or 0)
    except (TypeError, ValueError):
        account_id = 0
    if not account_id or not db.get(Account, account_id):
        return  # a purchase we cannot attribute; Stripe's dashboard still has it
    sub_id = str(obj.get("subscription") or "")
    if sub_id:
        sub = db.query(Subscription).filter_by(stripe_subscription_id=sub_id).first()
        if not sub:
            sub = Subscription(account_id=account_id, stripe_subscription_id=sub_id)
            db.add(sub)
        sub.stripe_customer_id = str(obj.get("customer") or "")
        sub.status = "active"
        sub.updated_at = utc_now_iso()
    _set_entitlement(db, account_id, DEFAULT_PLAN, "active")


def _handle_subscription_event(db: Session, obj: dict, deleted: bool) -> None:
    """customer.subscription.updated / .deleted: status changes after purchase."""
    sub_id = str(obj.get("id") or "")
    sub = db.query(Subscription).filter_by(stripe_subscription_id=sub_id).first()
    if not sub:
        return  # a subscription we never attributed to an account
    status = "canceled" if deleted else str(obj.get("status") or "")
    sub.status = status
    period_end = obj.get("current_period_end")
    if isinstance(period_end, (int, float)):
        sub.current_period_end = str(int(period_end))
    sub.updated_at = utc_now_iso()

    plan = DEFAULT_PLAN
    items = (obj.get("items") or {}).get("data") or []
    if items:
        price_id = str(((items[0] or {}).get("price") or {}).get("id") or "")
        if price_id:
            plan = _plan_for_price(price_id)
    active = not deleted and status in _ACTIVE_STATUSES
    _set_entitlement(db, sub.account_id, plan, "active" if active else "inactive")


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    header = request.headers.get("Stripe-Signature", "")
    if not verify_stripe_signature(payload, header,
                                   settings.stripe_webhook_secret,
                                   now=int(time.time())):
        raise HTTPException(400, detail="Invalid Stripe signature")

    try:
        event = json.loads(payload)
    except ValueError:
        raise HTTPException(400, detail="Invalid payload")

    event_id = str(event.get("id") or "")
    event_type = str(event.get("type") or "")
    if event_id:
        if db.query(StripeEvent).filter_by(event_id=event_id).first():
            return {"ok": True, "duplicate": True}
        db.add(StripeEvent(event_id=event_id, event_type=event_type,
                           processed_at=utc_now_iso()))
        db.commit()

    obj = (event.get("data") or {}).get("object") or {}
    if event_type == "checkout.session.completed":
        _handle_checkout_completed(db, obj)
    elif event_type == "customer.subscription.updated":
        _handle_subscription_event(db, obj, deleted=False)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_event(db, obj, deleted=True)
    # Unrecognised event types are acknowledged so Stripe stops retrying them.
    return {"ok": True}
