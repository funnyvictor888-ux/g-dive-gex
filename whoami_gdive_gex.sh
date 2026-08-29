#!/bin/bash
# whoami_gdive_gex.sh — G-DIVE gex chat sabah durum kontrolü
# Kullanım: ssh root@178.105.37.173 "/root/g-dive-gex/whoami_gdive_gex.sh"
# Amaç: 30 saniyede tam sistem durumu — memory + bu çıktı ile chat başlar

cd /root/g-dive-gex
source ./run_edge_shadow_cron.sh > /dev/null 2>&1

echo "======================================================================"
echo " G-DIVE gex — SABAH DURUM   $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "======================================================================"

# ─── [1] Sağlık ping ───
echo ""
echo "[1] SAĞLIK PING"
python3 << 'PYEOF'
import urllib.request, json, os, subprocess
from datetime import datetime, timezone

h = {'apikey': os.environ['SUPABASE_KEY'], 
     'Authorization': f"Bearer {os.environ['SUPABASE_KEY']}"}

# Son snapshot yaşı
try:
    snap = json.loads(urllib.request.urlopen(urllib.request.Request(
        f"{os.environ['SUPABASE_URL']}/rest/v1/snapshots?select=timestamp,spot&order=id.desc&limit=1",
        headers=h), timeout=10).read())[0]
    ts = snap['timestamp']
    ts_norm = ts.split('.')[0] + '+00:00'
    age_min = (datetime.now(timezone.utc) - datetime.fromisoformat(ts_norm)).total_seconds() / 60
    marker = '✓' if age_min < 15 else ('⚠ STALE' if age_min < 30 else '✗ DEAD')
    print(f"  Snapshot: ${float(snap['spot']):.0f}  yaş: {age_min:.1f} dk  {marker}")
except Exception as e:
    print(f"  ✗ Snapshot fetch HATA: {e}")

# cron.log mtime + son 100 satırda hata var mı
try:
    r = subprocess.run(['stat', '-c', '%Y', 'cron.log'], capture_output=True, text=True)
    age = (int(datetime.now(timezone.utc).timestamp()) - int(r.stdout.strip())) / 60
    marker = '✓' if age < 15 else ('⚠ STALE' if age < 30 else '✗ DEAD')
    print(f"  cron.log yaşı: {age:.1f} dk  {marker}")
    
    with open('cron.log') as f:
        recent = f.readlines()[-100:]
    errors = [l for l in recent if 
              '401 ' in l or 'Unauthorized' in l or 
              'Traceback' in l or 'raise ' in l or
              l.strip().endswith('Error') or 
              'ERROR:' in l or 'CRITICAL' in l]
    if errors:
        print(f"  ⚠ Son 100 satırda {len(errors)} hata satırı!")
        for e in errors[:2]:
            print(f"      {e.strip()[:80]}")
    else:
        print(f"  cron.log son 100: temiz")
except Exception as e:
    print(f"  ✗ cron.log kontrol HATA: {e}")

try:
    r = subprocess.run(['stat', '-c', '%Y', 'edge_shadow.log'], capture_output=True, text=True)
    age = (int(datetime.now(timezone.utc).timestamp()) - int(r.stdout.strip())) / 60
    marker = '✓' if age < 15 else ('⚠ STALE' if age < 30 else '✗ DEAD')
    print(f"  edge_shadow.log yaşı: {age:.1f} dk  {marker}")
except: pass
PYEOF

# ─── [2] Trader — son cron ne dedi ───
echo ""
echo "[2] TRADER — son cron sinyali"
tail -8 cron.log | sed 's/^/  /'

# ─── [3] Canlı trader — PnL + pozisyon ───
echo ""
echo "[3] CANLI TRADER — gerçek para"
python3 << 'PYEOF'
import urllib.request, json, os
h = {'apikey': os.environ['SUPABASE_KEY'], 
     'Authorization': f"Bearer {os.environ['SUPABASE_KEY']}"}
trades = json.loads(urllib.request.urlopen(urllib.request.Request(
    f"{os.environ['SUPABASE_URL']}/rest/v1/trades?select=id,dir,status,entry,exit_price,pnl,exit_date,date&order=id.desc&limit=50",
    headers=h), timeout=10).read())
closed = [t for t in trades if t.get('status')=='CLOSED']
open_ = [t for t in trades if t.get('status')=='OPEN']
pnl = sum(float(t.get('pnl') or 0) for t in closed)
wins = sum(1 for t in closed if float(t.get('pnl') or 0) > 0)
wr = wins/max(len(closed),1)*100
print(f"  Kapalı: {len(closed)}  ({wins}W/{len(closed)-wins}L, WR {wr:.1f}%)")
print(f"  Gerçekleşen PnL: ${pnl:+.2f}")
print(f"  Açık pozisyon: {len(open_)}")
for t in open_:
    print(f"    #{t['id']} {t['dir']} entry={t.get('entry')}")
if closed:
    last = max(closed, key=lambda t: t.get('exit_date') or '')
    print(f"  Son kapanış: {(last.get('exit_date') or '?')[:10]} ${float(last.get('pnl') or 0):+.0f}")
PYEOF

# ─── [4] Edge shadow — son 3 tick ───
echo ""
echo "[4] EDGE_SHADOW — son 3 tick"
tail -9 edge_shadow.log | grep -E "^\[EDGE_CRON\] snapshot|^\[EDGE_CRON\] metadata" | tail -6 | sed 's/^/  /'

# ─── [5] Ghost — özet ───
echo ""
echo "[5] GHOST — kısa özet"
python3 << 'PYEOF'
import urllib.request, json, os
h = {'apikey': os.environ['SUPABASE_KEY'], 
     'Authorization': f"Bearer {os.environ['SUPABASE_KEY']}"}
try:
    gs = json.loads(urllib.request.urlopen(urllib.request.Request(
        f"{os.environ['SUPABASE_URL']}/rest/v1/long_edge_shadow?select=id,status,direction,slot,pnl,exit_reason&order=id.asc",
        headers=h), timeout=10).read())
    closed = [g for g in gs if g['status']=='CLOSED']
    opens = [g for g in gs if g['status']=='OPEN']
    tp = sum(1 for g in closed if g.get('exit_reason')=='TP')
    stop = sum(1 for g in closed if g.get('exit_reason')=='STOP')
    pnl = sum(float(g.get('pnl') or 0) for g in closed)
    print(f"  Toplam: {len(gs)} ({len(closed)} kapalı, {len(opens)} açık)")
    print(f"  Kapalı: {tp} TP + {stop} STOP  |  sim PnL: ${pnl:+.0f}")
    if opens:
        print(f"  Açık ghost:")
        for g in opens:
            print(f"    #{g['id']} {g['direction']} {g['slot']}")
    n_lim = 20
    if len(closed) >= n_lim:
        print(f"  ✓ Sample eşiği geçildi (n={len(closed)}, hedef ≥{n_lim}) — momentum filter analizi zamanı")
    else:
        print(f"  ⏳ Sample eşiği altı (n={len(closed)}/{n_lim}, {n_lim-len(closed)} ghost daha gerek)")
except Exception as e:
    print(f"  HATA: {e}")
PYEOF

echo ""
echo "======================================================================"
echo " Detay: python3 analyze_edge_shadow.py"
echo "======================================================================"
