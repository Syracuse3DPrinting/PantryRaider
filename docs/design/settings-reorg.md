# Settings Reorganization Proposal

A design proposal for the Settings and Personalization pages (`/setup`,
`service/app/templates/setup.html`). The current layout grew one pane at a
time, so related options ended up far apart. This document inventories what
exists today, names the scatter, and proposes a target information
architecture grouped by what the user is trying to do. Nothing in this
document moves a setting by itself; it is the plan the moves will follow.

Deployment shapes referenced below: **server**, **pi_hosted**, and
**pi_remote** (satellite). Visibility notes cross-reference
[settings-matrix.md](../settings-matrix.md), which tracks per-setting
editability across the three shapes.

## 1. Current Inventory

### 1.1 First-time wizard (shown when unconfigured)

| Step | Contents | Shapes |
| --- | --- | --- |
| 1 Welcome | Deployment mode picker; on Pi Remote, `remote_server_url` + `upstream_api_key` with LAN scan and sync test | all |
| 2 Security | `auth_required`, `auth_password`, `api_key` (generate), `kiosk_pin` (satellite) | all |
| 3 Hardware | `has_streamdeck`, `streamdeck_key_count`; display block: `ui_scale`, `display_rotation`, `display_type`, `display_touch`; enable kiosk / Stream Deck service | all (service installs Pi only) |
| 4 Grocy | `grocy_base_url`, `grocy_api_key`, `grocy_public_url`, test | skipped on pi_remote |
| 5 AI | `vision_provider`, per-provider key + model, `ollama_base_url`, test | skipped on pi_remote |
| 6 Optional | `scanner_type` + scan test; Mealie (`mealie_base_url`, `mealie_public_url`, `mealie_api_key`, start-on-device); `recipe_source` + `spoonacular_api_key`; link to Remote Access | skipped on pi_remote |
| 7 Done | Summary and save | all |

### 1.2 Settings menu (group "s")

| Pane | Menu section | Settings and controls | Shapes |
| --- | --- | --- | --- |
| `pane-upstream` (Main Server) | Services | `remote_server_url`, `upstream_api_key`, sync status + Sync Now, `kiosk_pin`, `kiosk_readonly_when_locked`, switch back to full stack | pi_remote only |
| `pane-inventory` (Inventory) | Services | `grocy_base_url`, `grocy_api_key`, `grocy_public_url`, `device_hostname`, test | server, pi_hosted (satellite: no menu entry, values inherited) |
| `pane-ai` (AI) | Services | `vision_provider`; per-provider keys, models, `ai_extra_keys`; `ollama_base_url`; Barcode Enrichment card: `barcode_enrichment`, `barcode_llm_fallback`, `enrich_provider`, `enrich_model`; AI token usage card: `ai_token_budget`, usage display, reset | server, pi_hosted (satellite: read-only, no menu entry) |
| `pane-recipes` (Recipes) | Services | Mealie card: `mealie_base_url`, `mealie_public_url`, `mealie_api_key`, start-on-device (Pi), `barcode_autocheck_shopping`; External Recipes card: `recipe_source`, `themealdb_api_key`, `spoonacular_api_key` | server, pi_hosted (satellite: read-only, no menu entry) |
| `pane-security` (Security) | App | `auth_required`, `auth_password`, `api_key` + generate, satellite keys (`extra_api_keys`, `extra_api_key_names`), TOTP setup/disable, secrets-storage notes | all (auth is device-local everywhere) |
| `pane-tunnel` (Remote Access) | App | `tunnel_mode`, `tunnel_token`, connect/disconnect, status + `tunnel_url` | server, pi_hosted |
| `pane-hardware` (Hardware) | Devices & Hardware | `scanner_type`, `barcode_global_capture`, scanner test field; Attached hardware card (Pi): live display / Stream Deck detection, one-click enable | all (detection Pi only) |
| `pane-homeassistant` (Home Assistant) | Devices & Hardware | `streamdeck_ha_base_url`, `streamdeck_ha_token`, test; notifications card: `ha_events_enabled`, per-device override (localStorage), `ha_camera_popup_seconds`, test event, YAML snippets | all (satellite: read-only) |
| `pane-cameras` (Cameras) | Devices & Hardware | Add camera by IP (brand templates, LAN scan with `lan_scan_cidr` prefill); camera list (`streamdeck_cameras`), HA discovery | all (satellite: read-only list) |
| `pane-devices` (Satellite Devices) | Devices & Hardware | Registered satellites list, resync/forget, LAN scan for instances | server, pi_hosted |
| `pane-network` (Network) | Devices & Hardware | Wi-Fi SSID/password + scan, hostname change | Pi shapes only |
| `pane-data` (Backup & Updates) | System | Backup card: download (+ include secrets), restore zip, full-stack restore (Pi), `rclone_remote`, `rclone_schedule_hours`, `usb_backup_interval_hours`, USB back-up-now; Updates card: check/update, `auto_update`; Run as a satellite card (pi_hosted); Date & time card: `timezone`; Maintenance card: reload settings, reboot, `scheduled_reboot_time`; Diagnostics card: `debug_logging`, download logs | all (cards vary by shape) |

