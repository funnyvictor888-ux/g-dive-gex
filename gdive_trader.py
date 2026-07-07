#!/usr/bin/env python3
"""
G-DIVE Trader V2
C1 (Sharpe 1.46) + C4 ($1M) stratejileri
SHORT + EqCurve + 21DTE + 1/3Exit + IVCrush
"""
import json, urllib.request, os, math
from datetime import datetime


INVARIANTS = {
    "max_drawdown_pct": 0.20,
    "max_position_usd": 50000,
    "max_daily_loss_usd": 2000,
    "max_open_trades": 2,
    "max_daily_trades": 6,
}

def check_invariants(open_trades, closed_trades, price):
    violations = []
    if len(open_trades) >= INVARIANTS["max_open_trades"]:
        violations.append(f"MAX_OPEN: {len(open_trades)}")
    for t in open_trades:
        if abs(t.get("size",0))*price > INVARIANTS["max_position_usd"]:
            violations.append(f"MAX_POS: ${abs(t.get('size',0))*price:.0f}")
    from datetime import datetime as _dt
    today = _dt.utcnow().strftime("%Y-%m-%d")
    dpnl = sum(t.get("pnl",0) or 0 for t in closed_trades if (t.get("exit_date") or "").startswith(today))
    if dpnl < -INVARIANTS["max_daily_loss_usd"]:
        violations.append(f"DAILY_LOSS: ${dpnl:.0f}")
    dn = len([t for t in closed_trades+open_trades if (t.get("date") or "").startswith(today)])
    if dn >= INVARIANTS["max_daily_trades"]:
        violations.append(f"DAILY_TRADES: {dn}")
    CAPITAL=10000;eq=CAPITAL;pk=CAPITAL
    for t in sorted(closed_trades, key=lambda x: x.get("exit_date") or ""):
        eq+=(t.get("pnl") or 0)
        if eq>pk: pk=eq
    dd=(pk-eq)/pk if pk>0 else 0
    if dd>=INVARIANTS["max_drawdown_pct"]: violations.append(f"MAX_DD: {dd*100:.1f}%")
    return len(violations)==0, violations

def check_halt_status():
    import urllib.request, json as _j
    try:
        req=urllib.request.Request(f"{SUPABASE_URL}/rest/v1/option_notes?text=ilike.*MANUAL_HALT*&order=id.desc&limit=1",headers={"apikey":SUPABASE_KEY,"Authorization":f"Bearer {SUPABASE_KEY}"})
        with urllib.request.urlopen(req) as r: rows=_j.loads(r.read())
        if not rows: return False
        req2=urllib.request.Request(f"{SUPABASE_URL}/rest/v1/option_notes?text=ilike.*MANUAL_RESUME*&order=id.desc&limit=1",headers={"apikey":SUPABASE_KEY,"Authorization":f"Bearer {SUPABASE_KEY}"})
        with urllib.request.urlopen(req2) as r2: resume=_j.loads(r2.read())
        if resume and resume[0].get("id",0)>rows[0].get("id",0): return False
        return True
    except: return False

def log_halt(reason, violations):
    import urllib.request, json as _j
    from datetime import datetime as _dt
    try:
        row={"text":f"INVARIANT_HALT:{reason}|{'|'.join(violations)}","date":_dt.utcnow().strftime("%Y-%m-%d %H:%M"),"spot":0,"regime":"HALT"}
        req=urllib.request.Request(f"{SUPABASE_URL}/rest/v1/option_notes",data=_j.dumps(row).encode(),headers={"apikey":SUPABASE_KEY,"Authorization":f"Bearer {SUPABASE_KEY}","Content-Type":"application/json","Prefer":"return=minimal"},method="POST")
        urllib.request.urlopen(req)
    except: pass


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

ACTIVE_STRATEGY = os.environ.get("GDIVE_STRATEGY", "C1")

COST_CONFIG = {
    "taker_fee_rate": 0.0005,
    "funding_rate_daily": 0.00027,
    "slippage_rate": 0.0002,
}

TRAIL_PCT = 0.03

SHADOW_TRAIL_PCT = 0.08
SHADOW_TRAIL_PCTS = [0.06, 0.08, 0.10]

def _record_trailing_shadow(t, real_exit, real_pnl, cfg):
    try:
        d = t.get("dir", "")
        entry = t.get("entry", 0)
        peak = t.get("peak_price") if d == "LONG" else t.get("trough_price")
        peak = peak or real_exit
        for _pct in SHADOW_TRAIL_PCTS:
            supa_post("trailing_shadow", {
                "trade_id": str(t.get("trade_id","")),
                "dir": d, "entry": entry, "size": t.get("size",0),
                "leverage": cfg.get("leverage",2),
                "real_exit_price": real_exit, "real_pnl": round(real_pnl,2), "real_peak": peak,
                "shadow_trail_pct": _pct, "shadow_peak": peak,
                "shadow_status": "OPEN", "opened_date": t.get("date","")
            })
        print(f"[SHADOW] kayit: {d} #{t.get('trade_id')} real_pnl=${real_pnl:.0f} peak={peak:.0f} (3 pct: 6/8/10)")
    except Exception as e:
        print(f"[SHADOW] record hata (gercek trade etkilenmez): {e}")

