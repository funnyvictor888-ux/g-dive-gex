#!/usr/bin/env python3
"""
G-DIVE Trader V2
C1 (Sharpe 1.46) + C4 ($1M) stratejileri
SHORT + EqCurve + 21DTE + 1/3Exit + IVCrush
"""
import json, urllib.request, os, math
from datetime import datetime

SUPABASE_URL = os.environ.get("SUPABASE_URL","")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY","")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal"
}

# ── STRATEJİ KONFİGÜRASYONLARI ───────────────────────────────────
STRATEGIES = {
    "C1": {
        "name": "C1_Conservative",
        "atr_stop_mult": 2.25,
        "atr_tp_mult": 6.0,
        "rsi_bull_min": 50, "rsi_bull_max": 72,
        "rsi_bear_min": 30, "rsi_bear_max": 48,
        "eq_ema_period": 10, "eq_down_risk": 0.5,
        "iv_crush_threshold": 65,
        "dte_exit": 14,
        "third_tp": 0.25,
        "trend_confirm_e200": True,
        "base_risk": 0.02,
        "leverage": 2,
        "description": "Sharpe 1.46 | DD %14 | CAGR %56"
    },
    "C4": {
        "name": "C4_Aggressive",
        "atr_stop_mult": 1.5,
        "atr_tp_mult": 6.0,
        "rsi_bull_min": 50, "rsi_bull_max": 75,
        "rsi_bear_min": 25, "rsi_bear_max": 55,
        "eq_ema_period": 10, "eq_down_risk": 0.5,
        "iv_crush_threshold": 75,
        "dte_exit": 7,
        "third_tp": 0.333,
        "trend_confirm_e200": True,
        "base_risk": 0.02,
        "leverage": 2,
        "description": "Sharpe 1.12 | DD %24 | CAGR %108"
    }
}

# Aktif strateji — env'den al, yoksa C1
ACTIVE_STRATEGY = os.environ.get("GDIVE_STRATEGY", "C1")

def supa_get(path):
    try:
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/{path}",
            headers=HEADERS
        )
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"[ERR] GET {path}: {e}")
        return []

def supa_post(path, data):
    try:
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/{path}",
            data=json.dumps(data).encode(),
            headers=HEADERS,
            method="POST"
        )
        urllib.request.urlopen(req)
        return True
    except Exception as e:
        print(f"[ERR] POST {path}: {e}")
        return False

def supa_patch(path, data):
    try:
        h = dict(HEADERS)
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/{path}",
            data=json.dumps(data).encode(),
            headers=h,
            method="PATCH"
        )
        urllib.request.urlopen(req)
        return True
    except Exception as e:
        print(f"[ERR] PATCH {path}: {e}")
        return False

def get_btc_price():
    try:
        req = urllib.request.Request(
            "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
        )
        with urllib.request.urlopen(req) as r:
            return float(json.loads(r.read())["price"])
    except:
        return None

def get_binance_ohlcv(interval="4h", limit=250):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={interval}&limit={limit}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read())
        return [{"o":float(k[1]),"h":float(k[2]),"l":float(k[3]),"c":float(k[4])} for k in data]
    except:
        return []

def ema(prices, period):
    k = 2/(period+1); e = prices[0]
    result = []
    for p in prices:
        e = p*k + e*(1-k)
        result.append(e)
    return result

def rsi(prices, period=14):
    gains, losses = [], []
    for i in range(1, len(prices)):
        d = prices[i]-prices[i-1]
        gains.append(max(d,0)); losses.append(max(-d,0))
    ag = sum(gains[:period])/period
    al = sum(losses[:period])/period
    result = [None]*period
    rs = ag/al if al>0 else 100
    result.append(100-100/(1+rs))
    for i in range(period, len(gains)):
        ag = (ag*(period-1)+gains[i])/period
        al = (al*(period-1)+losses[i])/period
        rs = ag/al if al>0 else 100
        result.append(100-100/(1+rs))
    return result

def get_equity_curve_mult(trades_closed, cfg):
    """EqCurve: son kapalı trade'lerin EMA'sı pozitifse tam boyut"""
    if len(trades_closed) < cfg["eq_ema_period"]:
        return 1.0
    recent_pnls = [t.get("pnl",0) for t in trades_closed[-cfg["eq_ema_period"]*2:]]
    eq = [10000 + sum(recent_pnls[:i+1]) for i in range(len(recent_pnls))]
    eq_ema = ema(eq, cfg["eq_ema_period"])
    if eq[-1] >= eq_ema[-1]:
        return 1.0
    return cfg["eq_down_risk"]

