#!/usr/bin/env python3
"""C4 observe-only sinyal analiz raporu. OBSERVE-ONLY, hicbir sey degistirmez."""
import os, sys, urllib.request, json
from collections import Counter

U = os.environ["SUPABASE_URL"]; K = os.environ["SUPABASE_KEY"]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 500

def g(path):
    r = urllib.request.Request(U + "/rest/v1/" + path,
                               headers={"apikey": K, "Authorization": "Bearer " + K})
    return json.loads(urllib.request.urlopen(r, timeout=20).read())

def paginate(base, limit=1000, maxpages=6):
    out = []
    for pg in range(maxpages):
        b = g("%s&limit=%d&offset=%d" % (base, limit, pg*limit))
        if not b: break
        out += b
        if len(b) < limit: break
    return out

print("="*64)
print(" C4 ALIGNMENT ANALIZ RAPORU  (son %d tick)" % N)
print("="*64)

sel = "alignment_log?select=timestamp,block_reason,bull_tech,bear_tech,gex,gex_z,hvl,spot,flip_near,long_signal,short_signal,funding_z,funding_veto,pyramid_agreement,pyramid_total,regime,trade_opened&order=id.desc"
rows = paginate(sel, limit=1000, maxpages=(N//1000)+1)[:N]
if not rows:
    print("VERI YOK"); sys.exit(0)

n = len(rows)
print("\ncekilen tick: %d | tarih: %s -> %s" % (n, rows[-1]["timestamp"][:16], rows[0]["timestamp"][:16]))

print("\n" + "-"*64)
print("1) BLOK DAGILIMI (sistem zamani nerede geciyor)")
print("-"*64)
bc = Counter(r.get("block_reason") for r in rows)
for k, v in bc.most_common():
    print("  %-20s %5d  (%.1f%%)" % (k, v, 100*v/n))

print("\n" + "-"*64)
print("2) FLIP_NEAR ANALIZI (bloklarken firsat kaciriyor mu)")
print("-"*64)
fn = [r for r in rows if r.get("block_reason") == "flip_near"]
print("  flip_near tick: %d" % len(fn))
if fn:
    would_long = 0; would_short = 0
    for r in fn:
        g_ = r.get("gex") or 0; sp = r.get("spot") or 0; hvl = r.get("hvl") or 0
        if r.get("bull_tech") and g_ > 0 and sp > hvl: would_long += 1
        if r.get("bear_tech") and g_ < 0 and sp < hvl: would_short += 1
    print("  flip olmasa LONG kosulu olusurdu: %d (%.1f%%)" % (would_long, 100*would_long/len(fn)))
    print("  flip olmasa SHORT kosulu olusurdu: %d (%.1f%%)" % (would_short, 100*would_short/len(fn)))

print("\n" + "-"*64)
print("3) GEX_Z vs HAM GEX (z-score ham esikten ne zaman ayrisir)")
print("-"*64)
gz = [r for r in rows if r.get("gex_z") is not None]
print("  gex_z dolu tick: %d" % len(gz))
if gz:
    import statistics as st
    zs = [r["gex_z"] for r in gz]
    print("  gex_z: mean=%.2f std=%.2f min=%.2f max=%.2f" % (st.mean(zs), st.stdev(zs) if len(zs)>1 else 0, min(zs), max(zs)))
    posz = sum(1 for z in zs if z > 0)
    print("  gex_z pozitif: %d (%.0f%%)  negatif: %d (%.0f%%)" % (posz, 100*posz/len(zs), len(zs)-posz, 100*(len(zs)-posz)/len(zs)))
    div_a = sum(1 for r in gz if (r.get("gex") or 0) > 0 and r["gex_z"] < 0)
    div_b = sum(1 for r in gz if (r.get("gex") or 0) < 0 and r["gex_z"] > 0)
    print("  ham gex>0 AMA gex_z<0: %d (%.0f%%)" % (div_a, 100*div_a/len(gz)))
    print("  ham gex<0 AMA gex_z>0: %d (%.0f%%)" % (div_b, 100*div_b/len(gz)))

print("\n" + "-"*64)
print("4) FUNDING_Z DAGILIMI (veto esigi 1.5 dogru mu)")
print("-"*64)
fz = [r["funding_z"] for r in rows if r.get("funding_z") is not None]
if fz:
    import statistics as st
    print("  funding_z: mean=%.2f std=%.2f min=%.2f max=%.2f (n=%d)" % (st.mean(fz), st.stdev(fz) if len(fz)>1 else 0, min(fz), max(fz), len(fz)))
    for thr in (1.0, 1.5, 2.0):
        over = sum(1 for z in fz if abs(z) > thr)
        print("    |z| > %.1f : %d tick (%.1f%%)" % (thr, over, 100*over/len(fz)))
    vc = Counter(r.get("funding_veto") for r in rows if r.get("funding_veto"))
    print("  gerceklesmis would_veto: %s" % (dict(vc) if vc else "hic"))

print("\n" + "-"*64)
print("5) PYRAMID AGREEMENT")
print("-"*64)
pa = Counter(r.get("pyramid_agreement") for r in rows if r.get("pyramid_agreement"))
tot_pa = sum(pa.values())
if tot_pa:
    for k, v in pa.most_common():
        print("  %-24s %5d  (%.1f%%)" % (k, v, 100*v/tot_pa))

print("\n" + "-"*64)
print("6) TRADE SONUCLARI (kapali)")
print("-"*64)
tr = g("trades?select=dir,pnl,status,regime&order=id.asc")
if tr:
    d = Counter(t["dir"] for t in tr)
    tot = sum((t.get("pnl") or 0) for t in tr)
    wins = sum(1 for t in tr if (t.get("pnl") or 0) > 0)
    print("  toplam: %d | yon: %s | toplam pnl: %.2f | win: %d/%d (%.0f%%)" % (
        len(tr), dict(d), tot, wins, len(tr), 100*wins/len(tr)))

print("\n" + "="*64)
