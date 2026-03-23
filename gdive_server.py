#!/usr/bin/env python3
"""
G-DIVE Deribit Data Server — localhost:7432
Deribit public API'den BTC options verisi çeker, GEX/IV hesaplar.
Kullanım: python3 gdive_server.py
"""

import json, math, time, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.error import URLError

import os
PORT = int(os.environ.get("PORT", 7432))
CACHE_TTL = 60  # saniye
BTC_PERP = "BTC-PERPETUAL"

# ── Deribit API ────────────────────────────────────────────────────
def deribit_get(method, params={}):
    base = "https://deribit.com/api/v2/public/"
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{base}{method}?{qs}"
    req = Request(url, headers={"User-Agent": "gdive/1.0"})
    try:
        with urlopen(req, timeout=10) as r:
            return json.loads(r.read())["result"]
    except Exception as e:
        print(f"[ERR] {method}: {e}")
        return None

# ── Spot fiyat ─────────────────────────────────────────────────────
def fetch_spot():
    urls = [
        ("coingecko", "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"),
        ("binance", "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"),
    ]
    for name, url in urls:
        try:
            from urllib.request import urlopen, Request
            req = Request(url, headers={"User-Agent":"gdive/1.0"})
            with urlopen(req, timeout=8) as r:
                import json
                data = json.loads(r.read())
                if name == "coingecko":
                    return float(data["bitcoin"]["usd"])
                else:
                    return float(data["price"])
        except Exception as e:
            print(f"[ERR] spot/{name}: {e}")
    return None

# ── Tüm BTC opsiyonları (özet) ─────────────────────────────────────
def fetch_book_summary():
    r = deribit_get("get_book_summary_by_currency", {"currency": "BTC", "kind": "option"})
    return r if r else []

# ── Term structure için ATM IV ─────────────────────────────────────
def fetch_term_structure(spot, summaries):
    # Her expiry için ATM strike'ı bul, IV'yi al
    from collections import defaultdict
    by_expiry = defaultdict(list)
    for s in summaries:
        name = s.get("instrument_name", "")
        parts = name.split("-")
        if len(parts) < 4:
            continue
        expiry = parts[1]
        strike = float(parts[2])
        opt_type = parts[3]
        iv = s.get("mark_iv") or s.get("bid_iv") or 0
        if iv and iv > 0:
            by_expiry[expiry].append({"strike": strike, "type": opt_type, "iv": iv})

    term = []
    for expiry, opts in sorted(by_expiry.items()):
        if not opts:
            continue
        # ATM'e en yakın strike
        atm = min(opts, key=lambda x: abs(x["strike"] - spot))
        # O strike için call ve put IV ortalaması
        atm_opts = [o for o in opts if o["strike"] == atm["strike"]]
        if atm_opts:
            iv_avg = sum(o["iv"] for o in atm_opts) / len(atm_opts)
            term.append({"expiry": expiry, "iv": round(iv_avg, 2)})

    return term[:8]  # ilk 8 expiry

# ── GEX Hesaplama ──────────────────────────────────────────────────
def black_scholes_gamma(S, K, T, r, sigma):
    """BSM Gamma"""
    if T <= 0 or sigma <= 0:
        return 0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        return math.exp(-0.5 * d1**2) / (S * sigma * math.sqrt(2 * math.pi * T))
    except:
        return 0

def parse_expiry_days(expiry_str):
    """DDMMMYY → gün sayısı (yaklaşık)"""
    months = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,
               "JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}
    try:
        day = int(expiry_str[:2])
        mon = expiry_str[2:5]
        yr = 2000 + int(expiry_str[5:])
        import datetime
        exp_date = datetime.date(yr, months[mon], day)
        today = datetime.date.today()
        return max((exp_date - today).days, 0)
    except:
        return 30

