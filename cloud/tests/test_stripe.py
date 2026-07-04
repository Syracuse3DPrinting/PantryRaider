"""Stripe webhook: signed events become entitlements, idempotently."""
import hashlib
import hmac
import json
import time

from app.config import PLAN_QUOTAS, settings
from app.database import SessionLocal
from app.models import Account, Entitlement, Subscription


def _post_event(client, event: dict, secret: str | None = None):
    payload = json.dumps(event).encode()
    ts = int(time.time())
    sig = hmac.new((secret or settings.stripe_webhook_secret).encode(),
                   f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return client.post("/v1/stripe/webhook", content=payload,
                       headers={"Stripe-Signature": f"t={ts},v1={sig}"})


def _account_id(client, session_token):
    db = SessionLocal()
    try:
        return db.query(Account).first().id
    finally:
        db.close()


def _checkout_event(account_id, event_id="evt_1"):
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {"object": {
            "client_reference_id": str(account_id),
            "customer": "cus_123",
            "subscription": "sub_123",
        }},
    }


def test_rejects_bad_signature(client):
    resp = _post_event(client, {"id": "evt_x", "type": "x"}, secret="whsec_wrong")
    assert resp.status_code == 400
    unsigned = client.post("/v1/stripe/webhook", content=b"{}")
    assert unsigned.status_code == 400


def test_checkout_completed_activates_entitlement(client, session_token):
    account_id = _account_id(client, session_token)
    resp = _post_event(client, _checkout_event(account_id))
    assert resp.status_code == 200

    db = SessionLocal()
    try:
        ent = db.query(Entitlement).filter_by(account_id=account_id).first()
        assert ent.status == "active"
        assert ent.monthly_token_quota == PLAN_QUOTAS["starter"]
        sub = db.query(Subscription).first()
        assert sub.stripe_subscription_id == "sub_123"
        assert sub.stripe_customer_id == "cus_123"
    finally:
        db.close()


def test_events_are_idempotent(client, session_token):
    account_id = _account_id(client, session_token)
    assert _post_event(client, _checkout_event(account_id)).status_code == 200
    dup = _post_event(client, _checkout_event(account_id))
    assert dup.status_code == 200
    assert dup.json().get("duplicate") is True
    db = SessionLocal()
    try:
        assert db.query(Subscription).count() == 1
    finally:
        db.close()


def test_subscription_deleted_deactivates(client, session_token):
    account_id = _account_id(client, session_token)
    _post_event(client, _checkout_event(account_id))
    resp = _post_event(client, {
        "id": "evt_2",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_123", "status": "canceled"}},
    })
    assert resp.status_code == 200
    db = SessionLocal()
    try:
        ent = db.query(Entitlement).filter_by(account_id=account_id).first()
        assert ent.status == "inactive"
        assert db.query(Subscription).first().status == "canceled"
    finally:
        db.close()


def test_subscription_updated_past_due_stays_active(client, session_token):
    account_id = _account_id(client, session_token)
    _post_event(client, _checkout_event(account_id))
    resp = _post_event(client, {
        "id": "evt_3",
        "type": "customer.subscription.updated",
        "data": {"object": {"id": "sub_123", "status": "past_due",
                            "current_period_end": 1780000000}},
    })
    assert resp.status_code == 200
    db = SessionLocal()
    try:
        ent = db.query(Entitlement).filter_by(account_id=account_id).first()
        assert ent.status == "active"
    finally:
        db.close()


def test_unattributed_events_are_acknowledged(client):
    # A checkout with no matching account, and an unknown event type: both
    # return 200 so Stripe stops retrying, and change nothing.
    assert _post_event(client, _checkout_event(999999)).status_code == 200
    assert _post_event(client, {"id": "evt_9", "type": "invoice.paid",
                                "data": {"object": {}}}).status_code == 200
    db = SessionLocal()
    try:
        assert db.query(Entitlement).count() == 0
    finally:
        db.close()
