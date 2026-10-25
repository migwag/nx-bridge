#!/usr/bin/env python3
"""
Check our yaw/pitch/roll signs against Bridgehead's documented convention.

Bridgehead specifies (https://supperware.net/headtracker/profile-txt/):

    yaw    anticlockwise positive   -- turning your head LEFT
    pitch  upward positive          -- tipping your head UP
    roll   clockwise positive       -- tipping your head toward your RIGHT
                                       shoulder, seen from behind

This walks you through one gesture per axis, measures which value moved and
in which direction, and prints the parameter line that makes our output match.

    python3 check_convention.py

Wear the tracker as you normally would. It speaks the prompts, so you do not
need to read the screen while moving your head.
"""
from __future__ import annotations

import asyncio
import math
import subprocess
import sys
import time

try:
    import nxboot  # noqa: F401
except ImportError:
    pass

from bleak import BleakClient

import nx_protocol as P

HOLD = 2.5          # seconds held in each pose
SETTLE = 1.0        # ignored at the start of a pose, while you move

GESTURES = [
    ("yaw", "Turn your head to the LEFT and hold",
     "anticlockwise, which Bridgehead calls positive yaw"),
    ("pitch", "Tip your head UP and hold",
     "upward, which Bridgehead calls positive pitch"),
    ("roll", "Tip your head toward your RIGHT shoulder and hold",
     "clockwise from behind, which Bridgehead calls positive roll"),
]


def speak(text):
    print(f"\n>>> {text}")
    if sys.platform == "darwin":
        subprocess.run(["say", text], check=False)
    else:
        time.sleep(1.5)


class Collector:
    def __init__(self):
        self.samples = []
        self.recording = False

    def __call__(self, _handle, data: bytearray):
        if not self.recording or len(data) != P.PACKET_LEN:
            return
        a, b, c, w, _s0, _s1 = P.decode_packet(bytes(data))
        self.samples.append(P.derive(a, b, c, w))

    async def capture(self, seconds):
        self.samples.clear()
        self.recording = True
        await asyncio.sleep(SETTLE)
        self.samples.clear()            # drop the movement, keep the hold
        await asyncio.sleep(seconds)
        self.recording = False
        if not self.samples:
            raise RuntimeError("no packets arrived")
        return {k: sum(s[k] for s in self.samples) / len(self.samples)
                for k in ("yaw", "pitch", "roll")}


def wrap_deg(radians):
    d = math.degrees(radians)
    return (d + 180.0) % 360.0 - 180.0


async def main():
    from nx_bridge import find_tracker
    print("scanning ...")
    device = await find_tracker(12.0)
    if device is None:
        print("tracker not found -- power it on and quit anything using it",
              file=sys.stderr)
        return 1

    collector = Collector()
    async with BleakClient(device, timeout=25.0) as client:
        await client.start_notify(P.CHAR_DATA, collector)
        await client.write_gatt_char(P.CHAR_CONTROL, P.CMD_START, response=True)
        print(f"connected to {device.address}")

        speak("Face straight forward and hold still.")
        neutral = await collector.capture(HOLD)

        results = {}
        for axis, prompt, meaning in GESTURES:
            speak(prompt)
            posed = await collector.capture(HOLD)
            deltas = {k: wrap_deg(posed[k] - neutral[k])
                      for k in ("yaw", "pitch", "roll")}
            results[axis] = deltas
            speak("Return to centre.")
            await collector.capture(1.2)

        await client.write_gatt_char(P.CHAR_CONTROL, P.CMD_STOP, response=True)
        await client.stop_notify(P.CHAR_DATA)

    print("\n" + "=" * 62)
    print("measured change from neutral, in degrees")
    print("=" * 62)
    print(f"{'gesture':24s} {'yaw':>9s} {'pitch':>9s} {'roll':>9s}")
    for axis, _p, _m in GESTURES:
        d = results[axis]
        print(f"{axis + ' (expect +)':24s} "
              f"{d['yaw']:+9.1f} {d['pitch']:+9.1f} {d['roll']:+9.1f}")

    print("\n" + "=" * 62)
    signs = {}
    for axis, _p, meaning in GESTURES:
        d = results[axis]
        moved = max(d, key=lambda k: abs(d[k]))
        value = d[axis]
        if abs(value) < 5.0:
            verdict = f"inconclusive -- only {value:+.1f} deg, move further"
        elif moved != axis:
            verdict = (f"PROBLEM: '{moved}' moved more ({d[moved]:+.1f}) "
                       f"than '{axis}' ({value:+.1f}) -- axes may be swapped")
        elif value > 0:
            verdict = f"matches Bridgehead ({value:+.1f} deg)"
        else:
            verdict = f"INVERTED relative to Bridgehead ({value:+.1f} deg)"
        signs[axis] = "-" if (abs(value) >= 5.0 and value < 0) else ""
        print(f"{axis:6s} {verdict}")
        print(f"       you moved {meaning}")

    line = ",".join(f"{signs[a]}{a}" for a in ("yaw", "pitch", "roll"))
    print("\n" + "=" * 62)
    if any(signs.values()):
        print("To match Bridgehead, use this parameter line:\n")
        print(f"    {line}\n")
        print("Paste it into the Parameters field in the OSC tab, or edit")
        print("profiles.txt and press Reload.")
    else:
        print("All three already match Bridgehead's convention.")
        print(f"Parameter line unchanged:  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
