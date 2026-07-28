#!/usr/bin/env python3
"""
long_short_edge_backtest.py

Amaç: C4'ün LONG ve SHORT edge'ini tarihsel snapshot'lar üzerinden ölçmek.

Aşama 1 (KALİBRASYON, ZORUNLU):
  18-20 Jul canlı `flip_point_real` vs approximate flip hesap uyumu.
  Uyum %80+ değilse SCRIPT DURUR — retrospektif güvenilmez.

Aşama 2 (BACKTEST):
  16 Haz - 17 Tem (canlı flip_real yokken) approximate flip ile
  paralel LONG + SHORT ghost trade'ler aç, ATR stop/TP ile çöz,
  Deribit 4H bar ile mark-to-market, rejime etiketle.

Kurallar:
- Tek pozisyon (aynı anda bir LONG veya bir SHORT açık, ikisi birden değil)
- Backtest sonucu KANIT değildir — 20-30 gerçek trade eşiği hâlâ geçerli.
- Bu sadece "acaba" sorusunun cevabı, karar temeli değil, karar HAZIRLIĞI.
- flip_dist [2%, 5%] band — çok yakın flip_near, çok uzak zayıf edge.
"""

import os, json, urllib.request, time
from datetime import datetime, timezone
from collections import defaultdict

SUPABASE_URL = "https://gigkmjutnucssgwcnegn.supabase.co"
SUPABASE_KEY = "sb_publishable_jiFBPVGeFXKl1myvEjTI8g_KKUenCmW"

CALIB_START = "2026-07-18T00:00:00"
CALIB_END = "2026-07-20T23:59:59"
BACKTEST_START = "2026-06-16T00:00:00"
BACKTEST_END = "2026-07-17T23:59:59"

FLIP_DIST_MIN = 2.0
FLIP_DIST_MAX = 5.0
ATR_STOP_MULT = 1.5
ATR_TP_MULT = 6.0
CAPITAL = 10000
RISK_PCT = 0.02
LEVERAGE = 2

# ─────────────────────────────────────────────────────
# Supabase helpers
# ─────────────────────────────────────────────────────
def sb_get(path, timeout=60):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def paginate(path_base, page_size=1000, max_pages=20):
    """Supabase için ofset paginasyon."""
    rows = []
    for pg in range(max_pages):
        offset = pg * page_size
        sep = "&" if "?" in path_base else "?"
        path = f"{path_base}{sep}limit={page_size}&offset={offset}"
        batch = sb_get(path)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
    return rows

# ─────────────────────────────────────────────────────
# Approximate gamma flip (retrospektif)
# ─────────────────────────────────────────────────────
def approx_flip(pos_nodes, neg_nodes):
    """
    pos_gex_nodes + neg_gex_nodes birleştir, strike sırala, cumulative
    net_gex hesapla, ilk sign-change'i bul (linear interpolation ile).
    Dönüş: flip price (float) veya None.
    """
    if not pos_nodes and not neg_nodes:
        return None
    nodes = []
    for n in (pos_nodes or []):
        if n.get("strike") is not None and n.get("net_gex") is not None:
            nodes.append((float(n["strike"]), float(n["net_gex"])))
    for n in (neg_nodes or []):
        if n.get("strike") is not None and n.get("net_gex") is not None:
            nodes.append((float(n["strike"]), float(n["net_gex"])))
    if len(nodes) < 2:
        return None
    nodes.sort(key=lambda x: x[0])
    
    cum = 0.0
    prev_strike, prev_cum = None, None
    for strike, gex in nodes:
        cum += gex
        if prev_cum is not None and prev_cum * cum < 0:
            # sign change — linear interp
            if cum - prev_cum == 0:
                return strike
            frac = -prev_cum / (cum - prev_cum)
            return prev_strike + frac * (strike - prev_strike)
        prev_strike, prev_cum = strike, cum
    # No zero-crossing found
    return None