def run_trader():
    cfg = STRATEGIES.get(ACTIVE_STRATEGY, STRATEGIES["C1"])
    print(f"[TRADER] {datetime.utcnow().isoformat()} — Strateji: {cfg['name']}")
    print(f"[TRADER] {cfg['description']}")

    # Son snapshot al
    rows = supa_get("snapshots?order=id.desc&limit=1")
    if not rows:
        print("[TRADER] Snapshot yok"); return

    d = rows[0]
    spot = d.get("spot", 0)
    regime = d.get("regime", "")
    gamma = d.get("gamma_regime", "")
    gex = d.get("total_net_gex", 0)
    hvl = d.get("hvl", 0)
    expiry = d.get("expiry") or {}
    max_pain = d.get("max_pain")
    call_res = d.get("call_resistance")
    put_sup = d.get("put_support")
    iv_rank = d.get("iv_rank", 0)
    term_shape = d.get("term_shape", "")
    layer = d.get("layer_budget") or {}
    flip_info = d.get("gamma_analysis") or {}

    # Canlı fiyat
    price = get_btc_price() or spot
    print(f"[TRADER] Spot:{price:.0f} Regime:{regime} Gamma:{gamma} GEX:{gex:.0f}M")

    # 4H teknik analiz
    candles = get_binance_ohlcv("4h", 250)
    if len(candles) >= 210:
        closes = [c["c"] for c in candles]
        e9 = ema(closes, 9)
        e21 = ema(closes, 21)
        e50 = ema(closes, 50)
        e200 = ema(closes, 200)
        rsis = rsi(closes, 14)
        atrs_arr = ema([max(c["h"]-c["l"], abs(c["h"]-closes[max(0,i-1)]), abs(c["l"]-closes[max(0,i-1)])) for i,c in enumerate(candles)], 14)
        
        n = len(closes)-1
        rsi_v = rsis[n-1] if rsis[n-1] else 50
        atr_v = atrs_arr[n]
        
        # Teknik sinyaller
        e200_long = price > e200[n] if cfg["trend_confirm_e200"] else True
        e200_short = price < e200[n] if cfg["trend_confirm_e200"] else True
        
        bull_tech = (e9[n]>e21[n] and
                    cfg["rsi_bull_min"]<rsi_v<cfg["rsi_bull_max"] and
                    price>e50[n] and e200_long)
        bear_tech = (e9[n]<e21[n] and
                    cfg["rsi_bear_min"]<rsi_v<cfg["rsi_bear_max"] and
                    price<e50[n] and e200_short)
        
        print(f"[TRADER] Tech: RSI={rsi_v:.1f} E9={e9[n]:.0f} E21={e21[n]:.0f} E200={e200[n]:.0f} ATR={atr_v:.0f}")
        print(f"[TRADER] bull_tech={bull_tech} bear_tech={bear_tech}")
    else:
        print("[TRADER] Teknik veri yetersiz"); return

    # Açık trade'leri al
    open_trades = supa_get("trades?status=eq.OPEN")
    closed_trades = supa_get("trades?status=eq.CLOSED&order=id.desc&limit=50")
    print(f"[TRADER] Açık: {len(open_trades)} | Kapalı son50: {len(closed_trades)}")

    # Filtreler
    flip_near = flip_info.get("flip_near", False) or abs(price-hvl)/price*100 < 0.5
    expiry_day = expiry.get("expiry_day", False)
    days_to_exp = expiry.get("days_to_expiry", 30)
    iv_crush = term_shape == "BACKWARDATION" and iv_rank > cfg["iv_crush_threshold"]
    
    # EqCurve multiplier
    ec_mult = get_equity_curve_mult(closed_trades, cfg)

    # Risk hesapla
    CAPITAL = 10000
    risk = CAPITAL * cfg["base_risk"] * ec_mult
    expiry_scalar = 0.5 if expiry.get("expiry_week") else 1.0

    # Açık trade yönetimi
    for t in open_trades:
        entry = t.get("entry", 0)
        stop = t.get("stop", 0)
        tp = t.get("tp", 0)
        size = t.get("size", 0)
        direction = t.get("dir", "")
        trade_id = t.get("trade_id", t.get("id"))
        partial_closed = t.get("partial_closed", False)

        if direction == "LONG":
            unreal = (price - entry) * size
            print(f"[TRADER] LONG #{trade_id} Entry:{entry:.0f} Stop:{stop:.0f} TP:{tp:.0f} Unrealized:${unreal:.0f}")
            
            # DTE exit kuralı
            if days_to_exp <= cfg["dte_exit"] and not partial_closed:
                pnl = (price - entry) * size * cfg["leverage"]
                if pnl > 0:
                    supa_patch(f"trades?trade_id=eq.{trade_id}", {
                        "status":"CLOSED","exit_price":price,
                        "exit_date":datetime.utcnow().isoformat(),
                        "pnl":round(pnl,2),
                        "notes":(t.get("notes","") + f" |DTE_EXIT d={days_to_exp}")
                    })
                    print(f"[TRADER] DTE EXIT LONG @${price:.0f} PnL:${pnl:.0f}")
                    continue
            
            # 1/3 TP exit
            if not partial_closed and tp > entry:
                t1 = entry + (tp - entry) * cfg["third_tp"]
                if price >= t1:
                    new_size = size / 2
                    next_wall = call_res * 1.03 if call_res else tp * 1.03
                    supa_patch(f"trades?trade_id=eq.{trade_id}", {
                        "size":new_size,"partial_closed":True,"tp":next_wall,
                        "notes":(t.get("notes","") + f" |{int(cfg['third_tp']*100)}%TP@{price:.0f}")
                    })
                    print(f"[TRADER] FRAC TP LONG @${price:.0f} %50 kapat, yeni TP:${next_wall:.0f}")
                    continue
            
            # Stop
            if price <= stop:
                pnl = (stop - entry) * size * cfg["leverage"]
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "status":"CLOSED","exit_price":stop,
                    "exit_date":datetime.utcnow().isoformat(),
                    "pnl":round(pnl,2),
                    "notes":(t.get("notes","") + " |STOP")
                })
                print(f"[TRADER] STOP LONG @${stop:.0f} PnL:${pnl:.0f}")
            
            # TP
            elif price >= tp:
                pnl = (tp - entry) * size * cfg["leverage"]
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "status":"CLOSED","exit_price":tp,
                    "exit_date":datetime.utcnow().isoformat(),
                    "pnl":round(pnl,2),
                    "notes":(t.get("notes","") + " |TP")
                })
                print(f"[TRADER] TP LONG @${tp:.0f} PnL:${pnl:.0f}")
            
            # Rejim tersine döndü
            elif bear_tech and not bull_tech:
                pnl = (price - entry) * size * cfg["leverage"]
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "status":"CLOSED","exit_price":price,
                    "exit_date":datetime.utcnow().isoformat(),
                    "pnl":round(pnl,2),
                    "notes":(t.get("notes","") + " |REGIME_EXIT")
                })
                print(f"[TRADER] REGIME EXIT LONG @${price:.0f} PnL:${pnl:.0f}")

        elif direction == "SHORT":
            unreal = (entry - price) * size
            print(f"[TRADER] SHORT #{trade_id} Entry:{entry:.0f} Stop:{stop:.0f} TP:{tp:.0f} Unrealized:${unreal:.0f}")
            
            # DTE exit
            if days_to_exp <= cfg["dte_exit"] and not partial_closed:
                pnl = (entry - price) * size * cfg["leverage"]
                if pnl > 0:
                    supa_patch(f"trades?trade_id=eq.{trade_id}", {
                        "status":"CLOSED","exit_price":price,
                        "exit_date":datetime.utcnow().isoformat(),
                        "pnl":round(pnl,2),
                        "notes":(t.get("notes","") + f" |DTE_EXIT d={days_to_exp}")
                    })
                    print(f"[TRADER] DTE EXIT SHORT @${price:.0f} PnL:${pnl:.0f}")
                    continue
            
            # 1/3 TP exit
            if not partial_closed and entry > tp:
                t1 = entry - (entry - tp) * cfg["third_tp"]
                if price <= t1:
                    new_size = size / 2
                    next_wall = put_sup * 0.97 if put_sup else tp * 0.97
                    supa_patch(f"trades?trade_id=eq.{trade_id}", {
                        "size":new_size,"partial_closed":True,"tp":next_wall,
                        "notes":(t.get("notes","") + f" |{int(cfg['third_tp']*100)}%TP@{price:.0f}")
                    })
                    print(f"[TRADER] FRAC TP SHORT @${price:.0f}")
                    continue
            
            # Stop
            if price >= stop:
                pnl = (entry - stop) * size * cfg["leverage"]
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "status":"CLOSED","exit_price":stop,
                    "exit_date":datetime.utcnow().isoformat(),
                    "pnl":round(pnl,2),
                    "notes":(t.get("notes","") + " |STOP")
                })
                print(f"[TRADER] STOP SHORT @${stop:.0f} PnL:${pnl:.0f}")
            
            elif price <= tp:
                pnl = (entry - tp) * size * cfg["leverage"]
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "status":"CLOSED","exit_price":tp,
                    "exit_date":datetime.utcnow().isoformat(),
                    "pnl":round(pnl,2),
                    "notes":(t.get("notes","") + " |TP")
                })
                print(f"[TRADER] TP SHORT @${tp:.0f} PnL:${pnl:.0f}")
            
            elif bull_tech and not bear_tech:
                pnl = (entry - price) * size * cfg["leverage"]
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "status":"CLOSED","exit_price":price,
                    "exit_date":datetime.utcnow().isoformat(),
                    "pnl":round(pnl,2),
                    "notes":(t.get("notes","") + " |REGIME_EXIT")
                })
                print(f"[TRADER] REGIME EXIT SHORT @${price:.0f} PnL:${pnl:.0f}")

    # Yeni trade aç
    if open_trades:
        print("[TRADER] Açık trade var — yeni açılmıyor"); return
    
    if flip_near:
        print(f"[TRADER] Flip yakın — bekle"); return
    if expiry_day:
        print("[TRADER] Expiry günü — bekle"); return
    if iv_crush:
        print(f"[TRADER] IV Crush ({term_shape}, IV:{iv_rank:.0f}%) — bekle"); return

    # Sinyal
    long_signal  = bull_tech and e9[n]>e21[n] and price>hvl and gex>0
    short_signal = bear_tech and e9[n]<e21[n] and price<hvl and gex<0

    print(f"[TRADER] long_signal={long_signal} short_signal={short_signal} ec_mult={ec_mult:.2f}")

    if long_signal:
        e = price
        sm = cfg["atr_stop_mult"]
        tm = cfg["atr_tp_mult"]
        sp = e - atr_v * sm
        tp2 = e + atr_v * tm
        sz = round((risk * expiry_scalar) / (atr_v * sm), 4)
        rr = round((tp2-e)/(e-sp), 2)
        tr = {
            "trade_id": str(int(datetime.utcnow().timestamp()*1000)),
            "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            "dir": "LONG", "entry": e, "stop": round(sp,0), "tp": round(tp2,0),
            "size": sz, "status": "OPEN", "regime": regime,
            "signal": f"Auto·L·{cfg['name']}",
            "notes": f"{cfg['name']} LONG ATR:{atr_v:.0f} RR:{rr} EC:{ec_mult:.2f}",
            "partial_closed": False
        }
        supa_post("trades", tr)
        print(f"[TRADER] ✅ LONG @${e:.0f} Stop:${sp:.0f} TP:${tp2:.0f} Size:{sz} RR:{rr}")

    elif short_signal:
        e = price
        sm = cfg["atr_stop_mult"]
        tm = cfg["atr_tp_mult"]
        sp = e + atr_v * sm
        tp2 = e - atr_v * tm
        sz = round((risk * expiry_scalar) / (atr_v * sm), 4)
        rr = round((e-tp2)/(sp-e), 2)
        tr = {
            "trade_id": str(int(datetime.utcnow().timestamp()*1000)),
            "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            "dir": "SHORT", "entry": e, "stop": round(sp,0), "tp": round(tp2,0),
            "size": sz, "status": "OPEN", "regime": regime,
            "signal": f"Auto·S·{cfg['name']}",
            "notes": f"{cfg['name']} SHORT ATR:{atr_v:.0f} RR:{rr} EC:{ec_mult:.2f}",
            "partial_closed": False
        }
        supa_post("trades", tr)
        print(f"[TRADER] ✅ SHORT @${e:.0f} Stop:${sp:.0f} TP:${tp2:.0f} Size:{sz} RR:{rr}")
    
    else:
        print(f"[TRADER] Sinyal yok — BEKLE")

    print("[TRADER] Tamamlandı")

if __name__ == "__main__":
    run_trader()
