#!/usr/bin/env python3
"""
NXOSC_Reborn -- Waves Nx Head Tracker to OSC, with a GUI, on macOS/Windows/Linux.

A reimplementation of the macOS-only Nxosc 1.0.5. The layout follows the
original (Connect at the top, device and battery, OSC destination, live
readouts, Reset Center at the bottom) and adds an OSC tab for editing the
message addresses, which the original hardcoded.

    python nxosc_reborn.py

Tkinter is in the standard library, so there is no GUI dependency to install.
"""
from __future__ import annotations

import asyncio
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

try:  # makes a project-local .venv importable under the macOS wrapper bundle
    import nxboot  # noqa: F401
except ImportError:
    pass

from bleak import BleakClient, BleakScanner
from pythonosc.udp_client import SimpleUDPClient

import nx_protocol as P

APP_NAME = "NXOSC_Reborn"      # internal: config directory, bundle id
APP_TITLE = "NXOSC Reborn"     # what the user sees
UI_HZ = 20          # readout refresh; the OSC stream always runs at the full 50 Hz


# --------------------------------------------------------------------- config
def resource_path(name: str) -> str:
    """Locate a bundled file, frozen (PyInstaller) or running from source."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def set_window_icon(root: tk.Tk) -> None:
    """Give the window our icon where the platform uses one.

    macOS takes the Dock icon from the app bundle instead, so this is mainly
    for Windows and Linux. Any failure is cosmetic -- never fatal.
    """
    path = resource_path("icon_256.png")
    if not os.path.exists(path):
        return
    try:
        root._icon_image = tk.PhotoImage(file=path)   # keep a reference alive
        root.iconphoto(True, root._icon_image)
    except Exception:
        pass


def config_path() -> str:
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(base, APP_NAME, "config.json")


DEFAULT_CONFIG = {
    "host": "localhost",
    "port": 8000,
    "degrees": True,
    "addresses": dict(P.DEFAULT_ADDRESSES),
    "enabled": list(P.MESSAGE_KEYS),
    "transforms": P.default_transforms(),
    "last_address": "",
}


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    try:
        with open(config_path()) as fh:
            stored = json.load(fh)
        for key, value in stored.items():
            if key in cfg:
                cfg[key] = value
        # never let a stale file drop a message key, or carry a transform
        # whose length no longer matches the message
        for key in P.MESSAGE_KEYS:
            cfg["addresses"].setdefault(key, P.DEFAULT_ADDRESSES[key])
            want = len(P.COMPONENT_LABELS[key])
            t = cfg["transforms"].get(key) or {}
            if (len(t.get("order", [])) != want
                    or len(t.get("signs", [])) != want
                    or len(t.get("offsets", [])) != want):
                cfg["transforms"][key] = P.default_transform(key)
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    path = config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(cfg, fh, indent=2)
    except OSError:
        pass  # a config we cannot persist is not worth crashing over


# --------------------------------------------------------------------- worker
class TrackerWorker:
    """Owns an asyncio loop on its own thread and does all BLE and OSC work.

    Never touches widgets. It posts ("event", payload) tuples to `events`,
    which the GUI drains on the main thread, and publishes the newest decoded
    frame to `latest` (a plain attribute -- reference assignment is atomic).
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.events: queue.Queue = queue.Queue()
        self.latest = None
        self.frames = 0
        self._client: BleakClient | None = None
        self._osc: SimpleUDPClient | None = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.rebuild_osc()

    # -- plumbing -------------------------------------------------------
    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _post(self, kind, payload=None):
        self.events.put((kind, payload))

    def rebuild_osc(self):
        try:
            self._osc = SimpleUDPClient(self.cfg["host"], int(self.cfg["port"]))
        except Exception as exc:
            self._osc = None
            self._post("error", f"bad OSC destination: {exc}")

    # -- public, callable from the GUI thread ---------------------------
    def scan(self):
        self._submit(self._scan())

    def connect(self, address):
        self._submit(self._connect(address))

    def disconnect(self):
        self._submit(self._disconnect())

    def recenter(self):
        self._submit(self._recenter())

    def shutdown(self):
        # Wait for the disconnect to finish before killing the loop, otherwise
        # the tracker never receives CMD_STOP and keeps streaming after we quit.
        try:
            self._submit(self._disconnect()).result(timeout=3.0)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)

    # -- coroutines -----------------------------------------------------
    async def _scan(self):
        self._post("scanning")
        try:
            found = await BleakScanner.discover(timeout=8.0, return_adv=True)
        except Exception as exc:
            self._post("error", f"scan failed: {exc}")
            self._post("scan_done", [])
            return
        devices = []
        for dev, adv in found.values():
            uuids = {u.lower() for u in (adv.service_uuids or [])}
            name = adv.local_name or dev.name or ""
            if P.ADV_SERVICE in uuids or name == P.ADV_NAME:
                devices.append((dev.address, name or P.ADV_NAME, adv.rssi))
        devices.sort(key=lambda d: -(d[2] or -999))
        self._post("scan_done", devices)

    async def _connect(self, address):
        await self._disconnect()
        self._post("connecting", address)
        try:
            client = BleakClient(address, timeout=25.0,
                                 disconnected_callback=self._on_dropped)
            await client.connect()
        except Exception as exc:
            self._post("error", f"could not connect: {exc}")
            self._post("disconnected")
            return

        self._client = client
        info = {"address": address, "name": P.ADV_NAME,
                "manufacturer": "", "battery": None}
        for key, uuid in (("manufacturer", "00002a29-0000-1000-8000-00805f9b34fb"),
                          ("name", P.CHAR_NAME)):
            try:
                raw = await client.read_gatt_char(uuid)
                info[key] = raw.decode("utf-8", "replace").strip("\x00") or info[key]
            except Exception:
                pass
        try:
            raw = await client.read_gatt_char(P.BATTERY_LEVEL)
            info["battery"] = P.battery_percent(raw[0])
        except Exception:
            pass

        self.frames = 0
        try:
            await client.start_notify(P.CHAR_DATA, self._on_packet)
            await client.write_gatt_char(P.CHAR_CONTROL, P.CMD_START, response=True)
        except Exception as exc:
            self._post("error", f"could not start the stream: {exc}")
            await self._disconnect()
            return

        self._post("connected", info)

    async def _disconnect(self):
        client, self._client = self._client, None
        if client is None:
            return
        for action in (
            client.write_gatt_char(P.CHAR_CONTROL, P.CMD_STOP, response=True),
            client.stop_notify(P.CHAR_DATA),
            client.disconnect(),
        ):
            try:
                await action
            except Exception:
                pass
        self.latest = None
        self._post("disconnected")

    async def _recenter(self):
        if self._client is None:
            return
        try:
            for command in P.CMD_RECENTER:
                await self._client.write_gatt_char(P.CHAR_CONTROL, command, response=True)
            self._post("recentered")
        except Exception as exc:
            self._post("error", f"recenter failed: {exc}")

    # -- callbacks ------------------------------------------------------
    def _on_dropped(self, _client):
        self._client = None
        self.latest = None
        self._post("dropped")

    def _on_packet(self, _handle, data: bytearray):
        if len(data) != P.PACKET_LEN:
            return
        try:
            values = P.compute(bytes(data))
            messages = P.osc_messages(
                bytes(data),
                addresses=self.cfg["addresses"],
                enabled=self.cfg["enabled"],
                degrees=self.cfg["degrees"],
                transforms=self.cfg["transforms"],
            )
        except Exception:
            return
        if self._osc is not None:
            try:
                for address, args in messages:
                    self._osc.send_message(address, args)
            except Exception:
                pass
        self.frames += 1
        self.latest = values


