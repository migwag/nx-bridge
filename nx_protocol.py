"""
Waves Nx Head Tracker protocol — pure decode logic, no I/O.

Derived by reverse engineering Nxosc.app 1.0.5 (com.audiooo.Nxosc).
Every constant below is traceable to a specific instruction in that binary;
see PROTOCOL.md for the derivation.
"""
import math, struct

# ---------------------------------------------------------------- BLE identifiers
BASE          = "-5761-7665-7341-7564696f4c74"   # ASCII tail spells "WavesAudioLt"
SERVICE_MAIN  = "0000a010" + BASE
CHAR_DATA     = "0000a015" + BASE   # read, notify  -> 10-byte orientation packets @50 Hz
CHAR_CONTROL  = "0000a011" + BASE   # read, write   -> command channel
CHAR_NAME     = "0000a018" + BASE   # device name
BATTERY_LEVEL = "00002a19-0000-1000-8000-00805f9b34fb"

# Advertisement uses the 16-bit short form of 0xA010, not the Waves base:
ADV_SERVICE   = "0000a010-0000-1000-8000-00805f9b34fb"
ADV_NAME      = "Nx Tracker"

# ---------------------------------------------------------------- commands
# From -[NxoscAppDelegate didDiscoverCharacteristicsForService:] and
# -[NxoscAppDelegate caribButtonPressed:]: 5-byte payloads, write WITH response.
CMD_START     = bytes([0x32, 0x00, 0x00, 0x00, 0x01])
CMD_STOP      = bytes([0x32, 0x00, 0x00, 0x00, 0x00])
# Recenter = STOP then START (that is literally what the calibrate button does).
CMD_RECENTER  = (CMD_STOP, CMD_START)

# ---------------------------------------------------------------- packet decode
PACKET_LEN = 10
_SCALE = 2.0 / 32767.0       # the binary divides by 32767.0f then doubles

def decode_packet(buf):
    """10 raw bytes -> (x, y, z, w, status0, status1).

    Wire layout: 4x int16 little-endian (Q14-ish: +-16383.5 == +-1.0), then 2 status bytes.
    The returned x,y,z,w are already in Nxosc's output frame, i.e. the axis
    remap (q0, q2, -q1, q3) that -[updateGyroData:] applies before sending
    /nxosc/quaternion. Components form a unit quaternion.
    """
    if len(buf) != PACKET_LEN:
        raise ValueError(f"expected {PACKET_LEN} bytes, got {len(buf)}")
    q0, q1, q2, q3 = struct.unpack_from("<4h", buf, 0)
    a = q0 * _SCALE
    b = q2 * _SCALE
    c = -q1 * _SCALE          # note the negation
    w = q3 * _SCALE
    return a, b, c, w, buf[8], buf[9]

def _threeaxisrot(r11, r12, r21, r31, r32):
    """Mirrors _threeaxisrot in the binary, including the asin clamp."""
    return (
        math.atan2(r31, r32),
        math.asin(max(-1.0, min(1.0, r21))),
        math.atan2(r11, r12),
    )

def euler_mode4(a, b, c, w):
    """quaternion2Euler(..., 4) — the order Nxosc uses for /SceneRotator/*."""
    return _threeaxisrot(
        2.0 * (a * c + w * b),              # r11
        w * w - a * a - b * b + c * c,      # r12
        2.0 * (a * w - b * c),              # r21
        2.0 * (a * b + w * c),              # r31
        w * w - a * a + b * b - c * c,      # r32
    )

def euler_mode6(a, b, c, w):
    """quaternion2Euler(..., 6) — the order Nxosc uses for /nxosc/xyz."""
    return _threeaxisrot(
        2.0 * (b * w - a * c),              # r11
        w * w + a * a - b * b - c * c,      # r12
        2.0 * (a * b + w * c),              # r21
        2.0 * (a * w - b * c),              # r31
        w * w - a * a + b * b - c * c,      # r32
    )

def battery_percent(raw: int):
    """Interpret the Battery Level byte the way Nxosc does.

    From -[NxoscAppDelegate updateBatteryData:]:
      bit 7 set (>=128) -> no reading available
      101..127          -> clamped and displayed as "100 %"
      0..100            -> the value itself
    Returns an int 0-100, or None when no reading is available.
    """
    if raw & 0x80:
        return None
    return min(raw, 100)


DEG = 180.0 / math.pi

# Message identities, in the order Nxosc 1.0.5 sends them. The addresses are
# defaults -- callers may rename them -- but the keys and the value each key
# carries are fixed, because downstream tools key off the meaning.
MESSAGE_KEYS = ("quaternion", "xyz", "yaw", "pitch", "roll")

DEFAULT_ADDRESSES = {
    "quaternion": "/nxosc/quaternion",
    "xyz":        "/nxosc/xyz",
    "yaw":        "/SceneRotator/yaw",
    "pitch":      "/SceneRotator/pitch",
    "roll":       "/SceneRotator/roll",
}


