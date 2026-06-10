# FoodAssistant

Self-hosted food spoilage tracker with LLM-powered photo/receipt import,
barcode lookup, and Home Assistant integration. Uses
[Grocy](https://grocy.info/) as the inventory backend.

## Features

- **Inventory dashboard** — 4-panel view (Refrigerated / Frozen / Room Temp / Pantry) with drag-and-drop moves, inline edits, and sorting
- **Photo analysis** — snap a food item; a vision LLM (Gemini, OpenAI, Anthropic Claude, or local Ollama) extracts name, brand, quantity, and any printed best-by date
- **Receipt import** — photograph a grocery receipt; every food item is extracted and queued for import
- **Barcode lookup** — camera scanner, headless wireless scanner, or manual entry, backed by Open Food Facts; the LLM cleans up messy product names and picks the right category/storage/shelf-life (`BARCODE_ENRICHMENT=llm`, works fully local with Ollama)
- **Expiry defaults** — editable rules table fills in best-by dates automatically; everything is overridable before import
- **Web UI** — inventory dashboard, expiring-items view, add-food page, defaults editor
- **Home Assistant** — REST sensors, notification automations, Lovelace dashboard with inventory panels
- **Web setup wizard** — configure everything at `/setup` with connection testers; no file editing required
- **Auth** — optional password login for the UI + API key for headless clients

## Architecture

```
Browser/Phone ──► FoodAssistant service (FastAPI, :9284)
                    ├─► Gemini or Ollama (vision LLM)
                    ├─► Open Food Facts (barcode lookup)
                    └─► Grocy (:9383) — inventory, stock, consumption log
Home Assistant ◄── REST sensors ◄── /expiring and /inventory endpoints
```

## Quick Start

### Option A — FoodAssistant only (you already have Grocy)

```bash
git clone https://github.com/Syracuse3DPrinting/FoodAssistant.git
cd FoodAssistant
docker compose up -d --build
```

Open **http://localhost:9284/setup**, fill in your Grocy URL/API key and Gemini key,
click **Test Connection** for each, then **Save & Continue**.

### Option B — FoodAssistant + Grocy (all-in-one)

```bash
docker compose --profile with-grocy up -d --build
```

Grocy will be available at **http://localhost:9383**.
Open its UI, set a password, then generate an API key under
**Profile → Manage API Keys** and paste it into the setup wizard at
**http://localhost:9284/setup**.

### Option C — Local vision with Ollama

```bash
docker compose --profile with-ollama up -d --build
docker exec foodassistant-ollama ollama pull llava:7b
```

In the setup wizard choose **Ollama** as the provider and set the URL to
`http://ollama:11434`.

You can combine profiles: `docker compose --profile with-grocy --profile with-ollama up -d`

---

## Configuration

The **web setup wizard** at `/setup` is the recommended way to configure the app.
Settings are saved to `service/data/settings.json`, which persists across container
restarts via the volume mount.

Environment variables (`.env`) override the wizard — useful for CI or scripted deploys:

```bash
cp .env.example .env   # edit only what you want to pin
```

`SECRET_KEY` is auto-generated on first run if not set.

## Home Assistant

See [homeassistant/README.md](homeassistant/README.md) for sensors, automations,
and the Lovelace dashboard (includes a read-only inventory panel grid).

## Development notes

- App code is volume-mounted with uvicorn `--reload`: after `git pull`, changes apply automatically.
- **Rebuild required** only when `requirements.txt` or the Dockerfile change: `docker compose up -d --build service`

## Endpoints

| Endpoint | Purpose |
|---|---|
| `/setup` | Web setup wizard |
| `/ui/` | Inventory dashboard (default) |
| `/ui/expiring` | Expiring items view |
| `/ui/add` | Add food (barcode / photo / manual) |
| `/ui/defaults` | Expiry defaults editor |
| `POST /analyze/food` | Photo → parsed item(s) |
| `POST /analyze/receipt` | Receipt → parsed item list |
| `GET /analyze/barcode/{code}` | Open Food Facts lookup |
| `POST /inventory/import` | Import items to Grocy |
| `GET /inventory/dashboard` | Full stock grouped by storage bucket |
| `GET /expiring/?days=N` | Expiring items (JSON) |
| `GET /expiring/summary` | Urgency counts for HA sensors |
| `GET /health` | Provider + Grocy connectivity |

Interactive API docs at `/docs`.
