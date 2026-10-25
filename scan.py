"""Discover the Waves Nx Head Tracker over BLE."""
import nxboot; nxboot.log_to("scan.log")
import asyncio, traceback
from bleak import BleakScanner

NX_SERVICE = "0000a010-5761-7665-7341-7564696f4c74"

async def main():
    print("scanning 12s ...\n")
    devs = await BleakScanner.discover(timeout=12.0, return_adv=True)
    if not devs:
        print("no BLE devices seen at all")
        return
    hits = []
    for addr, (d, adv) in sorted(devs.items(), key=lambda k: -(k[1][1].rssi or -999)):
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        name = adv.local_name or d.name or "(no name)"
        is_nx = NX_SERVICE in uuids or "waves" in name.lower() or name.lower().startswith("nx")
        print(f"{'>>> ' if is_nx else '    '}{addr}  rssi={adv.rssi:>4}  {name}")
        if uuids: print(f"          services: {uuids}")
        for k, v in (adv.manufacturer_data or {}).items():
            print(f"          mfr 0x{k:04x}: {v.hex()}")
        if is_nx: hits.append((addr, name))
    print(f"\n{len(devs)} devices seen.")
    print("MATCHES:", hits if hits else "none")

try:
    asyncio.run(main())
    print("\n[done]")
except Exception:
    traceback.print_exc()
