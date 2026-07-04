# Pantry Raider Cloud

The hosted subscription service behind Pantry Raider's optional paid
features, starting with managed AI (photo analysis, receipt parsing, and
barcode enrichment without your own API key). The self-hosted app in
`service/` works fully without it; this service only adds to a linked
install.

Design and rationale: [docs/design/cloud-platform.md](../docs/design/cloud-platform.md).

## What it does

- Accounts with password login and a portal session token.
- Instance pairing: the portal mints a short-lived code, an install redeems
  it for its own bearer token, and from then on the install appears in the
  account's instance list.
- An AI proxy that checks the account's subscription and monthly token
  quota, records usage in a ledger, and answers over-quota requests with a
  402 the app can show as a friendly message. The upstream LLM call is a
  stub until a provider is chosen.
- A Stripe webhook (signature-verified, idempotent) that turns Checkout and
  subscription events into the entitlement each request checks.

## Run the tests

The suite is self-contained (SQLite in memory; production uses Postgres):

```bash
cd cloud
pip install -r requirements.txt pytest
python -m pytest
```

## Deploy on a VPS

Requirements: a small Debian/Ubuntu VPS with Docker and Docker Compose, and
a DNS record for the cloud domain pointing at it.

```bash
git clone https://github.com/Syracuse3DPrintingOrg/PantryRaider.git
cd PantryRaider/cloud
cp -f .env.example .env
nano .env        # domain, Postgres password, Stripe webhook secret
docker compose up -d --build
curl https://$YOUR_DOMAIN/health
```

Caddy terminates TLS with automatic certificates; the app container never
binds a public port. Postgres data lives in the `pgdata` volume; back it up
with `docker compose exec db pg_dump -U pantry pantrycloud`.

Point the Stripe webhook endpoint at `https://$YOUR_DOMAIN/v1/stripe/webhook`
and put its signing secret in `.env`.

## Layout

| Path | What lives there |
|---|---|
| `app/config.py` | Env-driven settings (`CLOUD_` prefix) and the plan quota table |
| `app/models.py` | Accounts, sessions, instances, pairing codes, subscriptions, entitlements, usage ledger, Stripe events |
| `app/security.py` | scrypt password hashing, token issue/hash, Stripe signature verification |
| `app/usage.py` | Per-account monthly token accounting and the quota gate |
| `app/forwarder.py` | The `AIForwarder` interface; the real provider call replaces `StubForwarder` |
| `app/routers/` | `accounts`, `instances` (pairing), `ai` (the proxy), `stripe_webhook` |
| `tests/` | Standalone pytest suite (SQLite, no Docker or network) |

Schema is created with `create_all` at startup; the switch to Alembic before
the first production deployment is documented in the design doc.
