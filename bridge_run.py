import nxboot; nxboot.log_to("bridge.log")
import sys, traceback
sys.argv = ["nx_bridge"] + sys.argv[1:]
try:
    import nx_bridge
    code = nx_bridge.main()
    print(f"\n[exit {code}]")
except Exception:
    traceback.print_exc(); print("\n[exit crash]")
