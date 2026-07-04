"""The AI proxy's gates: entitlement, quota, ledger, and rate limit."""
import io

from app.database import SessionLocal
from app.forwarder import StubForwarder
from app.models import UsageLedger
from tests.conftest import activate_entitlement


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _analyze(client, token, kind="food"):
    files = {}
    if kind in ("food", "receipt"):
        files = {"image": ("photo.jpg", io.BytesIO(b"fake-jpeg-bytes"), "image/jpeg")}
    return client.post("/v1/ai/analyze", data={"kind": kind},
                       files=files, headers=_auth(token))


def test_requires_instance_token(client):
    resp = client.post("/v1/ai/analyze", data={"kind": "food"})
    assert resp.status_code == 401


def test_no_subscription_is_402(client, instance_token):
    resp = _analyze(client, instance_token)
    assert resp.status_code == 402
    assert resp.json()["detail"]["error"] == "no_subscription"


def test_analyze_records_usage(client, instance_token):
    activate_entitlement()
    resp = _analyze(client, instance_token)
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["stub"] is True
    assert body["tokens"] == StubForwarder.STUB_TOKENS
    assert body["quota"]["used"] == StubForwarder.STUB_TOKENS

    db = SessionLocal()
    try:
        rows = db.query(UsageLedger).all()
        assert len(rows) == 1
        assert rows[0].tokens == StubForwarder.STUB_TOKENS
        assert rows[0].kind == "food"
    finally:
        db.close()


def test_enrich_needs_no_image(client, instance_token):
    activate_entitlement()
    resp = client.post("/v1/ai/analyze",
                       data={"kind": "enrich", "text": "barcode product data"},
                       headers=_auth(instance_token))
    assert resp.status_code == 200
    assert resp.json()["result"]["kind"] == "enrich"


def test_quota_exceeded_is_402(client, instance_token):
    account_id = activate_entitlement()
    # Spend the whole quota directly in the ledger, then make one more call.
    from app import usage
    from app.config import PLAN_QUOTAS
    db = SessionLocal()
    try:
        usage.record(db, account_id, 1, PLAN_QUOTAS["starter"], "food",
                     usage.month_key(), "2026-01-01T00:00:00+00:00")
    finally:
        db.close()
    resp = _analyze(client, instance_token)
    assert resp.status_code == 402
    detail = resp.json()["detail"]
    assert detail["error"] == "quota_exceeded"
    assert detail["used"] >= detail["quota"] > 0
    assert detail["month"]


def test_rejects_bad_inputs(client, instance_token):
    activate_entitlement()
    no_image = client.post("/v1/ai/analyze", data={"kind": "food"},
                           headers=_auth(instance_token))
    assert no_image.status_code == 400
    bad_kind = client.post("/v1/ai/analyze", data={"kind": "poetry"},
                           headers=_auth(instance_token))
    assert bad_kind.status_code == 400
    bad_mime = client.post(
        "/v1/ai/analyze", data={"kind": "food"},
        files={"image": ("x.gif", io.BytesIO(b"gif"), "image/gif")},
        headers=_auth(instance_token))
    assert bad_mime.status_code == 400


def test_proxy_rate_limit(client, instance_token, monkeypatch):
    activate_entitlement()
    from app.config import settings
    monkeypatch.setattr(settings, "proxy_rate_per_minute", 2)
    assert _analyze(client, instance_token).status_code == 200
    assert _analyze(client, instance_token).status_code == 200
    assert _analyze(client, instance_token).status_code == 429
