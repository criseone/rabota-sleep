#!/usr/bin/env python3
"""Causal streaming extraction of the three rabota sleep layers from live HR.

Sprint A2 of the rabota sleep pipeline. Given the ~1-2 Hz heart-rate stream
(from sleep_logger.py / the BLE watch), derive three expressive layers:

    pulse        - the beat itself: lightly de-spiked instantaneous HR (bpm),
                   and a 0..1 tempo for driving the robot's base rhythm.
    depth        - slow sleep-depth proxy: a long trailing average of HR,
                   mapped to 0..1 where 1 = deepest (lowest HR vs. an adaptive
                   baseline). Lower HR through the night => deeper sleep.
    restlessness - short-term agitation: trailing variability of HR plus
                   above-trend spikes (position changes / arousals), 0..1.

DESIGN — everything here is CAUSAL and STREAMING. Each update() uses only past
samples within a bounded trailing window: no future lookahead, no whole-night
normalization. That is a hard requirement (see the realtime-constraint memo):
the SAME extractor runs offline over a recorded night to tune (analyze_night.py)
and live in A3 to drive the robot, so tuning transfers directly. Feed it one
(unix_time, hr_bpm) sample at a time; it returns a Layers snapshot each call.

Latency budget (≤~1 min end-to-end is fine):
    pulse        ~ PULSE_WINDOW_S (5 s) trailing median
    restlessness ~ REST_WINDOW_S  (45 s) trailing window
    depth        deliberately slow (DEPTH_TAU_S ~ 8 min EMA) — its lag is the
                 point, not a violation; it's a slow trend by design.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

# --- Tunables (offline tuning in A2 lands here; live A3 imports the same) ----
PULSE_WINDOW_S = 5.0      # trailing median window to de-spike the beat
DEPTH_TAU_S = 8 * 60.0    # slow EMA time-constant for the depth trend
DEPTH_RANGE_TAU_S = 60 * 60.0  # how fast the adaptive depth baseline forgets
REST_WINDOW_S = 45.0      # trailing window for short-term variability
REST_FULL_SCALE = 8.0     # HR std (bpm) that maps to restlessness = 1.0
SPIKE_BPM = 6.0           # bpm above the slow trend that counts as a full spike

# Plausible human sleeping-HR bounds; readings outside are dropped as artefacts.
HR_MIN_VALID = 30
HR_MAX_VALID = 180


@dataclass
class Layers:
    """One causal snapshot of the three layers at a given time."""
    t: float                 # unix time of the sample
    hr: float                # raw HR (bpm) for reference
    pulse_bpm: float         # de-spiked instantaneous HR (bpm)
    pulse_tempo: float       # 0..1 beat tempo (slow..fast) for robot rhythm
    depth: float             # 0..1, 1 = deepest sleep
    restlessness: float      # 0..1, 1 = most agitated
    warmup: bool             # True until the adaptive baseline has settled


def _ema_alpha(dt: float, tau: float) -> float:
    """Irregular-sample EMA weight for a gap of dt seconds at time-constant tau."""
    if dt <= 0:
        return 0.0
    return 1.0 - math.exp(-dt / tau)


class LayerExtractor:
    """Streaming, causal extractor. Feed samples in time order via update()."""

    def __init__(self, warmup_s: float = 5 * 60.0):
        self._warmup_s = warmup_s
        self._t0: float | None = None
        self._last_t: float | None = None

        # trailing raw buffers (time-bounded)
        self._pulse_buf: deque[tuple[float, float]] = deque()
        self._rest_buf: deque[tuple[float, float]] = deque()

        # EMAs / adaptive baseline state
        self._hr_slow: float | None = None      # depth trend (slow EMA)
        self._slow_lo: float | None = None       # adaptive low  of hr_slow
        self._slow_hi: float | None = None       # adaptive high of hr_slow

    @staticmethod
    def _trim(buf: deque[tuple[float, float]], now: float, window: float) -> None:
        while buf and now - buf[0][0] > window:
            buf.popleft()

    @staticmethod
    def _median(vals: list[float]) -> float:
        s = sorted(vals)
        n = len(s)
        mid = n // 2
        return s[mid] if n % 2 else 0.5 * (s[mid - 1] + s[mid])

    def update(self, t: float, hr: float) -> Layers | None:
        """Ingest one (unix_time, hr_bpm) sample; return a Layers snapshot.

        Returns None if the reading is an implausible artefact (dropped).
        """
        if not (HR_MIN_VALID <= hr <= HR_MAX_VALID):
            return None
        if self._t0 is None:
            self._t0 = t
        dt = 0.0 if self._last_t is None else max(0.0, t - self._last_t)
        self._last_t = t

        # --- pulse: trailing-median de-spike of the instantaneous beat -------
        self._pulse_buf.append((t, hr))
        self._trim(self._pulse_buf, t, PULSE_WINDOW_S)
        pulse_bpm = self._median([v for _, v in self._pulse_buf])

        # --- depth: slow EMA trend, normalized against an adaptive baseline --
        if self._hr_slow is None:
            self._hr_slow = pulse_bpm
        else:
            self._hr_slow += _ema_alpha(dt, DEPTH_TAU_S) * (pulse_bpm - self._hr_slow)

        # Adaptive low/high of the slow trend: track toward extremes fast,
        # forget slowly (so the 0..1 range follows the night causally).
        if self._slow_lo is None:
            self._slow_lo = self._slow_hi = self._hr_slow
        else:
            relax = _ema_alpha(dt, DEPTH_RANGE_TAU_S)
            # decay the envelope back toward the current trend...
            self._slow_lo += relax * (self._hr_slow - self._slow_lo)
            self._slow_hi += relax * (self._hr_slow - self._slow_hi)
            # ...but snap immediately to any new extreme.
            self._slow_lo = min(self._slow_lo, self._hr_slow)
            self._slow_hi = max(self._slow_hi, self._hr_slow)

        span = max(1e-6, self._slow_hi - self._slow_lo)
        depth = (self._slow_hi - self._hr_slow) / span      # low HR -> deep
        depth = min(1.0, max(0.0, depth))

        # --- restlessness: trailing HR variability + above-trend spikes ------
        self._rest_buf.append((t, hr))
        self._trim(self._rest_buf, t, REST_WINDOW_S)
        vals = [v for _, v in self._rest_buf]
        if len(vals) >= 2:
            mean = sum(vals) / len(vals)
            std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
        else:
            std = 0.0
        var_term = std / REST_FULL_SCALE
        spike_term = max(0.0, hr - self._hr_slow) / SPIKE_BPM
        restlessness = min(1.0, max(var_term, 0.6 * spike_term))

        # --- pulse tempo: instantaneous beat vs. the adaptive HR envelope ----
        pulse_tempo = min(1.0, max(0.0, (pulse_bpm - self._slow_lo) / span))

        warmup = (t - self._t0) < self._warmup_s
        return Layers(
            t=t, hr=hr, pulse_bpm=pulse_bpm, pulse_tempo=pulse_tempo,
            depth=depth, restlessness=restlessness, warmup=warmup,
        )
