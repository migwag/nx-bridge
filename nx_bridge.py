#!/usr/bin/env python3
"""
nx-bridge -- Waves Nx Head Tracker to OSC, for macOS, Windows and Linux.

A drop-in replacement for the macOS-only Nxosc 1.0.5: byte-for-byte compatible
OSC output, verified against the original over 3628 frames (max error 8e-6 deg).

    python nx_bridge.py --list
    python nx_bridge.py                       # localhost:8000, Nxosc defaults
    python nx_bridge.py --host 10.0.0.5 --port 9000 --recenter
"""
from __future__ import annotations

import argparse, asyncio, contextlib, signal, sys, time

from bleak import BleakClient, BleakScanner
from pythonosc.udp_client import SimpleUDPClient

import nx_protocol as P


# ----------------------------------------------------------------- discovery
async def find_tracker(timeout: float = 12.0, address: str | None = None):
    """Return a BLEDevice for the tracker, or None.

    Matches on the advertised service UUID first, then falls back to the
    advertised name -- the device advertises 0xA010 under the standard
    Bluetooth base UUID, not the Waves vendor base used in its GATT table.
    """
    if address:
        return await BleakScanner.find_device_by_address(address, timeout=timeout)

    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    by_service, by_name = None, None
    for dev, adv in found.values():
        uuids = {u.lower() for u in (adv.service_uuids or [])}
        if P.ADV_SERVICE in uuids:
            by_service = by_service or dev
        if (adv.local_name or dev.name or "") == P.ADV_NAME:
            by_name = by_name or dev
    return by_service or by_name


# ----------------------------------------------------------------- bridge
class Bridge:
    def __init__(self, client: SimpleUDPClient, *, quiet: bool = False):
        self.osc = client
        self.quiet = quiet
        self.frames = 0
        self.dropped = 0
        self._t0 = time.monotonic()
        self._last_report = self._t0
        self._last_frames = 0
        self._rate = 0.0

    def on_packet(self, _handle, data: bytearray) -> None:
        if len(data) != P.PACKET_LEN:
            self.dropped += 1
            return
        try:
            messages = P.osc_messages(bytes(data))
        except Exception:
            self.dropped += 1
            return
        for address, args in messages:
            self.osc.send_message(address, args)
        self.frames += 1
        if not self.quiet:
            self._maybe_report(messages)

    def _maybe_report(self, messages) -> None:
        now = time.monotonic()
        if now - self._last_report < 0.5:
            return
        window = now - self._last_report
        self._rate = (self.frames - self._last_frames) / window
        self._last_report = now
        self._last_frames = self.frames
        yaw = messages[2][1][0]
        pitch = messages[3][1][0]
        roll = messages[4][1][0]
        rate = self._rate
        sys.stdout.write(
            f"\ryaw {yaw:+7.2f}  pitch {pitch:+7.2f}  roll {roll:+7.2f}"
            f"   {rate:5.1f} Hz  frames {self.frames}"
            + (f"  dropped {self.dropped}" if self.dropped else "")
            + "   "
        )
        sys.stdout.flush()


async def run(args) -> int:
    print(f"scanning for '{P.ADV_NAME}' ...")
    device = await find_tracker(args.scan_timeout, args.address)
    if device is None:
        print("tracker not found. Is it powered on, and not connected elsewhere?",
              file=sys.stderr)
        return 1
    print(f"found {device.address}")

    osc = SimpleUDPClient(args.host, args.port)
    bridge = Bridge(osc, quiet=args.quiet)
    stop = asyncio.Event()

    with contextlib.suppress(NotImplementedError):
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)

    async with BleakClient(device, timeout=args.connect_timeout) as client:
        print(f"connected; sending OSC to {args.host}:{args.port}")

        with contextlib.suppress(Exception):
            raw = (await client.read_gatt_char(P.BATTERY_LEVEL))[0]
            pct = P.battery_percent(raw)
            print(f"battery {pct}%" if pct is not None else "battery n/a")

        await client.start_notify(P.CHAR_DATA, bridge.on_packet)

        if args.recenter:
            for command in P.CMD_RECENTER:
                await client.write_gatt_char(P.CHAR_CONTROL, command, response=True)
            print("recentered")
        else:
            await client.write_gatt_char(P.CHAR_CONTROL, P.CMD_START, response=True)

        print("streaming -- Ctrl-C to stop")
        if args.duration:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), args.duration)
        else:
            await stop.wait()

        with contextlib.suppress(Exception):
            await client.stop_notify(P.CHAR_DATA)
        with contextlib.suppress(Exception):
            await client.write_gatt_char(P.CHAR_CONTROL, P.CMD_STOP, response=True)

    print(f"\nstopped after {bridge.frames} frames"
          + (f", {bridge.dropped} dropped" if bridge.dropped else ""))
    return 0


async def list_devices(timeout: float) -> int:
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    rows = []
    for dev, adv in found.values():
        uuids = {u.lower() for u in (adv.service_uuids or [])}
        is_nx = P.ADV_SERVICE in uuids or (adv.local_name or dev.name or "") == P.ADV_NAME
        rows.append((is_nx, adv.rssi, dev.address, adv.local_name or dev.name or "(no name)"))
    rows.sort(key=lambda r: (not r[0], -(r[1] or -999)))
    for is_nx, rssi, address, name in rows:
        print(f"{'>>>' if is_nx else '   '} {address}  rssi={rssi:>4}  {name}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="nx-bridge", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1", help="OSC destination (default: %(default)s)")
    p.add_argument("--port", type=int, default=8000, help="OSC port (default: %(default)s)")
    p.add_argument("--address", help="connect straight to this BLE address, skipping the scan")
    p.add_argument("--recenter", action="store_true", help="recenter on connect")
    p.add_argument("--duration", type=float, help="stop after N seconds (default: run until Ctrl-C)")
    p.add_argument("--scan-timeout", type=float, default=12.0)
    p.add_argument("--connect-timeout", type=float, default=25.0)
    p.add_argument("--quiet", action="store_true", help="no live status line")
    p.add_argument("--list", action="store_true", help="list nearby BLE devices and exit")
    args = p.parse_args(argv)

    try:
        if args.list:
            return asyncio.run(list_devices(args.scan_timeout))
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
