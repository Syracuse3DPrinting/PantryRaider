# FoodAssistant Home Assistant Add-on

Run FoodAssistant directly inside Home Assistant - no separate server, no
extra login. The UI appears in the HA sidebar and Home Assistant authenticates
you through Ingress.

## Requirements

- **Home Assistant OS** or **Supervised** (the add-on store is required;
  HA Container and HA Core installs do not support add-ons - use Docker Compose
  instead, see the project README).
- A **Grocy** instance for inventory. The easiest option is the community Grocy
  add-on; install it first.

## Install

1. In Home Assistant go to **Settings → Add-ons → Add-on Store**, open the
   three-dot menu, choose **Repositories**, and add:
   `https://github.com/Syracuse3DPrinting/FoodAssistant`
2. Install **FoodAssistant** from the list and start it.
3. Click **Open Web UI** (or the sidebar entry) to launch the setup wizard.

## Configure

Everything is configured in the in-app setup wizard (it persists to the add-on's
`/data`, so it survives restarts and updates):

- **Grocy** - point it at your Grocy add-on. On the Supervisor network the
  community Grocy add-on is reachable at a hostname such as
  `http://a0d7b954-grocy:80` (check the Grocy add-on's "Hostname" on its info
  page). Create an API key in Grocy under Profile → Manage API Keys.
- **AI provider** - optional. On low-power HA hardware (Raspberry Pi, HA Green),
  a local vision model is impractical, so use a cloud key (Gemini has a free
  tier) or leave AI off and enter items manually. Photo/receipt/barcode-cleanup
  features need a provider; everything else works without one.

Because Home Assistant secures the Ingress UI, the app's own password is **off
by default** in the add-on. You will not be asked to log in twice.

## Optional: direct LAN access for REST sensors

The `homeassistant/` folder in the project ships REST sensors, automations, and
a Lovelace dashboard for a **standalone** install. Those make HTTP calls to a
fixed URL, which Ingress does not provide. If you want them with the add-on:

1. Open the add-on **Network** tab and map port `8000` to a host port
   (e.g. `9284`).
2. In the setup wizard set a **UI password and/or API key** - exposing the port
   bypasses HA's Ingress auth, so app-level auth must be on.
3. Point the REST sensors at `http://<HA-IP>:9284`.

If you only use the sidebar UI, leave the port unmapped (the secure default).

## Backups

Use **Settings → Security → Download Backup** in the app, or the rclone remote
push, for the app's data. Home Assistant's own add-on backups also capture the
add-on's `/data` directory.