def calc_gex(spot, summaries):
    """
    Net GEX per strike (USD millions)
    GEX = Gamma × OI × Spot² × contract_size
    Net GEX = Call GEX - Put GEX
    """
    from collections import defaultdict
    gex_by_strike = defaultdict(float)

    for s in summaries:
        name = s.get("instrument_name", "")
        parts = name.split("-")
        if len(parts) < 4:
            continue
        expiry = parts[1]
        strike = float(parts[2])
        opt_type = parts[3]  # C or P

        oi = s.get("open_interest", 0) or 0  # BTC cinsinden
        iv = (s.get("mark_iv") or 0) / 100   # decimal
        days = parse_expiry_days(expiry)
        T = days / 365.0

        if oi <= 0 or iv <= 0 or T <= 0:
            continue

        gamma = black_scholes_gamma(spot, strike, T, 0.0, iv)
        # USD cinsinden GEX = gamma × OI_contracts × spot²
        # OI Deribit'te BTC, 1 contract = 1 BTC
        gex_usd = gamma * oi * spot * spot  # USD

        if opt_type == "C":
            gex_by_strike[strike] += gex_usd
        else:  # Put: dealer negatif gamma
            gex_by_strike[strike] -= gex_usd

    # USD → Milyon USD, strike'a göre sırala
    result = []
    for strike, gex in sorted(gex_by_strike.items()):
        gex_m = round(gex / 1e6, 2)
        if abs(gex_m) > 0.1:  # küçük değerleri atla
            result.append({"strike": strike, "net_gex": gex_m})

    return result

# ── Ana veri paketi ────────────────────────────────────────────────
def build_menthorq_state(spot, summaries):
    total_call_oi=0.0; total_put_oi=0.0
    weighted_bias=0.0; weighted_count=0.0
    call_wall=None; put_wall=None
    max_call_oi=-1.0; max_put_oi=-1.0
    for s in summaries:
        name=s.get("instrument_name",""); parts=name.split("-")
        if len(parts)<4: continue
        try: strike=float(parts[2])
        except: continue
        opt_type=parts[3]; oi=float(s.get("open_interest",0) or 0)
        if oi<=0: continue
        moneyness=(strike-spot)/spot
        weight=1.0/(1.0+abs(moneyness)*60.0)
        if opt_type=="C":
            total_call_oi+=oi
            if oi>max_call_oi: max_call_oi=oi; call_wall=strike
            weighted_bias+=weight*oi if strike>=spot else 0.25*weight*oi
        else:
            total_put_oi+=oi
            if oi>max_put_oi: max_put_oi=oi; put_wall=strike
            weighted_bias-=weight*oi if strike<=spot else 0.25*weight*oi
        weighted_count+=weight*oi
    total_oi=total_call_oi+total_put_oi
    if total_oi<=0: return {"gamma_z":0.0,"dealer_bias":0.0,"flow_score":0.0,"score":0.0,"scalar":1.0,"regime":"neutral","call_wall":call_wall,"put_wall":put_wall,"pc_ratio":1.0}
    dealer_bias=(total_call_oi-total_put_oi)/total_oi
    wall_conc=0.0
    if max_call_oi>0: wall_conc+=max_call_oi/total_oi
    if max_put_oi>0: wall_conc+=max_put_oi/total_oi
    gamma_z=max(-2.0,min(2.0,(wall_conc-0.15)/0.10))
    flow_score=max(-2.0,min(2.0,weighted_bias/weighted_count if weighted_count else 0))
    dealer_bias=max(-2.0,min(2.0,dealer_bias*2.0))
    score=0.5*gamma_z+0.3*dealer_bias+0.2*flow_score
    if score<=-1.0: scalar,regime=0.85,"stress"
    elif score<=-0.6: scalar,regime=0.95,"cautious"
    elif score<=-0.2: scalar,regime=0.97,"soft_risk_off"
    elif score<0.2: scalar,regime=1.00,"neutral"
    elif score<0.6: scalar,regime=1.02,"firm"
    elif score<0.9: scalar,regime=1.04,"positive"
    elif score<1.2: scalar,regime=1.06,"strong_squeeze"
    else: scalar,regime=1.08,"extreme_squeeze"
    return {"gamma_z":round(gamma_z,4),"dealer_bias":round(dealer_bias,4),"flow_score":round(flow_score,4),"score":round(score,4),"scalar":round(scalar,4),"regime":regime,"call_wall":call_wall,"put_wall":put_wall,"pc_ratio":round(total_put_oi/total_call_oi,3) if total_call_oi>0 else 1.0}


import csv
from pathlib import Path
from datetime import datetime
STATE_LOG = Path("state_history.csv")

