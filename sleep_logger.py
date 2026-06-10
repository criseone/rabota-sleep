#!/usr/bin/env python3
"""Log live heart rate from a Garmin (or any BLE HR-broadcast) watch to CSV.

Path A of the rabota sleep pipeline: the watch broadcasts the standard BLE
Heart Rate Service (~1 Hz). This connects, decodes each measurement, and
appends it to a CSV. It auto-reconnects so it can run unattended overnight.

Usage:
    python sleep_logger.py --scan              # find your watch's address
    python sleep_logger.py                     # connect to any HR broadcaster
    python sleep_logger.py --name Forerunner   # match by name
    python sleep_logger.py --address <addr>    # connect directly
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import signal
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakClient, BleakScanner

# Standard BLE Heart Rate Service / Measurement characteristic.
HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

CSV_HEADER = ["iso_time", "unix_time", "hr_bpm", "rr_ms", "sensor_contact"]
_CONTACT = {0: "unsupported", 1: "unsupported", 2: "no_contact", 3: "contact"}


def parse_hr_measurement(data: bytes) -> tuple[int, list[float], str]:
    """Decode a Heart Rate Measurement (0x2A37) packet.

    Byte 0 is a flags bitfield (BLE HR spec): bit0 = HR is uint16 (else uint8),
    bits1-2 = sensor-contact status, bit3 = energy-expended field present,
    bit4 = RR-intervals present. The fields that follow appear in that order.
    """
    flags = data[0]
    hr_is_uint16 = flags & 0x01
    contact = _CONTACT[(flags >> 1) & 0x03]
    energy_present = (flags >> 3) & 0x01
    rr_present = (flags >> 4) & 0x01

    offset = 1
    if hr_is_uint16:
        hr = int.from_bytes(data[offset:offset + 2], "little")
        offset += 2
    else:
        hr = data[offset]
        offset += 1

    if energy_present:
        offset += 2  # skip energy expended (kJ); unused here

    rr_ms: list[float] = []
    if rr_present:
        while offset + 2 <= len(data):
            raw = int.from_bytes(data[offset:offset + 2], "little")
            rr_ms.append(round(raw * 1000 / 1024, 1))  # 1/1024 s units -> ms
            offset += 2

    return hr, rr_ms, contact


class HeartRateLogger:
    """Appends decoded HR readings to a CSV and prints a live summary."""

    def __init__(self, csv_path: Path):
        self.csv_path = csv_path
        self._fh = None
        self._writer = None
        self.count = 0
        self.hr_min: int | None = None
        self.hr_max: int | None = None
        self._hr_sum = 0

    def open(self) -> None:
        is_new = not self.csv_path.exists() or self.csv_path.stat().st_size == 0
        self._fh = self.csv_path.open("a", newline="")
        self._writer = csv.writer(self._fh)
        if is_new:
            self._writer.writerow(CSV_HEADER)
            self._fh.flush()

    def close(self) -> None:
        if self._fh:
            self._fh.flush()
            self._fh.close()

    def record(self, data: bytes) -> None:
        hr, rr_ms, contact = parse_hr_measurement(data)
        now = datetime.now(timezone.utc).astimezone()
        self._writer.writerow([
            now.isoformat(timespec="milliseconds"),
            f"{now.timestamp():.3f}",
            hr,
            ";".join(str(x) for x in rr_ms),
            contact,
        ])
        self._fh.flush()  # flush every reading so an overnight crash loses nothing

        self.count += 1
        self._hr_sum += hr
        self.hr_min = hr if self.hr_min is None else min(self.hr_min, hr)
        self.hr_max = hr if self.hr_max is None else max(self.hr_max, hr)
        mean = self._hr_sum / self.count
        rr_str = f"  rr={rr_ms}" if rr_ms else ""
        print(f"[{now:%H:%M:%S}] HR {hr:3d} bpm  contact={contact:11}  "
              f"n={self.count} mean={mean:.1f} min={self.hr_min} max={self.hr_max}{rr_str}",
              flush=True)


def default_output_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(__file__).parent / "data" / f"hr_{stamp}.csv"


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def find_device(name: str, address: str, scan_timeout: float):
    if address:
        print(f"Looking for device {address} ...", flush=True)
        return await BleakScanner.find_device_by_address(address, timeout=scan_timeout)

    print(f"Scanning {scan_timeout:.0f}s for a heart-rate broadcaster ...", flush=True)
    found = await BleakScanner.discover(timeout=scan_timeout, return_adv=True)
    candidates = []
    for dev, adv in found.values():
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        has_hr = HR_SERVICE_UUID in uuids
        dev_name = dev.name or adv.local_name or ""
        if name and name.lower() not in dev_name.lower():
            continue
        if name or has_hr:
            candidates.append((has_hr, dev, dev_name))

    candidates.sort(key=lambda c: not c[0])  # HR-advertising devices first
    if not candidates:
        return None
    has_hr, dev, dev_name = candidates[0]
    print(f"Found {dev_name or '(no name)'} [{dev.address}]  "
          f"hr_service={'yes' if has_hr else 'no'}", flush=True)
    return dev


async def scan_only(scan_timeout: float) -> None:
    print(f"Scanning {scan_timeout:.0f}s ...\n", flush=True)
    found = await BleakScanner.discover(timeout=scan_timeout, return_adv=True)
    if not found:
        print("No BLE devices found. Is Bluetooth on and the watch broadcasting?")
        return
    rows = []
    for dev, adv in found.values():
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        rows.append((adv.rssi or -999, dev.address,
                     dev.name or adv.local_name or "(unknown)",
                     HR_SERVICE_UUID in uuids))
    rows.sort(reverse=True)
    print(f"{'ADDRESS':38} {'RSSI':>5}  {'HR':>3}  NAME")
    for rssi, addr, dev_name, has_hr in rows:
        print(f"{addr:38} {rssi:>5}  {'yes' if has_hr else 'no':>3}  {dev_name}")
    print("\nUse your watch's ADDRESS with --address, or a name substring with --name.")


async def run(args, stop: asyncio.Event) -> None:
    out = Path(args.output) if args.output else default_output_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    logger = HeartRateLogger(out)
    logger.open()
    print(f"Logging to {out}", flush=True)

    try:
        while not stop.is_set():
            device = await find_device(args.name, args.address, args.scan_timeout)
            if device is None:
                print("No matching device — is HR broadcast enabled? Retrying ...", flush=True)
                await _sleep_or_stop(stop, args.reconnect_delay)
                continue

            disconnected = asyncio.Event()
            try:
                async with BleakClient(
                    device, disconnected_callback=lambda _c: disconnected.set()
                ) as client:
                    await client.start_notify(
                        HR_MEASUREMENT_UUID, lambda _s, d: logger.record(bytes(d))
                    )
                    print("Connected. Receiving heart rate ... (Ctrl+C to stop)", flush=True)
                    while client.is_connected and not stop.is_set() and not disconnected.is_set():
                        await asyncio.sleep(0.5)
            except Exception as exc:
                print(f"Connection error: {exc}", flush=True)

            if not stop.is_set():
                print(f"Disconnected. Reconnecting in {args.reconnect_delay:.0f}s ...", flush=True)
                await _sleep_or_stop(stop, args.reconnect_delay)
    finally:
        logger.close()
        print(f"\nStopped. {logger.count} readings saved to {out}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Log BLE heart rate to CSV (rabota sleep pipeline, Path A).")
    p.add_argument("--scan", action="store_true", help="List nearby BLE devices and exit")
    p.add_argument("--name", default="", help="Substring of the device name to match (e.g. 'Forerunner')")
    p.add_argument("--address", default="", help="Connect directly to this BLE address/UUID (skips scan)")
    p.add_argument("--output", default="", help="CSV output path (default: ./data/hr_<timestamp>.csv)")
    p.add_argument("--scan-timeout", type=float, default=10.0, help="Seconds to scan (default 10)")
    p.add_argument("--reconnect-delay", type=float, default=5.0, help="Seconds between reconnect attempts (default 5)")
    return p


async def _amain(args) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    await run(args, stop)


def main() -> None:
    args = build_parser().parse_args()
    if args.scan:
        asyncio.run(scan_only(args.scan_timeout))
    else:
        asyncio.run(_amain(args))


if __name__ == "__main__":
    main()
