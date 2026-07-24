#!/usr/bin/env python3
"""
analyze_edge_shadow.py — long_edge_shadow tablosunu okur, rapor üretir.

Sadece READ, tablo değişmez. İstediğin zaman çalıştır:
  python3 analyze_edge_shadow.py

Kırılım:
  1. Toplam durum (kaç açık, kaç kapalı, direction bazında)
  2. Slot × direction matrix
  3. Kapalı ghost'ların WR / avg PnL / exit_reason dağılımı
  4. Filter analizi (bull_tech ile / bull_tech olmadan; pyramid_total split)
  5. Zaman sıralı örnekler (son 10 kapalı)
"""

import os, json, urllib.request
from collections import defaultdict
from statistics import mean

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    # Fallback: gdive_trader.py ile aynı env değişkenlerini oku
    import sys
    print("SUPABASE_URL veya SUPABASE_KEY environment'ta yok.")
    print("Çalıştırma öncesi export et veya .env yükle.")
    sys.exit(1)

def sb_get(path):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def main():
    print("=" * 70)
    print("long_edge_shadow — GHOST ANALIZ RAPORU")
    print("=" * 70)

    rows = sb_get("long_edge_shadow?select=*&order=id.asc&limit=1000")
    total = len(rows)
    if total == 0:
        print("Henüz ghost yok.")
        return

    opens = [r for r in rows if r["status"] == "OPEN"]
    closes = [r for r in rows if r["status"] == "CLOSED"]
    longs = [r for r in rows if r["direction"] == "LONG"]
    shorts = [r for r in rows if r["direction"] == "SHORT"]

    print(f"\n1) TOPLAM: {total} ghost ({len(opens)} OPEN, {len(closes)} CLOSED)")
    print(f"   Direction: {len(longs)} LONG, {len(shorts)} SHORT")

    # ─── 2) Slot × Direction matrix ───
    print(f"\n2) SLOT × DIRECTION (açık | kapalı)")
    matrix = defaultdict(lambda: {"LONG_OPEN": 0, "LONG_CLOSED": 0, "SHORT_OPEN": 0, "SHORT_CLOSED": 0})
    for r in rows:
        key = f"{r['direction']}_{r['status']}"
        matrix[r["slot"]][key] += 1
    print(f"   {'Slot':<6} {'L-Open':>7} {'L-Closed':>9} {'S-Open':>7} {'S-Closed':>9}")
    for slot in sorted(matrix.keys()):
        m = matrix[slot]
        print(f"   {slot:<6} {m['LONG_OPEN']:>7} {m['LONG_CLOSED']:>9} "
              f"{m['SHORT_OPEN']:>7} {m['SHORT_CLOSED']:>9}")

    # ─── 3) Kapalı ghost analizi ───
    if closes:
        print(f"\n3) KAPALI GHOST PERFORMANS")
        for dirx in ("LONG", "SHORT"):
            dc = [r for r in closes if r["direction"] == dirx]
            if not dc:
                continue
            pnls = [float(r["pnl"] or 0) for r in dc]
            wins = [p for p in pnls if p > 0]
            total_pnl = sum(pnls)
            wr = len(wins) / len(dc) * 100
            avg_pnl = mean(pnls) if pnls else 0
            print(f"   {dirx}: {len(dc)} ghost, WR {wr:.1f}%, ort ${avg_pnl:+.0f}, toplam ${total_pnl:+.0f}")

            reason_c = defaultdict(list)
            for r in dc:
                reason_c[r["exit_reason"]].append(float(r["pnl"] or 0))
            for reason, ps in sorted(reason_c.items()):
                print(f"     {reason:8}: {len(ps):>3} × ort ${mean(ps):+.0f} (toplam ${sum(ps):+.0f})")

            # Slot bazlı
            print(f"     Slot bazlı:")
            slot_c = defaultdict(list)
            for r in dc:
                slot_c[r["slot"]].append(float(r["pnl"] or 0))
            for slot in sorted(slot_c.keys()):
                ps = slot_c[slot]
                wins_s = sum(1 for p in ps if p > 0)
                print(f"       {slot}: {len(ps):>3} ghost, {wins_s}W/{len(ps)-wins_s}L, ort ${mean(ps):+.0f}")

    # ─── 4) Filter analizi ───
    if closes:
        print(f"\n4) FİLTRE ANALİZİ (kapalı ghost'lar)")
        for dirx, tech_col in [("LONG", "bull_tech"), ("SHORT", "bear_tech")]:
            dc = [r for r in closes if r["direction"] == dirx]
            if not dc:
                continue
            with_tech = [r for r in dc if r.get(tech_col) is True]
            without_tech = [r for r in dc if not r.get(tech_col)]
            if with_tech:
                p_w = [float(r["pnl"] or 0) for r in with_tech]
                wins_w = sum(1 for p in p_w if p > 0)
                print(f"   {dirx} + {tech_col}=True:  {len(with_tech)} ghost, "
                      f"WR {wins_w/len(with_tech)*100:.1f}%, ort ${mean(p_w):+.0f}")
            if without_tech:
                p_wo = [float(r["pnl"] or 0) for r in without_tech]
                wins_wo = sum(1 for p in p_wo if p > 0)
                print(f"   {dirx} + {tech_col}=False: {len(without_tech)} ghost, "
                      f"WR {wins_wo/len(without_tech)*100:.1f}%, ort ${mean(p_wo):+.0f}")

    # ─── 5) Son 10 kapalı ─── 
    if closes:
        print(f"\n5) SON 10 KAPALI GHOST")
        last = sorted(closes, key=lambda r: r["exit_at"] or "", reverse=True)[:10]
        for r in last:
            print(f"   #{r['id']:>3} {r['direction']:5} {r['slot']} "
                  f"entry={float(r['entry']):.0f} exit={float(r['exit_price']):.0f} "
                  f"{r['exit_reason']:8} ${float(r['pnl'] or 0):+.0f} "
                  f"held={float(r['days_held'] or 0):.1f}d")

    # ─── 6) Açık ghost'lar ───
    if opens:
        print(f"\n6) AÇIK GHOST'LAR ({len(opens)})")
        for r in sorted(opens, key=lambda x: x["opened_at"]):
            print(f"   #{r['id']:>3} {r['direction']:5} {r['slot']} "
                  f"entry={float(r['entry']):.0f} stop={float(r['stop']):.0f} "
                  f"tp={float(r['tp']):.0f} opened={r['opened_at'][:16]}")

if __name__ == "__main__":
    main()
