"""Launch NXOSC_Reborn under the macOS Bluetooth wrapper, with a log file.

    open -a "$PWD/NxTracker.app" --args "$PWD/gui_run.py"

Running `python nxosc_reborn.py` straight from a terminal that already has
Bluetooth permission is simpler; this exists for when it does not.
"""
import nxboot; nxboot.log_to("gui.log")
import traceback
try:
    import nxosc_reborn
    nxosc_reborn.main()
except Exception:
    traceback.print_exc()
