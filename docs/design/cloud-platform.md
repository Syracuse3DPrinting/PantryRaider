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
2. **Accounts and instance linking.** An account is created on the
   Forager web portal (email + password, or Google sign-in). An install
   links to the account by signing in from the app with the same
   credentials (one-step provisioning), which issues the instance a
   long-lived bearer token, shown once and stored hashed. This mirrors
   the satellite pairing pattern: the install dials out, authenticates
   with its token, and appears in the account's kitchen list. Pairing
   codes remain as an advanced alternative.
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
| `accounts` | One row per subscriber: email (unique), scrypt password hash (empty for Google-created accounts until they set one), auth provider, disabled flag (the admin kill switch), created timestamp |
| `auth_sessions` | Portal login sessions: hashed bearer token, account, expiry |
| `instances` | Paired installs: hashed instance token, account, name, last-seen metadata (version, deployment mode) |
| `pairing_codes` | Short-lived one-use codes that redeem into an instance |
| `subscriptions` | Mirror of the Stripe subscription: customer id, subscription id, status, current period end |
| `entitlements` | What the account is allowed right now: plan, status, monthly token quota, source (stripe or comp) and an optional hard expiry for comped grants. The single source every request checks |
| `usage_ledger` | Append-only token usage: account, instance, month key (`YYYY-MM`), tokens, kind (food / receipt / enrich). Monthly totals are sums over this table |
| `stripe_events` | Processed Stripe event ids, for webhook idempotency (Stripe retries deliveries) |
| `admin_actions` | Audit trail for the admin panel: admin email, action, target account, detail, timestamp |

Tokens (session and instance) are random 256-bit values with a readable
prefix (`prs_` for sessions, `prc_` for instances), stored only as SHA-256
hashes. A leaked database does not leak usable credentials. Passwords use
`hashlib.scrypt` with per-user salts (stdlib, no new dependency; the
parameters are stored alongside the hash so they can be raised later).

### Auth model

- **Portal (human):** email + password, returning a session bearer token
  with a server-side expiry (the web portal carries the same token in an
  HttpOnly cookie). Password hashing via scrypt as above. Google sign-in
  (a hand-rolled OpenID Connect code flow, gated on
  `CLOUD_GOOGLE_CLIENT_ID`/`CLOUD_GOOGLE_CLIENT_SECRET`) is an optional
  alternative; magic-link login is a later addition, not a v1 blocker.
- **Instance (machine):** one-step provisioning is the primary flow: the
  app posts the account's email and password (rate-limited like login)
  and receives its instance token directly. The advanced alternative is
  the pairing flow: the portal issues a pairing code (short, 15-minute
  TTL, single use) and the install redeems it unauthenticated (the code
  is the credential). Either way the token is shown exactly once; the
  cloud keeps only the hash. Revocation is removing the kitchen in the
  portal, or the app self-revoking via `DELETE /v1/instance` when the
  user unlinks; the month's usage ledger survives revocation so
  unlink-and-relink cannot reset a quota.
- The AI proxy and usage endpoints authenticate with the instance token as
  a standard `Authorization: Bearer` header.

### API surface (v1)

| Route | Auth | What it does |
|---|---|---|
| `GET /health` | none | Liveness, version |
| `GET /v1/meta` | none | Capability discovery for the app (currently `{"oauth_google": bool}`) |
| `POST /v1/accounts/signup` | none | Create account, return session token |
| `POST /v1/accounts/login` | none | Password login, return session token (rate-limited) |
| `GET /v1/accounts/me` | session | Account, entitlement, instances, this month's usage |
| `POST /v1/instances/provision` | account credentials | One-step linking: verify email + password, create the instance, return its token plus plan/quota/usage and a `suggested_public_url` field (null until hosted tunnels exist) |
| `POST /v1/pairing/code` | session | Mint a pairing code (advanced path) |
| `POST /v1/pairing/redeem` | pairing code | Exchange the code for an instance token (also redeems Google app-flow codes) |
| `GET /v1/instance/me` | instance | Entitlement status, quota remaining, and the linked account's email, for the app's settings page |
| `DELETE /v1/instance` | instance | Self-revoke: the app's Unlink kills its own credential server-side |
| `GET /auth/google/start`, `/auth/google/callback` | Google OAuth | Portal Google sign-in, and the `flow=app` variant that returns a provision code to the app's `return_url`. Only mounted when Google credentials are configured |
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

