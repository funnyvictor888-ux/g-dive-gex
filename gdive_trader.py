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
            
            # TP hit
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
    
    if flip_near or expiry_day or gamma_conflict:
        return
    
    fs = (layer.get("final_scalar") or 1.0) * expiry_scalar
    risk = 10000 * 0.02 * 3 * fs
    
    if long_ok and gex > 0 and spot > hvl and iv_rank < 80:
        e = price
        sp = max(put_sup or e*0.93, e * 0.95)
        tp2 = max_pain if expiry_week and max_pain else (call_res or e * 1.07)
        sz = round(risk / abs(e - sp), 4)
        tr = {
            "trade_id": str(int(datetime.utcnow().timestamp()*1000)),
            "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            "dir": "LONG", "entry": e, "stop": round(sp,0), "tp": round(tp2,0),
            "size": sz, "status": "OPEN", "regime": regime, "signal": f"Auto·L·{regime}",
            "notes": f"Auto LONG GEX:{gex:.0f}M scalar:{fs:.2f}{' Backwardation' if term_shape=='BACKWARDATION' else ''}",
            "partial_closed": False
        }
        supa_post("trades", tr)
        print(f"[TRADER] ✅ AUTO LONG açıldı @${e:.0f} Stop:${sp:.0f} TP:${tp2:.0f} Size:{sz} BTC")
    
    elif short_ok and gex < 0 and spot < hvl:
        e = price
        sp = min(call_res or e*1.07, e * 1.05)
        tp2 = max_pain if expiry_week and max_pain else (put_sup or e * 0.93)
        sz = round(risk / abs(e - sp), 4)
        backwardation = term_shape == "BACKWARDATION"
        if backwardation:
            sp = e + abs(e - sp) * 1.2
        tr = {
            "trade_id": str(int(datetime.utcnow().timestamp()*1000)),
            "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            "dir": "SHORT", "entry": e, "stop": round(sp,0), "tp": round(tp2,0),
            "size": sz, "status": "OPEN", "regime": regime, "signal": f"Auto·S·{regime}",
            "notes": f"Auto SHORT GEX:{gex:.0f}M scalar:{fs:.2f}{' Backwardation+20%stop' if backwardation else ''}",
            "partial_closed": False
        }
        supa_post("trades", tr)
        print(f"[TRADER] ✅ AUTO SHORT açıldı @${e:.0f} Stop:${sp:.0f} TP:${tp2:.0f} Size:{sz} BTC")
    
    else:
        print(f"[TRADER] Koşullar sağlanmadı — BEKLE")
    
    print("[TRADER] Tamamlandı")

if __name__ == "__main__":
    run_trader()
