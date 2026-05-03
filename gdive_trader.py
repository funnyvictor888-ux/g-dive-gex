#!/usr/bin/env python3
"""
G-DIVE Auto Trader — GitHub Actions'ta çalışır
Her 5 dakikada piyasa koşullarını kontrol eder, trade açar/kapatır
"""
import json, urllib.request, urllib.error, os
from datetime import datetime

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal"
}

def supa_get(path):
    try:
        req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/{path}", headers=HEADERS)
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"[ERR] GET {path}: {e}")
        return []

def supa_post(path, data):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/{path}", data=body, headers=HEADERS, method="POST")
        urllib.request.urlopen(req)
        return True
    except Exception as e:
        print(f"[ERR] POST {path}: {e}")
        return False

def supa_patch(path, data):
    try:
        body = json.dumps(data).encode()
        h = dict(HEADERS)
        h["Prefer"] = "return=minimal"
        req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/{path}", data=body, headers=h, method="PATCH")
        urllib.request.urlopen(req)
        return True
    except Exception as e:
        print(f"[ERR] PATCH {path}: {e}")
        return False

def get_btc_price():
    try:
        req = urllib.request.Request("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
        with urllib.request.urlopen(req) as r:
            return float(json.loads(r.read())["price"])
    except:
        return None


# ── Range Trade Modülü ───────────────────────────────────────────
def detect_range_mode(snapshots):
    """
    Son 12 snapshot (1 saat) incelenir.
    Fiyat belirli bir band içinde kalıyorsa range modu.
    """
    if len(snapshots) < 6:
        return False, 0, 0
    
    spots = [s.get("spot", 0) for s in snapshots if s.get("spot")]
    if len(spots) < 6:
        return False, 0, 0
    
    high = max(spots)
    low = min(spots)
    range_pct = (high - low) / low * 100
    
    # %3'ten dar range = range modu
    is_range = range_pct < 3.0
    return is_range, high, low

def check_range_entry(spot, call_res, put_sup, max_pain, iv_rank, gex, snapshots):
    """
    Range trade giriş koşulları:
    - GEX pozitif (dealer söndürüyor)
    - IV Rank < 45% (düşük volatilite beklentisi)
    - Spot, duvarlardan birine yakın
    """
    if not call_res or not put_sup:
        return None, None, None, None
    
    if gex <= 0:
        return None, None, None, None
    
    if iv_rank > 45:
        return None, None, None, None
    
    is_range, range_high, range_low = detect_range_mode(snapshots)
    if not is_range:
        return None, None, None, None
    
    range_width = call_res - put_sup
    
    # Alt duvara yakın mı? (Put Support ±%2)
    dist_to_put = (spot - put_sup) / spot * 100
    if dist_to_put < 2.0:
        # RANGE LONG
        entry = spot
        stop = put_sup * 0.985  # Put Support %1.5 altı
        tp = max_pain if max_pain and abs(max_pain - spot) > abs(put_sup - spot) else put_sup + range_width * 0.5
        return "RANGE_LONG", entry, stop, tp
    
    # Üst duvara yakın mı? (Call Resistance ±%2)
    dist_to_call = (call_res - spot) / spot * 100
    if dist_to_call < 2.0:
        # RANGE SHORT
        entry = spot
        stop = call_res * 1.015  # Call Resistance %1.5 üstü
        tp = max_pain if max_pain and abs(max_pain - spot) > abs(call_res - spot) else call_res - range_width * 0.5
        return "RANGE_SHORT", entry, stop, tp
    
    return None, None, None, None

def get_recent_snapshots(supabase_url, supabase_key, limit=12):
    """Son 12 snapshot'ı çek (yaklaşık 1 saat)."""
    try:
        req = urllib.request.Request(
            f"{supabase_url}/rest/v1/snapshots?order=id.desc&limit={limit}",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}"
            }
        )
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except:
        return []