# --------------------------------------------------------------------- GUI
class App(ttk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root, padding=12)
        self.root = root
        self.cfg = load_config()
        self.worker = TrackerWorker(self.cfg)
        self.connected = False
        self.busy = False
        self._last_frames = 0
        self._last_time = time.monotonic()
        self._rate = 0.0

        root.title(APP_TITLE)
        root.resizable(False, False)
        self.grid(sticky="nsew")

        self._build()
        self._tick()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- construction ---------------------------------------------------
    def _build(self):
        notebook = ttk.Notebook(self)
        notebook.grid(row=0, column=0, sticky="nsew")
        tracker = ttk.Frame(notebook, padding=12)
        osc = ttk.Frame(notebook, padding=12)
        transform = ttk.Frame(notebook, padding=12)
        notebook.add(tracker, text="Tracker")
        notebook.add(osc, text="OSC")
        notebook.add(transform, text="Transform")
        self._build_tracker(tracker)
        self._build_osc(osc)
        self._build_transform(transform)

        self.status = ttk.Label(self, text="not connected", anchor="w")
        self.status.grid(row=1, column=0, sticky="ew", pady=(8, 0))

    def _build_tracker(self, parent):
        parent.columnconfigure(1, weight=1)
        row = 0

        self.connect_button = ttk.Button(parent, text="Connect",
                                         command=self._on_connect)
        self.connect_button.grid(row=row, column=0, columnspan=2, sticky="ew")
        row += 1

        self.spinner = ttk.Progressbar(parent, mode="indeterminate", length=120)
        self.spinner.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(6, 10))
        row += 1

        self.device_var = tk.StringVar(value="No Data")
        self.battery_var = tk.StringVar(value="No Data")
        for label, var in (("Device", self.device_var),
                           ("Battery Level", self.battery_var)):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
            ttk.Label(parent, textvariable=var).grid(row=row, column=1, sticky="e")
            row += 1

        ttk.Separator(parent).grid(row=row, column=0, columnspan=2,
                                   sticky="ew", pady=10)
        row += 1

        mono = ("Menlo" if sys.platform == "darwin"
                else "Consolas" if os.name == "nt" else "monospace", 11)
        self.readouts = {}
        for key, label in (("quaternion", "Quaternion"), ("xyz", "Euler xyz"),
                           ("yaw", "Yaw"), ("pitch", "Pitch"), ("roll", "Roll")):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
            var = tk.StringVar(value="--")
            ttk.Label(parent, textvariable=var, font=mono).grid(
                row=row, column=1, sticky="e")
            self.readouts[key] = var
            row += 1

        ttk.Separator(parent).grid(row=row, column=0, columnspan=2,
                                   sticky="ew", pady=10)
        row += 1

        self.recenter_button = ttk.Button(parent, text="Reset Center",
                                          command=self._on_recenter,
                                          state="disabled")
        self.recenter_button.grid(row=row, column=0, columnspan=2)

    def _build_osc(self, parent):
        parent.columnconfigure(1, weight=1)
        row = 0

        self.host_var = tk.StringVar(value=str(self.cfg["host"]))
        self.port_var = tk.StringVar(value=str(self.cfg["port"]))
        for label, var in (("OSC IP", self.host_var), ("OSC Port", self.port_var)):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(parent, textvariable=var, width=22).grid(
                row=row, column=1, sticky="ew", pady=2)
            row += 1

        ttk.Label(parent, text="Angle units").grid(row=row, column=0, sticky="w",
                                                   pady=(8, 2))
        self.units_var = tk.StringVar(value="deg" if self.cfg["degrees"] else "rad")
        units = ttk.Frame(parent)
        units.grid(row=row, column=1, sticky="e", pady=(8, 2))
        ttk.Radiobutton(units, text="Degrees", value="deg",
                        variable=self.units_var).grid(row=0, column=0)
        ttk.Radiobutton(units, text="Radians", value="rad",
                        variable=self.units_var).grid(row=0, column=1)
        row += 1

        box = ttk.LabelFrame(parent, text="Messages", padding=8)
        box.grid(row=row, column=0, columnspan=2, sticky="ew", pady=10)
        box.columnconfigure(1, weight=1)
        self.addr_vars, self.enable_vars = {}, {}
        for i, key in enumerate(P.MESSAGE_KEYS):
            enabled = tk.BooleanVar(value=key in self.cfg["enabled"])
            # Applies at once: a tickbox that waits for Apply reads as broken.
            ttk.Checkbutton(box, variable=enabled,
                            command=self._apply_enabled).grid(row=i, column=0)
            address = tk.StringVar(value=self.cfg["addresses"][key])
            entry = ttk.Entry(box, textvariable=address, width=26)
            entry.grid(row=i, column=1, sticky="ew", pady=1)
            entry.bind("<Return>", lambda _e: self._on_apply())
            self.enable_vars[key], self.addr_vars[key] = enabled, address
        row += 1

        buttons = ttk.Frame(parent)
        buttons.grid(row=row, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Restore Nxosc Defaults",
                   command=self._on_defaults).grid(row=0, column=0, padx=4)
        ttk.Button(buttons, text="Apply", command=self._on_apply).grid(row=0, column=1)

    def _build_transform(self, parent):
        parent.columnconfigure(0, weight=1)
        ttk.Label(parent, wraplength=360, justify="left", text=(
            "Adapt the numbers to what the receiver expects. Order picks which "
            "component goes in each slot; Invert flips the sign. Offsets apply "
            "to angles only and wrap at \u00b1180\u00b0.")
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        self.order_vars, self.invert_vars, self.offset_vars = {}, {}, {}
        self.transform_boxes = {}
        row = 1
        for key in P.MESSAGE_KEYS:
            labels = P.COMPONENT_LABELS[key]
            t = self.cfg["transforms"][key]
            box = ttk.LabelFrame(parent, text=self.cfg["addresses"][key],
                                 padding=8)
            box.grid(row=row, column=0, sticky="ew", pady=4)
            self.transform_boxes[key] = box
            row += 1
            inner = 0

            if len(labels) > 1:
                ttk.Label(box, text="Order").grid(row=inner, column=0, sticky="w")
                order = tk.StringVar(value="".join(labels[i] for i in t["order"]))
                entry = ttk.Entry(box, textvariable=order, width=10)
                entry.grid(row=inner, column=1, sticky="w")
                entry.bind("<Return>", lambda _e: self._on_apply())
                ttk.Label(box, text=f"(any order of {' '.join(labels)})",
                          foreground="grey").grid(row=inner, column=2, sticky="w",
                                                  padx=6)
                self.order_vars[key] = order
                inner += 1

            ttk.Label(box, text="Invert").grid(row=inner, column=0, sticky="w")
            flags = ttk.Frame(box)
            flags.grid(row=inner, column=1, columnspan=2, sticky="w")
            self.invert_vars[key] = []
            for i, label in enumerate(labels):
                var = tk.BooleanVar(value=t["signs"][i] < 0)
                ttk.Checkbutton(flags, text=label, variable=var,
                                command=self._apply_transforms).grid(
                                    row=0, column=i, padx=(0, 6))
                self.invert_vars[key].append(var)
            inner += 1

            # Offsetting a quaternion component would break normalisation.
            if key in P.ANGLE_KEYS:
                ttk.Label(box, text="Offset\u00b0").grid(row=inner, column=0,
                                                         sticky="w")
                offs = ttk.Frame(box)
                offs.grid(row=inner, column=1, columnspan=2, sticky="w")
                self.offset_vars[key] = []
                for i, _label in enumerate(labels):
                    var = tk.StringVar(value=f"{t['offsets'][i]:g}")
                    e = ttk.Entry(offs, textvariable=var, width=7)
                    e.grid(row=0, column=i, padx=(0, 4))
                    e.bind("<Return>", lambda _e: self._on_apply())
                    self.offset_vars[key].append(var)
                inner += 1

        buttons = ttk.Frame(parent)
        buttons.grid(row=row, column=0, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="Reset Transforms",
                   command=self._on_reset_transforms).grid(row=0, column=0, padx=4)
        ttk.Button(buttons, text="Apply",
                   command=self._on_apply).grid(row=0, column=1)

    # -- actions --------------------------------------------------------
    def _on_connect(self):
        if self.connected:
            self.worker.disconnect()
            return
        self._set_busy(True, "scanning for Nx Tracker ...")
        self.worker.scan()

    def _apply_enabled(self):
        """Ticking a box takes effect immediately -- no Apply needed."""
        self.cfg["enabled"] = [k for k in P.MESSAGE_KEYS
                               if self.enable_vars[k].get()]
        save_config(self.cfg)
        n = len(self.cfg["enabled"])
        self._note(f"sending {n} of {len(P.MESSAGE_KEYS)} messages"
                   if n else "all messages muted")

    def _apply_transforms(self):
        """Same for the Invert boxes."""
        for key in P.MESSAGE_KEYS:
            signs = [-1 if v.get() else 1 for v in self.invert_vars[key]]
            self.cfg["transforms"][key]["signs"] = signs
        save_config(self.cfg)
        self._note("transform updated")

    def _read_transforms(self):
        """Parse the Order and Offset fields. Returns (transforms, error)."""
        transforms = {}
        for key in P.MESSAGE_KEYS:
            labels = P.COMPONENT_LABELS[key]
            current = self.cfg["transforms"][key]
            order = list(current["order"])

            if key in self.order_vars:
                text = self.order_vars[key].get().replace(" ", "").lower()
                if sorted(text) != sorted(labels):
                    return None, (f"Order for {self.cfg['addresses'][key]} must "
                                  f"use each of {' '.join(labels)} exactly once.")
                order = [labels.index(ch) for ch in text]

            offsets = list(current["offsets"])
            if key in self.offset_vars:
                offsets = []
                for i, var in enumerate(self.offset_vars[key]):
                    raw = var.get().strip() or "0"
                    try:
                        offsets.append(float(raw))
                    except ValueError:
                        return None, (f"Offset '{raw}' for "
                                      f"{self.cfg['addresses'][key]} "
                                      f"({labels[i]}) is not a number.")

            transforms[key] = {
                "order": order,
                "signs": [-1 if v.get() else 1 for v in self.invert_vars[key]],
                "offsets": offsets,
            }
        return transforms, None

    def _on_reset_transforms(self):
        self.cfg["transforms"] = P.default_transforms()
        for key in P.MESSAGE_KEYS:
            labels = P.COMPONENT_LABELS[key]
            if key in self.order_vars:
                self.order_vars[key].set("".join(labels))
            for var in self.invert_vars[key]:
                var.set(False)
            for var in self.offset_vars.get(key, []):
                var.set("0")
        save_config(self.cfg)
        self._note("transforms reset")

    def _on_recenter(self):
        self.worker.recenter()

    def _on_defaults(self):
        for key in P.MESSAGE_KEYS:
            self.addr_vars[key].set(P.DEFAULT_ADDRESSES[key])
            self.enable_vars[key].set(True)
        self.host_var.set("localhost")
        self.port_var.set("8000")
        self.units_var.set("deg")
        self._on_reset_transforms()
        self._on_apply()

    def _on_apply(self):
        try:
            port = int(self.port_var.get())
            if not 1 <= port <= 65535:
                raise ValueError("port must be between 1 and 65535")
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, f"Invalid port: {exc}")
            return

        addresses = {}
        for key in P.MESSAGE_KEYS:
            address = self.addr_vars[key].get().strip()
            if not address.startswith("/"):
                messagebox.showerror(
                    APP_TITLE, f"OSC address for '{key}' must start with '/'")
                return
            addresses[key] = address

        transforms, error = self._read_transforms()
        if error:
            messagebox.showerror(APP_TITLE, error)
            return

        self.cfg["transforms"] = transforms
        self.cfg["host"] = self.host_var.get().strip() or "localhost"
        self.cfg["port"] = port
        self.cfg["degrees"] = self.units_var.get() == "deg"
        self.cfg["addresses"] = addresses
        self.cfg["enabled"] = [k for k in P.MESSAGE_KEYS
                               if self.enable_vars[k].get()]
        for key, box in self.transform_boxes.items():
            box.configure(text=addresses[key])
        self.worker.rebuild_osc()
        save_config(self.cfg)
        self._note(f"OSC -> {self.cfg['host']}:{self.cfg['port']}"
                   f"  ({len(self.cfg['enabled'])} of {len(P.MESSAGE_KEYS)} messages)")

    def _choose_device(self, devices):
        """Modal device picker, standing in for the original's Device Scan sheet."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Device Scan")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=12)
        frame.grid()
        ttk.Label(frame, text="Choose a tracker:").grid(row=0, column=0,
                                                        columnspan=2, sticky="w")
        listbox = tk.Listbox(frame, height=min(6, len(devices)), width=46,
                             exportselection=False)
        for address, name, rssi in devices:
            listbox.insert("end", f"{name}   rssi {rssi}   {address}")
        listbox.selection_set(0)
        listbox.grid(row=1, column=0, columnspan=2, pady=8)

        chosen = {}

        def accept():
            selection = listbox.curselection()
            if selection:
                chosen["address"] = devices[selection[0]][0]
            dialog.destroy()

        ttk.Button(frame, text="Cancel", command=dialog.destroy).grid(
            row=2, column=0, sticky="w")
        ttk.Button(frame, text="Choose Device", command=accept).grid(
            row=2, column=1, sticky="e")
        listbox.bind("<Double-Button-1>", lambda _e: accept())
        dialog.grab_set()
        self.root.wait_window(dialog)
        return chosen.get("address")

    # -- state ----------------------------------------------------------
    def _set_busy(self, busy, note=None):
        self.busy = busy
        if busy:
            self.spinner.start(12)
            self.connect_button.configure(state="disabled")
        else:
            self.spinner.stop()
            self.connect_button.configure(state="normal")
        if note:
            self._note(note)

    def _note(self, text):
        self.status.configure(text=text)

    def _clear_readouts(self):
        for var in self.readouts.values():
            var.set("--")
        self.device_var.set("No Data")
        self.battery_var.set("No Data")

    # -- event pump -----------------------------------------------------
    def _tick(self):
        while True:
            try:
                kind, payload = self.worker.events.get_nowait()
            except queue.Empty:
                break
            self._handle(kind, payload)

        values = self.worker.latest
        if values is not None:
            a, b, c, w = values["quaternion"]
            self.readouts["quaternion"].set(
                f"{a:+.4f} {b:+.4f} {c:+.4f} {w:+.4f}")
            x, y, z = (v * P.DEG for v in values["xyz"])
            self.readouts["xyz"].set(f"{x:+8.2f} {y:+8.2f} {z:+8.2f}")
            for key in ("yaw", "pitch", "roll"):
                self.readouts[key].set(f"{values[key] * P.DEG:+8.2f}°")

        if self.connected:
            # Time-based, exponentially smoothed: counting frames per tick would
            # quantise to multiples of UI_HZ and flicker.
            now = time.monotonic()
            elapsed = now - self._last_time
            if elapsed > 0:
                instant = (self.worker.frames - self._last_frames) / elapsed
                self._rate = (instant if self._rate == 0.0
                              else self._rate * 0.8 + instant * 0.2)
            self._last_frames, self._last_time = self.worker.frames, now
            self._note(f"streaming   {self._rate:.1f} Hz   "
                       f"frames {self.worker.frames}   "
                       f"OSC -> {self.cfg['host']}:{self.cfg['port']}")

        self.after(int(1000 / UI_HZ), self._tick)

    def _handle(self, kind, payload):
        if kind == "scanning":
            self._note("scanning for Nx Tracker ...")
        elif kind == "scan_done":
            self._set_busy(False)
            if not payload:
                self._note("no tracker found")
                messagebox.showwarning(
                    APP_NAME,
                    "No Nx Tracker found.\n\n"
                    "Check that it is powered on and not already connected "
                    "in another app.")
                return
            address = payload[0][0] if len(payload) == 1 else self._choose_device(payload)
            if address:
                self._set_busy(True, "connecting ...")
                self.worker.connect(address)
        elif kind == "connecting":
            self._note("connecting ...")
        elif kind == "connected":
            self._set_busy(False)
            self.connected = True
            self._last_frames = self.worker.frames
            self._last_time = time.monotonic()
            self._rate = 0.0
            self.cfg["last_address"] = payload["address"]
            save_config(self.cfg)
            self.connect_button.configure(text="Disconnect")
            self.recenter_button.configure(state="normal")
            self.device_var.set(payload.get("manufacturer")
                                or payload.get("name") or P.ADV_NAME)
            battery = payload.get("battery")
            self.battery_var.set(f"{battery} %" if battery is not None else "No Data")
            self._note("connected")
        elif kind in ("disconnected", "dropped"):
            self._set_busy(False)
            self.connected = False
            self.connect_button.configure(text="Connect")
            self.recenter_button.configure(state="disabled")
            self._clear_readouts()
            self._note("connection lost" if kind == "dropped" else "not connected")
        elif kind == "recentered":
            self._note("reset center sent")
        elif kind == "error":
            self._set_busy(False)
            self._note(str(payload))

    def _on_close(self):
        save_config(self.cfg)
        self.worker.shutdown()
        self.root.destroy()


def main():
    root = tk.Tk()
    set_window_icon(root)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
