# Forager remote-access tunnel

Remote access lets a kitchen reach its own Pantry Raider from anywhere,
without opening a port on the home router or exposing the LAN. It is a paid
or trial feature of Forager (Pantry Raider's hosted service).

Each kitchen dials out to the Forager VPS as a WireGuard peer. The VPS runs
Caddy, which terminates TLS for the kitchen's own subdomain and reverse
proxies it back down the tunnel to the kitchen's app. The kitchen's private
key never leaves the device.

## Topology

- **VPS**: one host running three things.
  - WireGuard server on `wg0`, UDP `51820`, server tunnel IP `10.99.0.1/16`.
  - Caddy, terminating TLS for the apex (`forager.pantryraider.app`, the
    portal and API) and for each kitchen subdomain
    (`<sub>.forager.pantryraider.app`).
  - `forager-tunnel-agent`, a small root helper on `127.0.0.1:9300` that
    programs `wg0` and rewrites Caddy's per-kitchen routes on the cloud
    app's behalf.
- **Cloud app** (the FastAPI service in `cloud/`): owns allocation,
  entitlement gating, and the tunnel records. It never runs `wg` or edits
  Caddy; it calls the agent.
- **Kitchen** (a Pantry Raider install, usually a Pi appliance): holds its
  own WireGuard keypair, dials out to the VPS, and serves its app on
  `:9284` over the tunnel.

Each kitchen gets a stable `/32` out of `10.99.0.0/16` and a subdomain
sanitized from its hostname. Caddy proxies
`https://<sub>.forager.pantryraider.app` to `<tunnel_ip>:9284`.

## Why this shape

- **Kitchen dials out.** Home routers rarely allow inbound connections and
  many are behind CGNAT. A peer that initiates the tunnel (with a keepalive)
  needs no port forwarding and no public IP at home.
- **On-demand TLS, no wildcard cert, no DNS token.** Caddy issues a
  certificate for a kitchen subdomain the first time it is visited, and only
  after asking the app whether that subdomain is a live tunnel. There is no
  wildcard certificate to manage and no Cloudflare (or other) DNS API token
  on the VPS. DNS just needs a wildcard A record pointing at the VPS.
- **The VPS holds only public keys.** The kitchen's private key never
  leaves the device; the database stores the public half, the allocated IP,
  and the subdomain.

## Enable / disable flow

Enable:

1. The app generates (or reuses) its WireGuard keypair and calls
   `POST /v1/tunnel/enable` with its public key and a hostname hint.
2. The cloud checks entitlement. No active plan or trial gives `402
   {"error": "no_subscription"}`.
3. The cloud allocates the lowest free `/32` in `10.99.0.0/16` (skipping
   `.0` and `.1`) and a unique subdomain from the hint. If the kitchen
   already has a tunnel, it keeps its IP and subdomain and only refreshes
   the public key.
4. The cloud calls the agent (`POST /peer`) to add the WireGuard peer and
   write the Caddy route. Only after the agent confirms does the cloud
   persist the `TunnelPeer` row and set the instance's `public_url`. A
   failed agent call returns `503` and leaves nothing behind.
5. The cloud returns the WireGuard parameters (server public key, endpoint,
   tunnel IP, allowed IPs, keepalive) and the public URL. The app brings up
   its side of the tunnel.

Disable (`POST /v1/tunnel/disable`): the cloud tells the agent to remove the
peer, deletes the row, and clears the instance `public_url`. Idempotent: a
kitchen with no tunnel still gets `200 {"disabled": true}`.

## Security model

- **The kitchen's private key never leaves the device.** The cloud and the
  VPS only ever see the public key.
- **The VPS holds public keys only.** The `tunnel_peers` table stores the
  public key, the tunnel IP, and the subdomain, nothing secret.
- **Entitlement gating.** Enable requires an active entitlement (trial or
  paid), the same `entitled` flag the AI proxy reads. When a plan lapses
  (admin disable or a Stripe cancellation), `disable_tunnel_for_account`
  tears the tunnel down. A periodic sweep for trials that expire on their
  own is a follow-up (see below); for now teardown is on-demand and the app
  re-checks entitlement.
- **The app-must-have-a-password gate is enforced app-side.** Exposing a
  kitchen publicly is only safe if the app itself requires a login. That
  gate lives in the app (it refuses to enable remote access without a set
  password); the cloud does not re-implement it.
- **On-demand TLS ask.** Caddy issues a certificate for a subdomain only
  after `GET /v1/tunnel/tls-check` returns `200`, which happens solely for a
  known subdomain with a live peer. The endpoint is unauthenticated (Caddy
  calls it with no credentials) and does a single indexed lookup, plus a
  Caddy-side issuance rate guard, so a flood of bogus hostnames cannot drive
  certificate churn.
- **The agent is a narrow root surface.** It listens only on loopback,
  requires the shared token on every state-changing route, and shells out
  only with argument lists (never `shell=True`).

## API contract

All under `/v1/tunnel`, instance-token auth (the `current_instance`
dependency) except `tls-check`, which is unauthenticated for Caddy.

### `POST /enable`

Request:

```json
{"public_key": "<wireguard public key>", "hostname_hint": "Kitchen Pi"}
```

Response `200`:

```json
{
  "server_public_key": "<VPS wg server public key>",
  "server_endpoint": "forager.pantryraider.app:51820",
  "tunnel_ip": "10.99.0.2",
  "tunnel_cidr": "10.99.0.0/16",
  "dns_name": "kitchen-pi.forager.pantryraider.app",
  "public_url": "https://kitchen-pi.forager.pantryraider.app",
  "keepalive": 25,
  "allowed_ips": "10.99.0.1/32"
}
```

- `402 {"error": "no_subscription", "message": ...}` when not entitled.
- `503 {"error": "tunnel_agent_unavailable", "message": ...}` when the agent
  cannot be reached; nothing is persisted.

The app builds its WireGuard config from this: its own private key, the
`server_public_key` as the peer key, `server_endpoint` as the peer endpoint,
`tunnel_ip` as its interface address, `allowed_ips` as the peer's allowed IPs
(the server `/32`, since only the server needs to be routed), and
`keepalive` as the persistent keepalive.

### `POST /disable`

No body. Response `200 {"disabled": true}`.

### `GET /status`

Response `200`:

```json
{
  "enabled": true,
  "dns_name": "kitchen-pi.forager.pantryraider.app",
  "public_url": "https://kitchen-pi.forager.pantryraider.app",
  "tunnel_ip": "10.99.0.2",
  "last_handshake": ""
}
```

With no tunnel: `{"enabled": false, "dns_name": "", "public_url": "",
"tunnel_ip": "", "last_handshake": ""}`.

### `GET /tls-check?domain=<host>`

Caddy's `on_demand_tls ask` target. `200 {"allow": true}` only when
`<host>` is `<known-subdomain>.forager.pantryraider.app` for a live peer;
`404` otherwise. Unauthenticated.

### `public_url` on the instance status endpoints

`GET /v1/instance/me` and `POST /v1/instances/provision` now carry the
install's `public_url` (the field is `public_url` on `me`,
`suggested_public_url` on `provision`), `null` until a tunnel is enabled.
The app reads it to show and link its own remote address.

