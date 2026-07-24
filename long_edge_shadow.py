"""
long_edge_shadow.py — Persistent ghost LONG/SHORT log for edge measurement.

Amaç: flip'ten UZAK bölgede (flip_dist ∈ [2%, 10%]) 5 slot band'ta LONG + SHORT
ghost trade'ler biriktir, sample doldukça edge dağılımını gör.

Tasarım:
- 5 slot × 2 direction = 10 paralel slot (bağımsız açılır)
- Tek pozisyon SLOT BAŞINA (aynı slot'ta açık ghost varsa yeni açma)
- Yol B: tek ghost + metadata (bull_tech, pyramid_total, gex_z, funding_z, rsi)
- 30 gün timeout
- LONG: long_ok_real=True AND in_positive_real=True (SIKI)
- SHORT: spot<flip AND flip_dist>=2% AND in_positive_real=False (simetrik lokal)

Live trade akışına DOKUNMAZ. Sadece Supabase'e ghost yazar/günceller.
Mevcut flip_shadow'a paralel çalışır, ilgili değil.
"""

import os, json, urllib.request
from datetime import datetime, timezone
from urllib.error import URLError, HTTPError

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# ─────────────────────────────────────────────────────
# Slot band tanımları — 5 slot, LONG ve SHORT için aynı
# ─────────────────────────────────────────────────────
SLOTS = [
    ("S1", 2.0, 3.0),
    ("S2", 3.0, 4.0),
    ("S3", 4.0, 5.0),
    ("S4", 5.0, 7.0),
    ("S5", 7.0, 10.0),
]

ATR_STOP_MULT = 1.5
ATR_TP_MULT = 6.0
CAPITAL = 10000
RISK_PCT = 0.02
LEVERAGE = 2
TIMEOUT_DAYS = 30

# ─────────────────────────────────────────────────────
# Supabase REST helpers
# ─────────────────────────────────────────────────────
def _req(method, path, body=None, timeout=15):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body_bytes = r.read()
            if not body_bytes:
                return []
            return json.loads(body_bytes)
    except (URLError, HTTPError) as e:
        print(f"[EDGE_SHADOW] Supabase {method} error: {e}")
        return None

def _get(path):
    return _req("GET", path)

def _post(table, row):
    return _req("POST", table, row)

def _patch(path, row):
    return _req("PATCH", path, row)

# ─────────────────────────────────────────────────────
# Slot seçimi
# ─────────────────────────────────────────────────────
def find_slot(flip_dist_pct):
    """flip_dist_pct → slot adı ve band string. Uygun slot yoksa (None, None)."""
    for name, lo, hi in SLOTS:
        if lo <= flip_dist_pct < hi:
            return name, f"{lo:.0f}-{hi:.0f}%"
    return None, None

# ─────────────────────────────────────────────────────
# Açık ghost var mı kontrolü (slot + direction bazında)
# ─────────────────────────────────────────────────────
def open_ghost_exists(direction, slot):
    """O slot'ta o direction'da açık ghost varsa True."""
    rows = _get(f"long_edge_shadow?status=eq.OPEN&direction=eq.{direction}&slot=eq.{slot}&select=id&limit=1")
    return bool(rows)

# ─────────────────────────────────────────────────────
# Ghost açma
# ─────────────────────────────────────────────────────
def open_ghost(direction, spot, flip_point, flip_dist_pct, atr, metadata):
    """Yeni ghost trade aç. metadata dict: bull_tech, bear_tech, pyramid_total, gex_z, funding_z, rsi"""
    slot, band = find_slot(flip_dist_pct)
    if slot is None:
        return None
    if atr is None or atr <= 0:
        return None
    if open_ghost_exists(direction, slot):
        return None  # o slot dolu

    if direction == "LONG":
        stop = spot - atr * ATR_STOP_MULT
        tp = spot + atr * ATR_TP_MULT
    else:  # SHORT
        stop = spot + atr * ATR_STOP_MULT
        tp = spot - atr * ATR_TP_MULT

    risk_dollars = CAPITAL * RISK_PCT
    size = round(risk_dollars / (atr * ATR_STOP_MULT), 4)
    if size <= 0:
        return None

    row = {
        "direction": direction,
        "slot": slot,
        "slot_band": band,
        "entry": round(spot, 2),
        "spot0": round(spot, 2),
        "flip_at_entry": round(flip_point, 2),
        "flip_dist_pct": round(flip_dist_pct, 4),
        "atr": round(atr, 2),
        "stop": round(stop, 2),
        "tp": round(tp, 2),
        "size": size,
        "bull_tech": metadata.get("bull_tech"),
        "bear_tech": metadata.get("bear_tech"),
        "pyramid_total": metadata.get("pyramid_total"),
        "gex_z": metadata.get("gex_z"),
        "funding_z": metadata.get("funding_z"),
        "rsi": metadata.get("rsi"),
        "status": "OPEN",
        "peak": round(spot, 2),
    }
    result = _post("long_edge_shadow", row)
    if result:
        print(f"[EDGE_SHADOW] {direction} {slot} ({band}) ghost açıldı entry={spot:.0f} "
              f"stop={stop:.0f} tp={tp:.0f} flip_dist={flip_dist_pct:.2f}%")
    return result