def derive(a, b, c, w):
    """Quaternion -> every value we expose. Angles in radians."""
    e4 = euler_mode4(a, b, c, w)
    e6 = euler_mode6(a, b, c, w)
    return {
        "quaternion": (a, b, c, w),
        "xyz":   (e6[0], e6[2], e6[1]),
        "yaw":    e4[2],
        "pitch": -e4[1],
        "roll":  -e4[0],
    }


def compute(buf):
    """10 raw bytes -> every derived value, so callers need not repeat the math.

    Angles are radians here; convert at the edge.
    """
    a, b, c, w, status0, status1 = decode_packet(buf)
    values = derive(a, b, c, w)
    values["status"] = (status0, status1)
    return values


def bridgehead_quaternion(a, b, c, w):
    """Our component frame -> Supperware Bridgehead's.

    Fixed empirically: in Bridgehead the parameter line

        qw,qy,-qx,qz

    produces the same output as our old naming's

        qw,-qz,-qx,qy

    Equating them term by term gives qw = w, qx = a, qy = -c, qz = b, i.e.
    our y and z are swapped with a sign flip -- the usual Z-up against Y-up
    difference.
    """
    return w, a, -c, b


def bridgehead_angles(qw, qx, qy, qz):
    """Yaw/pitch/roll from a Bridgehead-frame quaternion, in radians.

    The standard intrinsic Z-Y-X decomposition, which gives Bridgehead's
    documented directions: yaw anticlockwise positive, pitch upward
    positive, roll clockwise positive.
    """
    yaw = math.atan2(2.0 * (qw * qz + qx * qy),
                     1.0 - 2.0 * (qy * qy + qz * qz))
    pitch = math.asin(max(-1.0, min(1.0, 2.0 * (qw * qy - qz * qx))))
    roll = math.atan2(2.0 * (qw * qx + qy * qz),
                      1.0 - 2.0 * (qx * qx + qy * qy))
    return yaw, pitch, roll


def profile_values_from(values):
    """Derived values -> the names a Bridgehead profile can reference.

    Everything here is in Bridgehead's frame, so a profile written for
    Bridgehead behaves the same in both applications. The Nxosc-compatible
    output lives in osc_messages() and is unaffected.
    """
    a, b, c, w = values["quaternion"]
    qw, qx, qy, qz = bridgehead_quaternion(a, b, c, w)
    yaw, pitch, roll = bridgehead_angles(qw, qx, qy, qz)
    return {"yaw": yaw, "pitch": pitch, "roll": roll,
            "qw": qw, "qx": qx, "qy": qy, "qz": qz}


def profile_values(buf):
    """10 raw bytes -> the named values a Bridgehead profile can reference."""
    return profile_values_from(compute(buf))


class Smoother:
    """Exponential low-pass on the quaternion.

    Angles are smoothed through the quaternion rather than individually:
    filtering yaw as a number would swing it the long way round whenever it
    crosses +-180 degrees. Blending is normalised lerp, which is close enough
    to slerp at the small step a 50 Hz stream produces and much cheaper.

    `tau` is the time constant in seconds: after tau, roughly 63% of a step
    change has been followed. Zero disables smoothing.
    """

    def __init__(self, tau=0.0):
        self.tau = max(0.0, float(tau))
        self._state = None
        self._last = None

    def reset(self):
        self._state = None
        self._last = None

    def push(self, quat, now):
        if self.tau <= 0.0:
            self._state = quat
            self._last = now
            return quat
        if self._state is None or self._last is None or now <= self._last:
            self._state = quat
            self._last = now
            return quat

        dt = now - self._last
        self._last = now
        alpha = 1.0 - math.exp(-dt / self.tau)

        prev = self._state
        # q and -q are the same rotation; without this the filter can take
        # the long way round and lurch.
        if sum(p * c for p, c in zip(prev, quat)) < 0.0:
            quat = tuple(-c for c in quat)

        blended = tuple(p + (c - p) * alpha for p, c in zip(prev, quat))
        norm = math.sqrt(sum(c * c for c in blended))
        if norm < 1e-9:
            self._state = quat
            return quat
        self._state = tuple(c / norm for c in blended)
        return self._state


def osc_messages(buf, addresses=None, enabled=None, degrees=True):
    """10 raw bytes -> list of (address, [args]).

    With no arguments the output is exactly what Nxosc 1.0.5 emits. Pass
    `addresses` to rename messages, `enabled` (an iterable of keys) to send
    only some of them, or degrees=False to send angles in radians.

    The GUI does not use this -- it builds messages from a Bridgehead profile
    via nx_profile. This is the CLI's path and the one validate.py checks.
    """
    v = compute(buf)
    addr = dict(DEFAULT_ADDRESSES)
    if addresses:
        addr.update(addresses)
    keep = MESSAGE_KEYS if enabled is None else tuple(
        k for k in MESSAGE_KEYS if k in set(enabled))
    scale = DEG if degrees else 1.0

    args = {
        "quaternion": list(v["quaternion"]),
        "xyz":        [x * scale for x in v["xyz"]],
        "yaw":        [v["yaw"] * scale],
        "pitch":      [v["pitch"] * scale],
        "roll":       [v["roll"] * scale],
    }
    return [(addr[k], args[k]) for k in keep]