# ─────────────────────────────────────────────────────
# Aşama 1: Kalibrasyon
# ─────────────────────────────────────────────────────
def calibration():
    print("=" * 70)
    print("AŞAMA 1: KALİBRASYON (18-20 Jul, canlı flip_real vs approximate)")
    print("=" * 70)
    
    path = (f"snapshots?"
            f"timestamp=gte.{CALIB_START}&timestamp=lte.{CALIB_END}"
            f"&select=timestamp,spot,pos_gex_nodes,neg_gex_nodes,gamma_analysis"
            f"&order=timestamp.asc")
    rows = paginate(path)
    print(f"Snapshot sayısı: {len(rows)}")
    
    matches = []
    misses = 0
    for r in rows:
        ga = r.get("gamma_analysis") or {}
        live_flip = ga.get("flip_point_real")
        if live_flip is None:
            misses += 1
            continue
        approx = approx_flip(r.get("pos_gex_nodes"), r.get("neg_gex_nodes"))
        if approx is None:
            misses += 1
            continue
        matches.append({
            "ts": r["timestamp"],
            "spot": r["spot"],
            "live": live_flip,
            "approx": approx,
            "diff_pct": abs(live_flip - approx) / live_flip * 100
        })
    
    if not matches:
        print("HATA: hiç eşleşme yok, kalibrasyon yapılamaz.")
        return False, 0.0
    
    n = len(matches)
    diffs = [m["diff_pct"] for m in matches]
    within_1pct = sum(1 for d in diffs if d <= 1.0)
    within_2pct = sum(1 for d in diffs if d <= 2.0)
    within_5pct = sum(1 for d in diffs if d <= 5.0)
    mean_diff = sum(diffs) / n
    max_diff = max(diffs)
    
    print(f"\nEşleşme: {n} snapshot (missed: {misses})")
    print(f"Ortalama fark: {mean_diff:.2f}%")
    print(f"Max fark: {max_diff:.2f}%")
    print(f"Fark <= 1%:  {within_1pct} / {n} ({within_1pct/n*100:.1f}%)")
    print(f"Fark <= 2%:  {within_2pct} / {n} ({within_2pct/n*100:.1f}%)")
    print(f"Fark <= 5%:  {within_5pct} / {n} ({within_5pct/n*100:.1f}%)")
    
    # Örnek 5 satır göster
    print("\nİlk 5 örnek:")
    for m in matches[:5]:
        print(f"  {m['ts'][:16]}  spot={m['spot']:.0f}  live={m['live']:.0f}  "
              f"approx={m['approx']:.0f}  diff={m['diff_pct']:.2f}%")
    
    # Karar
    agreement_5pct = within_5pct / n * 100
    print(f"\nUyum (fark <= 5%): {agreement_5pct:.1f}%")
    if agreement_5pct >= 80.0:
        print("✓ KALİBRASYON GEÇTİ, Aşama 2'ye devam.")
        return True, agreement_5pct
    else:
        print("✗ KALİBRASYON YETERSİZ (%80 altı). Backtest güvenilmez, DURUYORUZ.")
        return False, agreement_5pct

