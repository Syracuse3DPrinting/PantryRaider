"""Forager settings (Pantry Raider's hosted cloud service).

Environment-driven (CLOUD_ prefix), no settings.json: the cloud runs on one
VPS with an env file, not on appliances with a setup wizard. This service
shares nothing at import time with service/ (see docs/design/cloud-platform.md);
where behaviour matches the app, the logic is duplicated on purpose.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings

CLOUD_VERSION = "0.1.0"

# The plan table. Quotas are AI tokens per calendar month, the same unit
# service/app/services/usage.py meters locally. Every paired account gets
# the free trial tier automatically, no subscription needed; "starter"
# requires an active entitlement. Prices live in Stripe, never in code.
PLAN_QUOTAS: dict[str, int] = {
    "free": 100_000,
    "starter": 2_000_000,
}
FREE_PLAN = "free"
# The plan a paid Stripe purchase maps to when the price id is unrecognised.
DEFAULT_PLAN = "starter"


class CloudSettings(BaseSettings):
    # Prod is Postgres (multi-tenant, concurrent webhook + proxy writers).
    # Tests override this with SQLite so the suite runs without Docker.
    database_url: str = "postgresql+psycopg2://pantry:pantry@db:5432/pantrycloud"

    # Stripe webhook endpoint secret ("whsec_..."). The placeholder keeps the
    # signature check real in tests; the VPS env file supplies the live value.
    stripe_webhook_secret: str = "whsec_placeholder"

    # The Stripe price id for the starter plan (price_...). A Checkout
    # purchase or subscription carrying this price maps to "starter".
    stripe_price_starter: str = ""

    # The Stripe Checkout link the portal's Subscribe button points at.
    # Empty until billing goes live; the account page says so honestly
    # instead of showing a dead button.
    stripe_checkout_url: str = ""

    # Extra price-id-to-plan mappings, for future tiers.
    stripe_price_to_plan: dict[str, str] = {}

    # Google sign-in ("Continue with Google"). Fully gated: the portal
    # buttons and the /auth/google routes only exist when both values are
    # set. Credentials come from a Google Cloud OAuth client.
    google_client_id: str = ""
    google_client_secret: str = ""

    # The public origin this service is reached at. Google redirects back
    # to {public_base_url}/auth/google/callback, which must match the
    # redirect URI registered with the OAuth client.
    public_base_url: str = "https://forager.pantryraider.app"

    # Admin panel access: comma-separated account emails allowed into
    # /admin. Empty means nobody. Anyone not on the list gets a 404 there,
    # the same answer as a route that does not exist.
    admin_emails: str = ""

    # Blended Gemini 2.5 Flash cost per million tokens, used only for the
    # admin panel's month-to-date spend estimate. A rough weighting of the
    # $0.30/M input and $2.50/M output list prices for the proxy's
    # image-heavy, short-answer workload; tune it as real bills arrive.
    gemini_cost_per_million_tokens: float = 0.60

    # Which AIForwarder backs the proxy: "stub" (tests, local dev) or
    # "gemini" (production).
    ai_forwarder: str = "stub"

    # Gemini upstream for the AI proxy (used when ai_forwarder is "gemini").
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    forward_timeout_seconds: float = 60.0

    # Portal session lifetime.
    session_ttl_hours: int = 24 * 14

    # The portal session cookie is HttpOnly and SameSite=Lax always; Secure
    # is on by default (production sits behind Caddy TLS) and switched off
    # only for tests and plain-HTTP local dev.
    cookie_secure: bool = True

    # Pairing codes are a short-lived credential typed by hand; keep the
    # window tight.
    pairing_code_ttl_minutes: int = 15

    # Fixed-window rate limits (requests per minute) for the abuse-prone
    # unauthenticated/spendy endpoints. 0 disables (used by most tests).
    signup_rate_per_minute: int = 10
    login_rate_per_minute: int = 10
    proxy_rate_per_minute: int = 30

    model_config = {"env_prefix": "CLOUD_"}


settings = CloudSettings()
