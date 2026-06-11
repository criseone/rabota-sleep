#!/usr/bin/env python3
"""Build a self-contained interactive HTML dashboard of all logged nights.

Sprint A2 (sharing layer) of the rabota sleep pipeline. Scans every
data/hr_*.csv, replays each night through the causal LayerExtractor (the same
code the live robot will use), and writes ONE portable .html file:

    - top: aggregate panels comparing nights (resting HR, sleep duration,
      deep-sleep fraction, restlessness)
    - below: an interactive pulse / depth / restlessness chart per night
      (hover for values, drag to zoom, click legend to toggle layers)

Plotly's JS is loaded from its CDN (not inlined), so the file stays ~300 KB.
The charts are interactive, which means they need JavaScript - so view the
dashboard over a real URL in a browser (e.g. served via GitHub Pages; see
README). Opening the raw .html in a mobile *preview pane* (iOS Quick Look /
in-app attachment viewer) shows the page shell but blank charts, because those
panes don't run JavaScript. A hosted URL opens in a real browser and works.

    python build_dashboard.py                 # all nights in ./data
    python build_dashboard.py --out share.html
    python build_dashboard.py --min-minutes 30  # ignore tiny test captures
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import plotly.graph_objects as go
from plotly.offline import get_plotlyjs_version
from plotly.subplots import make_subplots

from sleep_layers import LayerExtractor

# Installation palette (dark theme).
BG = "#0e0e14"
PANEL = "#16161f"
FG = "#e8e8f0"
MUTED = "#8a8a9a"
C_PULSE = "#ff5a6e"
C_RAW = "#55556a"
C_DEPTH = "#4aa3ff"
C_REST = "#ffb14a"

DEEP_THRESH = 0.70      # depth >= this counts as "deep sleep"
RESTLESS_THRESH = 0.50  # restlessness >= this counts as "restless"
BUCKET_S = 15.0         # downsample grid for the plotted series


@dataclass
class Night:
    label: str          # e.g. "Wed Jun 10"
    sub: str            # e.g. "00:26 - 06:00 - 5.6 h"
    t: list             # datetimes (downsampled)
    raw: list
    pulse: list
    depth: list
    rest: list
    dur_h: float
    min_hr: int
    mean_hr: float
    deep_frac: float    # fraction of (post-warmup) time in deep sleep
    rest_frac: float    # fraction of time restless


def load_night(path: Path):
    times, hrs = [], []
    with path.open() as f:
        for row in csv.DictReader(f):
            try:
                times.append(float(row["unix_time"]))
                hrs.append(int(row["hr_bpm"]))
            except (KeyError, ValueError):
                continue
    return times, hrs


def process(path: Path) -> Night | None:
    times, hrs = load_night(path)
    if len(times) < 2:
        return None

    ext = LayerExtractor()
    # accumulate into BUCKET_S grid as we stream
    t0 = times[0]
    buckets: dict[int, dict] = {}
    deep_n = rest_n = post_warm = 0
    for t, hr in zip(times, hrs):
        s = ext.update(t, hr)
        if s is None:
            continue
        if not s.warmup:
            post_warm += 1
            if s.depth >= DEEP_THRESH:
                deep_n += 1
            if s.restlessness >= RESTLESS_THRESH:
                rest_n += 1
        b = int((s.t - t0) // BUCKET_S)
        d = buckets.setdefault(b, {"raw": [], "p": [], "d": [], "r": []})
        d["raw"].append(s.hr)
        d["p"].append(s.pulse_bpm)
        d["d"].append(s.depth)
        d["r"].append(s.restlessness)

    if not buckets:
        return None
    keys = sorted(buckets)
    T = [datetime.fromtimestamp(t0 + k * BUCKET_S) for k in keys]
    avg = lambda xs: sum(xs) / len(xs)
    raw = [avg(buckets[k]["raw"]) for k in keys]
    pulse = [avg(buckets[k]["p"]) for k in keys]
    depth = [avg(buckets[k]["d"]) for k in keys]
    rest = [avg(buckets[k]["r"]) for k in keys]

    dur_h = (times[-1] - times[0]) / 3600
    start, end = datetime.fromtimestamp(times[0]), datetime.fromtimestamp(times[-1])
    return Night(
        label=start.strftime("%a %b %d"),
        sub=f"{start:%H:%M} - {end:%H:%M} - {dur_h:.1f} h",
        t=T, raw=raw, pulse=pulse, depth=depth, rest=rest,
        dur_h=dur_h, min_hr=min(hrs), mean_hr=sum(hrs) / len(hrs),
        deep_frac=(deep_n / post_warm) if post_warm else 0.0,
        rest_frac=(rest_n / post_warm) if post_warm else 0.0,
    )


def _dark(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        paper_bgcolor=BG, plot_bgcolor=PANEL, font=dict(color=FG, size=12),
        height=height, margin=dict(l=60, r=24, t=48, b=40),
        legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", y=1.08, x=0),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=MUTED)
    fig.update_yaxes(gridcolor="#262634", zeroline=False, linecolor=MUTED)
    return fig


def _labels(nights: list[Night], anon: bool) -> list[str]:
    return ([f"Night {i}" for i in range(1, len(nights) + 1)] if anon
            else [n.label for n in nights])


def aggregate_fig(nights: list[Night], anon: bool = False) -> go.Figure:
    x = _labels(nights, anon)
    # Resting HR (min bpm) is a biometric number; drop it in anonymized builds.
    # Titles are kept short so they don't overflow their column and collide on
    # narrow (phone) widths once Plotly's responsive mode shrinks the figure.
    bars = [
        ("Duration (h)", [round(n.dur_h, 1) for n in nights], FG),
        ("Deep (%)", [round(100 * n.deep_frac) for n in nights], C_DEPTH),
        ("Restless (%)", [round(100 * n.rest_frac) for n in nights], C_REST),
    ]
    if not anon:
        bars.insert(0, ("Rest HR (bpm)", [n.min_hr for n in nights], C_PULSE))
    fig = make_subplots(rows=1, cols=len(bars), horizontal_spacing=0.12,
                        subplot_titles=tuple(title for title, _, _ in bars))
    for col, (_, y, color) in enumerate(bars, start=1):
        fig.add_bar(x=x, y=y, marker_color=color, row=1, col=col)
    # Smaller subplot-title font keeps each title inside its column on phones.
    fig.update_annotations(font_size=13)
    fig.update_layout(showlegend=False)
    return _dark(fig, 300)


def night_fig(n: Night, anon: bool = False) -> go.Figure:
    # Anonymized: plot elapsed time from sleep onset (anchored at midnight) so the
    # real wall-clock schedule isn't revealed, just the shape of the night.
    t = n.t
    if anon:
        base = datetime(2000, 1, 1)
        t = [base + (ti - n.t[0]) for ti in n.t]
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.06,
        row_heights=[0.42, 0.3, 0.28],
        subplot_titles=("pulse", "depth (sleep)", "restlessness"),
    )
    fig.add_scatter(x=t, y=n.raw, line=dict(color=C_RAW, width=0.6),
                    name="raw HR", row=1, col=1)
    fig.add_scatter(x=t, y=n.pulse, line=dict(color=C_PULSE, width=1.4),
                    name="pulse", row=1, col=1)
    fig.add_scatter(x=t, y=n.depth, fill="tozeroy", line=dict(color=C_DEPTH, width=1),
                    fillcolor="rgba(74,163,255,0.35)", name="depth", row=2, col=1)
    fig.add_scatter(x=t, y=n.rest, fill="tozeroy", line=dict(color=C_REST, width=1),
                    fillcolor="rgba(255,177,74,0.35)", name="restlessness", row=3, col=1)
    fig.update_yaxes(range=[0, 1], row=2, col=1)
    fig.update_yaxes(range=[0, 1], row=3, col=1)
    if anon:
        # Hide the bpm scale (resting HR is mildly identifying); keep the curve.
        fig.update_yaxes(title_text="", showticklabels=False, row=1, col=1)
        fig.update_xaxes(tickformat="%H:%M", title_text="time since onset", row=3, col=1)
    else:
        fig.update_yaxes(title_text="bpm", row=1, col=1)
    fig.update_annotations(font_size=13)
    fig = _dark(fig, 480)
    # The shared dark theme parks the horizontal legend at y=1.08, right where
    # the row-1 ("pulse") subplot title sits — they overlap. Lift the legend
    # clear above the titles and give the top margin room for both.
    fig.update_layout(margin=dict(l=60, r=24, t=64, b=40),
                      legend=dict(y=1.12, yanchor="bottom"))
    return fig


def kpi_cards(nights: list[Night], anon: bool = False) -> str:
    total_h = sum(n.dur_h for n in nights)
    avg_dur = total_h / len(nights)
    avg_min = sum(n.min_hr for n in nights) / len(nights)
    avg_deep = 100 * sum(n.deep_frac for n in nights) / len(nights)
    cards = [
        ("Nights logged", f"{len(nights)}"),
        ("Total recorded", f"{total_h:.1f} h"),
        ("Avg duration", f"{avg_dur:.1f} h"),
    ]
    if not anon:  # avg resting HR is a biometric figure
        cards.append(("Avg resting HR", f"{avg_min:.0f} bpm"))
    cards.append(("Avg deep sleep", f"{avg_deep:.0f} %"))
    return "".join(
        f'<div class="card"><div class="v">{v}</div><div class="k">{k}</div></div>'
        for k, v in cards
    )


def build_html(nights: list[Night], out: Path, anonymize: bool = False) -> None:
    # Load Plotly from its CDN rather than inlining the ~3.5 MB bundle.
    # A single inline <script> that big silently aborts on mobile Safari/Chrome
    # (tab JS-memory limit), leaving the static shell but no charts. The CDN
    # tag keeps this file ~300 KB and loads fast on phones. Pinned to the
    # bundled plotly.js version so the URL always matches the figures we emit.
    # (Note: this is the plotly.js version, e.g. 3.6.0 - NOT the plotly Python
    # package version, e.g. 6.8.0; the CDN is keyed on the former.)
    plotly_cdn = f"https://cdn.plot.ly/plotly-{get_plotlyjs_version()}.min.js"
    div = lambda fig: fig.to_html(full_html=False, include_plotlyjs=False,
                                  config={"displayModeBar": False, "responsive": True})

    if anonymize:
        # No date span / clock times - just the night count.
        tag = f"{len(nights)} night{'s' if len(nights) != 1 else ''}"
    else:
        span = (f"{nights[0].label} - {nights[-1].label}" if len(nights) > 1
                else nights[0].label)
        tag = f"{span} - {len(nights)} night{'s' if len(nights) != 1 else ''}"

    def block(i: int, n: Night) -> str:
        label = f"Night {i}" if anonymize else n.label
        sub = f"{n.dur_h:.1f} h" if anonymize else n.sub
        return (f'<section class="night"><h3>{label}<span class="sub">{sub}</span></h3>'
                f'{div(night_fig(n, anonymize))}</section>')

    night_blocks = "".join(block(i, n) for i, n in enumerate(nights, 1))

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>rabota - sleep layers</title>
<script src="{plotly_cdn}" charset="utf-8"></script>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; background:{BG}; color:{FG};
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:32px 20px 80px; }}
  header h1 {{ font-size:26px; font-weight:600; margin:0 0 4px; letter-spacing:0.5px; }}
  header .tag {{ color:{MUTED}; font-size:14px; margin-bottom:4px; }}
  header .desc {{ color:{MUTED}; font-size:13px; max-width:620px; line-height:1.5; }}
  .kpis {{ display:flex; flex-wrap:wrap; gap:12px; margin:28px 0 8px; }}
  .card {{ background:{PANEL}; border:1px solid #242432; border-radius:12px;
    padding:16px 20px; min-width:120px; flex:1; }}
  .card .v {{ font-size:24px; font-weight:600; }}
  .card .k {{ color:{MUTED}; font-size:12px; margin-top:4px; }}
  h2 {{ font-size:15px; font-weight:600; color:{MUTED}; text-transform:uppercase;
    letter-spacing:1.5px; margin:40px 0 8px; }}
  .night {{ background:{PANEL}; border:1px solid #242432; border-radius:14px;
    padding:8px 14px 14px; margin:18px 0; }}
  .night h3 {{ font-size:17px; margin:10px 8px 0; font-weight:600; }}
  .night h3 .sub {{ color:{MUTED}; font-weight:400; font-size:13px; margin-left:12px; }}
  footer {{ color:{MUTED}; font-size:12px; margin-top:48px; text-align:center; }}
  .legend-dot {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin:0 4px 0 14px; }}
</style></head>
<body><div class="wrap">
  <header>
    <h1>rabota - sleep layers</h1>
    <div class="tag">{tag}</div>
    <div class="desc">Live heart rate from a Garmin watch, decomposed into three expressive
      layers that will drive the robot:
      <span class="legend-dot" style="background:{C_PULSE}"></span>pulse (the beat),
      <span class="legend-dot" style="background:{C_DEPTH}"></span>depth (sleep depth),
      <span class="legend-dot" style="background:{C_REST}"></span>restlessness.
      Hover for values - drag to zoom - toggle layers in each legend.</div>
  </header>
  <div class="kpis">{kpi_cards(nights, anonymize)}</div>
  <h2>Across nights</h2>
  {div(aggregate_fig(nights, anonymize))}
  <h2>Each night</h2>
  {night_blocks}
  <footer>rabota sleep pipeline - {len(nights)} logged night{'s' if len(nights) != 1 else ''} -
    layers computed causally (the same code drives the robot live).
    {'Anonymized: dates and clock times removed; x-axis is time since sleep onset.' if anonymize else ''}</footer>
</div></body></html>"""
    out.write_text(html)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the rabota sleep dashboard (single HTML).")
    ap.add_argument("--data", default="", help="Data dir (default: ./data)")
    ap.add_argument("--out", default="", help="Output HTML (default: ./sleep-dashboard.html)")
    ap.add_argument("--min-minutes", type=float, default=10.0,
                    help="Skip captures shorter than this (ignore test runs)")
    ap.add_argument("--anonymize", action="store_true",
                    help="Strip dates, clock times and biometric numbers - safe to host/share")
    args = ap.parse_args()

    data = Path(args.data) if args.data else Path(__file__).parent / "data"
    out = Path(args.out) if args.out else Path(__file__).parent / "sleep-dashboard.html"
    csvs = sorted(data.glob("hr_*.csv"))
    if not csvs:
        raise SystemExit(f"No {data}/hr_*.csv found - record a night first.")

    nights = []
    for p in csvs:
        n = process(p)
        if n is None:
            print(f"  skip {p.name}: no usable data")
        elif n.dur_h * 60 < args.min_minutes:
            print(f"  skip {p.name}: only {n.dur_h*60:.0f} min (< --min-minutes)")
        else:
            nights.append(n)
            print(f"  + {p.name}: {n.label}, {n.dur_h:.1f} h, "
                  f"deep {100*n.deep_frac:.0f}%, restless {100*n.rest_frac:.0f}%")
    if not nights:
        raise SystemExit("No nights long enough to plot.")

    build_html(nights, out, anonymize=args.anonymize)
    size_mb = out.stat().st_size / 1e6
    mode = "anonymized" if args.anonymize else "REAL DATA - keep local"
    print(f"\nWrote {out}  ({size_mb:.1f} MB, {len(nights)} night(s), {mode}) - open it in any browser.")


if __name__ == "__main__":
    main()