def run_trader():
    print(f"[TRADER] {datetime.utcnow().isoformat()} başlıyor...")
    
    # Son snapshot al
    rows = supa_get("snapshots?order=id.desc&limit=1")
    if not rows:
        print("[TRADER] Snapshot yok, çıkılıyor")
        return
    
    d = rows[0]
    spot = d.get("spot", 0)
    regime = d.get("regime", "")
    gamma = d.get("gamma_regime", "")
    gex = d.get("total_net_gex", 0)
    hvl = d.get("hvl", 0)
    long_ok = d.get("long_ok", False)
    short_ok = d.get("short_ok", False)
    flip = d.get("flip_point", hvl)
    expiry = d.get("expiry") or {}
    max_pain = d.get("max_pain")
    call_res = d.get("call_resistance")
    put_sup = d.get("put_support")
    iv_rank = d.get("iv_rank", 0)
    term_shape = d.get("term_shape", "")
    layer = d.get("layer_budget") or {}
    
    print(f"[TRADER] Spot:{spot} Regime:{regime} Gamma:{gamma} GEX:{gex:.0f}M long_ok:{long_ok}")
    
    # Canlı fiyat al
    price = get_btc_price() or spot
    
    # Açık trade'leri al
    open_trades = supa_get("trades?status=eq.OPEN")
    print(f"[TRADER] Açık trade: {len(open_trades)}")
    
    # Kill switch kontrolleri
    flip_near = flip and abs(price - flip) / price < 0.02
    expiry_day = expiry.get("expiry_day", False)
    expiry_week = expiry.get("expiry_week", False)
    expiry_scalar = expiry.get("expiry_scalar", 1.0)
    gamma_conflict = (long_ok and gamma == "SHORT_GAMMA") or (short_ok and gamma == "LONG_GAMMA")
    
    if flip_near:
        print(f"[TRADER] Flip yakın ({abs(price-flip)/price*100:.1f}%) — trade açılmıyor")
    if expiry_day:
        print("[TRADER] Expiry günü — trade açılmıyor")
    if gamma_conflict:
        print(f"[TRADER] Gamma çelişki — trade açılmıyor")
    
    # Açık trade'leri yönet
    for t in open_trades:
        entry = t.get("entry", 0)
        stop = t.get("stop", 0)
        tp = t.get("tp", 0)
        size = t.get("size", 0)
        direction = t.get("dir", "")
        trade_id = t.get("trade_id", t.get("id"))
        
        if direction == "LONG":
            unreal = (price - entry) * size
            print(f"[TRADER] LONG #{trade_id} Entry:{entry} Stop:{stop} TP:{tp} Unrealized:+${unreal:.0f}")
            
            # 21 DTE Kuralı (Overby)
            days_left = expiry.get("days_to_expiry", 30)
            if days_left <= 21 and not t.get("partial_closed"):
                pnl = (price - entry) * size
                if pnl > 0:
                    supa_patch(f"trades?trade_id=eq.{trade_id}", {
                        "status": "CLOSED", "exit_price": price,
                        "exit_date": datetime.utcnow().isoformat(),
                        "pnl": round(pnl, 2),
                        "notes": (t.get("notes","") + f" |21DTE d={days_left}")
                    })
                    print(f"[TRADER] 21DTE EXIT LONG @${price:.0f} PnL:${pnl:.0f}")
                    continue
            
            
            # 21 DTE Kuralı (Overby/McMillan) — expiry yakınsa kapat
            days_left = expiry.get("days_to_expiry", 30)
            if days_left <= 21 and not t.get("partial_closed"):
                pnl = (price - entry) * size
                if pnl > 0:  # Karda ise kapat
                    supa_patch(f"trades?trade_id=eq.{trade_id}", {
                        "status": "CLOSED", "exit_price": price,
                        "exit_date": datetime.utcnow().isoformat(),
                        "pnl": round(pnl, 2),
                        "notes": (t.get("notes","") + f" |21DTE_EXIT days={days_left}")
                    })
                    print(f"[TRADER] 21 DTE KURALI — LONG @${price:.0f} kapatıldı PnL:${pnl:.0f}")
                    continue
            
            # Stop hit
            if price <= stop:
                pnl = (stop - entry) * size
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "status": "CLOSED", "exit_price": stop,
                    "exit_date": datetime.utcnow().isoformat(),
                    "pnl": round(pnl, 2), "rr": -1,
                    "notes": (t.get("notes","") + " |STOP")
                })
                print(f"[TRADER] STOP HIT LONG @${stop} PnL:${pnl:.0f}")
            
            # 1/3 Move Exit (tastylive) — TP'nin 1/3'üne ulaştıysa %50 kapat
            elif price >= (entry + (tp - entry) / 3) and not t.get("partial_closed"):
                new_size = size / 2
                next_wall = call_res * 1.03 if call_res else tp * 1.03
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "size": new_size, "partial_closed": True, "tp": next_wall,
                    "notes": (t.get("notes","") + f" |1/3TP@{price:.0f}")
                })
                print(f"[TRADER] 1/3 MOVE EXIT LONG @${price:.0f} — %50 kapat, yeni TP:${next_wall:.0f}")
            
            # 1/3 Move Exit (tastylive)
            elif price >= (entry + (tp - entry) / 3) and not t.get("partial_closed") and (tp > entry):
                new_size = size / 2
                next_wall = call_res * 1.03 if call_res else tp * 1.03
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "size": new_size, "partial_closed": True, "tp": next_wall,
                    "notes": (t.get("notes","") + f" |1/3TP@{price:.0f}")
                })
                print(f"[TRADER] 1/3 EXIT LONG @${price:.0f} %50 kapat, TP→${next_wall:.0f}")
            
            # TP hit — tam TP
            elif price >= tp and not t.get("partial_closed"):
                if long_ok and not gamma_conflict:
                    # %50 kapat
                    new_size = size / 2
                    next_wall = call_res * 1.03 if call_res else tp * 1.03
                    supa_patch(f"trades?trade_id=eq.{trade_id}", {
                        "size": new_size, "partial_closed": True, "tp": next_wall,
                        "notes": (t.get("notes","") + f" |TP50@{tp}")
                    })
                    print(f"[TRADER] TP1 %50 LONG @${tp} — kalan devam, yeni TP:${next_wall:.0f}")
                else:
                    pnl = (tp - entry) * size
                    supa_patch(f"trades?trade_id=eq.{trade_id}", {
                        "status": "CLOSED", "exit_price": tp,
                        "exit_date": datetime.utcnow().isoformat(),
                        "pnl": round(pnl, 2), "rr": round((tp-entry)/(entry-stop), 2),
                        "notes": (t.get("notes","") + " |TP")
                    })
                    print(f"[TRADER] TP %100 LONG @${tp} PnL:${pnl:.0f}")
            
            # Rejim tersine döndü
            elif short_ok:
                pnl = (price - entry) * size
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "status": "CLOSED", "exit_price": price,
                    "exit_date": datetime.utcnow().isoformat(),
                    "pnl": round(pnl, 2),
                    "notes": (t.get("notes","") + " |REJIM")
                })
                print(f"[TRADER] REJİM DEĞİŞTİ — LONG kapatıldı @${price:.0f} PnL:${pnl:.0f}")
        
        elif direction == "SHORT":
            unreal = (entry - price) * size
            print(f"[TRADER] SHORT #{trade_id} Entry:{entry} Unrealized:+${unreal:.0f}")
            
            # 21 DTE Kuralı
            days_left = expiry.get("days_to_expiry", 30)
            if days_left <= 21 and not t.get("partial_closed"):
                pnl = (entry - price) * size
                if pnl > 0:
                    supa_patch(f"trades?trade_id=eq.{trade_id}", {
                        "status": "CLOSED", "exit_price": price,
                        "exit_date": datetime.utcnow().isoformat(),
                        "pnl": round(pnl, 2),
                        "notes": (t.get("notes","") + f" |21DTE_EXIT days={days_left}")
                    })
                    print(f"[TRADER] 21 DTE KURALI — SHORT @${price:.0f} kapatıldı PnL:${pnl:.0f}")
                    continue
            
            if price >= stop:
                pnl = (entry - stop) * size
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "status": "CLOSED", "exit_price": stop,
                    "exit_date": datetime.utcnow().isoformat(),
                    "pnl": round(pnl, 2), "rr": -1,
                    "notes": (t.get("notes","") + " |STOP")
                })
                print(f"[TRADER] STOP HIT SHORT @${stop} PnL:${pnl:.0f}")
            
            elif price <= tp and not t.get("partial_closed"):
                if short_ok:
                    new_size = size / 2
                    supa_patch(f"trades?trade_id=eq.{trade_id}", {
                        "size": new_size, "partial_closed": True,
                        "notes": (t.get("notes","") + f" |TP50@{tp}")
                    })
                    print(f"[TRADER] TP1 %50 SHORT @${tp}")
                else:
                    pnl = (entry - tp) * size
                    supa_patch(f"trades?trade_id=eq.{trade_id}", {
                        "status": "CLOSED", "exit_price": tp,
                        "exit_date": datetime.utcnow().isoformat(),
                        "pnl": round(pnl, 2), "rr": round((entry-tp)/(stop-entry), 2),
                        "notes": (t.get("notes","") + " |TP")
                    })
                    print(f"[TRADER] TP %100 SHORT @${tp} PnL:${pnl:.0f}")
            
            elif long_ok:
                pnl = (entry - price) * size
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "status": "CLOSED", "exit_price": price,
                    "exit_date": datetime.utcnow().isoformat(),
                    "pnl": round(pnl, 2),
                    "notes": (t.get("notes","") + " |REJIM")
                })
                print(f"[TRADER] REJİM — SHORT kapatıldı @${price:.0f}")
    
    # Yeni trade açma
    today = datetime.utcnow().strftime("%Y-%m-%d")
    today_trades = supa_get(f"trades?date=gte.{today}%2000:00")
    has_open = any(t.get("status") == "OPEN" for t in today_trades)
    
    if has_open:
        print("[TRADER] Bugün açık trade var — yeni açılmıyor")
        return
    
    # Recent snapshots for range detection
    recent_snaps = get_recent_snapshots(SUPABASE_URL, SUPABASE_KEY, 12)
    
    # IV Crush Kill Switch (McMillan) — Backwardation + ani IV düşüşü
    iv_crush = term_shape == "CONTANGO" and iv_rank < 25  # IV çok düşük, crush riskli değil
    iv_spike = term_shape == "BACKWARDATION" and iv_rank > 75  # IV yüksek + backwardation = sat premium değil al
    
    # IV Crush Kill Switch (McMillan) — Backwardation + ani IV düşüşü
    iv_crush = term_shape == "CONTANGO" and iv_rank < 25  # IV çok düşük, crush riskli değil
    iv_spike = term_shape == "BACKWARDATION" and iv_rank > 75  # IV yüksek + backwardation = sat premium değil al
    
    # IV Crush Kill Switch (McMillan) — Backwardation + ani IV düşüşü
    iv_crush = term_shape == "CONTANGO" and iv_rank < 25  # IV çok düşük, crush riskli değil
    iv_spike = term_shape == "BACKWARDATION" and iv_rank > 75  # IV yüksek + backwardation = sat premium değil al
    
    if flip_near or expiry_day or gamma_conflict:
        return
    
    if iv_spike and not (long_ok and gex > 0):
        print(f"[TRADER] IV Crush kilswitch — Backwardation IV {iv_rank:.0f}% > 75 → bekle")
        return
    
    if iv_spike and not (long_ok and gex > 0):
        print(f"[TRADER] IV Crush kilswitch — Backwardation IV {iv_rank:.0f}% > 75 → bekle")
        return
    
    if iv_spike and not (long_ok and gex > 0):
        print(f"[TRADER] IV Crush kilswitch — Backwardation IV {iv_rank:.0f}% > 75 → bekle")
        return
    
    fs = (layer.get("final_scalar") or 1.0) * expiry_scalar
    risk = 10000 * 0.02 * 3 * fs
    
    # ── tastylive: 45 DTE Entry Filtresi ─────────────────────────
    days_to_exp = expiry.get("days_to_expiry", 30)
    if days_to_exp < 7:
        print(f"[TRADER] tastylive 45DTE: Expiry {days_to_exp}g — çok yakın, bekle")
        return
    if days_to_exp > 60:
        print(f"[TRADER] tastylive 45DTE: Expiry {days_to_exp}g — çok uzak, 45DTE bekle")
        # Engelleme değil, uyarı — range trade hariç
    
    # ── tastylive: P50 Filtresi (Delta bazlı olasılık) ─────────────
    # Put Support mesafesinden basit olasılık hesabı
    def calc_p50(spot, stop, target):
        """Basit risk/reward bazlı P50 tahmini."""
        if not spot or not stop or not target: return 0.5
        risk = abs(spot - stop)
        reward = abs(target - spot)
        if risk <= 0: return 0.5
        rr = reward / risk
        # tastylive: RR > 1:1 ise P50 > 50% kabul
        return min(0.75, 0.4 + rr * 0.15)

    # ── tastylive: 45 DTE Entry Filtresi ─────────────────────────
    days_to_exp = expiry.get("days_to_expiry", 30)
    if days_to_exp < 7:
        print(f"[TRADER] tastylive 45DTE: Expiry {days_to_exp}g — çok yakın, bekle")
        return
    if days_to_exp > 60:
        print(f"[TRADER] tastylive 45DTE: Expiry {days_to_exp}g — çok uzak, 45DTE bekle")
        # Engelleme değil, uyarı — range trade hariç
    
    # ── tastylive: P50 Filtresi (Delta bazlı olasılık) ─────────────
    # Put Support mesafesinden basit olasılık hesabı
    def calc_p50(spot, stop, target):
        """Basit risk/reward bazlı P50 tahmini."""
        if not spot or not stop or not target: return 0.5
        risk = abs(spot - stop)
        reward = abs(target - spot)
        if risk <= 0: return 0.5
        rr = reward / risk
        # tastylive: RR > 1:1 ise P50 > 50% kabul
        return min(0.75, 0.4 + rr * 0.15)

    # ── Range Trade Kontrolü ──────────────────────────────────────
    range_signal, range_entry, range_stop, range_tp = check_range_entry(
        price, call_res, put_sup, max_pain, iv_rank, gex, recent_snaps
    )
    
    if range_signal and not flip_near and not expiry_day:
        dir_ = "LONG" if range_signal == "RANGE_LONG" else "SHORT"
        sz = round(risk / abs(range_entry - range_stop), 4) if range_stop and abs(range_entry - range_stop) > 0 else 0.001
        tr = {
            "trade_id": str(int(datetime.utcnow().timestamp()*1000)),
            "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            "dir": dir_,
            "entry": range_entry,
            "stop": round(range_stop, 0),
            "tp": round(range_tp, 0),
            "size": sz,
            "status": "OPEN",
            "regime": regime + "_RANGE",
            "signal": f"Range·{range_signal}",
            "notes": f"RANGE {dir_} · GEX +{gex:.0f}M · IV {iv_rank:.0f}% · CR ${call_res:.0f} PS ${put_sup:.0f}",
            "partial_closed": False
        }
        supa_post("trades", tr)
        print(f"[TRADER] ✅ RANGE {dir_} açıldı @${range_entry:.0f} Stop:${range_stop:.0f} TP:${range_tp:.0f}")
        return
    
    # ── Trend Trade (Normal Mod) ───────────────────────────────────
    if long_ok and gex > 0 and spot > hvl and iv_rank < 80:
        e = price
        sp = max(put_sup or e*0.93, e * 0.95)
        tp2 = max_pain if expiry_week and max_pain else (call_res or e * 1.07)
        sz = round(risk / abs(e - sp), 4)
        
        # tastylive P50 filtresi
        p50 = calc_p50(e, sp, tp2)
        if p50 < 0.45:
            print(f"[TRADER] P50 filtre: {p50:.0%} < 45% — LONG açılmıyor")
            return
        
        # tastylive 1/3 Move hedefi ekle — birinci çıkış
        one_third_tp = e + (tp2 - e) / 3
        
        # tastylive P50 filtresi
        p50 = calc_p50(e, sp, tp2)
        if p50 < 0.45:
            print(f"[TRADER] P50 filtre: {p50:.0%} < 45% — LONG açılmıyor")
            return
        
        # tastylive 1/3 Move hedefi ekle — birinci çıkış
        one_third_tp = e + (tp2 - e) / 3
        tr = {
            "trade_id": str(int(datetime.utcnow().timestamp()*1000)),
            "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            "dir": "LONG", "entry": e, "stop": round(sp,0), "tp": round(tp2,0),
            "size": sz, "status": "OPEN", "regime": regime, "signal": f"Auto·L·{regime}",
            "notes": f"Auto LONG GEX:{gex:.0f}M scalar:{fs:.2f} P50:{p50:.0%} 1/3TP:${one_third_tp:.0f}{' Backwardation' if term_shape=='BACKWARDATION' else ''}",
            "partial_closed": False
        }
        supa_post("trades", tr)
        print(f"[TRADER] ✅ AUTO LONG açıldı @${e:.0f} Stop:${sp:.0f} TP:${tp2:.0f} Size:{sz} BTC")
    
    elif short_ok and gex < 0 and spot < hvl:
        e = price
        sp = min(call_res or e*1.07, e * 1.05)
        tp2 = max_pain if expiry_week and max_pain else (put_sup or e * 0.93)
        sz = round(risk / abs(e - sp), 4)
        
        # tastylive P50 filtresi
        p50 = calc_p50(e, sp, tp2)
        if p50 < 0.45:
            print(f"[TRADER] P50 filtre: {p50:.0%} < 45% — SHORT açılmıyor")
            return
        
        one_third_tp = e - (e - tp2) / 3
        
        # tastylive P50 filtresi
        p50 = calc_p50(e, sp, tp2)
        if p50 < 0.45:
            print(f"[TRADER] P50 filtre: {p50:.0%} < 45% — SHORT açılmıyor")
            return
        
        one_third_tp = e - (e - tp2) / 3
        backwardation = term_shape == "BACKWARDATION"
        if backwardation:
            sp = e + abs(e - sp) * 1.2
        tr = {
            "trade_id": str(int(datetime.utcnow().timestamp()*1000)),
            "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            "dir": "SHORT", "entry": e, "stop": round(sp,0), "tp": round(tp2,0),
            "size": sz, "status": "OPEN", "regime": regime, "signal": f"Auto·S·{regime}",
            "notes": f"Auto SHORT GEX:{gex:.0f}M scalar:{fs:.2f} P50:{p50:.0%} 1/3TP:${one_third_tp:.0f}{' Backwardation+20%stop' if backwardation else ''}",
            "partial_closed": False
        }
        supa_post("trades", tr)
        print(f"[TRADER] ✅ AUTO SHORT açıldı @${e:.0f} Stop:${sp:.0f} TP:${tp2:.0f} Size:{sz} BTC")
    
    else:
        print(f"[TRADER] Koşullar sağlanmadı — BEKLE")
    
    print("[TRADER] Tamamlandı")

if __name__ == "__main__":
    run_trader()
