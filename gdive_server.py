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
from urllib.parse import urlparse, parse_qs

import os
PORT = int(os.environ.get("PORT", 7432))
CACHE_TTL = 60  # saniye
BTC_PERP = "BTC-PERPETUAL"

def claude_complete(prompt, max_tokens=500):
    """Groq API'ye istek gönderir, JSON string döndürür."""
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        return None
    try:
        body = json.dumps({
            "model": "llama-3.1-8b-instant",
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]
        }).encode()
        req = Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {groq_key}"
            },
            method="POST"
        )
        with urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
            raw = resp["choices"][0]["message"]["content"]
            return raw
    except Exception as e:
        print(f"[ERR] groq_complete: {e}")
        return None

# ── FOMC / FED ─────────────────────────────────────────────────────
FOMC_RSS = "https://www.federalreserve.gov/feeds/press_monetary.xml"
_fomc_cache = {"text": None, "title": "—", "date": "—", "fetched_at": 0}
FOMC_TTL = 3600 * 6  # 6 saat

def fetch_fomc_statement():
    """Fed RSS'ten son FOMC açıklamasını çeker. 6 saatte bir yeniler."""
    now = time.time()
    if _fomc_cache["text"] and (now - _fomc_cache["fetched_at"]) < FOMC_TTL:
        return _fomc_cache
    try:
        req = Request(FOMC_RSS, headers={"User-Agent": "gdive/1.0"})
        with urlopen(req, timeout=12) as r:
            raw = r.read().decode("utf-8", errors="ignore")

        # XML'i basit string parse ile işle (lxml yok)
        import re
        items = re.findall(r"<item>(.*?)</item>", raw, re.DOTALL)
        title, date, link = "FOMC Statement", "", ""
        for item in items:
            t = re.search(r"<title><!\[CDATA\[(.*?)\]\]>|<title>(.*?)</title>", item)
            d = re.search(r"<pubDate>(.*?)</pubDate>", item)
            l = re.search(r"<link>(.*?)</link>|<guid>(.*?)</guid>", item)
            if t:
                title_txt = (t.group(1) or t.group(2) or "").strip()
                kws = ["federal open market", "fomc", "federal funds", "monetary policy"]
                if any(k in title_txt.lower() for k in kws):
                    title = title_txt
                    date = (d.group(1) or "").strip() if d else ""
                    link = (l.group(1) or l.group(2) or "").strip() if l else ""
                    break

        # Sayfadan metin çek
        text = ""
        if link and link.startswith("http"):
            try:
                req2 = Request(link, headers={"User-Agent": "gdive/1.0"})
                with urlopen(req2, timeout=12) as r2:
                    html = r2.read().decode("utf-8", errors="ignore")
                # Script/style temizle, düz metin al
                html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL)
                html = re.sub(r"<[^>]+>", " ", html)
                html = re.sub(r"\s+", " ", html).strip()
                text = html[:3000]
            except Exception as e:
                print(f"[FOMC] page fetch error: {e}")

        if not text:
            # RSS description'dan al
            desc_m = re.search(r"<description><!\[CDATA\[(.*?)\]\]>|<description>(.*?)</description>", raw, re.DOTALL)
            text = (desc_m.group(1) or desc_m.group(2) or "")[:2000] if desc_m else "FOMC verisi alınamadı."

        _fomc_cache.update({"text": text, "title": title, "date": date[:30], "fetched_at": now})
        print(f"[FOMC] Fetched: {title[:60]}")
        return _fomc_cache

    except Exception as e:
        print(f"[FOMC] fetch error: {e}")
        if not _fomc_cache["text"]:
            _fomc_cache["text"] = "FOMC verisi alınamadı. Son bilinen: Fed faiz oranını sabit tuttu."
            _fomc_cache["title"] = "FOMC (hata)"
            _fomc_cache["date"] = "—"
        return _fomc_cache

# ── LLM FILTER ─────────────────────────────────────────────────────
_llm_filter_cache = {"result": None, "gamma_score": None, "regime": None, "fetched_at": 0}
LLM_FILTER_TTL = 300  # 5 dakika