### 1.3 Personalization menu (group "p")

| Pane | Settings and controls | Shapes |
| --- | --- | --- |
| `pane-theme` (Theme) | `ui_theme`, custom theme builder (`custom_theme_base/primary/accent/bg/surface/text`, `custom_themes`), Background image card (`background_image_url`, upload, `background_opacity`) | all |
| `pane-navigation` (Navigation) | Nav tab editor (`nav_order`, `nav_hidden`, `nav_parents`, `custom_nav_tabs`, headings), `quiet_mode`, `qr_url_mode`, `qr_public_url`; On-screen navigation bar card (`nav_visibility`, `floating_nav_position`, `floating_nav_autohide_streamdeck`) | all |
| `pane-personalization-recipes` (Recipe Preferences) | `staple_items`, `cook_ai_context`, `kitchen_appliances`, `perishable_days`, `expiring_soon_days`, `suggest_per_tier` | all (satellite: read-only) |
| `pane-personalization-storage` (Storage Categories) | `custom_storage_categories` editor | server, pi_hosted |
| `pane-display` (Display) | Kiosk Display card: `ui_scale`, `display_type`, `display_touch`, touch driver + calibration, `display_idle_timeout`, `wake_on_motion`, `screensaver_minutes`, `screensaver_speed`, `screensaver_mode`; Orientation card: `display_rotation` (KMS); Kiosk Service card: provision/install | Pi shapes only |
| `pane-start-page` (Start Page / Start & Stream Deck) | `start_page_enabled`, `start_page_keys`, `start_page_layout`, shared custom keys, `streamdeck_key_style`, `streamdeck_icon_color` | all (Pi: toggles to the deck view) |
| `pane-streamdeck` (Stream Deck, no menu entry of its own) | `has_streamdeck`, `streamdeck_key_count`, deck rotation, brightness, key layout, custom keys (`streamdeck_key_overrides`), `streamdeck_idle_timeout`, `streamdeck_key_style`, `streamdeck_icon_color`, profiles, service install/restart | Pi shapes only |

Weather location and units have no settings section; they are edited on the
Weather page itself, with hidden inputs in setup.html keeping the deck save
payload complete.

## 2. The Scatter

Groupings a user would expect that today span several panes:

- **Everything display-ish** lives in four places: sleep, wake, screensaver,
  scale, and rotation in Display (Personalization); background image and
  theme in Theme; on-screen nav bar visibility, dock position, and quiet
  mode in Navigation; the kiosk-freshness nightly reboot in Backup &
  Updates under Maintenance.
- **Everything scanning-ish** lives in three places: scanner type and
  global capture in Hardware (Settings); barcode enrichment, LLM fallback,
  and the enrichment provider/model in AI; auto-check shopping list on scan
  in Recipes. The default scanner mode is set on the Manage Pantry page,
  not in Settings at all.
- **Recipes are split across the two menus**: sources and Mealie in
  Settings > Recipes, tuning (staples, AI context, appliances, thresholds)
  in Personalization > Recipe Preferences. Both affect the same Cook page.
- **Backups share a pane with five unrelated cards**: updates, the
  satellite switch, timezone, maintenance, and diagnostics all sit in
  Backup & Updates below the backup card.
- **Hostname appears twice**: `device_hostname` (link building) in the
  Inventory pane, and the real OS hostname change in Network. Users cannot
  be expected to know which one they want.
- **Kiosk PIN moves depending on shape**: wizard Security step and the
  Main Server pane (satellite), never the Security pane.
- **The Settings / Personalization split itself** is the biggest cost: a
  user has to know which of two top-level menus holds a pane before the
  side menu can help them, and the boundary is fuzzy (Storage Categories
  is personalization, Cameras is settings).