# ─────────────────────────────────────────────────────
# PnL hesap (mevcut trader ile aynı formül)
# ─────────────────────────────────────────────────────
def calc_ghost_pnl(entry, exit_price, size, direction, days_held):
    if direction == "LONG":
        gross = (exit_price - entry) * size * LEVERAGE
    else:
        gross = (entry - exit_price) * size * LEVERAGE
    notional = (entry + exit_price) / 2 * size
    fees = notional * 0.0005 * 2
    slip = notional * 0.0002 * 2
    funding = notional * 0.00027 * max(days_held, 0)
    return round(gross - fees - slip - funding, 2)

# ─────────────────────────────────────────────────────
# Açık ghost'ları güncelle (TP/SL/TIMEOUT kontrol + peak update)
# ─────────────────────────────────────────────────────
def update_open_ghosts(price):
    """Her tick'te çağrılır — açık ghost'ların lifecycle'ını yürütür."""
    open_rows = _get("long_edge_shadow?status=eq.OPEN&select=*&limit=100")
    if not open_rows:
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    now_ts = datetime.now(timezone.utc)

    for g in open_rows:
        gid = g["id"]
        direction = g["direction"]
        entry = float(g["entry"])
        stop = float(g["stop"])
        tp = float(g["tp"])
        size = float(g["size"])
        peak = float(g.get("peak") or entry)
        opened_at = g["opened_at"]
        try:
            opened_dt = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
        except Exception:
            continue
        days_held = (now_ts - opened_dt).total_seconds() / 86400

        # Peak güncelle
        if direction == "LONG" and price > peak:
            peak = price
            _patch(f"long_edge_shadow?id=eq.{gid}", {"peak": round(peak, 2)})
        elif direction == "SHORT" and price < peak:
            peak = price
            _patch(f"long_edge_shadow?id=eq.{gid}", {"peak": round(peak, 2)})

        # Exit kontrolü
        exit_reason = None
        exit_price = None

        if direction == "LONG":
            if price <= stop:
                exit_reason, exit_price = "STOP", stop
            elif price >= tp:
                exit_reason, exit_price = "TP", tp
        else:  # SHORT
            if price >= stop:
                exit_reason, exit_price = "STOP", stop
            elif price <= tp:
                exit_reason, exit_price = "TP", tp

        # Timeout
        if exit_reason is None and days_held >= TIMEOUT_DAYS:
            exit_reason, exit_price = "EXPIRED", price

        if exit_reason:
            pnl = calc_ghost_pnl(entry, exit_price, size, direction, days_held)
            _patch(f"long_edge_shadow?id=eq.{gid}", {
                "status": "CLOSED",
                "exit_at": now_iso,
                "exit_price": round(exit_price, 2),
                "exit_reason": exit_reason,
                "pnl": pnl,
                "days_held": round(days_held, 2),
            })
            print(f"[EDGE_SHADOW] {direction} {g['slot']} {exit_reason} @${exit_price:.0f} "
                  f"held={days_held:.1f}d PnL:${pnl:+.0f}")

# ─────────────────────────────────────────────────────
# Ana entry point (her tick'te çağrılır)
# ─────────────────────────────────────────────────────
def process_edge_ghosts(price, gamma_analysis, metadata):
    """
    Ana entry: her cron tick'inde 1x çağrılır.
    - Önce açık ghost'ları güncelle (peak/TP/SL/timeout)
    - Sonra yeni ghost'lar için LONG + SHORT tetik kontrolü
    
    gamma_analysis: snapshot.gamma_analysis dict
      required: long_ok_real, in_positive_real, flip_point_real, flip_dist_real_pct
    metadata: {bull_tech, bear_tech, pyramid_total, gex_z, funding_z, rsi}
    """
    try:
        update_open_ghosts(price)
    except Exception as e:
        print(f"[EDGE_SHADOW] update error: {e}")

    ga = gamma_analysis or {}
    flip_real = ga.get("flip_point_real")
    dist_pct = ga.get("flip_dist_real_pct")
    long_ok = ga.get("long_ok_real")
    in_pos = ga.get("in_positive_real")

    if flip_real is None or dist_pct is None:
        return  # observe-only data yok, atla

    atr = metadata.get("atr")
    if atr is None or atr <= 0:
        return

    dist_abs = abs(float(dist_pct))
    if dist_abs < 2.0 or dist_abs > 10.0:
        return  # slot dışı

    # LONG tetik: SIKI (long_ok_real AND in_positive_real)
    if long_ok is True and in_pos is True:
        try:
            open_ghost("LONG", price, flip_real, dist_abs, atr, metadata)
        except Exception as e:
            print(f"[EDGE_SHADOW] LONG open error: {e}")

    # SHORT tetik: lokal formül (spot < flip AND dist >= 2% AND in_positive_real == False)
    if price < flip_real and dist_abs >= 2.0 and in_pos is False:
        try:
            open_ghost("SHORT", price, flip_real, dist_abs, atr, metadata)
        except Exception as e:
            print(f"[EDGE_SHADOW] SHORT open error: {e}")