def fetch_asset_price(symbol):
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/"+symbol+"?interval=1d&range=90d"
        from urllib.request import urlopen, Request
        req = Request(url, headers={"User-Agent":"gdive/4.0"})
        with urlopen(req, timeout=10) as r:
            import json
            d = json.loads(r.read())
            closes = d["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            return [x for x in closes if x is not None]
    except Exception as e:
        print("[ERR] asset/"+symbol+": "+str(e))
        return None

def fetch_multi_asset():
    assets = {}
    for sym,key in [("BTC-USD","BTC"),("GLD","GLD"),("TLT","TLT")]:
        p = fetch_asset_price(sym)
        if p and len(p)>=20: assets[key]=p
    return assets

def trend_signal(series, fast_n, slow_n):
    if len(series)<slow_n: return 0.0
    fast=sum(series[-fast_n:])/fast_n; slow=sum(series[-slow_n:])/slow_n
    if slow==0: return 0.0
    spread=(fast-slow)/slow; trend=max(min(spread*8.0,1.0),-1.0)
    if abs(spread)<0.015: trend*=0.25
    return float(trend)

def compute_multi_asset_signals(assets, menthorq_scalar=1.0):
    weights={}
    for key,prices in assets.items():
        fn,sn=(15,40) if key=="BTC" else (20,50)
        weights[key]=trend_signal(prices,fn,sn)
    gross=sum(abs(v) for v in weights.values())
    if gross==0: return {"BTC":0.0,"GLD":0.0,"TLT":0.0}
    weights={k:v/gross for k,v in weights.items()}
    if "BTC" in weights:
        weights["BTC"]*=menthorq_scalar
        gross2=sum(abs(v) for v in weights.values())
        if gross2>0: weights={k:v/gross2 for k,v in weights.items()}
    return {k:round(float(v),4) for k,v in weights.items()}

def realized_vol(prices, window=20):
    import math
    if len(prices)<window+1: return 0.25
    rets=[math.log(prices[i]/prices[i-1]) for i in range(-window,0)]
    mean=sum(rets)/len(rets)
    variance=sum((r-mean)**2 for r in rets)/len(rets)
    return math.sqrt(variance*252)

def dynamic_vol_target(weights, realized, target_vol=0.20, posture="RISK_ON"):
    mults={"RISK_ON":1.0,"RISK_NEUTRAL":0.75,"RISK_OFF":0.5}
    mult=mults.get(posture,1.0)
    if realized<=0: return weights
    scale=min((target_vol/realized)*mult,1.5)
    return {k:round(v*scale,4) for k,v in weights.items()}

def apply_execution_costs(weights, prev_weights, fee=0.0002):
    return {k:round(float(v)-abs(float(v)-float(prev_weights.get(k,0)))*fee,4) for k,v in weights.items()}

def append_state_log(data):
    header=["timestamp","spot","gamma_z","dealer_bias","flow_score","score","scalar","final_scalar","btc_weight","gld_weight","tlt_weight","regime","menthorq_regime"]
    write_header=not STATE_LOG.exists()
    try:
        with open(STATE_LOG,"a",newline="") as f:
            w=csv.writer(f)
            if write_header: w.writerow(header)
            mq=data.get("menthorq",{}); lb=data.get("layer_budget",{}); ma=data.get("multi_asset",{}).get("weights",{})
            w.writerow([datetime.utcnow().isoformat(),data.get("spot"),mq.get("gamma_z"),mq.get("dealer_bias"),mq.get("flow_score"),mq.get("score"),mq.get("scalar"),lb.get("final_scalar"),ma.get("BTC"),ma.get("GLD"),ma.get("TLT"),data.get("regime"),mq.get("regime")])
    except Exception as e: print("[ERR] log:",e)

def read_state_log(n=200):
    if not STATE_LOG.exists(): return []
    rows=[]
    try:
        with open(STATE_LOG,"r") as f:
            reader=csv.DictReader(f)
            for row in reader: rows.append(row)
    except: pass
    return rows[-n:]

_prev_weights_ma = {}

def build_data():
    print("[INFO] Fetching Deribit data...")
    t0 = time.time()

    spot = fetch_spot()
    if not spot:
        print("[ERR] Spot fetch failed")
        return None

    summaries = fetch_book_summary()
    if not summaries:
        print("[ERR] Book summary failed")
        return None

    print(f"[INFO] Spot: {spot:.0f}, Options: {len(summaries)}")
    # Multi-asset data
    assets = fetch_multi_asset()
    ma_weights = compute_multi_asset_signals(assets, 1.0)
    btc_prices = assets.get("BTC",[])
    rvol = realized_vol(btc_prices) if btc_prices else 0.25
    posture = "RISK_ON" if True else "RISK_OFF"
    ma_weights = dynamic_vol_target(ma_weights, rvol, 0.20, posture)
    ma_weights = apply_execution_costs(ma_weights, _prev_weights_ma)

    mq = build_menthorq_state(spot, summaries)
    mq = build_menthorq_state(spot, summaries)
    gex_nodes = calc_gex(spot, summaries)
    total_net_gex = round(sum(n["net_gex"] for n in gex_nodes), 2)
    pos_nodes = sorted([n for n in gex_nodes if n["net_gex"] > 0], key=lambda x: -x["net_gex"])[:6]
    neg_nodes = sorted([n for n in gex_nodes if n["net_gex"] < 0], key=lambda x: x["net_gex"])[:6]

    # Call/Put wall → en yüksek mutlak GEX'li strikeler
    call_walls = [n["strike"] for n in pos_nodes[:4]]
    put_walls  = [n["strike"] for n in neg_nodes[:4]]

    # HVL: GEX pozitiften negatife geçtiği en yakın nokta
    hvl = spot
    sorted_gex = sorted(gex_nodes, key=lambda x: x["strike"])
    for i in range(len(sorted_gex)-1):
        if sorted_gex[i]["net_gex"] * sorted_gex[i+1]["net_gex"] < 0:
            if abs(sorted_gex[i]["strike"] - spot) < abs(hvl - spot):
                hvl = sorted_gex[i]["strike"]
    if hvl == spot and pos_nodes:
        hvl = min(pos_nodes, key=lambda x: abs(x["strike"]-spot))["strike"]

    # Call resistance / Put support
    call_resistance = call_walls[0] if call_walls else round(spot * 1.1 / 1000) * 1000
    put_support     = put_walls[0]  if put_walls  else round(spot * 0.9 / 1000) * 1000

    # Term structure
    term_ivs = fetch_term_structure(spot, summaries)
    front_iv = term_ivs[0]["iv"] if term_ivs else 55.0
    back_iv  = term_ivs[-1]["iv"] if len(term_ivs) > 1 else 50.0
    term_shape = "CONTANGO" if back_iv > front_iv else "BACKWARDATION"

    # IV Rank (yaklaşık — front IV / 100 * 100, gerçek için 252 günlük gerekir)
    iv_rank = min(round(front_iv / 1.2, 1), 100)

    # P/C oranı (OI bazlı)
    call_oi = sum(s.get("open_interest", 0) or 0 for s in summaries if s.get("instrument_name", "").endswith("-C"))
    put_oi  = sum(s.get("open_interest", 0) or 0 for s in summaries if s.get("instrument_name", "").endswith("-P"))
    pc_ratio = round(put_oi / call_oi, 3) if call_oi > 0 else 1.0

    # Regime
    gamma_regime = "LONG_GAMMA" if total_net_gex > 0 else "SHORT_GAMMA"
    if total_net_gex > 0 and front_iv < 60:
        regime = "IDEAL_LONG" if spot > hvl else "BULLISH_HIGH_VOL"
    elif total_net_gex > 0 and front_iv >= 60:
        regime = "BULLISH_HIGH_VOL"
    elif total_net_gex < 0 and front_iv >= 60:
        regime = "BEARISH_VOLATILE"
    elif total_net_gex < 0:
        regime = "BEARISH_LOW_VOL"
    else:
        regime = "NEUTRAL"

    long_ok  = regime in ("IDEAL_LONG", "BULLISH_HIGH_VOL") and spot > hvl
    short_ok = regime in ("BEARISH_VOLATILE", "BEARISH_LOW_VOL") and spot < hvl

    # Scores
    option_score  = 5 if long_ok else (4 if total_net_gex > 0 else 2)
    vol_score     = 4 if front_iv > 50 else (3 if front_iv > 35 else 2)
    momentum_score = 4 if spot > hvl else 2

    elapsed = round(time.time() - t0, 1)
    print(f"[INFO] Done in {elapsed}s — GEX: {total_net_gex}M, IV: {front_iv}%, Regime: {regime}")

    return {
        "spot": round(spot, 0),
        "ts": time.strftime("%Y-%m-%d %H:%M UTC"),
        "total_net_gex": total_net_gex,
        "put_support": round(put_support / 500) * 500,
        "call_resistance": round(call_resistance / 500) * 500,
        "hvl": round(hvl / 500) * 500,
        "put_support_0dte": round(put_support * 1.01 / 250) * 250,
        "call_resistance_0dte": round(call_resistance * 0.99 / 250) * 250,
        "front_iv": round(front_iv, 2),
        "iv_rank": round(iv_rank, 2),
        "term_shape": term_shape,
        "pc_ratio": pc_ratio,
        "hv_30d": 68.0,  # yakında HV hesabı eklenecek
        "option_score": option_score,
        "vol_score": vol_score,
        "momentum_score": momentum_score,
        "gamma_regime": gamma_regime,
        "regime": regime,
        "long_ok": long_ok,
        "short_ok": short_ok,
        "term_ivs": term_ivs,
        "call_walls": call_walls,
        "put_walls": put_walls,
        "pos_gex_nodes": pos_nodes,
        "neg_gex_nodes": neg_nodes,
        "n_contracts": len(summaries),
        "menthorq": {"gamma_z":mq["gamma_z"],"dealer_bias":mq["dealer_bias"],"flow_score":mq["flow_score"],"scalar":mq["scalar"],"regime":mq["regime"],"score":mq["score"],"wall_adj":0.0},
        "funding": {"score":0,"scalar":1.0,"regime":"neutral"},
        "layer_budget": {"final_scalar":round(mq["scalar"],4),"menthorq_scalar":mq["scalar"],"funding_scalar":1.0},
        "menthorq": {"gamma_z":mq["gamma_z"],"dealer_bias":mq["dealer_bias"],"flow_score":mq["flow_score"],"scalar":mq["scalar"],"regime":mq["regime"],"score":mq["score"],"wall_adj":0.0},
        "funding": {"score":0,"scalar":1.0,"regime":"neutral"},
        "layer_budget": {"final_scalar":round(mq["scalar"],4),"menthorq_scalar":mq["scalar"],"funding_scalar":1.0},
        "multi_asset": {"weights": ma_weights, "realized_vol": round(rvol,4), "posture": posture, "vol_target": 0.20},
        "_source": "deribit_live",
        "_elapsed": elapsed,
    }


# ── Server-Side Trade Management ──────────────────────────────────
TRADES_FILE = Path("trades.json")

def load_trades():
    if not TRADES_FILE.exists(): return []
    try: return json.loads(TRADES_FILE.read_text())
    except: return []

def save_trades(trades):
    TRADES_FILE.write_text(json.dumps(trades, indent=2))

def check_and_manage_trades(data):
    if not data or data.get("_source") != "deribit_live": return
    trades = load_trades()
    if not trades: return
    spot = data["spot"]
    regime = data["regime"]
    gex = data["total_net_gex"]
    hvl = data["hvl"]
    bullish = regime in ("IDEAL_LONG","BULLISH_HIGH_VOL") and spot > hvl and gex > 0
    bearish = regime in ("BEARISH_VOLATILE","BEARISH_LOW_VOL","HIGH_RISK") and spot < hvl and gex < 0
    changed = False
    updated = []
    for t in trades:
        if t["status"] != "OPEN":
            updated.append(t)
            continue
        from datetime import datetime
        now = datetime.utcnow().isoformat()[:16].replace("T"," ")
        if t["dir"] == "LONG":
            if spot <= t["stop"]:
                pnl = round((t["stop"]-t["entry"])*t["size"], 2)
                rr = -1.0
                t.update({"status":"CLOSED","exitPrice":t["stop"],"exitDate":now,"pnl":pnl,"rr":rr,"notes":(t.get("notes",""))+" | STOP"})
                print(f"[TRADE] STOP HIT LONG @ {t['stop']} PnL:{pnl}")
                changed = True
            elif bearish:
                pnl = round((spot-t["entry"])*t["size"], 2)
                rr = round((spot-t["entry"])/(t["entry"]-t["stop"]),2) if t["entry"]!=t["stop"] else 0
                t.update({"status":"CLOSED","exitPrice":spot,"exitDate":now,"pnl":pnl,"rr":rr,"notes":(t.get("notes",""))+" | Rejim SHORT"})
                print(f"[TRADE] REGIME EXIT LONG @ {spot} PnL:{pnl}")
                changed = True
            elif spot >= t["tp"] and not t.get("partialClosed"):
                half = round(t["size"]/2, 4)
                halfPnl = round((t["tp"]-t["entry"])*half, 2)
                if bullish:
                    call_walls = data.get("call_walls",[])
                    nextTP = next((w for w in sorted(call_walls) if w > t["tp"]), t["tp"]*1.03)
                    t.update({"size":half,"partialClosed":True,"partialPnl":halfPnl,"tp":nextTP,"notes":(t.get("notes",""))+f" | %50 @ {t['tp']}"})
                    print(f"[TRADE] TP50 LONG @ {t['tp']} PnL:{halfPnl} nextTP:{nextTP}")
                else:
                    pnl = round((t["tp"]-t["entry"])*t["size"], 2)
                    rr = round((t["tp"]-t["entry"])/(t["entry"]-t["stop"]),2) if t["entry"]!=t["stop"] else 0
                    t.update({"status":"CLOSED","exitPrice":t["tp"],"exitDate":now,"pnl":pnl,"rr":rr,"notes":(t.get("notes",""))+" | TP"})
                    print(f"[TRADE] TP100 LONG @ {t['tp']} PnL:{pnl}")
                changed = True
        elif t["dir"] == "SHORT":
            if spot >= t["stop"]:
                pnl = round((t["entry"]-t["stop"])*t["size"], 2)
                t.update({"status":"CLOSED","exitPrice":t["stop"],"exitDate":now,"pnl":pnl,"rr":-1.0,"notes":(t.get("notes",""))+" | STOP"})
                print(f"[TRADE] STOP HIT SHORT @ {t['stop']} PnL:{pnl}")
                changed = True
            elif bullish:
                pnl = round((t["entry"]-spot)*t["size"], 2)
                rr = round((t["entry"]-spot)/(t["stop"]-t["entry"]),2) if t["entry"]!=t["stop"] else 0
                t.update({"status":"CLOSED","exitPrice":spot,"exitDate":now,"pnl":pnl,"rr":rr,"notes":(t.get("notes",""))+" | Rejim LONG"})
                print(f"[TRADE] REGIME EXIT SHORT @ {spot} PnL:{pnl}")
                changed = True
            elif spot <= t["tp"] and not t.get("partialClosed"):
                half = round(t["size"]/2, 4)
                halfPnl = round((t["entry"]-t["tp"])*half, 2)
                if bearish:
                    put_walls = data.get("put_walls",[])
                    nextTP = next((w for w in sorted(put_walls,reverse=True) if w < t["tp"]), t["tp"]*0.97)
                    t.update({"size":half,"partialClosed":True,"partialPnl":halfPnl,"tp":nextTP,"notes":(t.get("notes",""))+f" | %50 @ {t['tp']}"})
                    print(f"[TRADE] TP50 SHORT @ {t['tp']} PnL:{halfPnl} nextTP:{nextTP}")
                else:
                    pnl = round((t["entry"]-t["tp"])*t["size"], 2)
                    rr = round((t["entry"]-t["tp"])/(t["stop"]-t["entry"]),2) if t["entry"]!=t["stop"] else 0
                    t.update({"status":"CLOSED","exitPrice":t["tp"],"exitDate":now,"pnl":pnl,"rr":rr,"notes":(t.get("notes",""))+" | TP"})
                    print(f"[TRADE] TP100 SHORT @ {t['tp']} PnL:{pnl}")
                changed = True
        updated.append(t)
    if changed:
        save_trades(updated)
    # Auto entry
    today = __import__("datetime").date.today().isoformat()
    has_open = any(t["status"]=="OPEN" and t.get("date","").startswith(today) for t in updated)
    if not has_open:
        final_scalar = data.get("layer_budget",{}).get("final_scalar",1.0)
        risk = 10000 * 0.02 * 2 * final_scalar
        if bullish:
            entry=spot; stop=data["put_support"]; tp=data["call_resistance"]
            size=round(risk/abs(entry-stop),4) if entry!=stop else 0.001
            trade={"id":int(time.time()*1000),"date":__import__("datetime").datetime.utcnow().isoformat()[:16].replace("T"," "),"dir":"LONG","entry":entry,"stop":stop,"tp":tp,"size":size,"regime":regime,"signal":"Server·Auto·LONG·scalar"+str(final_scalar),"notes":f"Auto LONG. GEX:{gex}M scalar:{final_scalar}","status":"OPEN","pnl":None,"rr":None,"exitPrice":None,"exitDate":None,"partialClosed":False}
            updated.append(trade)
            save_trades(updated)
            print(f"[TRADE] AUTO LONG @ {entry} stop:{stop} tp:{tp} size:{size}")
        elif bearish:
            entry=spot; stop=data["call_resistance"]; tp=data["put_support"]
            size=round(risk/abs(entry-stop),4) if entry!=stop else 0.001
            trade={"id":int(time.time()*1000),"date":__import__("datetime").datetime.utcnow().isoformat()[:16].replace("T"," "),"dir":"SHORT","entry":entry,"stop":stop,"tp":tp,"size":size,"regime":regime,"signal":"Server·Auto·SHORT·scalar"+str(final_scalar),"notes":f"Auto SHORT. GEX:{gex}M scalar:{final_scalar}","status":"OPEN","pnl":None,"rr":None,"exitPrice":None,"exitDate":None,"partialClosed":False}
            updated.append(trade)
            save_trades(updated)
            print(f"[TRADE] AUTO SHORT @ {entry} stop:{stop} tp:{tp} size:{size}")


# ── Cache ──────────────────────────────────────────────────────────
cache = {"data": None, "ts": 0, "lock": threading.Lock()}

def get_data():
    with cache["lock"]:
        now = time.time()
        if cache["data"] is None or (now - cache["ts"]) > CACHE_TTL:
            d = build_data()
            if d:
                cache["data"] = d
                cache["ts"] = now
        if cache["data"]: check_and_manage_trades(cache["data"])
        return cache["data"]

# ── HTTP Server ────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # sessiz log

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"ok": True, "port": PORT})
        elif self.path == "/data":
            d = get_data()
            if d:
                self.send_json(200, d)
            else:
                self.send_json(503, {"error": "Deribit fetch failed"})
        elif self.path == "/refresh":
            with cache["lock"]:
                cache["ts"] = 0  # cache'i sıfırla
            d = get_data()
            if d:
                self.send_json(200, d)
            else:
                self.send_json(503, {"error": "refresh failed"})
        elif self.path=="/trades":
            self.send_json(200, load_trades())
        elif self.path=="/history":
            self.send_json(200, read_state_log(200))
        elif self.path=="/attribution":
            rows=read_state_log(500)
            scalars=[float(r.get("scalar",1)) for r in rows if r.get("scalar")]
            report={"rows":len(rows),"avg_scalar":round(sum(scalars)/len(scalars),4) if scalars else None}
            self.send_json(200, report)
        else:
            self.send_json(404, {"error": "not found"})

# ── Main ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"")
    print(f"  ◆ G-DIVE Deribit Server")
    print(f"  Port : {PORT}")
    print(f"  Cache: {CACHE_TTL}s")
    print(f"")
    print(f"  Endpoints:")
    print(f"    GET /health  → sunucu durumu")
    print(f"    GET /data    → canlı opsiyonlar verisi")
    print(f"    GET /refresh → cache'i sıfırla ve yenile")
    print(f"")
    print(f"  İlk veri çekiliyor...")
    print(f"")

    # Arka planda ilk fetch
    threading.Thread(target=get_data, daemon=True).start()

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"  ✓ Sunucu hazır → http://localhost:{PORT}")
    print(f"  Durdurmak için: Ctrl+C")
    print(f"")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  ✓ Sunucu durduruldu.")
