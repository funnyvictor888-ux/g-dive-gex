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

PORT = 7432
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
    try:
        from urllib.request import urlopen, Request
        req = Request("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", headers={"User-Agent":"gdive/1.0"})
        with urlopen(req, timeout=8) as r:
            import json
            return float(json.loads(r.read())["price"])
    except Exception as e:
        print(f"[ERR] spot/binance: {e}")
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
        "_source": "deribit_live",
        "_elapsed": elapsed,
    }

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

    server = HTTPServer(("localhost", PORT), Handler)
    print(f"  ✓ Sunucu hazır → http://localhost:{PORT}")
    print(f"  Durdurmak için: Ctrl+C")
    print(f"")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  ✓ Sunucu durduruldu.")
