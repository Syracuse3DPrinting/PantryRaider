# SD-card image guide

Flash a pre-configured FoodAssistant appliance to an SD card (or USB/NVMe),
boot your board, and reach the app at **http://foodassistant.local:9284/** with
minimal setup. No terminal required on the device.

> New to the hardware side? See [supported-hardware.md](supported-hardware.md)
> for boards, RAM guidance, and peripherals.

## How it works

FoodAssistant uses the official **Raspberry Pi OS Lite (64-bit)** image plus a
small **first-boot provisioner** instead of a bespoke custom image. On first
boot the device installs Docker, downloads the FoodAssistant + Grocy
containers, and starts them automatically. This keeps you on Raspberry Pi's
official, security-patched base image.

**Tradeoff:** the very first boot needs internet and takes a few minutes while
it pulls Docker and the container images. After that it is fully self-contained
and boots fast. (Maintainer/build details: `scripts/image-build/README.md`.)

## What you need

- A supported board — **Raspberry Pi 4 or Pi 5 (ARM64)** recommended; generic
  ARM64/x86-64 Debian/Ubuntu also works (see "Hardware coverage" below).
- A 16 GB+ SD card (32 GB+ recommended).
- Ethernet or Wi-Fi with internet for the first boot.
- A flashing tool: **Raspberry Pi Imager** (recommended) or **balenaEtcher**.

## Step 1 — Flash Raspberry Pi OS Lite (64-bit)

### Using Raspberry Pi Imager (recommended)

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. **Choose Device:** your Pi model. **Choose OS:** *Raspberry Pi OS (other) →
   Raspberry Pi OS Lite (64-bit)*. **Choose Storage:** your card.
3. Click the gear / **Edit Settings** and set:
   - **Hostname:** `foodassistant` (optional — our config sets this too).
   - **Wi-Fi** credentials (skip if using Ethernet).
   - **Locale / timezone.**
   - Enable **SSH** if you want remote access (optional).
4. **Write** the image, but **do not eject yet.**

### Using balenaEtcher