# ─────────────────────────────────────────────────────
# Deribit 4H bar fetch
# ─────────────────────────────────────────────────────
def fetch_deribit_4h(start_iso, end_iso):
    """Deribit BTC-PERPETUAL 4H OHLC."""
    start_ms = int(datetime.fromisoformat(start_iso).replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime.fromisoformat(end_iso).replace(tzinfo=timezone.utc).timestamp() * 1000)
    url = (f"https://www.deribit.com/api/v2/public/get_tradingview_chart_data?"
           f"instrument_name=BTC-PERPETUAL&resolution=240"
           f"&start_timestamp={start_ms}&end_timestamp={end_ms}")
    req = urllib.request.Request(url, headers={"User-Agent": "backtest/edge/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())
    res = d.get("result", {})
    bars = []
    for i in range(len(res.get("ticks", []))):
        bars.append({
            "ts": res["ticks"][i] / 1000,
            "o": res["open"][i], "h": res["high"][i],
            "l": res["low"][i], "c": res["close"][i]
        })
    return bars

# ─────────────────────────────────────────────────────
# ATR (14-period on 4H)
# ─────────────────────────────────────────────────────
def compute_atr(bars, period=14):
    trs = []
    for i, b in enumerate(bars):
        prev_c = bars[max(0, i-1)]["c"]
        tr = max(b["h"] - b["l"], abs(b["h"] - prev_c), abs(b["l"] - prev_c))
        trs.append(tr)
    # EMA of TR
    k = 2 / (period + 1)
    e = trs[0]
    out = []
    for tr in trs:
        e = tr * k + e * (1 - k)
        out.append(e)
    return out

# ─────────────────────────────────────────────────────
# Aşama 2: Backtest
# ─────────────────────────────────────────────────────
def resolve_ghost(entry, stop, tp, direction, entry_ts, bars):
    """Ghost trade'i sonraki bar'larda çöz. Return: (exit_price, exit_reason, exit_ts, days_held)."""
    for b in bars:
        if b["ts"] <= entry_ts:
            continue
        if direction == "LONG":
            if b["l"] <= stop:
                return (stop, "STOP", b["ts"], (b["ts"] - entry_ts) / 86400)
            if b["h"] >= tp:
                return (tp, "TP", b["ts"], (b["ts"] - entry_ts) / 86400)
        else:  # SHORT
            if b["h"] >= stop:
                return (stop, "STOP", b["ts"], (b["ts"] - entry_ts) / 86400)
            if b["l"] <= tp:
                return (tp, "TP", b["ts"], (b["ts"] - entry_ts) / 86400)
    # Not resolved in window
    if bars:
        return (bars[-1]["c"], "UNRESOLVED", bars[-1]["ts"], (bars[-1]["ts"] - entry_ts) / 86400)
    return (entry, "NO_DATA", entry_ts, 0)

def calc_pnl(entry, exit_price, size, direction, days_held):
    if direction == "LONG":
        gross = (exit_price - entry) * size * LEVERAGE
    else:
        gross = (entry - exit_price) * size * LEVERAGE
    notional = (entry + exit_price) / 2 * size
    fees = notional * 0.0005 * 2  # taker in/out
    slip = notional * 0.0002 * 2
    funding = notional * 0.00027 * days_held
    return gross - fees - slip - funding

def classify_regime(spot, spot_history):
    """20-day SMA'ya göre rejim: bull/bear/choppy."""
    if len(spot_history) < 20:
        return "unknown"
    sma20 = sum(spot_history[-20:]) / 20
    ratio = spot / sma20
    if ratio > 1.03:
        return "bull"
    elif ratio < 0.97:
        return "bear"
    else:
        return "choppy"

def backtest():
    print("\n" + "=" * 70)
    print(f"AŞAMA 2: BACKTEST ({BACKTEST_START[:10]} - {BACKTEST_END[:10]})")
    print("=" * 70)
    
    # Snapshot + alignment_log
    print("Snapshot çekiliyor...")
    snap_rows = paginate(
        f"snapshots?"
        f"timestamp=gte.{BACKTEST_START}&timestamp=lte.{BACKTEST_END}"
        f"&select=timestamp,spot,pos_gex_nodes,neg_gex_nodes"
        f"&order=timestamp.asc"
    )
    print(f"  {len(snap_rows)} snapshot")
    
    print("Alignment_log çekiliyor...")
    align_rows = paginate(
        f"alignment_log?"
        f"timestamp=gte.{BACKTEST_START}&timestamp=lte.{BACKTEST_END}"
        f"&select=snapshot_ts,bull_tech,bear_tech,e9,e21,e50,e200"
        f"&order=snapshot_ts.asc"
    )
    print(f"  {len(align_rows)} alignment satırı")
    
    # snapshot_ts → alignment lookup
    align_map = {a["snapshot_ts"]: a for a in align_rows}
    
    # Deribit 4H bars (backtest + buffer for stop resolution)
    print("Deribit 4H çekiliyor...")
    bars = fetch_deribit_4h(BACKTEST_START, "2026-07-25T00:00:00")
    print(f"  {len(bars)} 4H bar")
    if not bars:
        print("HATA: bar yok")
        return
    
    atrs = compute_atr(bars, period=14)
    
    # ATR lookup by timestamp — bar başlangıcı
    def atr_at(ts):
        # ts unix seconds
        for i in range(len(bars) - 1, -1, -1):
            if bars[i]["ts"] <= ts:
                return atrs[i]
        return atrs[0] if atrs else 100.0
    
    ghosts_long = []
    ghosts_short = []
    spot_history = []
    
    # tek pozisyon kuralı
    long_open = False
    short_open = False
    long_active_close_ts = 0
    short_active_close_ts = 0
    
    print("\nGhost trade'ler simüle ediliyor...")
    for r in snap_rows:
        ts_iso = r["timestamp"]
        try:
            ts_unix = datetime.fromisoformat(ts_iso).replace(tzinfo=timezone.utc).timestamp()
        except:
            continue
        spot = float(r["spot"])
        spot_history.append(spot)
        
        # Approximate flip
        flip = approx_flip(r.get("pos_gex_nodes"), r.get("neg_gex_nodes"))
        if flip is None:
            continue
        
        # Uzak-band koşulu
        dist_pct = abs(spot - flip) / spot * 100
        if dist_pct < FLIP_DIST_MIN or dist_pct > FLIP_DIST_MAX:
            continue
        
        # Alignment
        align = align_map.get(ts_iso)
        if not align:
            continue
        bull_tech = bool(align.get("bull_tech"))
        bear_tech = bool(align.get("bear_tech"))
        
        # ATR
        atr = atr_at(ts_unix)
        
        # LONG entry
        if bull_tech and spot > flip and not long_open and ts_unix >= long_active_close_ts:
            stop = spot - atr * ATR_STOP_MULT
            tp = spot + atr * ATR_TP_MULT
            risk = CAPITAL * RISK_PCT
            size = round(risk / (atr * ATR_STOP_MULT), 4)
            exit_price, reason, exit_ts, days = resolve_ghost(spot, stop, tp, "LONG", ts_unix, bars)
            pnl = calc_pnl(spot, exit_price, size, "LONG", days)
            regime = classify_regime(spot, spot_history)
            ghosts_long.append({
                "entry_ts": ts_iso, "entry": spot, "stop": stop, "tp": tp,
                "size": size, "atr": atr, "flip": flip, "dist_pct": dist_pct,
                "exit_price": exit_price, "exit_reason": reason,
                "days": days, "pnl": pnl, "regime": regime
            })
            long_open = True
            long_active_close_ts = exit_ts
        
        if long_open and ts_unix >= long_active_close_ts:
            long_open = False
        
        # SHORT entry
        if bear_tech and spot < flip and not short_open and ts_unix >= short_active_close_ts:
            stop = spot + atr * ATR_STOP_MULT
            tp = spot - atr * ATR_TP_MULT
            risk = CAPITAL * RISK_PCT
            size = round(risk / (atr * ATR_STOP_MULT), 4)
            exit_price, reason, exit_ts, days = resolve_ghost(spot, stop, tp, "SHORT", ts_unix, bars)
            pnl = calc_pnl(spot, exit_price, size, "SHORT", days)
            regime = classify_regime(spot, spot_history)
            ghosts_short.append({
                "entry_ts": ts_iso, "entry": spot, "stop": stop, "tp": tp,
                "size": size, "atr": atr, "flip": flip, "dist_pct": dist_pct,
                "exit_price": exit_price, "exit_reason": reason,
                "days": days, "pnl": pnl, "regime": regime
            })
            short_open = True
            short_active_close_ts = exit_ts
        
        if short_open and ts_unix >= short_active_close_ts:
            short_open = False
    
    # ─────────────────────────────────────────────────────
    # Raporla
    # ─────────────────────────────────────────────────────
    def analyze(ghosts, label):
        print(f"\n{'='*70}")
        print(f"{label}: {len(ghosts)} ghost")
        print("=" * 70)
        if not ghosts:
            print("  yok")
            return
        by_reason = defaultdict(list)
        by_regime = defaultdict(list)
        for g in ghosts:
            by_reason[g["exit_reason"]].append(g["pnl"])
            by_regime[g["regime"]].append(g["pnl"])
        
        total_pnl = sum(g["pnl"] for g in ghosts)
        wins = [g for g in ghosts if g["pnl"] > 0]
        wr = len(wins) / len(ghosts) * 100
        avg_win = sum(g["pnl"] for g in wins) / len(wins) if wins else 0
        losses = [g for g in ghosts if g["pnl"] <= 0]
        avg_loss = sum(g["pnl"] for g in losses) / len(losses) if losses else 0
        avg_days = sum(g["days"] for g in ghosts) / len(ghosts)
        
        print(f"  Toplam PnL: ${total_pnl:+.0f}")
        print(f"  Win rate: {wr:.1f}% ({len(wins)}W / {len(losses)}L)")
        print(f"  Ort kazanç: ${avg_win:+.0f} | Ort kayıp: ${avg_loss:+.0f}")
        print(f"  Ort tutma: {avg_days:.1f} gün")
        
        print(f"\n  Exit dağılımı:")
        for reason in sorted(by_reason.keys()):
            pnls = by_reason[reason]
            print(f"    {reason:12s}: {len(pnls):>3} × ${sum(pnls)/len(pnls):+.0f} avg (toplam ${sum(pnls):+.0f})")
        
        print(f"\n  Rejim dağılımı:")
        for reg in sorted(by_regime.keys()):
            pnls = by_regime[reg]
            wins_r = sum(1 for p in pnls if p > 0)
            print(f"    {reg:8s}: {len(pnls):>3} ghost, {wins_r}W/{len(pnls)-wins_r}L, ${sum(pnls):+.0f}")
    
    analyze(ghosts_long, "LONG GHOST")
    analyze(ghosts_short, "SHORT GHOST")
    
    # Karşılaştırma
    print(f"\n{'='*70}")
    print("KARŞILAŞTIRMA")
    print("=" * 70)
    print(f"  LONG:  {len(ghosts_long):>3} ghost, ${sum(g['pnl'] for g in ghosts_long):+.0f}")
    print(f"  SHORT: {len(ghosts_short):>3} ghost, ${sum(g['pnl'] for g in ghosts_short):+.0f}")

# ─────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────
if __name__ == "__main__":
    ok, agreement = calibration()
    if not ok:
        print(f"\nKalibrasyon başarısız (uyum {agreement:.1f}%). Backtest atlandı.")
        exit(1)
    backtest()