def run_llm_filter(gamma_score, regime):
    """
    Gamma sinyalini FOMC + Deribit verileriyle LLM'e filtreden geçirir.
    ONAYLA / VETO / NÖTR döndürür.
    Sonucu 5 dakika cache'ler, aynı gamma/regime gelirse cache'den döner.
    """
    now = time.time()
    cached = _llm_filter_cache
    if (cached["result"] and
        cached["gamma_score"] == round(gamma_score, 2) and
        cached["regime"] == regime and
        (now - cached["fetched_at"]) < LLM_FILTER_TTL):
        return cached["result"]

    # Gamma sinyali
    threshold = 0.25
    if gamma_score >= threshold:
        action = "LONG"
    elif gamma_score <= -threshold:
        action = "SHORT"
    else:
        return {
            "verdict": "NÖTR", "confidence": 1.0, "action": "BEKLE",
            "reasoning": "Gamma skoru eşik altında, trade sinyali yok.",
            "veto_reasons": None,
            "fomc_title": "—", "fomc_date": "—"
        }

    # Veri topla
    fomc = fetch_fomc_statement()

    # Deribit verisi cache'den al
    deribit_summary = "Deribit verisi bekleniyor."
    onchain_summary = "On-chain verisi bekleniyor."
    with cache["lock"]:
        cd = cache.get("data")
        if cd:
            mq = cd.get("menthorq", {})
            deribit_summary = (
                f"P/C OI: {cd.get('pc_ratio', '?')} | "
                f"Front IV: {cd.get('front_iv', '?')}% | "
                f"IV Rank: {cd.get('iv_rank', '?')}% | "
                f"Net GEX: {cd.get('total_net_gex', '?')}M | "
                f"Term Shape: {cd.get('term_shape', '?')} | "
                f"MQ Score: {mq.get('score', '?')} ({mq.get('regime', '?')})"
            )
            ga = cd.get("gamma_analysis", {})
            onchain_summary = (
                f"Flip mesafesi: {ga.get('flip_distance_pct', '?')}% | "
                f"Flip yakın: {ga.get('flip_near', False)} | "
                f"Neg pocket: {ga.get('in_neg_pocket', False)} | "
                f"Max Pain: {cd.get('max_pain', '?')} | "
                f"Expiry: {cd.get('expiry', {}).get('days_to_expiry', '?')} gün"
            )

    prompt = f"""Sen bir BTC options trading risk filtresinsin.
Gamma sistemi {action} sinyali üretti (skor: {gamma_score:+.3f}, rejim: {regime}).
Görevin: makro ve sentiment verilerini değerlendirip bu sinyali ONAYLA veya VETO et.

FED/FOMC [{fomc.get('date', '—')}]:
{fomc.get('text', 'Veri yok')[:1200]}

DERİBİT SENTIMENT:
{deribit_summary}

GEX & ON-CHAIN:
{onchain_summary}

Karar kriterleri:
- ONAYLA: Makro/sentiment {action} yönünü destekliyor veya nötr
- VETO: Makro/sentiment {action} ile açıkça çelişiyor  
- NÖTR: Karışık sinyaller, net karar yok

Sadece JSON döndür:
{{"verdict":"ONAYLA"|"VETO"|"NÖTR","confidence":<0-1>,"reasoning":<50-80 kelime Türkçe>,"veto_reasons":<sadece VETO ise string listesi, diğerleri null>}}"""

    raw = claude_complete(prompt, max_tokens=400)
    if not raw:
        result = {
            "verdict": "NÖTR", "confidence": 0.0, "action": action,
            "reasoning": "LLM API'ye ulaşılamadı. ANTHROPIC_API_KEY kontrol edin.",
            "veto_reasons": None,
            "fomc_title": fomc.get("title", "—"),
            "fomc_date": fomc.get("date", "—")
        }
    else:
        try:
            # JSON bloğunu metinden çıkar
            import re as _re
            raw_clean = raw.replace("```json", "").replace("```", "").strip()
            # İlk { ile son } arasını al
            match = _re.search(r'\{.*\}', raw_clean, _re.DOTALL)
            if match:
                raw_clean = match.group(0)
            result = json.loads(raw_clean)
            result["action"] = action
            result["fomc_title"] = fomc.get("title", "—")
            result["fomc_date"] = fomc.get("date", "—")
        except Exception as e:
            print(f"[LLM Filter] JSON parse error: {e} | raw: {raw[:200]}")
            result = {
                "verdict": "NÖTR", "confidence": 0.0, "action": action,
                "reasoning": f"LLM yanıt parse hatası: {str(e)[:60]}",
                "veto_reasons": None,
                "fomc_title": fomc.get("title", "—"),
                "fomc_date": fomc.get("date", "—")
            }

    _llm_filter_cache.update({
        "result": result,
        "gamma_score": round(gamma_score, 2),
        "regime": regime,
        "fetched_at": now
    })
    print(f"[LLM Filter] {action} → {result.get('verdict')} (conf: {result.get('confidence', 0):.2f})")
    return result

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
        atm = min(opts, key=lambda x: abs(x["strike"] - spot))
        atm_opts = [o for o in opts if o["strike"] == atm["strike"]]
        if atm_opts:
            iv_avg = sum(o["iv"] for o in atm_opts) / len(atm_opts)
            term.append({"expiry": expiry, "iv": round(iv_avg, 2)})

    return term[:8]

