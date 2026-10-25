#!/usr/bin/env python3
"""
Send a synthetic rotation so you can see which way a plugin turns.

No tracker needed. It sweeps one axis at a time through a clean, slow arc
and sends it using any profile line, so you can watch a binauraliser and
work out the convention it expects.

    python3 osc_sweep.py --axis yaw
    python3 osc_sweep.py --axis pitch --params qw,qx,qy,qz --address /quaternion
    python3 osc_sweep.py --axis roll --params yaw,pitch,roll --address "/[yaw,pitch,roll]"
    python3 osc_sweep.py --list

Read it like this: start the sweep, watch the plugin, and note which way the
scene moves and on which axis. Repeat for each of the three axes. That tells
you the permutation and signs the plugin wants, which you then write as a
profile for it.

Axes follow Bridgehead's convention, which is what our profiles now emit:
yaw is anticlockwise positive, pitch upward positive, roll clockwise
positive.
"""
from __future__ import annotations

import argparse
import math
import sys
import time

try:
    import nxboot  # noqa: F401
except ImportError:
    pass

import nx_profile as NP
import nx_protocol as P

RATE = 50.0


def quaternion_for(axis, degrees):
    """A Bridgehead-frame quaternion rotating `degrees` about one axis."""
    half = math.radians(degrees) / 2.0
    s, c = math.sin(half), math.cos(half)
    vec = {"roll": (s, 0.0, 0.0),      # about x
           "pitch": (0.0, s, 0.0),     # about y
           "yaw": (0.0, 0.0, s)}[axis]
    return (c,) + vec                  # qw, qx, qy, qz


def values_for(axis, degrees):
    qw, qx, qy, qz = quaternion_for(axis, degrees)
    yaw, pitch, roll = P.bridgehead_angles(qw, qx, qy, qz)
    return {"yaw": yaw, "pitch": pitch, "roll": roll,
            "qw": qw, "qx": qx, "qy": qy, "qz": qz}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--axis", choices=("yaw", "pitch", "roll"), default="yaw")
    ap.add_argument("--amplitude", type=float, default=60.0,
                    help="peak angle in degrees (default: %(default)s)")
    ap.add_argument("--period", type=float, default=8.0,
                    help="seconds per full back-and-forth (default: %(default)s)")
    ap.add_argument("--cycles", type=float, default=3.0)
    ap.add_argument("--address", default="/[yaw,pitch,roll]")
    ap.add_argument("--params", default="yaw,pitch,roll")
    ap.add_argument("--dest", default="local 8000")
    ap.add_argument("--profile", help="use a named profile from profiles.txt")
    ap.add_argument("--list", action="store_true", help="list profiles and exit")
    args = ap.parse_args(argv)

    if args.list:
        import nxosc_reborn as R
        for prof in R.load_profiles()[0]:
            print(f"  {prof.name}")
            print(f"      {prof.raw_address}   {prof.raw_params}")
        return 0

    if args.profile:
        import nxosc_reborn as R
        profiles = {p.name: p for p in R.load_profiles()[0]}
        if args.profile not in profiles:
            print(f"no profile named {args.profile!r}; try --list", file=sys.stderr)
            return 1
        profile = profiles[args.profile]
    else:
        try:
            profile = NP.parse_profile_block(
                ["sweep", args.address, args.params] +
                [d.strip() for d in args.dest.split(",") if d.strip()])
        except NP.ProfileError as exc:
            print(f"bad profile: {exc}", file=sys.stderr)
            return 1

    from pythonosc.udp_client import SimpleUDPClient
    clients = [SimpleUDPClient(h, p) for h, p in profile.destinations]

    where = ", ".join(f"{h}:{p}" for h, p in profile.destinations)
    print(f"sweeping {args.axis} +-{args.amplitude:g} deg, "
          f"{args.period:g}s per cycle, {args.cycles:g} cycles")
    print(f"  {profile.raw_address}   {profile.raw_params}   -> {where}")
    print("  watch the plugin: which axis moves, and which way at the peak?\n")

    start = time.monotonic()
    total = args.period * args.cycles
    try:
        while True:
            now = time.monotonic() - start
            if now >= total:
                break
            phase = 2 * math.pi * now / args.period
            angle = args.amplitude * math.sin(phase)
            for address, outgoing in profile.messages(values_for(args.axis, angle)):
                for client in clients:
                    client.send_message(address, outgoing)
            sys.stdout.write(f"\r  {args.axis} {angle:+7.1f} deg   ")
            sys.stdout.flush()
            time.sleep(1.0 / RATE)
    except KeyboardInterrupt:
        pass

    # leave it centred rather than wherever the sweep stopped
    for address, outgoing in profile.messages(values_for(args.axis, 0.0)):
        for client in clients:
            client.send_message(address, outgoing)
    print("\n  returned to centre")
    return 0


if __name__ == "__main__":
    sys.exit(main())
