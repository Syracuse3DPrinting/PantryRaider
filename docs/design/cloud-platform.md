# Pantry Raider Cloud: Subscription Platform Design

Pantry Raider is self-hosted and stays that way. The cloud platform is an
optional paid layer on top: a small hosted service that gives subscribers
things a self-hosted install cannot provide on its own, starting with AI
vision and enrichment without bringing your own API key. Nothing in the app
requires the cloud; an install that never links an account keeps working
exactly as it does today.

This document is the design for the platform's first version, plus the
scaffold that implements it under `cloud/` in this repo. The app-side
integration (changes under `service/`) is deliberately deferred to a
follow-up; the exact changes are listed at the end.

## Decisions (2026-07-05)

Dan resolved the open product decisions:

- **Name and domain.** The service is **Forager**, at
  `forager.pantryraider.app`. The name shows up in user-facing copy, the
  FastAPI title, and deploy config. Internal module, package, and table
  names keep the original generic cloud naming (`cloud/`, the `CLOUD_` env
  prefix, table names); renaming them buys nothing and churns the scaffold.
- **Upstream provider.** The AI proxy is backed by **Gemini 2.5 Flash**
  through the plain REST API (`GeminiForwarder` in `cloud/app/forwarder.py`,
  key in `CLOUD_GEMINI_API_KEY`). The stub forwarder remains for tests and
  local dev, selected by `CLOUD_AI_FORWARDER`.
- **Pricing.** Two tiers: a **free trial** (100,000 tokens/month, granted
  to every paired account with no subscription) and one paid **starter**
  plan (2,000,000 tokens/month, requires an active entitlement). The
  starter price is set in Stripe, never in code;
  `CLOUD_STRIPE_PRICE_STARTER` maps the live price id to the plan.

Still open: VPS provider and region, and where Postgres backups go.

## Why these services, and why now

The codebase already anticipates this layer in several places:

- `service/app/services/usage.py` meters AI tokens per instance and gates
  calls on a monthly budget, and says in its own docstring that it "is the
  local foundation for a future cloud implementation that meters and limits
  tokens per user". The cloud usage ledger is the per-account version of the
  same accounting, and the quota error surfaces in the app exactly like the
  existing local budget gate (`routers/analyze.py` raising on
  `usage.over_budget()`).
- The satellite pattern (`services/satellite.py` pulling with an
  `X-API-Key`, `services/devices.py` registering devices that dial out) is
  the template for instance linking: the install always initiates the
  connection, the cloud never needs to reach into a home network.
- `services/auto_update.py` and the device registry give the fleet a
  version story the cloud can later build on (update channels, a fleet
  view), without needing any of that in v1.
- The affiliate config (`AMAZON_ASSOCIATES_TAG`) already establishes that
  the project has owner-side revenue plumbing; subscriptions are the second
  leg of that.

## v1 service set

1. **Managed AI proxy.** A subscriber's install sends its vision and
   enrichment requests to the cloud instead of a provider API. The cloud
   holds the real provider key, forwards the request, records the tokens the
   response reports against the account's monthly quota, and returns the
   result. Subscribers get photo analysis, receipt parsing, and barcode
   enrichment with zero API-key setup.
2. **Accounts and instance linking.** An account is created on the cloud
   portal (email + password). An install pairs to the account with a
   short-lived pairing code generated in the portal and typed into the
   app's settings; redeeming the code issues the instance a long-lived
   bearer token, shown once and stored hashed. This mirrors the satellite
   pairing pattern: the install dials out, authenticates with its token,
   and appears in the account's instance list.
3. **Subscriptions and billing via Stripe.** Stripe Checkout collects
   payment; a webhook (signature-verified) turns Stripe subscription events
   into an entitlement row (plan, status, monthly token quota). The cloud
   never stores card data. Entitlement, not the Stripe object, is what every
   request checks, so a Stripe outage degrades to "no entitlement changes",
   not "no service".

### Deliberately not in v1

- **Off-site encrypted backups.** High value but a storage, encryption-key
  custody, and restore-UX project of its own. The backup tarball format
  (`scripts/backup.sh`) and the host-bridge restore path already exist, so
  this slots in later as upload/download endpoints plus client-side
  encryption. Deferred so v1 stays a stateless-ish metering service.
- **Remote access / hosted tunnels.** The app already integrates Cloudflare
  tunnels (`services/tunnel.py`); reselling connectivity means running
  relay infrastructure and absorbing its abuse surface. Not worth it before
  there are paying users.
- **Magic-link email login.** Requires an outbound mail provider and
  deliverability work. Password login ships first; the auth table design
  does not preclude adding magic links later.
