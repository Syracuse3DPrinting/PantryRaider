# FoodAssistant – Change & Bead Dashboard

A read-only Cloudflare Worker that renders a live dashboard for the FoodAssistant project.

## What it shows

| Tab | Source | Description |
|---|---|---|
| 🔮 Beads | `.beads/issues.jsonl` on GitHub | All project issues grouped by category, filterable open/closed, searchable |
| 📋 Changelog | `CHANGELOG.md` on GitHub | Collapsible version sections with colour-coded Added/Changed/Fixed/Removed groups |
| 🔀 Commits | GitHub REST API | Last 50 commits with clickable hashes, author, and date |

- **Branch selector** in the header switches all three data sources at once (`?branch=` query param).
- Beads are auto-categorised into: Installer & Setup, Hardware & Pi, Architecture, Cloud & Remote Access, UI & UX, Inventory & Grocy, Recipes & Shopping, Security & Auth, Tests & CI, Docs, Bug Fixes, Other.

## Deploy to Cloudflare Workers

### 1. Install Wrangler

```bash
npm install -g wrangler
```

### 2. Log in

```bash
wrangler login
```

### 3. (Optional) Set a GitHub token

Without a token the GitHub API is rate-limited to 60 req/hour per IP.
A personal access token with **no extra scopes** is enough for public repos.

```bash
wrangler secret put GITHUB_TOKEN
# paste your token when prompted
```

### 4. Deploy

```bash
cd dashboard
wrangler deploy
```

Wrangler will print the worker URL (e.g. `https://foodassistant-dashboard.<account>.workers.dev`).

## Local preview

```bash
wrangler dev
```

Opens on `http://localhost:8787`. Add `?branch=arch/modular` to switch branch.

## Config

Edit `wrangler.toml` to change the worker name or add custom domains.
The GitHub owner/repo is hard-coded in `worker.js` at the top.

## Rate limits

- No token: 60 GitHub API requests/hour per IP (unauthenticated)
- With token: 5000 requests/hour

The worker responses are cached at the Cloudflare edge for 60 seconds (`Cache-Control: s-maxage=60`), so in practice it makes 3 API calls per cache miss (beads, changelog, commits).