Download Raspberry Pi OS Lite (64-bit) from
[raspberrypi.com](https://www.raspberrypi.com/software/operating-systems/),
flash it with [balenaEtcher](https://etcher.balena.io/), then continue to
Step 2 to add the FoodAssistant payload (Etcher has no customization, so the
prepare step is required).

## Step 2 — Add the FoodAssistant first-boot payload

After flashing, the card's **boot partition** (`bootfs`) reappears as a small
FAT volume. Add the provisioner to it.

### Option A — automated (Linux/macOS)

```bash
git clone https://github.com/Syracuse3DPrinting/FoodAssistant
cd FoodAssistant
# Edit the appliance config first (timezone, kiosk, Mealie/Ollama, hostname):
$EDITOR image/config.env
# Point at the mounted boot volume (path varies by OS):
scripts/image-build/prepare-image.sh --boot-dir /Volumes/bootfs        # macOS
scripts/image-build/prepare-image.sh --boot-dir /media/$USER/bootfs    # Linux
```

You can also bake it into an `.img` *before* flashing (Linux, as root):

```bash
sudo scripts/image-build/prepare-image.sh --image path/to/raspios-lite-arm64.img
```

### Option B — manual copy

Copy these onto the boot partition:

- `scripts/image-build/firstrun.sh` → `bootfs/firstrun.sh`
- the whole `scripts/image-build/` payload → `bootfs/foodassistant-setup/`
  (must contain `firstboot.sh`, `foodassistant-firstboot.service`,
  `docker-compose.appliance.yml`)
- `image/config.env` → `bootfs/foodassistant.config.env` (edit as desired)

Then append to the single line in `bootfs/cmdline.txt`:

```
systemd.run=/boot/firmware/firstrun.sh systemd.run_success_action=reboot systemd.unit=kernel-command-line.target
```

`prepare-image.sh` does all of this for you (Option A).

Eject the card safely.

## Step 3 — First boot

1. Insert the card, connect network, power on.
2. The first boot runs the provisioner. Expect **a few minutes** while it
   installs Docker and pulls images. The device may reboot once.
3. Watch progress (if you enabled SSH):
   ```bash
   ssh <user>@foodassistant.local
   tail -f /var/log/foodassistant-firstboot.log
   ```

## Step 4 — Open the app

Browse to:

```
http://foodassistant.local:9284/
```

First time, you'll be sent to `http://foodassistant.local:9284/setup` to set a
password and add your Grocy + AI provider details.

If `foodassistant.local` doesn't resolve, use the device's IP:
`http://<device-ip>:9284/`. (Some Android devices and older Windows lack mDNS;
see Troubleshooting.)

## Configuration (`config.env`)

Set these in `image/config.env` (or directly in
`bootfs/foodassistant.config.env` after flashing):

| Key | Default | Purpose |
|-----|---------|---------|
| `HOSTNAME` | `foodassistant` | Hostname and mDNS name (`<name>.local`). |
| `TZ` | `America/New_York` | Timezone (IANA name). |
| `ENABLE_MEALIE` | `false` | Start Mealie (recipes/meal plan). Needs 4 GB RAM. |
| `ENABLE_OLLAMA` | `false` | Start local Ollama. Not recommended on SBCs. |
| `ENABLE_KIOSK` | `false` | Auto-launch full-screen Chromium **if a display is present**. |
| `KIOSK_URL` | `http://localhost:9284/ui/` | What the kiosk opens. |
| `FOODASSISTANT_TAG` | `latest` | Pin a specific app image version. |
| `INSTALL_DIR` | `/opt/foodassistant` | Where the stack is installed on-device. |

### Enabling Mealie / Ollama later

Edit `config.env` before flashing, **or** on a running device:

```bash
cd /opt/foodassistant
docker compose --profile with-mealie up -d     # add Mealie
docker compose --profile with-ollama up -d      # add Ollama
```

### Kiosk mode (touchscreen)

Set `ENABLE_KIOSK=true`. On first boot, if a display is detected (DRM/KMS, or
an X/Wayland session), the provisioner installs `cage` + Chromium and starts
`foodassistant-kiosk.service`, which opens `KIOSK_URL` full-screen on `tty1`.
On a headless box the flag is harmless — it logs and skips. Manage it with:

```bash
systemctl status foodassistant-kiosk
systemctl restart foodassistant-kiosk
```

## Hardware coverage

| Board / class | Status |
|---------------|--------|
| Raspberry Pi 5 (ARM64) | ✅ Recommended |
| Raspberry Pi 4B 4/8 GB (ARM64) | ✅ Supported |
| Raspberry Pi 4B 2 GB | 🟡 Grocy-only; Mealie tight |
| Generic x86-64 Debian/Ubuntu | ✅ Provisioner runs (boot-partition wiring is Pi-specific; run `firstboot.sh` directly) |
| Other ARM64 Debian/Ubuntu boards | 🟡 Best-effort; Docker install via get.docker.com |
| Pi 3B+ / Zero 2 W | ❌ Insufficient RAM |

On non-Pi hardware there's no `cmdline.txt`/`firstrun.sh` boot hook. Install
the provisioner directly:

```bash
sudo cp -r scripts/image-build /opt/foodassistant-setup
sudo cp image/config.env /etc/foodassistant/config.env   # mkdir -p first
sudo /opt/foodassistant-setup/firstboot.sh
```

See [supported-hardware.md](supported-hardware.md) for the full matrix.

## Troubleshooting

**`foodassistant.local` won't resolve.** mDNS isn't universal. Use the device
IP, or install Bonjour (Windows) / ensure `avahi-daemon` is running on the
device (`systemctl status avahi-daemon`). Find the IP from your router or
`ssh` with the IP.

**First boot seems stuck.** It's pulling Docker images — give it 5–10 minutes
on a slow connection. Check `tail -f /var/log/foodassistant-firstboot.log`.
The provisioner is idempotent and retries on transient failures
(`foodassistant-firstboot.service` is `Restart=on-failure`).

**Want to re-run provisioning.** Remove the marker and restart the service:

```bash
sudo rm -f /var/lib/foodassistant/firstboot.done
sudo systemctl start foodassistant-firstboot.service
# or run directly:  sudo FORCE=1 /opt/foodassistant-setup/firstboot.sh
```

**Verify the stack.**

```bash
cd /opt/foodassistant && docker compose ps
```

**Containers didn't start.** Confirm Docker installed:
`docker --version && docker compose version`. Re-run the provisioner (above).

**No internet on first boot.** Docker install and image pulls require it.
Connect the network and re-run provisioning.
