# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for NXOSC_Reborn.

    ../.venv/bin/pyinstaller NXOSC_Reborn.spec     # from this directory

Builds dist/NXOSC_Reborn.app on macOS and dist/NXOSC_Reborn/ on Windows and
Linux. PyInstaller cannot cross-compile: build each platform on that platform.

The Info.plist below is the point of the whole exercise on macOS. CoreBluetooth
kills any process lacking NSBluetoothAlwaysUsageDescription, and a real bundle
carries its own, so the frozen app gets a proper permission prompt instead of
needing the NxTracker.app wrapper.
"""
import sys

from PyInstaller.utils.hooks import collect_submodules

# bleak selects its backend at runtime, so the platform one must be forced in.
hidden = collect_submodules("bleak")
if sys.platform == "darwin":
    hidden += [
        "CoreBluetooth",
        "libdispatch",
        "objc",
    ]
elif sys.platform == "win32":
    hidden += collect_submodules("winrt")

BLUETOOTH_REASON = (
    "NXOSC_Reborn reads head orientation from the Waves Nx Head Tracker "
    "over Bluetooth LE."
)

a = Analysis(
    ["nxosc_reborn.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    # nxboot only matters when running from source under the wrapper bundle;
    # a frozen app has no .venv to find.
    excludes=["nxboot"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NXOSC_Reborn",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI app: no terminal window
    argv_emulation=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="NXOSC_Reborn",
)
app = BUNDLE(
    coll,
    name="NXOSC_Reborn.app",
    icon=None,
    bundle_identifier="cc.wagner.nxoscreborn",
    version="1.0.0",
    info_plist={
        "CFBundleName": "NXOSC_Reborn",
        "CFBundleDisplayName": "NXOSC_Reborn",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "LSMinimumSystemVersion": "11.0",
        "LSApplicationCategoryType": "public.app-category.utilities",
        "NSHighResolutionCapable": True,
        "NSBluetoothAlwaysUsageDescription": BLUETOOTH_REASON,
        "NSBluetoothPeripheralUsageDescription": BLUETOOTH_REASON,
        "NSHumanReadableCopyright": "Protocol reverse engineered for interoperability.",
    },
)
