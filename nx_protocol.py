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


# What each message carries, in order. Used to label the transform UI and to
# size the per-component settings.
COMPONENT_LABELS = {
    "quaternion": ("x", "y", "z", "w"),
    "xyz":        ("x", "y", "z"),
    "yaw":        ("yaw",),
    "pitch":      ("pitch",),
    "roll":       ("roll",),
}

# Messages carrying angles: offsets are meaningful and results are wrapped.
# Offsetting a quaternion component is not -- it would break normalisation --
# so the quaternion gets reordering and sign flips only.
ANGLE_KEYS = ("xyz", "yaw", "pitch", "roll")


def default_transform(key):
    n = len(COMPONENT_LABELS[key])
    return {"order": list(range(n)), "signs": [1] * n, "offsets": [0.0] * n}


def default_transforms():
    return {k: default_transform(k) for k in MESSAGE_KEYS}


def _wrap(value, degrees):
    """Fold an angle back into +-180 degrees (or +-pi)."""
    limit = 180.0 if degrees else math.pi
    return (value + limit) % (2 * limit) - limit


def apply_transform(key, values, transform, degrees=True):
    """Reorder, negate and offset one message's values.

    order[i] says which source component lands in output slot i, so an order
    of [3, 0, 1, 2] turns xyzw into wxyz.
    """
    if not transform:
        return list(values)
    n = len(values)
    order = transform.get("order") or list(range(n))
    signs = transform.get("signs") or [1] * n
    offsets = transform.get("offsets") or [0.0] * n

    out = []
    for slot in range(n):
        src = order[slot] if slot < len(order) else slot
        if not 0 <= src < n:
            src = slot
        v = values[src] * (signs[slot] if slot < len(signs) else 1)
        if key in ANGLE_KEYS:
            v = _wrap(v + (offsets[slot] if slot < len(offsets) else 0.0), degrees)
        out.append(v)
    return out


def compute(buf):
    """10 raw bytes -> every derived value, so callers need not repeat the math.

    Angles are radians here; convert at the edge.
    """
    a, b, c, w, status0, status1 = decode_packet(buf)
    e4 = euler_mode4(a, b, c, w)
    e6 = euler_mode6(a, b, c, w)
    return {
        "quaternion": (a, b, c, w),
        "xyz":   (e6[0], e6[2], e6[1]),
        "yaw":    e4[2],
        "pitch": -e4[1],
        "roll":  -e4[0],
        "status": (status0, status1),
    }


def osc_messages(buf, addresses=None, enabled=None, degrees=True,
                 transforms=None):
    """10 raw bytes -> list of (address, [args]).

    With no arguments the output is exactly what Nxosc 1.0.5 emits. Pass
    `addresses` to rename messages, `enabled` (an iterable of keys) to send
    only some of them, degrees=False for radians, or `transforms` to reorder,
    negate or offset the values of individual messages.
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
    out = []
    for k in keep:
        values = args[k]
        if transforms:
            values = apply_transform(k, values, transforms.get(k), degrees)
        out.append((addr[k], values))
    return out
