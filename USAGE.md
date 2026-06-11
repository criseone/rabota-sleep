# rabota sleep pipeline — usage guide

Your night-to-night cheat sheet. Capture heart rate from the Garmin overnight,
turn it into the three expressive layers, and build a shareable dashboard.

> First time in a new terminal, always activate the environment:
> ```bash
> cd /Users/t1m/github/sleep-tracker-test
> source .venv/bin/activate
> ```

---

## Nightly routine (the short version)

**1. Before bed — put the watch in broadcast mode**
On the Forerunner 970: hold **UP** → **Watch Settings** → **Health & Wellness** →
**Wrist Heart Rate** → **Broadcast Heart Rate** → press **START**.
*Faster:* hold **LIGHT** (top button) → pick the broadcast-heart icon in the
controls menu.
You're on the right screen when it shows a **pulsing heart with your live BPM**.
(Broadcast lives under **Health & Wellness** — *not* "Sensors & Accessories",
which is for pairing external sensors *to* the watch, the wrong direction.)

**2. Start the logger** (keeps the Mac + Bluetooth awake all night):
```bash
./log_sleep.sh
```
Watch for live `HR … bpm` lines, then go to sleep. **Keep the Mac plugged in.**

**3. In the morning** — stop it with **Ctrl+C**. Nothing is lost; data is saved
continuously. Your night is now a CSV in `data/`.

**4a. Preview locally** (real data, stays on your Mac):
```bash
make preview          # = python build_dashboard.py
```
Open **`sleep-dashboard.html`**. The new night appears automatically.

**4b. Publish the shared dashboard** (anonymized, pushed to GitHub Pages):
```bash
make publish                      # build index.html + commit + push
make publish m="add Fri night"    # with a custom commit message
```
Equivalent long form:
```bash
python build_dashboard.py --anonymize --out index.html
git add index.html && git commit -m "update dashboard" && git push
```
⚠️ **Both flags matter.** Without `--out index.html` the build writes
`sleep-dashboard.html` instead — which is git-ignored — so `git commit` finds
nothing to commit and the hosted page silently stays on the *old* night. The
file GitHub hosts is **`index.html`**; that's the only one publishing touches.

That's it. Everything below is detail and troubleshooting.

---

## The commands in full

| What | Command |
|---|---|
| **Log a night** (recommended) | `./log_sleep.sh` |
| Log, targeting watch by address | `./log_sleep.sh --address <UUID>` |
| Find your watch / list BLE devices | `python sleep_logger.py --scan` |
| Logger directly (no caffeinate) | `python sleep_logger.py --name Forerunner` |
| **Preview locally** (real data) | `python build_dashboard.py` |
| **Publish** (anonymized → GitHub) | `python build_dashboard.py --anonymize --out index.html` then `git add index.html && git commit -m "update dashboard" && git push` |
| Single-night tuning plot (PNG) | `python analyze_night.py` |

### `./log_sleep.sh` — the overnight logger
Wraps the logger in `caffeinate` so the Mac doesn't sleep. Defaults to matching
the watch by the name **"Forerunner"**. Any flags pass through to the logger.
- Output: `data/hr_<timestamp>.csv` (git-ignored).
- Use `--name Forerunner` (the default), **not** `--address` — the watch's macOS
  Bluetooth UUID changes between sessions, but the name stays put.

### `python build_dashboard.py` — shareable HTML
Scans every night in `data/` and writes one self-contained file (works offline).
- **No flags** → `sleep-dashboard.html`, with **real** data. Git-ignored — local
  preview only, never published.
- `--anonymize --out index.html` → the **anonymized, hosted** build. `index.html`
  is the only file committed/served by GitHub Pages.
- `--out share.html` — choose a different output path
- `--min-minutes 30` — ignore short test captures (default skips < 10 min)

Why two filenames: it's a guardrail so real data can't be published by accident.
The "no usable data" skip line you may see is just a false-start capture (a
recording that caught nothing) — harmless; real nights still go through.

### `python analyze_night.py` — single-night detail (for tuning)
Renders one night to a 4-panel PNG next to the CSV. Defaults to the newest night;
pass a path to pick one: `python analyze_night.py data/hr_20260610_002608.csv`.

---

## The three layers (what you're looking at)

All computed **causally** (only past data) so the exact same code can drive the
robot live later. Tunables live at the top of `sleep_layers.py`.

- **pulse** — the heartbeat itself, lightly de-spiked → the robot's base rhythm.
- **depth** — a slow trend of HR, 0 (light) … 1 (deep). Lower HR ⇒ deeper sleep.
  *Note:* the first ~5 minutes is "warm-up" while the baseline settles — ignore it.
- **restlessness** — short-term HR variability + spikes (position changes /
  arousals), 0 … 1.

---

## Troubleshooting

**Watch doesn't show up in `--scan` / "No matching device"**
- Is broadcast mode actually on? Re-trigger it (it can time out) — look for the
  pulsing-heart screen.
- It may appear as `(unknown)` rather than "Forerunner" but with `HR yes` — that's
  fine. If `./log_sleep.sh` can't find it by name, scan and use `--address <UUID>`.

**macOS asks for Bluetooth permission (or scanning finds nothing)**
- Allow it: System Settings → Privacy & Security → Bluetooth → enable your
  terminal app. First run usually prompts automatically.

**It disconnected during the night**
- The logger auto-reconnects, so brief drops self-heal. If it ended early, the
  watch's broadcast probably timed out or the watch battery died — charge it
  before bed and confirm broadcast stays on.

**The Mac went to sleep**
- Use `./log_sleep.sh` (not the bare logger) and keep it **on AC power** —
  `caffeinate` only reliably holds off sleep when plugged in.

---

## Files in this project

| File | Role |
|---|---|
| `sleep_logger.py` | Overnight BLE heart-rate → CSV capture |
| `log_sleep.sh` | `caffeinate` wrapper for unattended nights |
| `sleep_layers.py` | Causal streaming layer extractor (also the live-robot core) |
| `analyze_night.py` | Single-night tuning plot (PNG) |
| `build_dashboard.py` | Multi-night shareable HTML dashboard |
| `Makefile` | Shortcuts: `make preview` / `make publish` / `make log` |
| `data/` | Your recorded nights (git-ignored) |
| `sleep-dashboard.html` | Local real-data preview (git-ignored, never published) |
| `index.html` | The anonymized dashboard hosted on GitHub Pages |
