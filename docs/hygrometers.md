# Fridge and room sensors (hygrometers)

Pantry Raider reads small Bluetooth temperature and humidity sensors, the
kind you drop in a refrigerator, freezer, pantry, or room, and shows their
readings on the Time & Temp page alongside your kitchen timers and cooking
probes. For a food tracker this is the natural companion feature: the same
screen that watches your roast can also tell you your fridge is sitting at a
safe 3 degrees.

These sensors are a separate class from the [cooking
thermometers](thermometers.md). A hygrometer has no probes, targets, or
doneness presets; it has a location (Fridge, Freezer, Pantry, Room), a
temperature, a humidity, and a battery. Alerts for a fridge that drifts warm
are coming in a later release; the min/max range you can set on each sensor
today is saved and will drive those alerts when they arrive.

## Supported hardware

All of these broadcast their readings over Bluetooth continuously, so Pantry
Raider only listens; nothing is paired or connected, and the sensor's phone
app keeps working alongside.

- **Govee H5075** (and the H5072/H5074 and similar Govee ambient sensors).
  Cheap, ubiquitous, and long-lived on a pair of AAA batteries.
- **Xiaomi LYWSD03MMC**, the little square Mijia sensor, **only when flashed
  with the community ATC firmware** (either the atc1441 or the pvvx build,
  both work). The stock Xiaomi firmware encrypts its broadcasts and is not
  supported; flashing takes a few minutes in a web browser and makes the
  sensor both readable and better on battery.
- **SwitchBot Meter and Meter Plus** (and the outdoor meter).
- **Inkbird IBS-TH1 and IBS-TH2**. A temperature-only IBS-TH2 shows just its
  temperature; the humidity spot stays blank.

## Setting it up

Hygrometers ride the same Bluetooth reader as the cooking thermometers, so if
probes already work on your device there is nothing more to install; see
[Bluetooth kitchen thermometers](thermometers.md) for the one-time reader
setup on a Pi appliance or a server.

Open Settings, Thermometers and find the **Hygrometers** section. A sensor
that is switched on nearby appears under Found nearby; add it, give it a name
and a location like Fridge or Freezer, and its card shows up on the Time &
Temp page with live temperature, humidity, and battery. A sensor that is out
of range right now can be added by its Bluetooth address instead.

Each sensor's row in Settings also has an alert range: the lowest and highest
temperature, and humidity, you consider normal for that spot. These are
saved now and will power fridge and freezer alerts in an upcoming release.

### From Home Assistant

No Bluetooth radio on the Pantry Raider machine? If Home Assistant already
sees your sensor (directly or through Bluetooth proxies), pick its
temperature entity, and its humidity entity if it has one, in the
Hygrometers section's From Home Assistant row. The pair shows up as one
sensor, readings and all, with nothing else to install.

### From an ESP device

A DIY WiFi sensor works too: an ESP32 or ESP8266 flashed with ESPHome (a
DHT22 or BME280 gives you temperature and humidity together) and the
`web_server` component can report to Pantry Raider directly, the same way
[ESP thermometers](thermometers.md#adding-an-esp-device) do, with the
humidity sensor read alongside the temperature one.

## On the Time & Temp page

Your sensors get their own Fridge & room sensors block under the cooking
probes: one card per sensor with its location, the temperature big and
readable across the kitchen, the humidity beside it, and the battery level.
A sensor that has not been heard from in a few minutes dims and shows a No
signal badge; fridge walls and metal doors eat Bluetooth, so a sensor deep in
a freezer may report less often than one on a shelf, and the card takes that
in stride.

Everything stays local: the sensors broadcast to your device (or to your own
Home Assistant), and nothing about your kitchen leaves the house.