# ── GEX Hesaplama ──────────────────────────────────────────────────
def black_scholes_gamma(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return 0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        return math.exp(-0.5 * d1**2) / (S * sigma * math.sqrt(2 * math.pi * T))
    except:
        return 0

def parse_expiry_days(expiry_str):
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
    from collections import defaultdict
    gex_by_strike = defaultdict(float)

    for s in summaries:
        name = s.get("instrument_name", "")
        parts = name.split("-")
        if len(parts) < 4:
            continue
        expiry = parts[1]
        strike = float(parts[2])
        opt_type = parts[3]

        oi = s.get("open_interest", 0) or 0
        iv = (s.get("mark_iv") or 0) / 100
        days = parse_expiry_days(expiry)
        T = days / 365.0

        if oi <= 0 or iv <= 0 or T <= 0:
            continue

        gamma = black_scholes_gamma(spot, strike, T, 0.0, iv)
        gex_usd = gamma * oi * spot * spot

        if opt_type == "C":
            gex_by_strike[strike] += gex_usd
        else:
            gex_by_strike[strike] -= gex_usd

    result = []
    for strike, gex in sorted(gex_by_strike.items()):
        gex_m = round(gex / 1e6, 2)
        if abs(gex_m) > 0.1:
            result.append({"strike": strike, "net_gex": gex_m})

    return result

# ── Gamma Regime Analyzer ─────────────────────────────────────────
import datetime as _dt


def funding_manipulation_detector(funding_history, current_rate, lookback=48, threshold=3.0):
    if len(funding_history) < 10:
        return {"signal":"NEUTRAL","z_score":0,"alert":False,"description":"Yeterli veri yok","annualized_pct":current_rate*3*365*100}
    import statistics
    recent = funding_history[-lookback:]
    mean = statistics.mean(recent)
    std = statistics.stdev(recent) if len(recent)>1 else 1e-9
    z = (current_rate - mean)/(std+1e-9)
    if z > threshold:
        return {"signal":"CONTRARIAN_LONG","z_score":round(z,3),"alert":True,"description":f"MANIPULATION: Pozitif spike (z={z:.1f}). Long flush edildi. Kontrarian LONG firsat.","annualized_pct":round(current_rate*3*365*100,2)}
    elif z < -threshold:
        return {"signal":"CONTRARIAN_SHORT","z_score":round(z,3),"alert":True,"description":f"MANIPULATION: Negatif spike (z={z:.1f}). Short flush edildi. Kontrarian SHORT firsat.","annualized_pct":round(current_rate*3*365*100,2)}
    return {"signal":"NEUTRAL","z_score":round(z,3),"alert":False,"description":f"Normal funding. Z={z:.2f}","annualized_pct":round(current_rate*3*365*100,2)}

def carry_arb_calculator(funding_annual_pct, borrow_rate_pct=5.0, fee=0.001):
    net=(funding_annual_pct-borrow_rate_pct)/100-fee
    return {"net_carry_pct":round((funding_annual_pct-borrow_rate_pct),2),"total_return_pct":round(net*100,2),"profitable":net>0,"break_even_funding_pct":round(borrow_rate_pct+fee*100,2),"verdict":"CARRY ARB ACIK" if net>0.08 else "DUSUK GETIRI" if net>0 else "KARLI DEGIL"}

_funding_history = []

def find_flip_point(gex_by_strike):
    nodes = sorted(gex_by_strike.items())
    flip = None
    for i in range(len(nodes)-1):
        if nodes[i][1] < 0 and nodes[i+1][1] > 0:
            flip = (nodes[i][0] + nodes[i+1][0]) / 2
    return flip

def find_neg_pockets(gex_by_strike, spot, threshold=-0.05):
    nodes = sorted(gex_by_strike.items())
    pockets = []
    for strike, gex in nodes:
        if gex < 0 and abs(gex) > abs(threshold):
            pockets.append({"strike": strike, "gex": round(gex/1e6, 2)})
    return sorted(pockets, key=lambda x: x["gex"])[:5]

def find_pos_walls(gex_by_strike, spot, threshold=0.05):
    nodes = sorted(gex_by_strike.items())
    walls = []
    for strike, gex in nodes:
        if gex > 0 and gex > threshold:
            walls.append({"strike": strike, "gex": round(gex/1e6, 2)})
    return sorted(walls, key=lambda x: -x["gex"])[:5]

def calc_max_pain(summaries):
    from collections import defaultdict
    call_oi = defaultdict(float)
    put_oi  = defaultdict(float)
    for s in summaries:
        parts = s.get("instrument_name","").split("-")
        if len(parts) < 4: continue
        try:
            strike = float(parts[2])
            oi = float(s.get("open_interest",0) or 0)
            if parts[3] == "C": call_oi[strike] += oi
            else: put_oi[strike] += oi
        except: continue
    
    strikes = sorted(set(list(call_oi.keys()) + list(put_oi.keys())))
    if not strikes: return None
    
    min_pain = float("inf")
    max_pain_strike = strikes[0]
    for s in strikes:
        call_pain = sum(max(0, s - k) * v for k, v in call_oi.items())
        put_pain  = sum(max(0, k - s) * v for k, v in put_oi.items())
        total = call_pain + put_pain
        if total < min_pain:
            min_pain = total
            max_pain_strike = s
    return max_pain_strike

def get_expiry_info():
    today = _dt.date.today()
    def last_friday(year, month):
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        d = _dt.date(year, month, last_day)
        while d.weekday() != 4:
            d -= _dt.timedelta(days=1)
        return d
    
    expiries = []
    for offset in range(3):
        m = (today.month + offset - 1) % 12 + 1
        y = today.year + (today.month + offset - 1) // 12
        exp = last_friday(y, m)
        if exp >= today:
            expiries.append(exp)
    
    if not expiries: return {}
    
    nearest = expiries[0]
    days_to_expiry = (nearest - today).days
    
    return {
        "nearest_expiry": nearest.strftime("%Y-%m-%d"),
        "days_to_expiry": days_to_expiry,
        "expiry_week": days_to_expiry <= 3,
        "expiry_day": days_to_expiry == 0,
        "expiry_scalar": 0.5 if days_to_expiry <= 3 else 1.0,
    }

def gamma_regime_analysis(spot, flip_point, gex_by_strike):
    if not flip_point or not spot:
        return {"regime": "UNKNOWN", "in_positive": True, "flip_distance_pct": 0}
    
    in_positive = spot > flip_point
    flip_dist = abs(spot - flip_point) / spot * 100
    flip_near = flip_dist < 2.0
    
    neg_nodes = [(k,v) for k,v in gex_by_strike.items() if v < 0]
    nearest_neg = min(neg_nodes, key=lambda x: abs(x[0]-spot), default=None)
    in_neg_pocket = nearest_neg and abs(nearest_neg[0]-spot)/spot < 0.015
    
    pos_nodes = [(k,v) for k,v in gex_by_strike.items() if v > 0 and k > spot]
    nearest_wall = min(pos_nodes, key=lambda x: abs(x[0]-spot), default=None)
    near_pos_wall = nearest_wall and abs(nearest_wall[0]-spot)/spot < 0.03
    
    if in_positive and not flip_near:
        regime = "POSITIVE_GAMMA"
        color = "green"
        total_gex = sum(gex_by_strike.values())/1e6
        desc = f"Pozitif Gamma: Spot {spot:.0f} > HVL {flip_point:.0f}, GEX +{total_gex:.0f}M. Dealer sondurur, LONG bolgesi."
    elif flip_near:
        regime = "FLIP_ZONE"
        color = "orange"
        desc = f"TEHLİKE: Flip noktasına {flip_dist:.1f}% yakın! Yeni trade açma."
    elif in_neg_pocket:
        regime = "NEG_POCKET"
        color = "red"
        desc = f"Negatif gamma cebi! Dealer düşüşü büyütür. Stop genişlet."
    else:
        regime = "NEGATIVE_GAMMA"
        color = "red"
        total_gex2 = sum(gex_by_strike.values())/1e6
        if total_gex2 > 0:
            regime="MIXED_NEGATIVE"
            color="orange"
            desc=f"Gecis: GEX +{total_gex2:.0f}M pozitif ama Spot {spot:.0f} < HVL {flip_point:.0f}. HVL kirilmasini bekle."
        else:
            desc = f"Negatif Gamma: Spot {spot:.0f} < HVL {flip_point:.0f}, GEX {total_gex2:.0f}M. Dealer buyutur, SHORT bolgesi."
    
    return {
        "regime": regime,
        "color": color,
        "description": desc,
        "in_positive": in_positive,
        "flip_point": flip_point,
        "flip_distance_pct": round(flip_dist, 2),
        "flip_near": flip_near,
        "in_neg_pocket": in_neg_pocket,
        "near_pos_wall": near_pos_wall,
        "nearest_wall_strike": nearest_wall[0] if nearest_wall else None,
        "nearest_neg_strike": nearest_neg[0] if nearest_neg else None,
    }

def combine_layer_scalars(funding_s, menthorq_s, max_down=0.10, max_up=0.08):
    delta = (funding_s-1.0) + (menthorq_s-1.0)
    delta = max(-max_down, min(max_up, delta))
    return round(1.0+delta, 4)

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
try:
    from taleb_integration_patch import compute_taleb_metrics
    TALEB_OK = True
except Exception:
    TALEB_OK = False

def dynamic_vol_target(weights, realized, target_vol=0.20, posture="RISK_ON"):
    mults={"RISK_ON":1.0,"RISK_NEUTRAL":0.75,"RISK_OFF":0.5}
    mult=mults.get(posture,1.0)
    if not realized or realized<=0: return weights
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
    expiry_info = get_expiry_info()
    max_pain = calc_max_pain(summaries)
    assets = fetch_multi_asset()
    ma_weights = compute_multi_asset_signals(assets, 1.0)
    btc_prices = assets.get("BTC",[])
    rvol = realized_vol(btc_prices) if btc_prices else 0.25
    posture = "RISK_ON" if True else "RISK_OFF"
    ma_weights = dynamic_vol_target(ma_weights, rvol, 0.20, posture)
    ma_weights = apply_execution_costs(ma_weights, _prev_weights_ma)

    mq = build_menthorq_state(spot, summaries)
    gex_nodes = calc_gex(spot, summaries)
    total_net_gex = round(sum(n["net_gex"] for n in gex_nodes), 2)
    pos_nodes = sorted([n for n in gex_nodes if n["net_gex"] > 0], key=lambda x: -x["net_gex"])[:6]
    neg_nodes = sorted([n for n in gex_nodes if n["net_gex"] < 0], key=lambda x: x["net_gex"])[:6]

    call_walls = [n["strike"] for n in pos_nodes[:4]]
    put_walls  = [n["strike"] for n in neg_nodes[:4]]

    hvl = spot
    sorted_gex = sorted(gex_nodes, key=lambda x: x["strike"])
    for i in range(len(sorted_gex)-1):
        if sorted_gex[i]["net_gex"] * sorted_gex[i+1]["net_gex"] < 0:
            if abs(sorted_gex[i]["strike"] - spot) < abs(hvl - spot):
                hvl = sorted_gex[i]["strike"]
    if hvl == spot and pos_nodes:
        hvl = min(pos_nodes, key=lambda x: abs(x["strike"]-spot))["strike"]

    flip_point = find_flip_point(mq["gex_by_strike"]) if mq.get("gex_by_strike") else hvl
    neg_pockets = find_neg_pockets(mq.get("gex_by_strike",{}), spot)
    pos_walls_data = find_pos_walls(mq.get("gex_by_strike",{}), spot)
    gamma_regime_info = gamma_regime_analysis(spot, flip_point, mq.get("gex_by_strike",{}))
    call_resistance = call_walls[0] if call_walls else round(spot * 1.1 / 1000) * 1000
    put_support     = put_walls[0]  if put_walls  else round(spot * 0.9 / 1000) * 1000

    term_ivs = fetch_term_structure(spot, summaries)
    front_iv = term_ivs[0]["iv"] if term_ivs else 55.0
    back_iv  = term_ivs[-1]["iv"] if len(term_ivs) > 1 else 50.0
    term_shape = "CONTANGO" if back_iv > front_iv else "BACKWARDATION"

    iv_rank = min(round(front_iv / 1.2, 1), 100)

    call_oi = sum(s.get("open_interest", 0) or 0 for s in summaries if s.get("instrument_name", "").endswith("-C"))
    put_oi  = sum(s.get("open_interest", 0) or 0 for s in summaries if s.get("instrument_name", "").endswith("-P"))
    pc_ratio = round(put_oi / call_oi, 3) if call_oi > 0 else 1.0

    gamma_regime = "LONG_GAMMA" if spot > flip_point else ("TRANSITION" if abs(spot-flip_point)/max(spot,1)<0.02 else "SHORT_GAMMA")
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

    option_score  = 5 if long_ok else (4 if total_net_gex > 0 else 2)
    vol_score     = 4 if front_iv > 50 else (3 if front_iv > 35 else 2)
    momentum_score = 4 if spot > hvl else 2

    # Funding manipulation
    _funding_history.append(mq.get("funding_rate", 0))
    if len(_funding_history) > 96: _funding_history[:] = _funding_history[-96:]
    funding_manip = funding_manipulation_detector(_funding_history, mq.get("funding_rate", 0))
    carry_arb = carry_arb_calculator(funding_manip.get("annualized_pct", 0))

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
        "hv_30d": 68.0,
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
        "multi_asset": {"weights": ma_weights, "realized_vol": round(rvol,4) if rvol else 0, "posture": posture, "vol_target": 0.20},
        "gamma_analysis": gamma_regime_info,
        "neg_pockets": neg_pockets,
        "pos_walls_list": pos_walls_data,
        "flip_point": flip_point,
        "max_pain": max_pain,
        "expiry": expiry_info,
        "funding_manipulation": funding_manip,
        "carry_arb": carry_arb,
        "taleb": None, "_source": "deribit_live",
        "_elapsed": elapsed,
    }