## 3. Target Information Architecture

One menu, grouped by intent. The Settings / Personalization toggle goes
away; the group headers below replace it. Panes keep per-card save buttons.

| New pane | Contents (from) | Shapes |
| --- | --- | --- |
| **Appearance** | Theme + custom theme builder + background image (pane-theme); nav tab editor, custom tabs (pane-navigation) | all |
| **Screen & Sleep** | Scale, rotation, display type, touch, calibration, sleep, wake on motion, screensaver, kiosk service (pane-display); on-screen nav bar + visibility (pane-navigation); quiet mode (pane-navigation); nightly reboot (pane-data Maintenance) | Pi shapes; a trimmed card (nav bar, quiet mode) on server |
| **Scanning & Intake** | Scanner type, global capture, scan test (pane-hardware); barcode enrichment, LLM fallback, enrich provider/model (pane-ai); auto-check shopping on scan (pane-recipes); AI vision provider, keys, models, token budget (pane-ai) | all (AI/enrichment read-only on pi_remote) |
| **Recipes & Meals** | Mealie connection (pane-recipes); external sources + keys (pane-recipes); staples, AI context, appliances, thresholds (pane-personalization-recipes) | all (read-only on pi_remote) |
| **Inventory & Storage** | Grocy connection (pane-inventory); custom storage categories (pane-personalization-storage) | server, pi_hosted |
| **Connections** | Home Assistant connection + on-screen events (pane-homeassistant); cameras (pane-cameras); remote access tunnel (pane-tunnel); QR code address mode (pane-navigation) | all (tunnel not on pi_remote) |
| **Devices** | Start Page + Stream Deck editors (pane-start-page, pane-streamdeck); attached hardware detection (pane-hardware); satellite device registry + LAN scan (pane-devices); Wi-Fi + hostname, absorbing `device_hostname` (pane-network, pane-inventory); Main Server link on a satellite (pane-upstream) | varies as today |
| **Security & Access** | Auth, password, API keys, satellite keys, TOTP (pane-security); kiosk PIN + read-only-when-locked on every shape that has a screen (from pane-upstream/wizard) | all |
| **Backups & Updates** | Backup download/restore, full restore, rclone, USB (pane-data Backup card); updates + auto-update (pane-data Updates card) | all |
| **Advanced** | Timezone, reload settings, reboot now (pane-data); diagnostics + debug logging (pane-data); run as a satellite / return to full stack (pane-data, pane-upstream); deployment-mode facts | all |

### Setting-by-setting map

| Setting / control | Today | Proposed home |
| --- | --- | --- |
| `ui_theme`, `custom_theme_*`, `custom_themes` | Theme | Appearance |
| `background_image_url`, `background_opacity` | Theme | Appearance |
| `nav_order`, `nav_hidden`, `nav_parents`, `custom_nav_tabs` | Navigation | Appearance |
| `nav_visibility`, `floating_nav_position`, `floating_nav_autohide_streamdeck` | Navigation | Screen & Sleep |
| `quiet_mode` | Navigation | Screen & Sleep |
| `qr_url_mode`, `qr_public_url` | Navigation | Connections |
| `ui_scale`, `display_rotation`, `display_type`, `display_touch` | Display | Screen & Sleep |
| touch driver, calibration, kiosk service | Display | Screen & Sleep |
| `display_idle_timeout`, `wake_on_motion`, `screensaver_minutes/_speed/_mode` | Display | Screen & Sleep |
| `scheduled_reboot_time` | Backup & Updates (Maintenance) | Screen & Sleep |
| `scanner_type`, `barcode_global_capture` | Hardware | Scanning & Intake |
| `barcode_enrichment`, `barcode_llm_fallback`, `enrich_provider`, `enrich_model` | AI | Scanning & Intake |
| `barcode_autocheck_shopping` | Recipes | Scanning & Intake |
| `vision_provider`, provider keys/models, `ollama_base_url`, `ai_extra_keys`, `ai_token_budget` | AI | Scanning & Intake |
| `mealie_base_url`, `mealie_public_url`, `mealie_api_key` | Recipes | Recipes & Meals |
| `recipe_source`, `themealdb_api_key`, `spoonacular_api_key` | Recipes | Recipes & Meals |
| `staple_items`, `cook_ai_context`, `kitchen_appliances`, `perishable_days`, `expiring_soon_days`, `suggest_per_tier` | Recipe Preferences | Recipes & Meals |
| `grocy_base_url`, `grocy_api_key`, `grocy_public_url` | Inventory | Inventory & Storage |
| `custom_storage_categories` | Storage Categories | Inventory & Storage |
| `device_hostname` | Inventory | Devices (with hostname) |
| `streamdeck_ha_base_url`, `streamdeck_ha_token`, `ha_events_enabled`, `ha_camera_popup_seconds` | Home Assistant | Connections |
| `streamdeck_cameras`, camera-by-IP, LAN camera scan | Cameras | Connections |
| `tunnel_mode`, `tunnel_token` | Remote Access | Connections |
| Start Page + Stream Deck editors and settings | Start & Stream Deck | Devices |
| attached hardware detection | Hardware | Devices |
| satellite registry, instance LAN scan | Satellite Devices | Devices |
| Wi-Fi, OS hostname | Network | Devices |
| `remote_server_url`, `upstream_api_key`, sync status | Main Server | Devices (satellite) |
| `auth_required`, `auth_password`, `api_key`, `extra_api_keys`, TOTP | Security | Security & Access |
| `kiosk_pin`, `kiosk_readonly_when_locked` | Main Server (satellite) | Security & Access |
| backup, restore, `rclone_remote`, `rclone_schedule_hours`, `usb_backup_interval_hours` | Backup & Updates | Backups & Updates |
| update check, `auto_update` | Backup & Updates | Backups & Updates |
| `timezone`, reload settings, reboot now | Backup & Updates | Advanced |
| `debug_logging`, log download | Backup & Updates | Advanced |
| run as satellite / return to full stack | Backup & Updates / Main Server | Advanced |

