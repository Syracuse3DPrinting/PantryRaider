# FoodAssistant Appliance — V1 Hardware Spec

> **Status:** Planning / pre-prototype  
> **Last updated:** June 2026  
> **Scope:** Countertop/wall-mount appliance running the full local FoodAssistant stack with integrated touchscreen and barcode scanner. No embedded camera (users scan items; photos taken via phone browser). No local LLM in V1.

---

## SKU Lineup

| SKU | Display | Target retail |
|-----|---------|--------------|
| **Headless** | None — access via phone/tablet/browser on LAN | ~$199 |
| **7"** | 7" HDMI capacitive touch, countertop or wall | ~$299 |
| **10"** | 10.1" HDMI capacitive touch, countertop or wall | ~$379 |

All three SKUs share identical compute and software. The headless SKU ships in the N100's stock enclosure with zero custom enclosure work.

---

## Compute: Intel N100 Mini PC

### Why not Raspberry Pi 5?

As of June 2026, the Pi 5 4 GB bare board costs **~$130** due to LPDDR4 memory shortages driven by AI infrastructure demand (two price increases in early 2026, >70% above original MSRP). At that price:

| | Pi 5 4 GB | N100 Mini PC (e.g. Beelink S12 Pro) |
|--|-----------|--------------------------------------|
| Price | ~$130 (bare board) | ~$150–165 (complete unit) |
| RAM | 4 GB | 16 GB |
| Storage | None (add SD ~$10) | 500 GB NVMe |
| Case | None | Included |
| PSU | None (add ~$10) | Included |
| Architecture | ARM | x86-64 |
| Idle power | ~3–5 W | ~6–10 W |

The N100 is unambiguously better value at current pricing. The Pi 5 advantage (DSI ribbon display, smaller board) is not worth the premium. **Revisit if Pi pricing normalizes** — the gap may close.

### Recommended unit

**Beelink Mini S12 Pro** (or equivalent GMKtec NucBox G3):
- Intel N100 (4C/4T, up to 3.4 GHz, Alder Lake-N)
- 16 GB DDR4
- 500 GB M.2 NVMe
- 2× HDMI 4K@60Hz, USB 3.2, 2.5 GbE, WiFi 6, BT 5.2
- Pre-certified (FCC/CE on the unit)
- 60 W listed external PSU included

For display SKUs the N100's dual HDMI is used for the panel; for headless the unit ships as-is. For display SKUs the N100 mounts inside the custom FDM enclosure; the factory case is not used.

### Power

N100 at idle (no LLM): 6–10 W. Under load serving the web stack: 12–18 W peak. The factory 60 W PSU brick is the power source — listed, certified, no custom power circuit needed. Safety cert burden stays on the PSU manufacturer.

---

## Display

### 7" SKU

**Waveshare 7" HDMI Capacitive Touchscreen (H), 1024×600 IPS** (or equivalent)
- HDMI video + USB-A for touch — both route internally to the N100
- Capacitive 5-point touch, works with Chromium kiosk
- Toughened glass face panel, bezel-mountable
- Est. ~$45–60 (verify current pricing at purchase)

### 10" SKU

**Waveshare 10.1" HDMI Capacitive Touchscreen, 1280×800 IPS** (or equivalent)
- Same HDMI + USB-A touch wiring pattern
- Larger surface area for inventory grid, meal plan week view, recipe cards
- Est. ~$75–95 (verify current pricing at purchase)

### Display note — no DSI

All SKUs use HDMI + USB touch rather than DSI. This is a consequence of using N100 compute (no DSI output). Wiring is slightly more involved than a Pi DSI ribbon but entirely standard for kiosk/signage integrations.

---

## Barcode Scanner

**Waveshare Barcode Scanner Module** (1D/2D) or equivalent compact OEM scan engine
- USB HID — presents as a keyboard to the OS; zero driver work
- Reads 1D (UPC-A, EAN-13, Code 128, etc.) and 2D (QR, DataMatrix)
- Compact rectangular form factor; scan window mounts flush in bezel cutout
- Est. ~$20–35 (verify current pricing at purchase)

### Integration

The module sits in a dedicated bay in the FDM enclosure with its scan window exposed through a 30×20 mm cutout in the top bezel or right edge. USB pigtail routes internally to the N100. From outside the device it looks built-in. Users wave items past the window; the decoded string fires into the focused browser tab as keystrokes, caught by the existing `barcode-input` listener on the add-item page.

No software changes needed — the existing barcode flow handles USB HID scanners already.

---

## Phone Camera (Photos & Receipts)

No embedded camera in V1. Users photograph items using their phone's browser:

1. Phone opens `http://foodassistant.local` (or IP) on LAN — or the cloud subscription URL
2. `<input type="file" accept="image/*" capture="environment">` triggers native phone camera
3. Photo uploads to the existing `/analyze` endpoint

**Improvement needed (software task):** Add a QR code or scannable link on the appliance display that deep-links the phone directly to the upload page, eliminating the need to type the URL.

---

## Software Stack (all SKUs)

Identical Docker Compose stack on all units:

```
FoodAssistant (FastAPI, port 9284)
Grocy          (inventory backend, port 9383)
Mealie         (recipes/meal plan/shopping, port 9285)
```

AI: **cloud subscription only** in V1. No local LLM. Vision analysis routes to the cloud provider configured in settings (Gemini/OpenAI/Anthropic). This keeps thermals flat and the N100 cool.

**Kiosk UI (display SKUs):**
- Raspberry Pi OS Lite → Debian-based x86 equivalent (Ubuntu Server or Debian minimal)
- Cage (Wayland compositor) + Chromium `--kiosk --app=http://localhost:9284/ui/`
- On-screen keyboard: `wvkbd` or `squeekboard` for text input fields
- Auto-login, auto-start on boot

**Touch target sizing:** The current Bootstrap 5 UI is mouse/desktop-tuned. A software task is needed to increase tap targets and test the full workflow on a 7" 1024×600 screen before shipping display SKUs.

---

## Enclosure (Display SKUs)

### Material

**PETG** (not PLA) — kitchen counter proximity to heat sources causes PLA to creep/deform over time.

### Form factor

- Two-piece shell: base + face plate
- **VESA 75mm keyhole** on back for wall mount
- **Detachable angled foot/stand** (15° tilt toward user) for countertop — same enclosure shell, two deployments
- All ports (HDMI passthrough is internal; expose: USB-A ×2, Ethernet, barrel jack or USB-C PSU, barrel jack from N100) through rear cutouts
- **Scanner bay** in top bezel or right edge with 30×20 mm window cutout
- Passive cooling: N100 without LLM stays cool enough at kitchen duty cycles; include a PWM fan mount in the shell but ship without fan by default

### N100 mounting

For display SKUs the N100's factory case is removed; the bare board mounts to standoffs in the custom enclosure base. Verify the specific N100 model board dimensions before committing enclosure geometry — Beelink and GMKtec boards are similar but not identical.

---

## BOM Summary (estimates — verify at purchase)

### Headless SKU (~$199 retail)

| Part | Est. cost |
|------|-----------|
| N100 mini PC (N100, 16 GB, 500 GB) | ~$150–165 |
| Barcode scanner module (optional add-on) | ~$20–35 |
| **Compute total (no scanner)** | **~$150–165** |

Ships in factory case. Zero enclosure work. Scanner offered as a separate USB add-on users plug in themselves.

### 7" SKU (~$299 retail)

| Part | Est. cost |
|------|-----------|
| N100 mini PC (bare board) | ~$150–165 |
| Waveshare 7" HDMI+USB touch panel | ~$45–60 |
| Barcode scanner module | ~$20–35 |
| PETG enclosure (FDM, in-house) | ~$12–16 |
| Misc (standoffs, internal cables, USB hub if needed) | ~$10–15 |
| **Total** | **~$237–291** |

### 10" SKU (~$379 retail)

| Part | Est. cost |
|------|-----------|
| N100 mini PC (bare board) | ~$150–165 |
| Waveshare 10.1" HDMI+USB touch panel | ~$75–95 |
| Barcode scanner module | ~$20–35 |
| PETG enclosure (FDM, in-house, larger) | ~$16–22 |
| Misc | ~$10–15 |
| **Total** | **~$271–332** |

---

## Certification

- **FCC/CE radio cert:** Inherited from N100 mini PC unit (already certified). No custom radio.
- **Safety:** N100 unit ships with a listed PSU; internal power is just the factory board's regulators. No custom power circuit.
- **EMC (unintentional radiator):** For an assembled product sold as consumer electronics, a pre-scan at an EMC lab ($1–2K) is advisable before committing to a production run. The N100 + HDMI panel combination is well-understood; risk is low but worth checking.
- **DIY kit path:** If sold as a kit (unassembled), FCC Part 15 Subpart B self-declaration + Declaration of Conformity. Cheaper, faster, standard for Crowd Supply / direct-sale products.

---

## Compute Watchlist

If Raspberry Pi 5 pricing returns toward original MSRP ($60 for 4 GB), re-evaluate the 7" SKU with Pi 5 + DSI panel:
- Eliminates USB touch controller complexity
- Smaller board = smaller enclosure
- Better power efficiency for the display SKU
- Pi 5 PCIe lane opens door to NVMe and future NPU add-ons

The software stack requires zero changes to switch compute platforms.

---

## Open Questions / Future SKUs

- [ ] Finalize N100 board dimensions (Beelink vs GMKtec) before enclosure CAD
- [ ] Test full FoodAssistant stack on N100 running Ubuntu Server (x86 Docker images — should be straightforward)
- [ ] Test Chromium kiosk + wvkbd on Wayland at 1024×600 — verify UI tap target sizing
- [ ] Evaluate USB hub requirement inside enclosure (N100 has multiple USB ports but routing all internal cables may need a hub)
- [ ] Phone QR code / deep link feature for photo upload UX
- [ ] **V2 consideration:** Expose M.2 slot for NVMe upgrade or future LLM accelerator; add NPU when viable M.2 LLM accelerator exists
- [ ] **V2 consideration:** Camera module option (autofocus CSI or USB) to enable on-device photo analysis without phone
