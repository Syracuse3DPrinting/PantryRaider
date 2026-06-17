# Changelog

All notable changes to FoodAssistant are recorded here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and the project follows
[semantic versioning](https://semver.org/).

> **For releases:** use the entry below as the GitHub Release description rather
> than the auto-generated commit list, so notes stay focused on user-facing
> changes.

## [1.3.1]

### Added
- **Synthwave theme** — a new neon-on-dark theme (hot pink, electric cyan, purple) with glow accents, in **Settings → Interface**.

### Fixed
- Corrected badge text contrast in the Cyborg and Darkly themes, where status labels (Today, Refrigerated, etc.) could be hard to read.

## [1.3.0]

### Added
- Theme switcher in **Settings → Interface** — choose between Dark and Light (and extra built-in themes), applied across the whole app.

### Changed
- Reorganized the Settings menu into clearer sections. Storage categories now live under **Inventory**, recipe-suggestion tuning under **Recipes**, and backup/update tools under a dedicated **Backup & Updates** section.
- "What can I cook?" now matches your stock against the external recipe database (TheMealDB) much more reliably, so web recipe ideas show up alongside your own Mealie recipes.

### Fixed
- Corrected a Settings toggle that could fail to update its hint text.

## [1.2.0]

### Added
- **Grocy public URL** — set a separate external address for Grocy so the in-app links work through a reverse proxy while internal API calls stay on the local network.
- **Auto-check shopping list** — optionally tick items off your Mealie shopping list automatically when you scan and commit a matching item.

### Fixed
- The app no longer fails to start when its data directory is read-only on first launch.
- Corrected a Home Assistant automation sensor reference so the "expiring in 3 days" alert fires reliably.

## [1.1.0]

### Added
- **Custom storage locations** — define your own storage buckets beyond the four built-ins (Refrigerated, Frozen, Room Temp, Pantry), such as Wine Cellar or Garage Fridge.
- Screenshots and an expanded setup guide in the README.

### Changed
- Pinned the bundled Grocy, Mealie, and Ollama images to specific versions so an unattended update can't move you onto a breaking release. Documented how to upgrade them safely.

## [1.0.0]

First public release.

### Added
- **Inventory dashboard** with storage panels, drag-and-drop moves, inline edits, and expiry badges, backed by Grocy.
- **Photo analysis** — photograph a food item to extract name, brand, quantity, and printed best-by date.
- **Receipt import** — photograph a grocery receipt to queue every food line item for review.
- **Barcode lookup** via camera, USB/wireless scanner, or manual entry, backed by Open Food Facts with optional AI name cleanup.
- **Expiry defaults** — an editable rules table that fills in best-by dates by product type.
- **Recipe suggestions** ("What can I cook?") ranked by what you already have in stock, with items expiring soon floated to the top.
- **Recipe import** from a webpage, a photographed recipe card, TheMealDB, or AI-generated from a dish name.
- **Meal planning and shopping lists** through optional Mealie integration, including a week view and check-off shopping list.
- **Home Assistant integration** — REST sensors, notification automations, and a Lovelace dashboard.
- **Web setup wizard** with live connection tests.
- **Two-factor authentication** (TOTP) on top of password login.
- **Backups** — download your data as a zip, with optional scheduled off-box backup via rclone.
- Optional fully-local operation using Ollama for vision and text.
- Docker, Docker Compose, and Home Assistant add-on installation paths.
