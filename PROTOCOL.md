# Waves Nx Head Tracker — BLE protocol

Reverse engineered from **[Nxosc](https://www.audiooo.com/nxosc) 1.0.5** by
[Katsuhiro Chiba](https://www.audiooo.com/) (`com.audiooo.Nxosc`, 2017), plus
live capture from a physical tracker (HW v4.4, FW v100, SW "A v1.30 B v1.13").

This document exists because of his work. Nxosc solved the problem first, and
what is written down here was learned from how it did so -- documented for
interoperability, so the tracker keeps working on platforms and systems Nxosc
does not reach.
Every claim below is either read off the wire or traced to an instruction address in
the app's arm64 slice.

## Discovery

| | |
|---|---|
| Advertised name | `Nx Tracker` |
| Advertised service | `0000a010-0000-1000-8000-00805f9b34fb` (16-bit short form of `0xA010`) |
| Manufacturer data | company `0x00AE`, payload `57617665734e5830303100` = `"WavesNX001\0"` |

Note the advertisement uses the **standard** Bluetooth base UUID, while the GATT table
uses a Waves vendor base. Scan filters must account for this.

## Vendor base UUID

    0000XXXX-5761-7665-7341-7564696F4C74
              ^^^^^^^^^^^^^^^^^^^^^^^^^^
              ASCII "WavesAudioLt"

## GATT table (as enumerated from the device)

### Service `A010` — head tracking
| Char | Handle | Properties | Purpose |
|---|---|---|---|
| `A015` | 13 | read, notify | orientation stream, 10 bytes @ 50 Hz |
| `A011` | 16 | read, write | control channel; idle value `03 01 0A 00 00` |
| `A018` | 18 | read, write, notify | device name, `"Nx Tracker"` padded to 16 bytes |

### Service `A050`
| Char | Handle | Properties | Observed |
|---|---|---|---|
| `A051` | 22 | read, write | empty |
| `A052` | 24 | read, notify | `00` |

### Service `A030` — presumed DFU (not used by Nxosc; left alone)
| Char | Handle | Properties |
|---|---|---|
| `A031` | 28 | notify, write |
| `A032` | 31 | write-without-response |

### Standard services
- `0x180F` Battery → `0x2A19` Battery Level, 1 byte percent. Nxosc reads this, not a
  vendor characteristic (`-[NxoscAppDelegate updateBatteryData:]`).
- `0x180A` Device Information → Manufacturer `"Waves Audio"`, Model `"1"`,
  HW `"v4.4"`, FW `"v100"`, SW `"A v1.30 B v1.13"`.

## Commands — write to `A011`, 5 bytes, write WITH response

| Command | Bytes | Source |
|---|---|---|
| start stream | `32 00 00 00 01` | `didDiscoverCharacteristicsForService:` @ `0x100004838`-`0x100004870` |
| stop stream | `32 00 00 00 00` | `caribButtonPressed:` first write @ `0x100003bc4`-`0x100003be0` |
| recenter | stop, then start | `caribButtonPressed:` issues both in sequence |

Subscribing to `A015` alone yields **no data** — the start command is required.
Recentering is literally a stop followed by a start.

## Orientation packet — `A015` notify, 10 bytes, 50 Hz

    offset 0-1  int16 LE  q0
    offset 2-3  int16 LE  q1
    offset 4-5  int16 LE  q2
    offset 6-7  int16 LE  q3   (scalar / w; approx +-16383 at rest)
    offset 8    uint8     status, observed 0x00 while streaming
    offset 9    uint8     status, observed 0x03 while streaming

Each component is scaled `value / 32767.0 * 2.0` (constant `32767.0f` at
`0x100005d98`; the doubling is an `fadd s1, s1, s1`). Equivalently +-16383.5 maps to
+-1.0. Verified over 1004 packets: mean |norm - 1| = 2.6e-5, i.e. a unit quaternion
to within int16 quantization.

A read of `A015` while idle returns `00 00 00 00 00 00 01 00 FF FF` — status bytes
`FF FF` mark "not streaming".

## Axis remap applied by Nxosc

`-[NxoscAppDelegate updateGyroData:]` reorders and negates before doing anything else:

    a = q0
    b = q2
    c = -q1      <-- negated
    w = q3

`/nxosc/quaternion` therefore carries `(q0, q2, -q1, q3)`, not the wire order.

## Euler conversion

`quaternion2Euler(a, b, c, w, mode)` is a 12-case jump table (`0x100003278`,
table at `0x100005d68`). Nxosc calls it with **mode 6** (for `/nxosc/xyz`) and
**mode 4** (for `/SceneRotator/*`); the mode-0 result is computed but unused.

All cases funnel into `_threeaxisrot(r11, r12, r21, r31, r32)` @ `0x100003208`:

    res[0] = atan2(r31, r32)
    res[1] = asin(clamp(r21, -1, 1))
    res[2] = atan2(r11, r12)

### mode 4 (block `0x1000033b0`)
    r11 = 2(ac + wb)
    r12 = w^2 - a^2 - b^2 + c^2
    r21 = 2(aw - bc)
    r31 = 2(ab + wc)
    r32 = w^2 - a^2 + b^2 - c^2

### mode 6 (block `0x100003444`)
    r11 = 2(bw - ac)
    r12 = w^2 + a^2 - b^2 - c^2
    r21 = 2(ab + wc)
    r31 = 2(aw - bc)
    r32 = w^2 - a^2 + b^2 - c^2

## OSC output

Default destination `localhost:8000` (prefs keys `OSC_Destination`, `OSC_Port`).
Five messages per packet, in this order, all float32:

| Address | Args | Value |
|---|---|---|
| `/nxosc/quaternion` | 4 | `a, b, c, w` |
| `/nxosc/xyz` | 3 | `e6[0], e6[2], e6[1]` in degrees |
| `/SceneRotator/yaw` | 1 | `+e4[2]` in degrees |
| `/SceneRotator/pitch` | 1 | `-e4[1]` in degrees |
| `/SceneRotator/roll` | 1 | `-e4[0]` in degrees |

The sign flips on pitch and roll come from dividing by the constant `-pi` at
`0x100005d90` instead of `+pi` at `0x100005d80`. `/SceneRotator/*` is the
IEM SceneRotator convention.

Note `/nxosc/xyz` sends the mode-6 angles in the order **0, 2, 1** — not 0, 1, 2.

## Battery

Nxosc reads the standard `0x2A19` Battery Level and interprets it in three bands
(`-[NxoscAppDelegate updateBatteryData:]` @ `0x100003f70`):

| Raw byte | Behaviour |
|---|---|
| bit 7 set (>= 128) | no reading available (1-char placeholder shown) |
| 101 .. 127 | clamped, displayed as `"100 %"` |
| 0 .. 100 | displayed as `"<n> %"` |

Our tracker reported `117` on one read, so the clamp is not hypothetical --
a naive `f"{raw}%"` prints "117%".

## A note on UUID short forms

Nxosc builds its CBUUIDs from *short* 4-character strings for standard
attributes -- `A010`, `1800`, `180A`, `180F`, `2A00`, `2A19`, `2A29` -- and
full 36-character strings for the vendor characteristics. Because it scans
with `CBUUID(string: "A010")`, CoreBluetooth expands it against the standard
Bluetooth base UUID, which is what the device actually advertises. A scanner
that filters on the *Waves* base UUID will never see the advertisement.

## Verification

- 1004 packets at rest: mean |norm - 1| = 2.6e-5 (int16 quantization only).
- 1278 frames captured from Nxosc 1.0.5 itself, covering yaw -178..+179 deg,
  pitch -53..+50 deg, roll -17..+53 deg. Feeding its own `/nxosc/quaternion`
  through the formulas above reproduces its own `/SceneRotator/*` and
  `/nxosc/xyz` values to a maximum error of **8e-6 degrees** -- float32
  rounding, i.e. an exact match.