### Agent contract (cloud app to VPS agent)

`POST http://<agent>/peer` with header `X-Tunnel-Token`:

```json
{"public_key": "<pk>", "tunnel_ip": "10.99.0.2",
 "domain": "kitchen-pi.forager.pantryraider.app"}
```

`domain` is included beyond the minimal `{public_key, tunnel_ip}` so the
agent can render the Caddy reverse-proxy block, which is keyed by the
kitchen's public hostname. `DELETE /peer` takes `{"public_key": "<pk>"}`.
Both answer `200 {"ok": true}`; `GET /health` needs no token.

## IP and subdomain allocation

Pure helpers in `cloud/app/tunnel.py`:

- `allocate_ip(existing_ips)`: the lowest free host in `10.99.0.0/16`,
  skipping `.0` (network) and `.1` (server). A `/16` holds roughly 65k
  kitchens.
- `sanitize_subdomain(hint)`: lowercases, keeps `[a-z0-9-]`, collapses runs
  of dashes, trims, caps the length, and falls back to `kitchen` when
  nothing usable survives.
- `ensure_unique_subdomain(base, existing)`: appends `-2`, `-3`, ... on
  collision, staying within the length cap.

## Follow-ups

- **Entitlement-lapse sweep.** Teardown today is on-demand (admin disable,
  Stripe cancellation) plus the app re-checking. A trial that simply expires
  leaves its tunnel until the next enable/disable or a manual action. A
  periodic job that disables tunnels for accounts whose entitlement has gone
  inactive would close that gap.
- **`last_handshake` updates.** The field exists but is best-effort and not
  yet populated. A future agent `GET /handshakes` (reading `wg show`) polled
  by the cloud would fill it, so the status endpoint can show whether a
  kitchen is currently connected.
- **Server (non-Pi) support.** The first target is the Pi appliance. A
  Docker-Compose `server` install can dial out too, but its WireGuard setup
  and app port mapping differ; treat that as a separate pass.
- **Multiple kitchens per account naming.** One tunnel per instance is
  enforced; an account with several kitchens gets several subdomains. A
  friendlier naming scheme (letting the owner pick or rename the subdomain)
  is a later refinement.
```
