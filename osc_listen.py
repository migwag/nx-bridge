"""Listen on 127.0.0.1:8000 and record what Nxosc emits, to validate our decode."""
import nxboot  # noqa: F401  -- makes .venv importable under the bundle
import sys, os, time, json
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DUR  = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
out  = open(os.path.join(HERE, "osc_recv.jsonl"), "w", buffering=1)
log  = open(os.path.join(HERE, "osc_listen.log"), "w", buffering=1)

frame = {}
n = [0]
t0 = time.time()

def handler(addr, *args):
    global frame
    frame[addr] = list(args)
    # a frame is complete once we've seen roll (the last message Nxosc sends)
    if addr == "/SceneRotator/roll":
        out.write(json.dumps({"t": round(time.time()-t0, 4), **frame}) + "\n")
        n[0] += 1
        if n[0] in (1, 5) or n[0] % 100 == 0:
            log.write(f"frames={n[0]}  {json.dumps(frame)}\n")
        frame = {}

d = Dispatcher()
d.set_default_handler(handler)
srv = BlockingOSCUDPServer(("127.0.0.1", PORT), d)
srv.timeout = 0.5
log.write(f"listening on 127.0.0.1:{PORT} for {DUR}s -- launch Nxosc and connect\n")
while time.time() - t0 < DUR:
    srv.handle_request()
log.write(f"\nDONE  frames={n[0]}\n")
out.close()
