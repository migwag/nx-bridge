"""Validate the 10-byte packet layout hypothesis: 4x int16 LE Q14 quaternion + 2 status bytes."""
import sys, struct, math, gzip

def _open(p):
    return gzip.open(p, "rt") if str(p).endswith(".gz") else open(p)

path = sys.argv[1] if len(sys.argv) > 1 else 'fixtures/still_raw_packets.txt.gz'
rows=[]
for line in _open(path):
    t,h = line.split()
    rows.append((float(t), bytes.fromhex(h)))
print(f"{len(rows)} packets from {path}\n")

Q = 1<<14
norms=[]
b8=set(); b9=set()
for t,p in rows:
    a,b,c,d = struct.unpack_from('<4h', p, 0)
    n = math.sqrt((a*a+b*b+c*c+d*d))/Q
    norms.append(n)
    b8.add(p[8]); b9.add(p[9])

print("hypothesis: bytes0-7 = int16 LE x4, scale 1/16384")
print(f"  norm  min={min(norms):.5f}  max={max(norms):.5f}  mean={sum(norms)/len(norms):.5f}")
off = sum(abs(n-1.0) for n in norms)/len(norms)
print(f"  mean |norm-1| = {off:.5f}  -> {'UNIT QUATERNION CONFIRMED' if off < 0.01 else 'NOT a unit quaternion'}")
print(f"\nbyte[8] values seen: {sorted(b8)}")
print(f"byte[9] values seen: {sorted(b9)}")

# which component is the scalar (closest to +-1 at rest)?
import statistics
cols = list(zip(*[struct.unpack_from('<4h', p, 0) for _,p in rows]))
print("\nper-component stats (raw int16):")
for i,col in enumerate(cols):
    print(f"  [{i}] bytes{2*i}-{2*i+1}  min={min(col):>7}  max={max(col):>7}  mean={statistics.mean(col):>9.1f}  scaled_mean={statistics.mean(col)/Q:+.4f}")