def run_trailing_shadow(price):
    try:
        ghosts = supa_get("trailing_shadow?shadow_status=eq.OPEN&select=*") or []
        for g in ghosts:
            d = g.get("dir",""); entry = g.get("entry",0); size = g.get("size",0)
            lev = g.get("leverage",2); peak = g.get("shadow_peak") or entry
            sid = g.get("id")
            if d == "LONG":
                if price > peak:
                    peak = price; supa_patch(f"trailing_shadow?id=eq.{sid}", {"shadow_peak": peak})
                trail = peak * (1 - (g.get("shadow_trail_pct") or 0.08))
                if price <= trail and peak > entry:
                    pnl,_ = _calc_realistic_pnl(entry, price, size, "LONG", g.get("opened_date",""), lev)
                    supa_patch(f"trailing_shadow?id=eq.{sid}", {"shadow_status":"CLOSED",
                        "shadow_exit_price":price,"shadow_pnl":round(pnl,2),
                        "shadow_exit_date":datetime.utcnow().isoformat(),"shadow_exit_reason":"SHADOW_TRAIL"})
                    print(f"[SHADOW] LONG #{g.get('trade_id')} kapandi @{price:.0f} shadow_pnl=${pnl:.0f} (real={g.get('real_pnl')})")
            else:
                if price < peak:
                    peak = price; supa_patch(f"trailing_shadow?id=eq.{sid}", {"shadow_peak": peak})
                trail = peak * (1 + (g.get("shadow_trail_pct") or 0.08))
                if price >= trail and peak < entry:
                    pnl,_ = _calc_realistic_pnl(entry, price, size, "SHORT", g.get("opened_date",""), lev)
                    supa_patch(f"trailing_shadow?id=eq.{sid}", {"shadow_status":"CLOSED",
                        "shadow_exit_price":price,"shadow_pnl":round(pnl,2),
                        "shadow_exit_date":datetime.utcnow().isoformat(),"shadow_exit_reason":"SHADOW_TRAIL"})
                    print(f"[SHADOW] SHORT #{g.get('trade_id')} kapandi @{price:.0f} shadow_pnl=${pnl:.0f} (real={g.get('real_pnl')})")
    except Exception as e:
        print(f"[SHADOW] run hata (gercek trade etkilenmez): {e}")


def _calc_realistic_pnl(entry, exit_price, size, direction, opened_date_str, leverage=1):
    if direction == "LONG":
        gross_pnl = (exit_price - entry) * size * leverage
    else:
        gross_pnl = (entry - exit_price) * size * leverage

    notional_in = entry * size
    notional_out = exit_price * size

    fee_in = notional_in * COST_CONFIG["taker_fee_rate"]
    fee_out = notional_out * COST_CONFIG["taker_fee_rate"]
    slip_in = notional_in * COST_CONFIG["slippage_rate"]
    slip_out = notional_out * COST_CONFIG["slippage_rate"]

    days_held = 0.0
    try:
        from datetime import datetime as _dt
        opened_dt = _dt.strptime(opened_date_str, "%Y-%m-%d %H:%M")
        elapsed = (_dt.utcnow() - opened_dt).total_seconds() / 86400.0
        days_held = max(elapsed, 0.0)
    except Exception:
        days_held = 0.5

    avg_notional = (notional_in + notional_out) / 2.0
    funding = avg_notional * COST_CONFIG["funding_rate_daily"] * days_held

    total_cost = fee_in + fee_out + slip_in + slip_out + funding
    net_pnl = gross_pnl - total_cost

    breakdown = {
        "gross": round(gross_pnl, 2),
        "fee": round(fee_in + fee_out, 2),
        "slip": round(slip_in + slip_out, 2),
        "funding": round(funding, 2),
        "days": round(days_held, 2),
        "cost": round(total_cost, 2),
        "net": round(net_pnl, 2),
    }
    return round(net_pnl, 2), breakdown


def _trade_opened_date(open_trades, trade_id):
    for t in open_trades:
        if str(t.get("trade_id")) == str(trade_id):
            return t.get("date", "")
    return ""


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
        h["Prefer"] = "return=minimal"
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

