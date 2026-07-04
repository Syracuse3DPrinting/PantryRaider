"""Pantry Raider Cloud settings.

Environment-driven (CLOUD_ prefix), no settings.json: the cloud runs on one
VPS with an env file, not on appliances with a setup wizard. This service
shares nothing at import time with service/ (see docs/design/cloud-platform.md);
where behaviour matches the app, the logic is duplicated on purpose.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings

CLOUD_VERSION = "0.1.0"

# Placeholder plan table until Dan picks real tiers and prices. The Stripe
# price id maps a Checkout purchase to a plan; the quota is AI tokens per
# calendar month, the same unit service/app/services/usage.py meters locally.
PLAN_QUOTAS: dict[str, int] = {
    "starter": 2_000_000,
}
DEFAULT_PLAN = "starter"


class CloudSettings(BaseSettings):
    # Prod is Postgres (multi-tenant, concurrent webhook + proxy writers).
    # Tests override this with SQLite so the suite runs without Docker.
    database_url: str = "postgresql+psycopg2://pantry:pantry@db:5432/pantrycloud"

    # Stripe webhook endpoint secret ("whsec_..."). The placeholder keeps the
    # signature check real in tests; the VPS env file supplies the live value.
    stripe_webhook_secret: str = "whsec_placeholder"

    # Maps Stripe price ids to plan names once real products exist.
    stripe_price_to_plan: dict[str, str] = {}

    # Portal session lifetime.
    session_ttl_hours: int = 24 * 14

    # Pairing codes are a short-lived credential typed by hand; keep the
    # window tight.
    pairing_code_ttl_minutes: int = 15

    # Fixed-window rate limits (requests per minute) for the abuse-prone
    # unauthenticated/spendy endpoints. 0 disables (used by most tests).
    signup_rate_per_minute: int = 10
    proxy_rate_per_minute: int = 30

    model_config = {"env_prefix": "CLOUD_"}


settings = CloudSettings()
