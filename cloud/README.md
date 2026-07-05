# Forager

Forager is Pantry Raider's hosted companion service at
`forager.pantryraider.app`. It powers the optional subscription features,
starting with managed AI (photo analysis, receipt parsing, and barcode
enrichment without your own API key). The self-hosted app in `service/`
works fully without it; Forager only adds to a linked install.

Design and rationale: [docs/design/cloud-platform.md](../docs/design/cloud-platform.md).
Internal module and table names keep the original generic cloud naming; the
Forager brand appears in user-facing copy, the domain, and deploy config.

## What it does

- Accounts with password login and a portal session token.
- Instance pairing: the portal mints a short-lived code, an install redeems
  it for its own bearer token, and from then on the install appears in the
  account's instance list.
- An AI proxy backed by Gemini 2.5 Flash. Every linked account gets a free
  trial of 100,000 AI tokens per month; the starter subscription raises
  that to 2,000,000. The proxy records real token counts from each response
  in a usage ledger and answers over-quota requests with a 402 the app
  shows as a friendly message.
- A Stripe webhook (signature-verified, idempotent) that turns Checkout and
  subscription events into the entitlement each request checks. Plan prices
  live in Stripe, not in code.

## Run the tests

The suite is self-contained (SQLite in memory, a stubbed or mocked AI
upstream; production uses Postgres and Gemini):

```bash
cd cloud
pip install -r requirements.txt pytest
python -m pytest
```

## Deploy on a VPS

Requirements: a small Debian/Ubuntu VPS with Docker and Docker Compose, and
a DNS record for `forager.pantryraider.app` pointing at it.

```bash
git clone https://github.com/Syracuse3DPrintingOrg/PantryRaider.git
cd PantryRaider/cloud
cp -f .env.example .env
nano .env        # Postgres password, Gemini API key, Stripe secrets
docker compose up -d --build
curl https://forager.pantryraider.app/health
```

The `.env` file needs, beyond the domain and Postgres password:

- `CLOUD_GEMINI_API_KEY`: the Google AI Studio key behind the AI proxy
  (`CLOUD_AI_FORWARDER=gemini` selects the Gemini upstream).
- `CLOUD_STRIPE_PRICE_STARTER`: the Stripe price id of the starter plan, so
  purchases map to the right quota.

Caddy terminates TLS with automatic certificates; the app container never
binds a public port. Postgres data lives in the `pgdata` volume; back it up
with `docker compose exec db pg_dump -U pantry pantrycloud`.

Point the Stripe webhook endpoint at
`https://forager.pantryraider.app/v1/stripe/webhook` and put its signing
secret in `.env`.

## Go-live checklist

1. DNS: an A record for `forager.pantryraider.app` pointing at the VPS.
2. Bring the stack up and confirm Caddy obtained the certificate:
   `curl -v https://forager.pantryraider.app/health` shows a valid cert and
   `{"status": "ok"}`.
3. `CLOUD_GEMINI_API_KEY` set in `.env` and the app restarted; a paired
   test install can run a photo analysis end to end.
4. Stripe live mode: the starter product's price id in
   `CLOUD_STRIPE_PRICE_STARTER`, the webhook endpoint added in the Stripe
   dashboard, and its signing secret in `CLOUD_STRIPE_WEBHOOK_SECRET`.
5. First account smoke test: sign up, pair an install with a code, run one
   analyze call (free tier), complete a test Checkout, and confirm
   `GET /v1/instance/me` reports the starter quota.

## Layout

| Path | What lives there |
|---|---|
| `app/config.py` | Env-driven settings (`CLOUD_` prefix) and the plan quota table |
| `app/models.py` | Accounts, sessions, instances, pairing codes, subscriptions, entitlements, usage ledger, Stripe events |
| `app/security.py` | scrypt password hashing, token issue/hash, Stripe signature verification |
| `app/usage.py` | Per-account monthly token accounting and the quota gate |
| `app/forwarder.py` | The `AIForwarder` interface: `GeminiForwarder` (production) and `StubForwarder` (tests) |
| `app/routers/` | `accounts`, `instances` (pairing), `ai` (the proxy), `stripe_webhook` |
| `tests/` | Standalone pytest suite (SQLite, no Docker or network) |

Schema is created with `create_all` at startup; the switch to Alembic before
the first production deployment is documented in the design doc.
