"""Enumerate the full GATT table of the Nx Tracker."""
import nxboot; nxboot.log_to("gatt.log")
import os, asyncio, traceback
from bleak import BleakClient

ADDR = os.environ.get("NX_ADDR", "1B4E67BB-C656-C730-9B13-F9B494A08F20")

async def main():
    print(f"connecting to {ADDR} ...")
    async with BleakClient(ADDR, timeout=25.0) as c:
        print("connected:", c.is_connected, "\n")
        for s in c.services:
            print(f"SERVICE {s.uuid}  ({s.description})")
            for ch in s.characteristics:
                props = ",".join(ch.properties)
                print(f"   CHAR {ch.uuid}  handle={ch.handle}  [{props}]  {ch.description}")
                if "read" in ch.properties:
                    try:
                        v = await c.read_gatt_char(ch)
                        txt = v.decode('utf-8','replace').strip('\x00')
                        printable = txt if txt.isprintable() and txt else ''
                        print(f"        read: {v.hex()}  len={len(v)}" + (f"  ascii={printable!r}" if printable else ""))
                    except Exception as e:
                        print(f"        read failed: {e}")
                for d in ch.descriptors:
                    print(f"        descr {d.uuid} handle={d.handle}")
            print()

try:
    asyncio.run(main()); print("[done]")
except Exception:
    traceback.print_exc()
