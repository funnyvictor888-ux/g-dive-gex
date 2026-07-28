#!/usr/bin/env python3
"""
edge_shadow_cron.py — Standalone cron entry point for long_edge_shadow.

Hetzner cron'una eklenir. Her 5 dakikada:
  1. Supabase'den son snapshot'u okur (gamma_analysis içinde long_ok_real, 
     flip_dist_real_pct, in_positive_real vb.)
  2. Aynı timestamp'e eşleşen alignment_log kaydını okur (bull_tech, bear_tech, 
     atr, rsi, gex_z, funding_z)
  3. long_edge_shadow.process_edge_ghosts() çağırır
  4. Ghost'lar Supabase'e yazılır/güncellenir

TRADER'A DOKUNMAZ. Bağımsız cron, izole.

Kurulum (Hetzner):
  cd /root/g-dive-gex
  # Bu dosyayı ve long_edge_shadow.py'yi buraya kopyala
  # Env: SUPABASE_URL, SUPABASE_KEY (trader ile aynı)
  # Cron entry (crontab -e):
  #   */5 * * * * cd /root/g-dive-gex && /usr/bin/python3 edge_shadow_cron.py >> /root/g-dive-gex/edge_shadow.log 2>&1
"""

import os, sys, json, urllib.request
from datetime import datetime, timezone
from urllib.error import URLError, HTTPError

# .env yükle (varsa) — trader ile aynı pattern
def _load_env():
    for env_path in [".env", "/root/g-dive-gex/.env", os.path.expanduser("~/gdive-dashboard/.env")]:
        if os.path.exists(env_path):
            try:
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
                return env_path
            except Exception:
                continue
    return None

_env_loaded = _load_env()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print(f"[EDGE_CRON] HATA: SUPABASE_URL veya SUPABASE_KEY yok. .env yolu: {_env_loaded}")
    sys.exit(1)

# long_edge_shadow modülü import
try:
    from long_edge_shadow import process_edge_ghosts
except ImportError as e:
    print(f"[EDGE_CRON] HATA: long_edge_shadow.py bulunamadı — dosya aynı dizinde mi?")
    print(f"           {e}")
    sys.exit(1)


def sb_get(path, timeout=30):
    """Supabase REST GET."""
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except (URLError, HTTPError) as e:
        print(f"[EDGE_CRON] Supabase GET error ({path}): {e}")
        return None


def main():
    ts_now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[EDGE_CRON] {ts_now} başladı")

    # 1) Son snapshot
    snapshots = sb_get(
        "snapshots?"
        "select=id,timestamp,spot,gamma_analysis,pyramid_total"
        "&order=id.desc&limit=1"
    )
    if not snapshots:
        print("[EDGE_CRON] Snapshot yok, atlandı.")
        return
    snap = snapshots[0]
    snap_ts = snap["timestamp"]
    price = float(snap["spot"])
    gamma_analysis = snap.get("gamma_analysis") or {}
    pyramid_total = snap.get("pyramid_total")

    # 2) Eşleşen alignment_log — aynı snapshot_ts
    align_rows = sb_get(
        f"alignment_log?"
        f"snapshot_ts=eq.{snap_ts}"
        f"&select=bull_tech,bear_tech,rsi,atr,gex_z,funding_z"
        f"&limit=1"
    )
    align = align_rows[0] if align_rows else {}

    # 3) Metadata birleştir
    metadata = {
        "bull_tech": align.get("bull_tech"),
        "bear_tech": align.get("bear_tech"),
        "pyramid_total": pyramid_total,
        "gex_z": align.get("gex_z"),
        "funding_z": align.get("funding_z"),
        "rsi": align.get("rsi"),
        "atr": align.get("atr"),
    }

    # 4) Log — teşhis için
    lok = gamma_analysis.get("long_ok_real")
    fdist = gamma_analysis.get("flip_dist_real_pct")
    fpr = gamma_analysis.get("flip_point_real")
    ipr = gamma_analysis.get("in_positive_real")
    print(f"[EDGE_CRON] snapshot #{snap['id']} ts={snap_ts[:19]} "
          f"spot={price:.0f} flip_real={fpr} dist={fdist} "
          f"long_ok={lok} in_pos={ipr}")
    print(f"[EDGE_CRON] metadata: bull_tech={metadata['bull_tech']} "
          f"bear_tech={metadata['bear_tech']} atr={metadata['atr']} "
          f"pyramid={metadata['pyramid_total']}")

    if metadata.get("atr") is None:
        print("[EDGE_CRON] ATR yok — alignment_log eşleşmedi, ghost açılmaz.")
        # Sadece açık ghost'ları güncelle (peak/timeout) mümkün ise atlamayalım
        # ama process_edge_ghosts atr olmadan open_ghost yapmaz zaten
    
    # 5) Ghost'ları işle (update + trigger)
    try:
        process_edge_ghosts(
            price=price,
            gamma_analysis=gamma_analysis,
            metadata=metadata,
        )
    except Exception as e:
        print(f"[EDGE_CRON] process_edge_ghosts hatası: {type(e).__name__}: {e}")
        raise

    print(f"[EDGE_CRON] tamamlandı")


if __name__ == "__main__":
    main()