### Panes that merge or disappear

| Existing pane | Outcome |
| --- | --- |
| `pane-theme` + nav editor half of `pane-navigation` | merge into `pane-appearance` |
| `pane-display` + nav-bar half of `pane-navigation` | merge into `pane-screen` |
| `pane-ai` + scanner half of `pane-hardware` | merge into `pane-scanning` |
| `pane-recipes` + `pane-personalization-recipes` | merge into `pane-recipes` (kept id) |
| `pane-inventory` + `pane-personalization-storage` | merge into `pane-inventory` (kept id) |
| `pane-homeassistant`, `pane-cameras`, `pane-tunnel` | merge into `pane-connections` |
| `pane-start-page`, `pane-streamdeck`, hardware-detect half of `pane-hardware`, `pane-devices`, `pane-network`, `pane-upstream` | merge into `pane-devices` (kept id), keeping the existing Start/Deck sub-toggle pattern for its sub-areas |
| `pane-security` | renamed content only; id kept |
| `pane-data` | split into `pane-backups` and `pane-advanced` |
| `pane-navigation`, `pane-hardware` | disappear (contents distributed) |

### Deep-link compatibility (anchor aliases)

`setup#pane-*` links appear in the app itself (wizard step 6, HA snippets),
in docs, and in users' bookmarks. Rather than keeping dead ids in the DOM,
the page resolves old hashes through a small client-side alias map before
activating a pill (shipped in this pass, see section 5):

| Old hash | Resolves to |
| --- | --- |
| `#pane-theme` | `#pane-appearance` |
| `#pane-navigation` | `#pane-appearance` |
| `#pane-display` | `#pane-screen` |
| `#pane-ai` | `#pane-scanning` |
| `#pane-hardware` | `#pane-scanning` |
| `#pane-personalization-recipes` | `#pane-recipes` |
| `#pane-personalization-storage` | `#pane-inventory` |
| `#pane-homeassistant`, `#pane-cameras`, `#pane-tunnel` | `#pane-connections` |
| `#pane-start-page`, `#pane-streamdeck`, `#pane-network`, `#pane-upstream` | `#pane-devices` |
| `#pane-data` | `#pane-backups` |

The map ships empty until a pane actually renames; each rename adds its row
in the same change. The `#pane-streamdeck` special case (open the combined
pill, then flip to the deck view) already exists and stays.

## 4. Visual Consistency Fixes

- **Card styling**: `section-card` + `section-title` (icon, accent color)
  is the standard and most panes follow it. The Backup card uses bare
  `form-label` text as sub-headers for its Restore, Full restore, and USB
  blocks; those should use one shared sub-header style (shipped in this
  pass as `.subsection-title`).
