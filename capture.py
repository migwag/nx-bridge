"""Subscribe to the Nx Tracker orientation stream and log raw packets."""
import nxboot
import sys, os, asyncio, time, traceback

LABEL = sys.argv[1] if len(sys.argv) > 1 else "cap"
DUR   = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
nxboot.log_to(f"capture_{LABEL}.log")

from bleak import BleakClient

ADDR  = os.environ.get("NX_ADDR", "1B4E67BB-C656-C730-9B13-F9B494A08F20")
DATA  = "0000a015-5761-7665-7341-7564696f4c74"
CTRL  = "0000a011-5761-7665-7341-7564696f4c74"

pkts = []

async def main():
    t_connect = time.time()
    async with BleakClient(ADDR, timeout=25.0) as c:
        print(f"connected in {time.time()-t_connect:.1f}s")
        ctrl_before = await c.read_gatt_char(CTRL)
        print("A011 (ctrl) before:", ctrl_before.hex())

        t0 = time.time()
        def on_data(_h, data: bytearray):
            pkts.append((time.time()-t0, bytes(data)))

        await c.start_notify(DATA, on_data)
        START = bytes([0x32,0x00,0x00,0x00,0x01])
        print("writing START", START.hex(' '), "-> A011")
        await c.write_gatt_char(CTRL, START, response=True)
        print(f"subscribed to A015; collecting {DUR}s  (label={LABEL})")
        await asyncio.sleep(3.0)
        if not pkts:
            print("!! no packets after 3s -- stream may need a start command on A011")
        await asyncio.sleep(max(0.0, DUR-3.0))
        await c.stop_notify(DATA)

    n = len(pkts)
    print(f"\npackets: {n}")
    if n:
        span = pkts[-1][0]-pkts[0][0]
        print(f"rate: {(n-1)/span:.1f} Hz over {span:.1f}s")
        print(f"lengths: {sorted({len(p) for _,p in pkts})}")
        print("\nfirst 25 packets:")
        for t, p in pkts[:25]:
            print(f"  {t:7.3f}  {p.hex(' ')}")
        with open(os.path.join(nxboot.HERE, f"raw_{LABEL}.txt"),"w") as f:
            for t,p in pkts: f.write(f"{t:.4f} {p.hex()}\n")
        print(f"\nwrote raw_{LABEL}.txt to {nxboot.HERE}")

try:
    asyncio.run(main()); print("[done]")
except Exception:
    traceback.print_exc(); print("[done]")