- **A hosted fleet dashboard.** The local device registry covers the home
  fleet; a cloud view adds little until multi-site users exist.
- **Per-seat or family accounts.** One account, one entitlement, many
  instances. Splitting quota across household members is a pricing question
  Dan has not decided yet.

## Architecture

A separate FastAPI service living in `cloud/` in this repo. Monorepo for
shared history and review, but the two services share **nothing at import
time**: `cloud/` never imports from `service/` and vice versa. Where logic
overlaps (token counting from a provider response, month keys), it is
duplicated with a comment pointing at the sibling. Duplication over
coupling: the app runs on appliances that update on their own schedule, and
the cloud must be deployable without dragging the app's dependency set
along.

- **Runtime:** FastAPI + Uvicorn, same stack as the app, one container.
- **Database: Postgres**, not SQLite. The app's SQLite is fine for one
  household; the cloud is multi-tenant with concurrent writers (webhooks,
  proxy calls, portal sessions) and needs real row locking and backups.
  Tests run on SQLite via the same SQLAlchemy models so the suite needs no
  Docker.
- **Deployment:** its own `cloud/docker-compose.yml` (app + postgres +
  caddy) on a VPS Dan provisions later. Caddy terminates TLS with automatic
  certificates and reverse-proxies to the app container, which never binds
  a public port itself.
- **Config:** pydantic-settings with a `CLOUD_` env prefix, mirroring the
  app's config style. Secrets (database password, Stripe secrets, provider
  API keys) come from the environment / an env file on the VPS, never the
  repo.

### Data model

| Table | Purpose |
|---|---|
| `accounts` | One row per subscriber: email (unique), scrypt password hash, created timestamp |
| `auth_sessions` | Portal login sessions: hashed bearer token, account, expiry |
| `instances` | Paired installs: hashed instance token, account, name, last-seen metadata (version, deployment mode) |
| `pairing_codes` | Short-lived one-use codes that redeem into an instance |
| `subscriptions` | Mirror of the Stripe subscription: customer id, subscription id, status, current period end |
| `entitlements` | What the account is allowed right now: plan, status, monthly token quota. The single source every request checks |
| `usage_ledger` | Append-only token usage: account, instance, month key (`YYYY-MM`), tokens, kind (food / receipt / enrich). Monthly totals are sums over this table |
| `stripe_events` | Processed Stripe event ids, for webhook idempotency (Stripe retries deliveries) |

Tokens (session and instance) are random 256-bit values with a readable
prefix (`prs_` for sessions, `prc_` for instances), stored only as SHA-256
hashes. A leaked database does not leak usable credentials. Passwords use
`hashlib.scrypt` with per-user salts (stdlib, no new dependency; the
parameters are stored alongside the hash so they can be raised later).

### Auth model

- **Portal (human):** email + password, returning a session bearer token
  with a server-side expiry. Password hashing via scrypt as above.
  Magic-link login is a later addition, not a v1 blocker.
- **Instance (machine):** the pairing flow. Portal issues a pairing code
  (short, 15-minute TTL, single use); the install redeems it unauthenticated
  (the code is the credential) and receives its instance token. The token
  is shown exactly once; the cloud keeps only the hash. Revocation is
  deleting the instance row from the portal.
- The AI proxy and usage endpoints authenticate with the instance token as
  a standard `Authorization: Bearer` header.

### API surface (v1)

| Route | Auth | What it does |
|---|---|---|
| `GET /health` | none | Liveness, version |
| `POST /v1/accounts/signup` | none | Create account, return session token |
| `POST /v1/accounts/login` | none | Password login, return session token |
| `GET /v1/accounts/me` | session | Account, entitlement, instances, this month's usage |
| `POST /v1/pairing/code` | session | Mint a pairing code |
| `POST /v1/pairing/redeem` | pairing code | Exchange the code for an instance token |
| `GET /v1/instance/me` | instance | Entitlement status and quota remaining, for the app's settings page |
| `POST /v1/ai/analyze` | instance | The AI proxy: entitlement + quota gate, forward, record usage |
| `POST /v1/stripe/webhook` | Stripe signature | Entitlement updates from Checkout / subscription events |

The proxy request carries the same inputs the app's providers already use
(a task kind, an image or text payload); the response is the provider's
JSON result plus the tokens charged. When the account is over quota the
proxy answers **402** with a structured body
(`{"error": "quota_exceeded", "used": N, "quota": N, "month": "YYYY-MM"}`),
which the app surfaces the same way it surfaces its local budget gate
today.

LLM forwarding lives behind an `AIForwarder` interface
(`cloud/app/forwarder.py`). Production uses `GeminiForwarder`, plain httpx
against the Gemini REST API (Gemini 2.5 Flash) with token counts read from
the response's `usageMetadata`, so the ledger records what the provider
actually charged. Tests and local dev use `StubForwarder`;
`CLOUD_AI_FORWARDER` selects the implementation.

