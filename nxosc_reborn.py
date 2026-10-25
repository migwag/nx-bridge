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
import subprocess
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

import nx_profile as NP
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


DEFAULT_PROFILE_NAME = "SceneRotator (IEM, SPARTA, degrees)"

DEFAULT_CONFIG = {
    # The active profile is always built from these three fields; the
    # drop-down simply fills them in. Editing them yields a one-off profile.
    "profile_name": DEFAULT_PROFILE_NAME,
    "address": "/SceneRotator/[yaw,pitch,roll]",
    "params": "yaw,pitch,roll",
    "destinations": "local 8000",
    "last_address": "",
}


def profiles_path() -> str:
    return os.path.join(os.path.dirname(config_path()), "profiles.txt")


def ensure_profiles_file() -> str:
    """Seed the user's profiles.txt from the one we ship, once."""
    path = profiles_path()
    if os.path.exists(path):
        return path
    shipped = resource_path("profiles.txt")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(shipped) as src, open(path, "w") as dst:
            dst.write(src.read())
    except OSError:
        pass
    return path


def load_profiles():
    """-> (profiles, errors). Falls back to the shipped file if need be."""
    for path in (ensure_profiles_file(), resource_path("profiles.txt")):
        try:
            with open(path) as fh:
                text = fh.read()
        except OSError:
            continue
        profiles, errors, _extras = NP.parse_profiles(text)
        if profiles or errors:
            return profiles, errors
    return [], []


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(config_path()) as fh:
            stored = json.load(fh)
        for key, value in stored.items():
            if key in cfg:            # unknown keys from older versions lapse
                cfg[key] = value
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
        self.profile = None
        self._clients: list = []
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    # -- plumbing -------------------------------------------------------
    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _post(self, kind, payload=None):
        self.events.put((kind, payload))

    def set_profile(self, profile):
        """Swap in a parsed profile and open a socket per destination."""
        clients = []
        for host, port in profile.destinations:
            try:
                clients.append(SimpleUDPClient(host, port))
            except Exception as exc:
                self._post("error", f"cannot send to {host}:{port} -- {exc}")
        self.profile = profile
        self._clients = clients

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
        profile = self.profile
        try:
            values = P.compute(bytes(data))
            if profile is not None:
                outgoing = profile.messages(P.profile_values(bytes(data)))
            else:
                outgoing = ()
        except Exception:
            return
        for client in self._clients:
            try:
                for address, args in outgoing:
                    client.send_message(address, args)
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
        # Activate the stored profile so the worker can send from the first
        # packet, without waiting for the user to visit the OSC tab.
        self._on_apply()
        self._note("not connected")
        self._tick()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- construction ---------------------------------------------------
    def _build(self):
        notebook = ttk.Notebook(self)
        notebook.grid(row=0, column=0, sticky="nsew")
        tracker = ttk.Frame(notebook, padding=12)
        osc = ttk.Frame(notebook, padding=12)
        notebook.add(tracker, text="Tracker")
        notebook.add(osc, text="OSC")
        self._build_tracker(tracker)
        self._build_osc(osc)

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

        ttk.Label(parent, text="Profile").grid(row=row, column=0, sticky="w")
        self.profile_var = tk.StringVar(value=self.cfg["profile_name"])
        self.profile_menu = ttk.Combobox(parent, textvariable=self.profile_var,
                                         state="readonly", width=34)
        self.profile_menu.grid(row=row, column=1, sticky="ew", pady=2)
        self.profile_menu.bind("<<ComboboxSelected>>", self._on_profile_chosen)
        row += 1

        buttons = ttk.Frame(parent)
        buttons.grid(row=row, column=1, sticky="e", pady=(0, 8))
        ttk.Button(buttons, text="Reload", width=9,
                   command=self._reload_profiles).grid(row=0, column=0, padx=2)
        ttk.Button(buttons, text="Show File", width=11,
                   command=self._show_profiles_file).grid(row=0, column=1, padx=2)
        row += 1

        self.address_var = tk.StringVar(value=self.cfg["address"])
        self.params_var = tk.StringVar(value=self.cfg["params"])
        for label, var in (("OSC address", self.address_var),
                           ("Parameters", self.params_var)):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
            entry = ttk.Entry(parent, textvariable=var, width=36)
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            entry.bind("<Return>", lambda _e: self._on_apply())
            row += 1

        ttk.Label(parent, text="Destinations").grid(row=row, column=0, sticky="nw")
        self.dest_text = tk.Text(parent, width=36, height=3, wrap="none",
                                 font=ttk.Style().lookup("TEntry", "font"))
        self.dest_text.grid(row=row, column=1, sticky="ew", pady=2)
        self.dest_text.insert("1.0", self.cfg["destinations"])
        row += 1

        ttk.Label(parent, foreground="grey", wraplength=330, justify="left",
                  text=("/[yaw,pitch,roll] sends separate messages; /ypr sends "
                        "one. Angles are degrees; :r radians, :1 maps to -1..1, "
                        ":0 to 0..1. A leading - reverses, each trailing _ adds "
                        "90\u00b0. One destination per line.")
                  ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 4))
        row += 1

        self.profile_note = ttk.Label(parent, wraplength=330, justify="left",
                                      text="")
        self.profile_note.grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        apply_row = ttk.Frame(parent)
        apply_row.grid(row=row, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(apply_row, text="Restore Defaults",
                   command=self._on_defaults).grid(row=0, column=0, padx=4)
        ttk.Button(apply_row, text="Apply",
                   command=self._on_apply).grid(row=0, column=1)

        self._reload_profiles(announce=False)

    # -- profiles -------------------------------------------------------
    def _reload_profiles(self, announce=True):
        self.profiles, errors = load_profiles()
        names = [p.name for p in self.profiles]
        self.profile_menu.configure(values=names)
        if self.cfg["profile_name"] in names:
            self.profile_var.set(self.cfg["profile_name"])
        if errors:
            self.profile_note.configure(
                foreground="#b00", text="profiles.txt: " + "; ".join(errors[:3]))
        else:
            self.profile_note.configure(foreground="grey", text="")
        if announce:
            self._note(f"{len(names)} profiles loaded"
                       + (f", {len(errors)} with errors" if errors else ""))

    def _on_profile_chosen(self, _event=None):
        chosen = next((p for p in self.profiles
                       if p.name == self.profile_var.get()), None)
        if chosen is None:
            return
        self.address_var.set(chosen.raw_address)
        self.params_var.set(chosen.raw_params)
        self.dest_text.delete("1.0", "end")
        self.dest_text.insert("1.0", "\n".join(
            f"{h} {p}" for h, p in chosen.destinations) or "local 8000")
        self._on_apply()

    def _show_profiles_file(self):
        path = ensure_profiles_file()
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", "-R", path], check=False)
            elif os.name == "nt":
                subprocess.run(["explorer", "/select,", path], check=False)
            else:
                subprocess.run(["xdg-open", os.path.dirname(path)], check=False)
        except Exception:
            messagebox.showinfo(APP_TITLE, f"Profiles file:\n{path}")

    def _current_profile(self):
        """Build a profile from the three fields. Returns (profile, error)."""
        destinations = self.dest_text.get("1.0", "end").strip()
        lines = [self.profile_var.get() or "Custom",
                 self.address_var.get().strip(),
                 self.params_var.get().strip()]
        lines += [d.strip() for d in destinations.splitlines() if d.strip()]
        if len(lines) < 4:
            return None, "Give at least one destination, such as 'local 8000'."
        try:
            return NP.parse_profile_block(lines), None
        except NP.ProfileError as exc:
            return None, str(exc)

    # -- actions --------------------------------------------------------
    def _on_connect(self):
        if self.connected:
            self.worker.disconnect()
            return
        self._set_busy(True, "scanning for Nx Tracker ...")
        self.worker.scan()

    def _on_recenter(self):
        self.worker.recenter()

    def _on_defaults(self):
        self.profile_var.set(DEFAULT_PROFILE_NAME)
        self.address_var.set(DEFAULT_CONFIG["address"])
        self.params_var.set(DEFAULT_CONFIG["params"])
        self.dest_text.delete("1.0", "end")
        self.dest_text.insert("1.0", DEFAULT_CONFIG["destinations"])
        self._on_apply()

    def _on_apply(self):
        profile, error = self._current_profile()
        if error:
            self.profile_note.configure(foreground="#b00", text=error)
            self._note("profile not applied")
            return

        self.profile_note.configure(foreground="grey", text="")
        self.cfg["profile_name"] = self.profile_var.get()
        self.cfg["address"] = self.address_var.get().strip()
        self.cfg["params"] = self.params_var.get().strip()
        self.cfg["destinations"] = self.dest_text.get("1.0", "end").strip()
        save_config(self.cfg)
        self.worker.set_profile(profile)

        where = ", ".join(f"{h}:{p}" for h, p in profile.destinations)
        self._note(f"{len(profile.addresses)} message"
                   f"{'' if len(profile.addresses) == 1 else 's'} -> {where}")

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