def _deribit_4h_ohlcv(limit=250):
    try:
        import time as _t
        now = int(_t.time() * 1000)
        hours = limit * 4 + 10
        start = now - hours * 3600 * 1000
        url = (f"https://www.deribit.com/api/v2/public/get_tradingview_chart_data"
               f"?instrument_name=BTC-PERPETUAL&resolution=60"
               f"&start_timestamp={start}&end_timestamp={now}")
        req = urllib.request.Request(url, headers={"User-Agent": "gdive/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        result = data.get("result", {})
        ticks = result.get("ticks", [])
        opens = result.get("open", [])
        highs = result.get("high", [])
        lows = result.get("low", [])
        closes = result.get("close", [])
        if not ticks or len(ticks) != len(closes):
            return []

        from collections import OrderedDict
        slots = OrderedDict()
        for ts_ms, o, h, l, c in zip(ticks, opens, highs, lows, closes):
            slot = (ts_ms // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
            if slot not in slots:
                slots[slot] = {"o": o, "h": h, "l": l, "c": c}
            else:
                bar = slots[slot]
                bar["h"] = max(bar["h"], h)
                bar["l"] = min(bar["l"], l)
                bar["c"] = c

        bars = list(slots.values())
        return bars[-limit:] if len(bars) > limit else bars
    except Exception as e:
        print(f"[TRADER] Deribit fallback hatasi: {e}")
        return []



# ============ FUNDING VETO (observe-only, C4 entegrasyon FAZ 1) ============
# Ablation: funding veto train Sharpe 1.28->1.34, test 0.89->1.23, 1.0-2.5 std robust.
# YON: funding asiri POZITIF = kalabalik LONG = long sinyalini veto (crowded fade riski).
# funding_manipulation_detector CONTRARIAN mantik kullanir; O YON DEGIL. Burada veto yonu ayri.
FUNDING_VETO_STD = 1.5
FUNDING_LOOKBACK = 48


# ============ GEX_Z (observe-only, C4 gex standardizasyonu) ============
# Ham total_net_gex non-stationary (%67 pozitif, drift'li). Rolling 4H z-score
# rejim-goreli sinyal verir (%58 pozitif, simetrik). Olcum: 421 4H bar, z aralik +-4.5.
# OBSERVE-ONLY: canli hala gex>0/gex<0 kullanir, gex_z sadece loglanir. Esik karari veri birikince.
GEX_Z_WINDOW = 30   # 30 4H bar = 5 gun rolling pencere

GEX_Z_CACHE = "/root/g-dive-gex/gex_z_cache.json"

def _bar_key(ts_str):
    from datetime import datetime as _dt
    ts = _dt.fromisoformat(ts_str.replace("Z",""))
    return ts.strftime("%Y-%m-%d ") + str(ts.hour//4*4).zfill(2)

def _gex_z_from_bars(gex4h):
    """4H bar listesinden son bar'in rolling z'sini hesapla."""
    if len(gex4h) < GEX_Z_WINDOW + 1:
        return None, len(gex4h)
    win = gex4h[-GEX_Z_WINDOW-1:-1]
    cur = gex4h[-1]
    m = sum(win)/len(win)
    var = sum((x-m)**2 for x in win)/len(win)
    sd = var**0.5
    return (cur - m)/(sd + 1e-9), len(gex4h)

def compute_gex_z():
    """4H-bucket gex serisi rolling z-score. CACHE'li: 4H bar degismediyse paginate ATLA,
    sadece guncel snapshot'i cekip son bar'i tazele. Doner: (gex_z, n_bars) veya (None, 0)."""
    try:
        import json as _json, os as _os
        # Guncel snapshot (tek istek) - her tick lazim
        latest = supa_get("snapshots?select=timestamp,total_net_gex&order=id.desc&limit=1")
        if not latest or latest[0].get("total_net_gex") is None:
            return None, 0
        cur_ts = latest[0]["timestamp"]
        cur_gex = latest[0]["total_net_gex"]
        cur_key = _bar_key(cur_ts)

        # Cache oku
        cache = None
        if _os.path.exists(GEX_Z_CACHE):
            try:
                with open(GEX_Z_CACHE) as _fh:
                    cache = _json.load(_fh)
            except Exception:
                cache = None

        # Cache gecerli mi: buckets var + en son bar key'i mevcut 4H icinde/oncesinde
        if cache and cache.get("buckets"):
            buckets = cache["buckets"]
            # Guncel bar'i tazele (ayni 4H bar ise ustune yaz = bar kapanisi mantigi)
            buckets[cur_key] = cur_gex
            keys = sorted(buckets.keys())
            gex4h = [buckets[k] for k in keys]
            z, n = _gex_z_from_bars(gex4h)
            # Cache'i guncelle (guncel bar tazelendi)
            try:
                with open(GEX_Z_CACHE, "w") as _fh:
                    _json.dump({"buckets": buckets, "last_key": cur_key}, _fh)
            except Exception:
                pass
            return z, n

        # CACHE YOK/BOZUK: tam paginate (nadir - gunde ~ilk tick veya cache silinince)
        rows = []
        for _pg in range(6):
            batch = supa_get("snapshots?select=timestamp,total_net_gex&order=id.desc&limit=1000&offset=%d" % (_pg*1000))
            if not batch:
                break
            rows += batch
            if len(batch) < 1000:
                break
        if not rows:
            return None, 0
        rows = [r for r in rows if r.get("total_net_gex") is not None]
        rows.reverse()
        buckets = {}
        for r in rows:
            buckets[_bar_key(r["timestamp"])] = r["total_net_gex"]
        keys = sorted(buckets.keys())
        gex4h = [buckets[k] for k in keys]
        try:
            with open(GEX_Z_CACHE, "w") as _fh:
                _json.dump({"buckets": buckets, "last_key": keys[-1] if keys else None}, _fh)
        except Exception:
            pass
        return _gex_z_from_bars(gex4h)
    except Exception as _e:
        print("[GEX_Z] hata: %s" % _e)
        return None, 0
# ======================================================================

def fetch_funding_series(hours=384):
    try:
        url = ("https://www.deribit.com/api/v2/public/get_funding_chart_data"
               "?instrument_name=BTC-PERPETUAL&length=1m")
        req = urllib.request.Request(url, headers={"User-Agent":"gdive/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        pts = data.get("result", {}).get("data", [])
        rates = [float(p.get("interest_8h", p.get("interest", 0)) or 0) for p in pts]
        rates = [x for x in rates if x == x]
        if len(rates) < 10:
            return None, None, len(rates)
        recent = rates[-FUNDING_LOOKBACK:]
        cur = recent[-1]
        mean = sum(recent)/len(recent)
        var = sum((x-mean)**2 for x in recent)/len(recent)
        std = var**0.5
        z = (cur - mean)/(std + 1e-9)
        return cur, z, len(recent)
    except Exception as _e:
        print("[FUNDING] fetch hata: %s" % _e)
        return None, None, 0

def get_binance_ohlcv(interval="4h", limit=250):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={interval}&limit={limit}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        candles = [{"o":float(k[1]),"h":float(k[2]),"l":float(k[3]),"c":float(k[4])} for k in data]
        if candles and len(candles) >= 50:
            return candles
    except Exception as e:
        print(f"[TRADER] Binance fail: {e}")

    if interval != "4h":
        print(f"[TRADER] Deribit fallback sadece 4h destekliyor, istenen: {interval}")
        return []
    print("[TRADER] Deribit fallback'e geciliyor (1H aggregate)")
    return _deribit_4h_ohlcv(limit)

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


# ============ MOMENTUM Q-SCORE (OBSERVE-ONLY, Menthor Q tarzi 0-5 normalize) ============
# Sinyali ETKILEMEZ. Sadece alignment_log'a yazilir, veri birikince (20-30 ornek)
# decide.py / funding veto entegrasyonu sonrasi filtre kararina kalibrasyon icin kullanilacak.
def momentum_score(e9_v, e21_v, e50_v, rsi_v, price, atr_v, direction="bull"):
    """
    0-5 normalize momentum guc skoru.
    Bilesenler:
      1) EMA spread gucu (e9-e21)/ATR -> trend ivmesi      (0-1.67)
      2) RSI 50'den uzaklik, yon-bilincli                   (0-1.67)
      3) Fiyat-e50 mesafesi /ATR -> trend genisligi          (0-1.67)
    direction: "bull" veya "bear" — hangi yon icin skorlandigini belirler.
    """
    if atr_v <= 0:
        return 0.0

    ema_spread = (e9_v - e21_v) / atr_v
    if direction == "bear":
        ema_spread = -ema_spread
    c1 = max(0.0, min(1.67, (ema_spread / 2.0) * 1.67))

    if direction == "bull":
        rsi_dev = max(0.0, rsi_v - 50) / 50.0
    else:
        rsi_dev = max(0.0, 50 - rsi_v) / 50.0
    c2 = max(0.0, min(1.67, rsi_dev * 1.67 * 2))

    dist = (price - e50_v) / atr_v
    if direction == "bear":
        dist = -dist
    c3 = max(0.0, min(1.67, (dist / 3.0) * 1.67))

    score = round(c1 + c2 + c3, 2)
    return min(5.0, score)


def get_equity_curve_mult(trades_closed, cfg):
    if len(trades_closed) < cfg["eq_ema_period"]:
        return 1.0
    recent_pnls = [t.get("pnl",0) for t in trades_closed[-cfg["eq_ema_period"]*2:]]
    eq = [10000 + sum(recent_pnls[:i+1]) for i in range(len(recent_pnls))]
    eq_ema = ema(eq, cfg["eq_ema_period"])
    if eq[-1] >= eq_ema[-1]:
        return 1.0
    return cfg["eq_down_risk"]


def _log_alignment(snapshot_ts=None, spot=None, rsi=None, e9=None, e21=None,
                   e50=None, e200=None, atr=None, bull_tech=None, bear_tech=None,
                   gex=None, hvl=None, flip_near=None, regime=None,
                   pyramid_decision=None, long_signal=None, short_signal=None,
                   trade_opened=False, block_reason=None, momentum_score=None,
                   funding_rate=None, funding_z=None, funding_veto=None,
                   pyramid_total=None, pyramid_agreement=None, gex_z=None):
    try:
        from datetime import datetime as _dt
        row = {"timestamp": _dt.utcnow().isoformat(), "snapshot_ts": snapshot_ts,
               "spot": spot, "rsi": rsi, "e9": e9, "e21": e21, "e50": e50,
               "e200": e200, "atr": atr, "bull_tech": bull_tech, "bear_tech": bear_tech,
               "gex": gex, "hvl": hvl, "flip_near": flip_near, "regime": regime,
               "pyramid_decision": pyramid_decision, "long_signal": long_signal,
               "short_signal": short_signal, "trade_opened": trade_opened,
               "block_reason": block_reason, "momentum_score": momentum_score,
               "funding_rate": funding_rate, "funding_z": funding_z, "funding_veto": funding_veto,
               "pyramid_total": pyramid_total, "pyramid_agreement": pyramid_agreement, "gex_z": gex_z}
        supa_post("alignment_log", row)
        print(f"[ALIGN_LOG] {block_reason} bull={bull_tech} bear={bear_tech} long={long_signal} short={short_signal} mom={momentum_score}")
    except Exception as _e:
        print(f"[ALIGN_LOG ERR] {_e}")


def _trade_age_days(date_str):
    try:
        from datetime import datetime as _dt
        opened = _dt.strptime(date_str.strip()[:16], "%Y-%m-%d %H:%M")
        return (_dt.utcnow() - opened).total_seconds() / 86400.0
    except Exception:
        return 0.0


def run_trader():
    cfg = STRATEGIES.get(ACTIVE_STRATEGY, STRATEGIES["C1"])
    print(f"[TRADER] {datetime.utcnow().isoformat()} — Strateji: {cfg['name']}")
    print(f"[TRADER] {cfg['description']}")

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

    price = get_btc_price() or spot
    print(f"[TRADER] Spot:{price:.0f} Regime:{regime} Gamma:{gamma} GEX:{gex:.0f}M")

    # FUNDING (observe-only): her tick'te bir kez cek, tum loglar gorsun. Veto karari sinyal blogunda.
    funding_rate, funding_z, _fn_n = fetch_funding_series()
    print("[FUNDING] rate=%s z=%s n=%s" % (funding_rate, funding_z, _fn_n))

    # PYRAMID SHADOW GATE (observe-only): pyramid_total oku + C4 sinyaliyle uyum logla. Trade akisini DEGISTIRMEZ.
    pyramid_total = d.get("pyramid_total")
    _pyr_dec = (d.get("pyramid_decision") or "").upper()
    if "LONG" in _pyr_dec:
        _pyr_dir = "long"
    elif "SHORT" in _pyr_dec:
        _pyr_dir = "short"
    else:
        _pyr_dir = "neutral"  # BEKLE / BLOKE
    print("[PYRAMID] total=%s decision=%s dir=%s" % (pyramid_total, _pyr_dec, _pyr_dir))

    # GEX_Z (observe-only): 4H-bucket rolling z-score, canli esigi DEGISTIRMEZ, sadece loglar.
    gex_z, _gz_n = compute_gex_z()
    print("[GEX_Z] z=%s bars=%s (ham gex=%s)" % (gex_z, _gz_n, gex))

    try: run_trailing_shadow(price)
    except Exception as _e: print(f"[SHADOW] cagri hata: {_e}")

    mom_score = None  # default, asagida hesaplanirsa doldurulur

    candles = get_binance_ohlcv("4h", 250)
    if len(candles) < 50:
        print("[TRADER] Binance erisilemedi, snapshot teknik kullaniliyor")
        bull_tech = regime in ("IDEAL_LONG","BULLISH_HIGH_VOL") and gex > 0
        bear_tech = regime in ("BEARISH_VOLATILE","BEARISH_LOW_VOL") and gex < 0
        rsi_v = 60 if bull_tech else 40
        atr_v = price * 0.018
        e9 = [price]; e21 = [hvl]; e50 = [price]; e200 = [price*0.9]
        n = 0
        long_signal = bull_tech and price > hvl
        short_signal = bear_tech and price < hvl
        print(f"[TRADER] Snapshot sinyal: bull={bull_tech} bear={bear_tech} long={long_signal} short={short_signal}")
        # snapshot fallback'te ATR/EMA placeholder degerler oldugundan mom_score None birakilir.
    elif len(candles) >= 50:
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

        # Momentum Q-Score (observe-only)
        mom_direction = "bull" if e9[n] > e21[n] else "bear"
        mom_score = momentum_score(e9[n], e21[n], e50[n], rsi_v, price, atr_v, direction=mom_direction)
        print(f"[TRADER] Momentum Q-Score (observe-only, {mom_direction}): {mom_score}/5.0")
    else:
        _log_alignment(snapshot_ts=d.get("timestamp"), spot=spot, gex=gex, hvl=hvl, regime=regime, pyramid_decision=d.get("pyramid_decision"), block_reason="tech_insufficient", funding_rate=funding_rate, funding_z=funding_z, pyramid_total=pyramid_total, pyramid_agreement=("pyr_%s_c4_blocked" % _pyr_dir if _pyr_dir!="neutral" else "neutral"), gex_z=gex_z)
        print("[TRADER] Teknik veri yetersiz"); return

    open_trades = supa_get("trades?status=eq.OPEN")
    closed_trades = supa_get("trades?status=eq.CLOSED&order=id.desc&limit=50")
    print(f"[TRADER] Açık: {len(open_trades)} | Kapalı son50: {len(closed_trades)}")
    if check_halt_status():
        _log_alignment(snapshot_ts=d.get("timestamp"), spot=spot, rsi=rsi_v, e9=e9[n], e21=e21[n], e50=e50[n], e200=e200[n], atr=atr_v, bull_tech=bull_tech, bear_tech=bear_tech, gex=gex, hvl=hvl, regime=regime, pyramid_decision=d.get("pyramid_decision"), block_reason="manual_halt", momentum_score=mom_score, funding_rate=funding_rate, funding_z=funding_z, pyramid_total=pyramid_total, pyramid_agreement=("pyr_%s_c4_blocked" % _pyr_dir if _pyr_dir!="neutral" else "neutral"), gex_z=gex_z)
        print("[TRADER] MANUAL HALT aktif"); return
    ok, violations = check_invariants(open_trades, closed_trades, price)
    if not ok:
        _log_alignment(snapshot_ts=d.get("timestamp"), spot=spot, rsi=rsi_v, e9=e9[n], e21=e21[n], e50=e50[n], e200=e200[n], atr=atr_v, bull_tech=bull_tech, bear_tech=bear_tech, gex=gex, hvl=hvl, regime=regime, pyramid_decision=d.get("pyramid_decision"), block_reason="invariant", momentum_score=mom_score, funding_rate=funding_rate, funding_z=funding_z, pyramid_total=pyramid_total, pyramid_agreement=("pyr_%s_c4_blocked" % _pyr_dir if _pyr_dir!="neutral" else "neutral"), gex_z=gex_z)
        print(f"[TRADER] INVARIANT: {violations}"); log_halt("AUTO", violations); return
    print("[TRADER] Invariants OK")

    flip_near = flip_info.get("flip_near", False) or abs(price-hvl)/price*100 < 0.5
    expiry_day = expiry.get("expiry_day", False)
    days_to_exp = expiry.get("days_to_expiry", 30)
    iv_crush = term_shape == "BACKWARDATION" and iv_rank > cfg["iv_crush_threshold"]
    
    ec_mult = get_equity_curve_mult(closed_trades, cfg)

    CAPITAL = 10000
    risk = CAPITAL * cfg["base_risk"] * ec_mult
    expiry_scalar = 0.5 if expiry.get("expiry_week") else 1.0

    for t in open_trades:
        entry = t.get("entry", 0)
        stop = t.get("stop", 0)
        tp = t.get("tp", 0)
        size = t.get("size", 0)
        direction = t.get("dir", "")
        trade_id = t.get("trade_id", t.get("id"))
        partial_closed = t.get("partial_closed", False)
        trade_days_held = _trade_age_days(t.get("date", ""))

        if direction == "LONG":
            unreal = (price - entry) * size
            print(f"[TRADER] LONG #{trade_id} Entry:{entry:.0f} Stop:{stop:.0f} TP:{tp:.0f} Unrealized:${unreal:.0f}")

            current_peak = t.get("peak_price") or entry
            if price > current_peak:
                current_peak = price
                supa_patch(f"trades?trade_id=eq.{trade_id}", {"peak_price": current_peak})
            trail_stop = current_peak * (1 - TRAIL_PCT)
            if price <= trail_stop and current_peak > entry:
                pnl, _cost = _calc_realistic_pnl(entry, price, size, "LONG", t.get("date",""), cfg["leverage"])
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "status":"CLOSED","exit_price":price,
                    "exit_date":datetime.utcnow().isoformat(),
                    "pnl":round(pnl,2),
                    "notes":(t.get("notes","") + f" |TRAIL_STOP peak={current_peak:.0f} trail={trail_stop:.0f}")
                })
                print(f"[TRADER] TRAIL STOP LONG @${price:.0f} peak={current_peak:.0f} PnL:${pnl:.0f}")
                try: _record_trailing_shadow(t, price, pnl, cfg)
                except Exception: pass
                continue

            if trade_days_held >= cfg["dte_exit"]:
                pnl, _cost = _calc_realistic_pnl(entry, price, size, "LONG", t.get("date",""), cfg["leverage"])
                if pnl > 0:
                    supa_patch(f"trades?trade_id=eq.{trade_id}", {
                        "status":"CLOSED","exit_price":price,
                        "exit_date":datetime.utcnow().isoformat(),
                        "pnl":round(pnl,2),
                        "notes":(t.get("notes","") + f" |TIME_EXIT held={trade_days_held:.1f}d")
                    })
                    print(f"[TRADER] TIME EXIT LONG @${price:.0f} held={trade_days_held:.1f}d PnL:${pnl:.0f}")
                    continue
            
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
            
            if price <= stop:
                pnl, _cost = _calc_realistic_pnl(entry, stop, size, "LONG", t.get("date",""), cfg["leverage"])
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "status":"CLOSED","exit_price":stop,
                    "exit_date":datetime.utcnow().isoformat(),
                    "pnl":round(pnl,2),
                    "notes":(t.get("notes","") + " |STOP")
                })
                print(f"[TRADER] STOP LONG @${stop:.0f} PnL:${pnl:.0f}")
            
            elif price >= tp:
                pnl, _cost = _calc_realistic_pnl(entry, tp, size, "LONG", t.get("date",""), cfg["leverage"])
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "status":"CLOSED","exit_price":tp,
                    "exit_date":datetime.utcnow().isoformat(),
                    "pnl":round(pnl,2),
                    "notes":(t.get("notes","") + " |TP")
                })
                print(f"[TRADER] TP LONG @${tp:.0f} PnL:${pnl:.0f}")
            
            elif bear_tech and not bull_tech:
                pnl, _cost = _calc_realistic_pnl(entry, price, size, "LONG", t.get("date",""), cfg["leverage"])
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

            current_trough = t.get("trough_price") or entry
            if price < current_trough:
                current_trough = price
                supa_patch(f"trades?trade_id=eq.{trade_id}", {"trough_price": current_trough})
            trail_stop_short = current_trough * (1 + TRAIL_PCT)
            if price >= trail_stop_short and current_trough < entry:
                pnl, _cost = _calc_realistic_pnl(entry, price, size, "SHORT", t.get("date",""), cfg["leverage"])
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "status":"CLOSED","exit_price":price,
                    "exit_date":datetime.utcnow().isoformat(),
                    "pnl":round(pnl,2),
                    "notes":(t.get("notes","") + f" |TRAIL_STOP trough={current_trough:.0f} trail={trail_stop_short:.0f}")
                })
                print(f"[TRADER] TRAIL STOP SHORT @${price:.0f} trough={current_trough:.0f} PnL:${pnl:.0f}")
                try: _record_trailing_shadow(t, price, pnl, cfg)
                except Exception: pass
                continue

            if trade_days_held >= cfg["dte_exit"]:
                pnl, _cost = _calc_realistic_pnl(entry, price, size, "SHORT", t.get("date",""), cfg["leverage"])
                if pnl > 0:
                    supa_patch(f"trades?trade_id=eq.{trade_id}", {
                        "status":"CLOSED","exit_price":price,
                        "exit_date":datetime.utcnow().isoformat(),
                        "pnl":round(pnl,2),
                        "notes":(t.get("notes","") + f" |TIME_EXIT held={trade_days_held:.1f}d")
                    })
                    print(f"[TRADER] TIME EXIT SHORT @${price:.0f} held={trade_days_held:.1f}d PnL:${pnl:.0f}")
                    continue
            
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
            
            if price >= stop:
                pnl, _cost = _calc_realistic_pnl(entry, stop, size, "SHORT", t.get("date",""), cfg["leverage"])
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "status":"CLOSED","exit_price":stop,
                    "exit_date":datetime.utcnow().isoformat(),
                    "pnl":round(pnl,2),
                    "notes":(t.get("notes","") + " |STOP")
                })
                print(f"[TRADER] STOP SHORT @${stop:.0f} PnL:${pnl:.0f}")
            
            elif price <= tp:
                pnl, _cost = _calc_realistic_pnl(entry, tp, size, "SHORT", t.get("date",""), cfg["leverage"])
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "status":"CLOSED","exit_price":tp,
                    "exit_date":datetime.utcnow().isoformat(),
                    "pnl":round(pnl,2),
                    "notes":(t.get("notes","") + " |TP")
                })
                print(f"[TRADER] TP SHORT @${tp:.0f} PnL:${pnl:.0f}")
            
            elif bull_tech and not bear_tech:
                pnl, _cost = _calc_realistic_pnl(entry, price, size, "SHORT", t.get("date",""), cfg["leverage"])
                supa_patch(f"trades?trade_id=eq.{trade_id}", {
                    "status":"CLOSED","exit_price":price,
                    "exit_date":datetime.utcnow().isoformat(),
                    "pnl":round(pnl,2),
                    "notes":(t.get("notes","") + " |REGIME_EXIT")
                })
                print(f"[TRADER] REGIME EXIT SHORT @${price:.0f} PnL:${pnl:.0f}")

    if open_trades:
        _log_alignment(snapshot_ts=d.get("timestamp"), spot=spot, rsi=rsi_v, e9=e9[n], e21=e21[n], e50=e50[n], e200=e200[n], atr=atr_v, bull_tech=bull_tech, bear_tech=bear_tech, gex=gex, hvl=hvl, flip_near=flip_near, regime=regime, pyramid_decision=d.get("pyramid_decision"), block_reason="open_trade", momentum_score=mom_score, funding_rate=funding_rate, funding_z=funding_z, pyramid_total=pyramid_total, pyramid_agreement=("pyr_%s_c4_blocked" % _pyr_dir if _pyr_dir!="neutral" else "neutral"), gex_z=gex_z)
        print("[TRADER] Açık trade var — yeni açılmıyor"); return
    
    if flip_near:
        _log_alignment(snapshot_ts=d.get("timestamp"), spot=spot, rsi=rsi_v, e9=e9[n], e21=e21[n], e50=e50[n], e200=e200[n], atr=atr_v, bull_tech=bull_tech, bear_tech=bear_tech, gex=gex, hvl=hvl, flip_near=flip_near, regime=regime, pyramid_decision=d.get("pyramid_decision"), block_reason="flip_near", momentum_score=mom_score, funding_rate=funding_rate, funding_z=funding_z, pyramid_total=pyramid_total, pyramid_agreement=("pyr_%s_c4_blocked" % _pyr_dir if _pyr_dir!="neutral" else "neutral"), gex_z=gex_z)
        print(f"[TRADER] Flip yakın — bekle"); return
    if expiry_day:
        _log_alignment(snapshot_ts=d.get("timestamp"), spot=spot, rsi=rsi_v, e9=e9[n], e21=e21[n], e50=e50[n], e200=e200[n], atr=atr_v, bull_tech=bull_tech, bear_tech=bear_tech, gex=gex, hvl=hvl, flip_near=flip_near, regime=regime, pyramid_decision=d.get("pyramid_decision"), block_reason="expiry_day", momentum_score=mom_score, funding_rate=funding_rate, funding_z=funding_z, pyramid_total=pyramid_total, pyramid_agreement=("pyr_%s_c4_blocked" % _pyr_dir if _pyr_dir!="neutral" else "neutral"), gex_z=gex_z)
        print("[TRADER] Expiry günü — bekle"); return
    if iv_crush:
        _log_alignment(snapshot_ts=d.get("timestamp"), spot=spot, rsi=rsi_v, e9=e9[n], e21=e21[n], e50=e50[n], e200=e200[n], atr=atr_v, bull_tech=bull_tech, bear_tech=bear_tech, gex=gex, hvl=hvl, flip_near=flip_near, regime=regime, pyramid_decision=d.get("pyramid_decision"), block_reason="iv_crush", momentum_score=mom_score, funding_rate=funding_rate, funding_z=funding_z, pyramid_total=pyramid_total, pyramid_agreement=("pyr_%s_c4_blocked" % _pyr_dir if _pyr_dir!="neutral" else "neutral"), gex_z=gex_z)
        print(f"[TRADER] IV Crush ({term_shape}, IV:{iv_rank:.0f}%) — bekle"); return

    long_signal  = bull_tech and e9[n]>e21[n] and price>hvl and gex>0
    short_signal = bear_tech and e9[n]<e21[n] and price<hvl and gex<0

    # --- FUNDING VETO karari (observe-only): trade akisini DEGISTIRMEZ ---
    funding_veto = None
    if funding_z is not None:
        if long_signal and funding_z > FUNDING_VETO_STD:
            funding_veto = "would_veto_long"
        elif short_signal and funding_z < -FUNDING_VETO_STD:
            funding_veto = "would_veto_short"
    print("[FUNDING] veto=%s" % funding_veto)

    print(f"[TRADER] long_signal={long_signal} short_signal={short_signal} ec_mult={ec_mult:.2f}")

    # PYRAMID agreement (sinyal path): C4 sinyali ile pyramid yonu uyusuyor mu
    if long_signal:
        pyramid_agreement = "agree_long" if _pyr_dir=="long" else ("conflict" if _pyr_dir=="short" else "c4_long_pyr_neutral")
    elif short_signal:
        pyramid_agreement = "agree_short" if _pyr_dir=="short" else ("conflict" if _pyr_dir=="long" else "c4_short_pyr_neutral")
    else:
        pyramid_agreement = ("pyr_%s_c4_flat" % _pyr_dir) if _pyr_dir!="neutral" else "both_neutral"
    print("[PYRAMID] agreement=%s" % pyramid_agreement)

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
        _log_alignment(snapshot_ts=d.get("timestamp"), spot=spot, rsi=rsi_v, e9=e9[n], e21=e21[n], e50=e50[n], e200=e200[n], atr=atr_v, bull_tech=bull_tech, bear_tech=bear_tech, gex=gex, hvl=hvl, flip_near=flip_near, regime=regime, pyramid_decision=d.get("pyramid_decision"), long_signal=long_signal, short_signal=short_signal, trade_opened=True, block_reason="opened_long", momentum_score=mom_score, funding_rate=funding_rate, funding_z=funding_z, funding_veto=funding_veto, pyramid_total=pyramid_total, pyramid_agreement=pyramid_agreement, gex_z=gex_z)

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
        _log_alignment(snapshot_ts=d.get("timestamp"), spot=spot, rsi=rsi_v, e9=e9[n], e21=e21[n], e50=e50[n], e200=e200[n], atr=atr_v, bull_tech=bull_tech, bear_tech=bear_tech, gex=gex, hvl=hvl, flip_near=flip_near, regime=regime, pyramid_decision=d.get("pyramid_decision"), long_signal=long_signal, short_signal=short_signal, trade_opened=True, block_reason="opened_short", momentum_score=mom_score, funding_rate=funding_rate, funding_z=funding_z, funding_veto=funding_veto, pyramid_total=pyramid_total, pyramid_agreement=pyramid_agreement, gex_z=gex_z)
    
    else:
        print(f"[TRADER] Sinyal yok — BEKLE")
        _log_alignment(snapshot_ts=d.get("timestamp"), spot=spot, rsi=rsi_v, e9=e9[n], e21=e21[n], e50=e50[n], e200=e200[n], atr=atr_v, bull_tech=bull_tech, bear_tech=bear_tech, gex=gex, hvl=hvl, flip_near=flip_near, regime=regime, pyramid_decision=d.get("pyramid_decision"), long_signal=long_signal, short_signal=short_signal, trade_opened=False, block_reason="no_signal", momentum_score=mom_score, funding_rate=funding_rate, funding_z=funding_z, funding_veto=funding_veto, pyramid_total=pyramid_total, pyramid_agreement=pyramid_agreement, gex_z=gex_z)

    print("[TRADER] Tamamlandı")

if __name__ == "__main__":
    run_trader()
