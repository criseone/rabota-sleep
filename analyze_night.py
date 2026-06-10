#!/usr/bin/env python3
"""Plot a recorded night through the causal layer extractor (rabota A2).

Replays a logged HR CSV (from sleep_logger.py) sample-by-sample through
LayerExtractor — exactly as the live A3 emitter will — and renders a 4-panel
figure plus summary stats, so the pulse / depth / restlessness layers can be
eyeballed and the tunables in sleep_layers.py adjusted.

    python analyze_night.py                 # newest CSV in ./data
    python analyze_night.py path/to/hr.csv  # a specific night
    python analyze_night.py --out fig.png   # choose output path
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless: write a PNG, no display needed
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from sleep_layers import LayerExtractor


def newest_csv() -> Path:
    data = Path(__file__).parent / "data"
    csvs = sorted(data.glob("hr_*.csv"))
    if not csvs:
        raise SystemExit("No data/hr_*.csv found — record a night first.")
    return csvs[-1]


def load(path: Path):
    times, hrs = [], []
    with path.open() as f:
        for row in csv.DictReader(f):
            try:
                times.append(float(row["unix_time"]))
                hrs.append(int(row["hr_bpm"]))
            except (KeyError, ValueError):
                continue
    if not times:
        raise SystemExit(f"No usable rows in {path}")
    return times, hrs


def main() -> None:
    ap = argparse.ArgumentParser(description="Plot a night's sleep layers (rabota A2).")
    ap.add_argument("csv", nargs="?", default="", help="CSV path (default: newest in ./data)")
    ap.add_argument("--out", default="", help="Output PNG (default: alongside the CSV)")
    args = ap.parse_args()

    path = Path(args.csv) if args.csv else newest_csv()
    out = Path(args.out) if args.out else path.with_suffix(".layers.png")
    times, hrs = load(path)

    # Replay through the causal extractor, exactly like the live stream will.
    ext = LayerExtractor()
    T, raw, pulse, depth, rest, dropped = [], [], [], [], [], 0
    for t, hr in zip(times, hrs):
        snap = ext.update(t, hr)
        if snap is None:
            dropped += 1
            continue
        T.append(datetime.fromtimestamp(snap.t))
        raw.append(snap.hr)
        pulse.append(snap.pulse_bpm)
        depth.append(snap.depth)
        rest.append(snap.restlessness)

    span_h = (times[-1] - times[0]) / 3600
    mean_hr = sum(hrs) / len(hrs)
    print(f"File:    {path.name}")
    print(f"Samples: {len(hrs):,}  ({dropped} dropped as artefacts)")
    print(f"Span:    {datetime.fromtimestamp(times[0]):%H:%M} -> "
          f"{datetime.fromtimestamp(times[-1]):%H:%M}  ({span_h:.2f} h)")
    print(f"HR:      min {min(hrs)}  max {max(hrs)}  mean {mean_hr:.1f} bpm")
    print(f"Depth:   peak {max(depth):.2f} (deepest)  mean {sum(depth)/len(depth):.2f}")
    print(f"Restless: peak {max(rest):.2f}  mean {sum(rest)/len(rest):.2f}")

    fig, axes = plt.subplots(4, 1, figsize=(13, 9), sharex=True)
    fig.suptitle(f"rabota sleep layers — {path.name}  ({span_h:.1f} h)", fontsize=12)

    axes[0].plot(T, raw, lw=0.4, color="#888", label="raw HR")
    axes[0].plot(T, pulse, lw=0.8, color="#c0392b", label="pulse (de-spiked)")
    axes[0].set_ylabel("HR (bpm)")
    axes[0].legend(loc="upper right", fontsize=8)

    axes[1].plot(T, pulse, lw=0.7, color="#c0392b")
    axes[1].set_ylabel("pulse\n(bpm)")

    axes[2].fill_between(T, depth, color="#2980b9", alpha=0.5)
    axes[2].set_ylabel("depth\n(0=light,1=deep)")
    axes[2].set_ylim(0, 1)

    axes[3].fill_between(T, rest, color="#e67e22", alpha=0.6)
    axes[3].set_ylabel("restlessness\n(0..1)")
    axes[3].set_ylim(0, 1)

    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    axes[-1].set_xlabel("time")
    for ax in axes:
        ax.grid(True, alpha=0.2)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(out, dpi=110)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
