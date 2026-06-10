# sleep-tracker-test

Sprint **A1** of the rabota sleep pipeline: capture live heart rate from a
Garmin Forerunner 970 (Path A — native BLE HR broadcast) to a CSV on the Mac.

This is the data-capture foundation. The expressive "layers" (pulse / depth /
restlessness) and the live feed to the robot come in later sprints (A2, A3) —
the goal here is to **log clean raw data from night one** so we have real
material to tune against.

## 1. Put the watch into HR broadcast mode

On the Forerunner 970:

- **Hold UP** → **Watch Settings** → **Health & Wellness** → **Wrist Heart Rate** →
  **Broadcast Heart Rate** → press **START** to begin broadcasting, **or**
- **Faster:** hold **LIGHT** (top button) to open the controls menu and pick the
  broadcast-heart icon (add it via controls customization if it's not there), **or**
- Start an activity (e.g. *Other* / *Cardio*) with **Broadcast During Activity**
  enabled, for an overnight session.

Note: broadcast lives under **Health & Wellness**, *not* "Sensors & Accessories"
(that submenu is for pairing external sensors *to* the watch — the wrong direction).

The watch now advertises the standard BLE Heart Rate Service (~1 Hz).
Note: the Garmin broadcast does **not** include RR intervals (so true HRV
isn't available here — we'll approximate variability from the HR stream in A2).

## 2. Set up

```bash
cd sleep-tracker-test
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**macOS Bluetooth permission:** the first run will prompt for Bluetooth access
for your terminal app. Allow it (or System Settings → Privacy & Security →
Bluetooth → enable your terminal/IDE), otherwise scanning finds nothing.

## 3. Find your watch (optional)

```bash
python sleep_logger.py --scan
```

Lists nearby BLE devices with signal strength and whether each advertises the
HR service. Note your watch's address (on macOS this is a CoreBluetooth UUID,
not a MAC address).

## 4. Log heart rate

```bash
# Connect to the first device advertising the HR service:
python sleep_logger.py

# Or target your watch explicitly (most reliable):
python sleep_logger.py --address <ADDRESS-FROM-SCAN>

# Or match by name:
python sleep_logger.py --name Forerunner
```

It prints each reading live and auto-reconnects if the link drops. Stop with
**Ctrl+C** — data is flushed on every reading, so nothing is lost if it crashes.

## Output

CSV at `data/hr_<timestamp>.csv` (the `data/` folder is git-ignored):

| column | meaning |
|---|---|
| `iso_time` | local timestamp, millisecond precision |
| `unix_time` | epoch seconds (float) |
| `hr_bpm` | heart rate in beats per minute |
| `rr_ms` | RR intervals in ms, `;`-separated (usually empty on Garmin broadcast) |
| `sensor_contact` | `contact` / `no_contact` / `unsupported` |

## Options

| flag | default | description |
|---|---|---|
| `--scan` | — | list nearby BLE devices and exit |
| `--name` | (any) | substring of the device name to match |
| `--address` | — | connect directly to a BLE address/UUID |
| `--output` | `data/hr_<ts>.csv` | CSV output path |
| `--scan-timeout` | `10` | seconds to scan |
| `--reconnect-delay` | `5` | seconds between reconnect attempts |
