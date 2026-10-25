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

What this tests, and what it does not: it probes how a RECEIVER reads the
values it is sent. It says nothing about how the tracker's physical axes map
onto our yaw, pitch and roll -- for that, wear the tracker and run
check_convention.py, which measures real gestures.

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
    """Set one named angle directly, and rotate the matching quaternion
    component. Deliberately not derived one from the other: doing that
    would make the test circular."""
    radians = math.radians(degrees)
    values = {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}
    values[axis] = radians
    qw, qx, qy, qz = quaternion_for(axis, degrees)
    values.update(qw=qw, qx=qx, qy=qy, qz=qz)
    return values


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--axis", choices=("yaw", "pitch", "roll", "all"),
                    default="yaw",
                    help="'all' sweeps each in turn, announcing them")
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
          f"{args.period:g}s per cycle, {args.cycles:g} cycles each")
    print(f"  {profile.raw_address}   {profile.raw_params}   -> {where}")
    print("  watch the plugin: which axis moves, and which way at the peak?\n")

    axes = ("yaw", "pitch", "roll") if args.axis == "all" else (args.axis,)
    for index, axis in enumerate(axes):
        if len(axes) > 1:
            announce(f"Now sweeping {axis}")
            print(f"\n--- {axis} ---")
        sweep(axis, args, profile, clients)
        if index < len(axes) - 1:
            time.sleep(1.0)

    print("\n  done. For each sweep, note which axis the plugin moved and")
    print("  which way at the peak -- that is the mapping.")
    return 0


def announce(text):
    if sys.platform == "darwin":
        import subprocess
        subprocess.run(["say", text], check=False)


def sweep(axis, args, profile, clients):
    start = time.monotonic()
    total = args.period * args.cycles
    try:
        while True:
            now = time.monotonic() - start
            if now >= total:
                break
            phase = 2 * math.pi * now / args.period
            angle = args.amplitude * math.sin(phase)
            for address, outgoing in profile.messages(values_for(axis, angle)):
                for client in clients:
                    client.send_message(address, outgoing)
            sys.stdout.write(f"\r  {axis} {angle:+7.1f} deg   ")
            sys.stdout.flush()
            time.sleep(1.0 / RATE)
    except KeyboardInterrupt:
        pass

    # leave it centred rather than wherever the sweep stopped
    for address, outgoing in profile.messages(values_for(axis, 0.0)):
        for client in clients:
            client.send_message(address, outgoing)
    print("\n  returned to centre")


if __name__ == "__main__":
    sys.exit(main())