# ── Server-Side Trade Management ──────────────────────────────────
TRADES_FILE = "/tmp/gdive_trades.json"

def load_trades_from_disk():
    try:
        if os.path.exists(TRADES_FILE):
            return json.load(open(TRADES_FILE))
        return []
    except:
        return []

def save_trades_to_disk(trades):
    try:
        json.dump(trades, open(TRADES_FILE, "w"))
    except Exception as e:
        print(f"[ERR] Trade save: {e}")

def load_trades():
    return load_trades_from_disk()

def save_trades(trades):
    save_trades_to_disk(trades)

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
                changed = True
            elif bearish:
                pnl = round((spot-t["entry"])*t["size"], 2)
                rr = round((spot-t["entry"])/(t["entry"]-t["stop"]),2) if t["entry"]!=t["stop"] else 0
                t.update({"status":"CLOSED","exitPrice":spot,"exitDate":now,"pnl":pnl,"rr":rr,"notes":(t.get("notes",""))+" | Rejim SHORT"})
                changed = True
            elif spot >= t["tp"] and not t.get("partialClosed"):
                half = round(t["size"]/2, 4)
                halfPnl = round((t["tp"]-t["entry"])*half, 2)
                if bullish:
                    call_walls = data.get("call_walls",[])
                    nextTP = next((w for w in sorted(call_walls) if w > t["tp"]), t["tp"]*1.03)
                    t.update({"size":half,"partialClosed":True,"partialPnl":halfPnl,"tp":nextTP,"notes":(t.get("notes",""))+f" | %50 @ {t['tp']}"})
                else:
                    pnl = round((t["tp"]-t["entry"])*t["size"], 2)
                    rr = round((t["tp"]-t["entry"])/(t["entry"]-t["stop"]),2) if t["entry"]!=t["stop"] else 0
                    t.update({"status":"CLOSED","exitPrice":t["tp"],"exitDate":now,"pnl":pnl,"rr":rr,"notes":(t.get("notes",""))+" | TP"})
                changed = True
        elif t["dir"] == "SHORT":
            if spot >= t["stop"]:
                pnl = round((t["entry"]-t["stop"])*t["size"], 2)
                t.update({"status":"CLOSED","exitPrice":t["stop"],"exitDate":now,"pnl":pnl,"rr":-1.0,"notes":(t.get("notes",""))+" | STOP"})
                changed = True
            elif bullish:
                pnl = round((t["entry"]-spot)*t["size"], 2)
                rr = round((t["entry"]-spot)/(t["stop"]-t["entry"]),2) if t["entry"]!=t["stop"] else 0
                t.update({"status":"CLOSED","exitPrice":spot,"exitDate":now,"pnl":pnl,"rr":rr,"notes":(t.get("notes",""))+" | Rejim LONG"})
                changed = True
            elif spot <= t["tp"] and not t.get("partialClosed"):
                half = round(t["size"]/2, 4)
                halfPnl = round((t["entry"]-t["tp"])*half, 2)
                if bearish:
                    put_walls = data.get("put_walls",[])
                    nextTP = next((w for w in sorted(put_walls,reverse=True) if w < t["tp"]), t["tp"]*0.97)
                    t.update({"size":half,"partialClosed":True,"partialPnl":halfPnl,"tp":nextTP,"notes":(t.get("notes",""))+f" | %50 @ {t['tp']}"})
                else:
                    pnl = round((t["entry"]-t["tp"])*t["size"], 2)
                    rr = round((t["entry"]-t["tp"])/(t["stop"]-t["entry"]),2) if t["entry"]!=t["stop"] else 0
                    t.update({"status":"CLOSED","exitPrice":t["tp"],"exitDate":now,"pnl":pnl,"rr":rr,"notes":(t.get("notes",""))+" | TP"})
                changed = True
        updated.append(t)
    if changed:
        save_trades(updated)
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
        elif bearish:
            entry=spot; stop=data["call_resistance"]; tp=data["put_support"]
            size=round(risk/abs(entry-stop),4) if entry!=stop else 0.001
            trade={"id":int(time.time()*1000),"date":__import__("datetime").datetime.utcnow().isoformat()[:16].replace("T"," "),"dir":"SHORT","entry":entry,"stop":stop,"tp":tp,"size":size,"regime":regime,"signal":"Server·Auto·SHORT·scalar"+str(final_scalar),"notes":f"Auto SHORT. GEX:{gex}M scalar:{final_scalar}","status":"OPEN","pnl":None,"rr":None,"exitPrice":None,"exitDate":None,"partialClosed":False}
            updated.append(trade)
            save_trades(updated)


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
        pass

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        content_length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(content_length)) if content_length else {}

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

        if path == "/trades/sync":
            save_trades(body if isinstance(body, list) else [])
            self.wfile.write(json.dumps({"ok": True, "count": len(body)}).encode())

        elif path == "/trades/add":
            trades = load_trades()
            body["id"] = int(time.time() * 1000)
            body["status"] = "OPEN"
            trades.append(body)
            save_trades(trades)
            self.wfile.write(json.dumps({"ok": True, "trade": body}).encode())

        elif path == "/trades/update":
            trade_id = body.get("id")
            updates = {k: v for k, v in body.items() if k != "id"}
            trades = load_trades()
            for t in trades:
                if t["id"] == trade_id:
                    t.update(updates)
                    break
            save_trades(trades)
            self.wfile.write(json.dumps({"ok": True}).encode())

        elif path == "/trades/close":
            trade_id = body.get("id")
            exit_price = body.get("exitPrice")
            trades = load_trades()
            for t in trades:
                if t["id"] == trade_id and t["status"] == "OPEN":
                    from datetime import datetime
                    pnl = (exit_price - t["entry"]) * t["size"] if t["dir"] == "LONG" else (t["entry"] - exit_price) * t["size"]
                    t.update({
                        "status": "CLOSED",
                        "exitPrice": exit_price,
                        "exitDate": datetime.utcnow().isoformat()[:16].replace("T", " "),
                        "pnl": round(pnl, 2),
                        "rr": round((exit_price - t["entry"]) / (t["entry"] - t["stop"]), 2) if t["dir"] == "LONG" else round((t["entry"] - exit_price) / (t["stop"] - t["entry"]), 2)
                    })
                    break
            save_trades(trades)
            self.wfile.write(json.dumps({"ok": True, "pnl": round(pnl, 2)}).encode())

        else:
            self.wfile.write(json.dumps({"error": "not found"}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        # Query string ayrıştır
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/health":
            self.send_json(200, {"ok": True, "port": PORT})

        elif path == "/data":
            d = get_data()
            if d:
                self.send_json(200, d)
            else:
                self.send_json(503, {"error": "Deribit fetch failed"})

        elif path == "/refresh":
            with cache["lock"]:
                cache["ts"] = 0
            d = get_data()
            if d:
                self.send_json(200, d)
            else:
                self.send_json(503, {"error": "refresh failed"})

        elif path == "/trades":
            self.send_json(200, load_trades())

        elif path == "/history":
            self.send_json(200, read_state_log(200))

        elif path == "/attribution":
            rows = read_state_log(500)
            scalars = [float(r.get("scalar",1)) for r in rows if r.get("scalar")]
            report = {"rows":len(rows),"avg_scalar":round(sum(scalars)/len(scalars),4) if scalars else None}
            self.send_json(200, report)

        elif path == "/llm-filter":
            # /llm-filter?gamma_score=0.42&regime=LONG_GAMMA
            try:
                gamma_score = float(params.get("gamma_score", [0])[0])
                regime = params.get("regime", ["NEUTRAL"])[0]
            except:
                self.send_json(400, {"error": "gamma_score ve regime parametreleri gerekli"})
                return

            if False:  # Ollama kullanıyor
                self.send_json(503, {"error": "Ollama çalışmıyor, ollama serve başlat", "verdict": "NÖTR", "confidence": 0})
                return

            # LLM filter'ı arka planda çalıştır (blocking ama timeout'lu)
            try:
                result = run_llm_filter(gamma_score, regime)
                self.send_json(200, result)
            except Exception as e:
                self.send_json(500, {"error": str(e), "verdict": "NÖTR", "confidence": 0})

        else:
            self.send_json(404, {"error": "not found"})

# ── Main ───────────────────────────────────────────────────────────

# ── GitHub Actions Cron Modu ──────────────────────────────────────
import sys as _sys

def run_cron():
    """GitHub Actions'tan her 5 dakikada çalışır."""
    import json, os
    
    SUPABASE_URL = os.environ.get("SUPABASE_URL","")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY","")
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("[CRON] Supabase credentials eksik")
        return
    
    print("[CRON] Veri çekiliyor...")
    data = build_data()
    if not data:
        print("[CRON] Veri alınamadı")
        return
    
    print(f"[CRON] Spot: {data.get('spot')}, Regime: {data.get('regime')}")
    
    # Market snapshot kaydet
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    import urllib.request, json as _json
    snapshot = {
        "spot": data.get("spot"),
        "regime": data.get("regime"),
        "gamma_regime": data.get("gamma_regime"),
        "total_net_gex": data.get("total_net_gex"),
        "hvl": data.get("hvl"),
        "flip_point": data.get("flip_point"),
        "max_pain": data.get("max_pain"),
        "iv_rank": data.get("iv_rank"),
        "term_shape": data.get("term_shape"),
        "long_ok": data.get("long_ok"),
        "short_ok": data.get("short_ok"),
        "front_iv": data.get("front_iv"),
        "hv_30d": data.get("hv_30d"),
        "pc_ratio": data.get("pc_ratio"),
        "call_resistance": data.get("call_resistance"),
        "put_support": data.get("put_support"),
        "call_resistance_0dte": data.get("call_resistance_0dte"),
        "put_support_0dte": data.get("put_support_0dte"),
        "option_score": data.get("option_score"),
        "vol_score": data.get("vol_score"),
        "momentum_score": data.get("momentum_score"),
        "n_contracts": data.get("n_contracts"),
        "expiry": data.get("expiry"),
        "gamma_analysis": data.get("gamma_analysis"),
        "menthorq": data.get("menthorq"),
        "funding": data.get("funding"),
        "layer_budget": data.get("layer_budget"),
        "pos_gex_nodes": data.get("pos_gex_nodes"),
        "neg_gex_nodes": data.get("neg_gex_nodes"),
        "call_walls": data.get("call_walls"),
        "put_walls": data.get("put_walls"),
        "term_ivs": data.get("term_ivs"),
        "timestamp": __import__("datetime").datetime.utcnow().isoformat()
    }
    
    try:
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/snapshots",
            data=_json.dumps(snapshot).encode(),
            headers=headers,
            method="POST"
        )
        urllib.request.urlopen(req)
        print("[CRON] Snapshot kaydedildi")
    except Exception as e:
        print(f"[CRON] Snapshot hatasi: {e}")
    
    # Günlük otomatik opsiyon notu (sadece sabah 06:00-07:00 UTC arası)
    import datetime as _dt_note
    now_h = _dt_note.datetime.utcnow().hour
    today_str = _dt_note.datetime.utcnow().strftime("%Y-%m-%d")
    
    spot = data.get("spot",0)
    regime = data.get("regime","")
    gamma = data.get("gamma_regime","")
    gex = data.get("total_net_gex",0)
    hvl = data.get("hvl",0)
    iv_rank = data.get("iv_rank",0)
    term = data.get("term_shape","")
    ga = data.get("gamma_analysis",{}) or {}
    flip_dist = ga.get("flip_distance_pct",0) or 0
    max_pain = data.get("max_pain",0) or 0
    expiry = data.get("expiry",{}) or {}
    
    # Her zaman çalıştır — ama aynı günde bir kez kaydet
    try:
        # Bugün zaten not var mı?
        check_req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/option_notes?date=gte.{today_str}%2000:00&limit=1",
            headers=headers, method="GET"
        )
        with urllib.request.urlopen(check_req) as r:
            existing = _json.loads(r.read())
        
        if not existing:
            # Otomatik not üret
            bull = regime in ("IDEAL_LONG","BULLISH_HIGH_VOL") and spot>hvl and gex>0
            bear = regime in ("BEARISH_VOLATILE","BEARISH_LOW_VOL") and spot<hvl and gex<0
            flip_near = flip_dist < 2.0
            
            if bull and not flip_near:
                note_text = f"AUTO: {regime.replace('_',' ')} · GEX +{gex/1000:.0f}K · Spot ${spot:.0f} HVL ${hvl:.0f} üstünde · {term} · IV Rank {iv_rank:.0f}% · Max Pain ${max_pain:.0f} · LONG bias"
            elif bear:
                note_text = f"AUTO: {regime.replace('_',' ')} · GEX {gex/1000:.0f}K · Spot ${spot:.0f} HVL ${hvl:.0f} altında · {term} · IV Rank {iv_rank:.0f}% · SHORT bias"
            elif flip_near:
                note_text = f"AUTO: Flip bölgesi · Spot ${spot:.0f} HVL ${hvl:.0f} · Mesafe {flip_dist:.1f}% · {regime.replace('_',' ')} · Yön belirsiz, bekleme"
            else:
                note_text = f"AUTO: {regime.replace('_',' ')} · GEX {gex/1000:.0f}K · IV Rank {iv_rank:.0f}% · {term} · Nötr"
            
            note_data = {
                "text": note_text,
                "date": _dt_note.datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
                "spot": spot,
                "regime": regime
            }
            note_req = urllib.request.Request(
                f"{SUPABASE_URL}/rest/v1/option_notes",
                data=_json.dumps(note_data).encode(),
                headers={**headers, "Prefer": "return=minimal"},
                method="POST"
            )
            urllib.request.urlopen(note_req)
            print(f"[CRON] Otomatik opsiyon notu kaydedildi: {note_text[:60]}...")
        else:
            print("[CRON] Bugün zaten opsiyon notu var")
    except Exception as e:
        print(f"[CRON] Opsiyon notu hatasi: {e}")
    
    print("[CRON] Tamamlandi")


if __name__ == "__main__" and len(_sys.argv) > 1 and _sys.argv[1] == "--cron":
    run_cron()
elif __name__ == "__main__":
    import http.server, socketserver
    PORT = int(os.environ.get("PORT", 7432))
    print(f"[INFO] Server basliyor port {PORT}")
    with socketserver.TCPServer(("", PORT), GDiveHandler) as httpd:
        httpd.serve_forever()