## Threat model and privacy stance

What the cloud can see, and what it cannot:

- **Inventory, recipes, meal plans, shopping lists: never.** Those live in
  the install's own Grocy/Mealie. The cloud has no endpoint that accepts
  them and no reason to.
- **Images pass through the AI proxy transiently and are never stored.**
  The proxy holds the image bytes in memory for the duration of the
  upstream call, forwards them, and discards them. No image bytes are
  written to the database, logs, or disk; the ledger records only token
  counts and a kind. This is a hard rule for every future forwarder
  implementation.
- **What is stored:** email, password hash, hashed tokens, Stripe customer
  and subscription ids (no card data, Stripe holds that), instance names
  and versions, and token counts per month. That is the complete inventory
  of personal data, which keeps a future data-export or deletion request
  simple.

Attack surface and mitigations:

- **Token theft:** tokens are stored hashed; an instance token only reaches
  the proxy and instance endpoints, never account management. Pairing codes
  are single-use with a 15-minute TTL.
- **Webhook forgery:** the Stripe signature (HMAC-SHA256 over
  `timestamp.payload` with the endpoint secret, constant-time compare,
  5-minute timestamp tolerance) is verified before the body is parsed;
  event ids are recorded so Stripe's retries are idempotent.
- **Quota abuse:** the entitlement + monthly ledger gate is the primary
  control. On top of it, per-instance rate limiting at the proxy (a simple
  fixed-window counter in v1, enforced before the upstream call) caps
  burst cost; Caddy adds connection-level limits in front. Signup gets the
  same fixed-window limiter to slow credential stuffing and junk accounts.
- **Multi-tenant isolation:** every query is scoped by the authenticated
  account id resolved from the token; there are no cross-account list
  endpoints.

## Migration and versioning

- The scaffold creates its schema with `Base.metadata.create_all()` at
  startup, which is correct for a brand-new database and for tests.
- Before the first real deployment takes paying users, switch to
  **Alembic**: `pip install alembic`, `alembic init cloud/migrations`,
  point `env.py` at `app.database.Base.metadata`, generate the initial
  revision with `alembic revision --autogenerate`, and replace the startup
  `create_all` with `alembic upgrade head` in the container entrypoint.
  From then on every schema change is a revision, and the production
  database is only ever migrated forward. The models are already
  metadata-driven, so nothing in the scaffold has to change shape for this.
- The cloud service versions independently of the app (`CLOUD_VERSION` in
  `cloud/app/config.py`); `/health` reports it. API breakage is handled by
  the `/v1` path prefix: a breaking change ships as `/v2` alongside `/v1`,
  because deployed installs update on their own schedule and old clients
  must keep working.

## App-side integration (follow-up bead, after design approval)

The scaffold does not touch `service/`. The integration, once Dan approves
the design, is:

1. **Settings** (`service/app/config.py` + `_SAVEABLE` +
   `docs/settings-matrix.md`): `cloud_base_url` (default the production
   domain), `cloud_instance_token` (secret-masked like `upstream_api_key`),
   and a derived linked/unlinked state for the UI.
2. **Pairing UI** (`routers/setup.py` + the settings template): a "Link to
   Pantry Raider Cloud" section that takes a pairing code, calls
   `POST /v1/pairing/redeem`, and stores the returned token; an unlink
   button that clears it.
3. **A new provider** (`service/app/providers/cloud.py`): a
   `VisionProvider` implementation whose `analyze_food`, `analyze_receipt`,
   and `enrich_product` call `POST /v1/ai/analyze` with the instance token,
   and whose `health_check` calls `GET /v1/instance/me`. Registered in
   `dependencies._build_provider()` as provider name `cloud` ("Pantry
   Raider Cloud" in the picker), gated on a stored instance token so
   `ai_configured` lights up when linked.
4. **Quota errors surfaced like the local budget gate**: a 402 from the
   proxy maps to the same user-facing message shape as
   `routers/analyze.py`'s `_BUDGET_MSG`, with the plan's quota and reset
   month from the response body.
5. **Status display**: the AI settings panel shows cloud quota
   used/remaining from `GET /v1/instance/me`, next to the existing local
   token-usage readout.

## Open decisions for Dan

The naming, provider, pricing, and domain decisions are recorded in the
Decisions section above. What remains:

- **VPS provider and region**, plus where Postgres backups go.
- **Stripe account** setup: the starter product and its live price id
  (into `CLOUD_STRIPE_PRICE_STARTER`), and the live webhook endpoint
  secret.
