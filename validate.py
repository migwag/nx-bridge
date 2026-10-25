"""Feed Nxosc's own /nxosc/quaternion through our Euler math and compare to its own angles."""
import sys, json, gzip
sys.path.insert(0,".")
import nx_protocol as P

def _open(p):
    return gzip.open(p, "rt") if str(p).endswith(".gz") else open(p)


rows=[json.loads(l) for l in _open(sys.argv[1] if len(sys.argv)>1 else 'fixtures/nxosc_reference.jsonl.gz') if l.strip()]
rows=[r for r in rows if len(r)>=6]
print(f"{len(rows)} complete frames from Nxosc\n")

err={k:[] for k in ("yaw","pitch","roll","xyz0","xyz1","xyz2")}
rng={k:[] for k in ("yaw","pitch","roll")}
for r in rows:
    a,b,c,w = r["/nxosc/quaternion"]
    e4 = P.euler_mode4(a,b,c,w)
    e6 = P.euler_mode6(a,b,c,w)
    mine = {
        "yaw":   e4[2]*P.DEG,
        "pitch": -e4[1]*P.DEG,
        "roll":  -e4[0]*P.DEG,
        "xyz0":  e6[0]*P.DEG,
        "xyz1":  e6[2]*P.DEG,
        "xyz2":  e6[1]*P.DEG,
    }
    theirs = {
        "yaw":   r["/SceneRotator/yaw"][0],
        "pitch": r["/SceneRotator/pitch"][0],
        "roll":  r["/SceneRotator/roll"][0],
        "xyz0":  r["/nxosc/xyz"][0],
        "xyz1":  r["/nxosc/xyz"][1],
        "xyz2":  r["/nxosc/xyz"][2],
    }
    for k in err: err[k].append(abs(mine[k]-theirs[k]))
    for k in rng: rng[k].append(theirs[k])

print(f"{'field':8s} {'max |err| deg':>14s} {'mean |err|':>12s}   observed range (deg)")
ok=True
for k in ("yaw","pitch","roll","xyz0","xyz1","xyz2"):
    mx=max(err[k]); mn=sum(err[k])/len(err[k])
    r = f"{min(rng[k]):+8.2f} .. {max(rng[k]):+8.2f}" if k in rng else ""
    print(f"{k:8s} {mx:14.6f} {mn:12.6f}   {r}")
    if mx > 1e-3: ok=False
print()
print("RESULT:", "EXACT MATCH (within float32 precision)" if ok else "MISMATCH -- decode is wrong")