## Onboarding: how a person actually joins

The Forager user is not assumed to be technical, so the whole journey is
two sign-ins with the same credentials and no codes, keys, or copying:

1. **Sign up on the web.** forager.pantryraider.app has a landing page
   explaining the service, and signup takes an email and password (or
   "Continue with Google"). Signup logs the browser straight into the
   account page.
2. **Sign in from the app.** In Pantry Raider's settings, the user enters
   the same email and password. Behind the scenes the app calls
   `POST /v1/instances/provision`, which verifies the credentials, creates
   the instance and its token in one step, and returns the plan and quota;
   the app stores the token and scanning works immediately. Deployments
   with Google sign-in enabled can offer "Continue with Google" here too:
   the app opens `GET /auth/google/start?flow=app&return_url=...` in a
   browser, and after the Google login the browser is redirected back to
   the app's `return_url` with a short-lived single-use code the app
   redeems at the existing `POST /v1/pairing/redeem`.
3. **Everything else auto-completes.** The install appears in the portal's
   kitchen list by the name the app chose; quota, plan, and usage show up
   in both the app and the portal with no further setup.

The **pairing-code path is the advanced alternative**: mint a code in the
portal, type it into the app's settings, and the app redeems it for its
token. It stays for people who prefer never typing their account password
into a device, and as the redemption half of the Google app flow, but it
is no longer the path the UI leads with.

### The web portal

Server-rendered pages (Jinja2, a small hand-written dark stylesheet that
echoes the app's Bootstrap look; nothing imported from `service/`). The
portal reuses the same session tokens as the JSON login endpoint, carried
in an HttpOnly SameSite=Lax cookie. Portal copy is written for a
non-technical person: it says "kitchen" where the API says instance, and
never mentions tokens or APIs (a test enforces this on the account page).

| Page | What it shows |
|---|---|
| `/` | What Forager is, Sign up / Log in, links to pantryraider.app |
| `/signup`, `/login`, `/logout` | Email + password forms (rate-limited), optional "Continue with Google" |
| `/account` | Plan with a usage meter, this month's scans, linked kitchens with Remove buttons (removal revokes the device's credential), Subscribe/Manage (honest "Billing is not live yet" while `CLOUD_STRIPE_CHECKOUT_URL` is unset), and change password |

Accounts created through Google sign-in have no password until they set
one on the account page (offered there); password login is simply refused
for them until then.

### The admin panel

`/admin` is the operator's side of the portal: same session cookie, same
templates and dark stylesheet, but gated by `CLOUD_ADMIN_EMAILS` (a
comma-separated email allowlist, checked by `deps.is_admin`). Anyone not
on the list gets a 404 rather than a 403, so the panel does not reveal its
own existence; an empty list locks everyone out. The subscriber-copy rule
is deliberately inverted here: these pages are for the operator and use
technical words (tokens, instances, Stripe ids) freely.

| Page | What it shows |
|---|---|
| `/admin` | Totals (accounts, kitchens, active paid subs, month-to-date tokens and estimated Gemini spend at the blended `CLOUD_GEMINI_COST_PER_MILLION_TOKENS` rate), a searchable account table capped at 500 rows, and the last twenty admin actions |
| `/admin/accounts/{id}` | Kitchens with Revoke, entitlement and Stripe subscription rows, usage by month (last six), the account's audit trail, and the action buttons |

Admin actions and how they land:

- **Disable / enable**: `accounts.disabled` is enforced at every seam a
  disabled account could act through: password and portal login, Google
  callback, one-step provisioning, pairing-code redemption, the AI proxy,
  and existing portal sessions (the session resolver treats a disabled
  account as logged out). Each refusal carries a clear "account disabled"
  message rather than a generic auth failure.
- **Comp plan**: grants a starter entitlement with `source="comp"` and a
  chosen expiry date; `usage.entitlement_active` treats an active row past
  its `expires_at` as inactive, so a lapsed comp falls back to the free
  tier without a cron job. A Stripe webhook event overwrites comp state
  (a real purchase wins), and comping an active Stripe subscriber is
  refused.
- **Revoke kitchen**: deletes the instance row, killing its credential,
  the same mechanism as the owner's own Remove button.

Every mutation writes an `admin_actions` row (admin email, action, target
account, detail, timestamp). The trail is append-only from the panel's
point of view; there is no admin UI to edit or delete it.

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