- **info() coverage**: the `info()` tooltip macro keeps long help out of
  the page flow, but coverage is uneven: newer panes (Start Page, Stream
  Deck, Maintenance) use it heavily while older panes mix long `form-text`
  paragraphs with fields that have no help at all (Framebuffer rotation,
  Touch-compatible display, the backup interval fields). Rule going
  forward: every input gets either a one-line `form-text` or an `info()`
  tooltip; paragraphs above the fields describe the card, not a field.
- **Save button placement**: today some cards save at their own bottom
  (Grocy, Cameras, Display), some panes have a single save after all cards
  (Security, AI, Navigation), and the Stream Deck editor adds a duplicate
  top save bar. Target: one save control per card, bottom-left, styled
  `btn-outline-info btn-sm` with the check icon, with the pane-level save
  removed once every card has its own. Long editors (Stream Deck) may keep
  the top bar as a duplicate of the same control, never a different one.
- **Settings search**: a filter box above the side menu (shipped in this
  pass). Typing filters the menu to panes whose title, section headers, or
  field labels match, across both menu groups at once, and outlines the
  matching cards when a filtered pane opens. This softens the two-menu
  problem immediately and remains useful after the reorganization.

## 5. Shipped Alongside This Proposal

Three low-risk pieces landed with this document, none of which moves a
setting between panes:

1. **Anchor alias resolver**: `PANE_HASH_ALIASES` map + `_resolvePaneHash()`
   in setup.html, applied wherever a `#pane-*` hash is read. Empty today;
   future renames add entries per the table above.
2. **Settings search box**: client-side filter at the top of the side
   menu, indexing pane titles, section titles, and field labels; matching
   cards get a highlight outline when opened from an active search.
3. **Consistency quick wins**: a shared `.subsection-title` style for the
   Backup card's sub-headers, and `info()` tooltips for the fields in the
   Display and Backup panes that had no help text.

Everything in section 3 (the actual moves and merges) waits for review.

## 6. Iteration 2 (Dan's review)

Dan reviewed the one-menu layout on-device and rejected the single menu:
"I like settings and personalizations as separate since users won't be
changing server settings and such often." The model to follow is Plex and
Jellyfin, which split user preferences (touched often) from server
administration (touched rarely). So the top toggle is back, showing one
side menu at a time, defaulting to Personalization and remembering the
last choice per device. Everything else the reorganization achieved stays:
intent-named panes, the search box, per-card saves, anchor aliases, and
the no-setting-lost guarantee.

### The two menus

| Menu | Pane | Contents |
| --- | --- | --- |
| Personalization (default) | Appearance | theme, custom themes, background image, nav tab editor |
| Personalization | Screen & Sleep | unchanged from iteration 1 |
| Personalization | Start Page & Stream Deck | the two editors, promoted out of Devices; the pane toggle is trimmed to just Start Page / Stream Deck (the This Device option is gone) |
| Personalization | Recipe Preferences | the Suggestion Tuning card: staples, AI recipe context, appliances, thresholds (`pane-personalization-recipes`, its pre-reorg id) |
| Settings | Connections | gains Mealie and the external recipe sources; keeps HA + events, cameras, tunnel, QR address |
| Settings | AI & Scanning | `pane-scanning` renamed; contents unchanged |
| Settings | Inventory & Storage | unchanged (Grocy card + storage categories; the categories are setup-ish, so they stay with Grocy) |
| Settings | Devices & Fleet | satellite registry, LAN scan, attached hardware, device hostname, Wi-Fi/network; the satellite's Main Server + Sync cards |
| Settings | Security & Access | unchanged, including the kiosk PIN |
| Settings | Backups & Updates | unchanged |
| Settings | Advanced | unchanged |

### Changes relative to iteration 1

- `pane-recipes` dissolved: Mealie + external sources render in
  `pane-connections`, the tuning card in the revived
  `pane-personalization-recipes`. The alias map gains
  `pane-recipes -> pane-connections`.
- `pane-start-page` is a pill target again (Personalization); the deck
  editor stays a pill-less sub-pane behind the two-way toggle, and
  `pane-streamdeck` aliases to `pane-start-page` (init still flips the
  toggle to the deck for a raw `#pane-streamdeck` hash).
- The `pane-personalization-recipes` and `pane-start-page` alias rows are
  removed (both are live panes again); every other original and
  iteration-1 anchor keeps resolving.
- The search box indexes both menus at once; opening a hit from the other
  menu switches the top toggle to match.
