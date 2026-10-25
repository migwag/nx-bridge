"""Bootstrap for scripts run inside the macOS Bluetooth wrapper bundle.

Two jobs:
  1. make a project-local .venv importable, since the bundled interpreter does
     not inherit the venv that launched it;
  2. tee stdout/stderr to a log file, since a bundle launched via `open` has no
     terminal attached.

On Windows and Linux neither is needed -- run the scripts directly.
"""
import atexit, glob, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))

for pattern in ("lib/python*/site-packages", "Lib/site-packages"):
    for path in glob.glob(os.path.join(HERE, ".venv", pattern)):
        if path not in sys.path:
            sys.path.insert(0, path)

def log_to(name):
    """Mirror stdout/stderr into HERE/<name>, keeping the terminal if present."""
    handle = open(os.path.join(HERE, name), "w", buffering=1)

    class Tee:
        def write(self, text):
            handle.write(text)
            try:
                sys.__stdout__.write(text)
            except Exception:
                pass
        def flush(self):
            handle.flush()

    sys.stdout = sys.stderr = Tee()
    atexit.register(handle.close)
