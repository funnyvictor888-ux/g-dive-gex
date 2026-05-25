"""
pyramid.py
G-DIVE Karar Piramidi — frontend buildDecisionLayers() Python portu.

Yaklaşım A (hızlı):
  - Katman 1 (Gamma Rejimi): snapshot field'larından direkt
  - Katman 2 (Opsiyon Yapısı): snapshot field'larından direkt
  - Katman 3 (Teknik Sinyal): Binance 4H closes → EMA/RSI/MACD/BB
  - Katman 4 (Opsiyon Notu): Supabase option_notes son satır + keyword match
  - Katman 5 (Risk Filtre): Sadece flipNear (kill_switch yok kabul)
  - Katman 6 (Taleb Shadow): taleb dict'ten direkt

Kullanım:
  from pyramid import compute_pyramid
  result = compute_pyramid(data, closes_4h, last_note_text)
  # result = {
  #   "total_score": int,
  #   "decision": "LONG HAZIR" | "BEKLE" | ...,
  #   "blocked": bool,
  #   "layers": [{"id": 1, "signal": 1, "status": "POZİTİF", ...}, ...]
  # }
"""

from typing import Optional, List, Dict


# ---------------------------------------------------------------------------
# Indicator hesaplamaları — frontend ile birebir
# ---------------------------------------------------------------------------

def ema(values: List[float], period: int) -> List[float]:
    """Exponential Moving Average. Frontend ile aynı: ilk N değer SMA, sonra EMA."""
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def rsi(values: List[float], period: int = 14) -> Optional[float]:
    """Wilder RSI. Frontend mantığıyla aynı."""
    if len(values) < period + 1:
        return None

    gains = []
    losses = []
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(values: List[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD histogram. Returns (macd_value, signal_value, hist_value)."""
    if len(values) < slow + signal:
        return None, None, None

    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)

    # Hizala — ema_slow daha kısa, ema_fast'ı kırp
    offset = len(ema_fast) - len(ema_slow)
    ema_fast = ema_fast[offset:]

    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = ema(macd_line, signal)

    # Hizala
    offset = len(macd_line) - len(signal_line)
    macd_line = macd_line[offset:]

    hist = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line[-1], signal_line[-1], hist[-1]


def bollinger_bands(values: List[float], period: int = 20, mult: float = 2.0):
    """Bollinger Bands. Returns (upper, middle, lower) of last bar."""
    if len(values) < period:
        return None
    recent = values[-period:]
    mean = sum(recent) / period
    var = sum((x - mean) ** 2 for x in recent) / period
    std = var ** 0.5
    return {
        "upper": mean + mult * std,
        "middle": mean,
        "lower": mean - mult * std,
    }


def compute_tech_score(closes: List[float]) -> Optional[Dict]:
    """
    Frontend computeTechScore mantığı:
      EMA9 vs EMA21, RSI thresholds, MACD signal, BB %B
    Returns: {price, ema9, ema21, rsi, macd, signal, hist, bb, score}
    """
    if not closes or len(closes) < 30:
        return None

    e9 = ema(closes, 9)
    e21 = ema(closes, 21)
    rsi_v = rsi(closes, 14)
    macd_v, sig_v, hist_v = macd(closes)
    bb = bollinger_bands(closes, 20, 2.0)

    if not (e9 and e21 and rsi_v is not None and macd_v is not None and bb):
        return None

    ema9_last = e9[-1]
    ema21_last = e21[-1]
    price = closes[-1]

    score = 0

    # EMA
    if ema9_last > ema21_last:
        score += 1
    else:
        score -= 1

    # RSI
    if rsi_v > 70:
        score -= 1
    elif rsi_v < 30:
        score += 1
    elif rsi_v > 55:
        score += 1
    elif rsi_v < 45:
        score -= 1

    # MACD
    if macd_v > sig_v:
        score += 1
    else:
        score -= 1

    # BB %B
    bp = (price - bb["lower"]) / (bb["upper"] - bb["lower"]) if bb["upper"] > bb["lower"] else 0.5
    if bp > 0.85:
        score -= 1
    elif bp < 0.15:
        score += 1
    elif bp > 0.5:
        score += 1

    return {
        "price": price,
        "ema9": ema9_last,
        "ema21": ema21_last,
        "rsi": rsi_v,
        "macd": macd_v,
        "signal": sig_v,
        "hist": hist_v,
        "bb": bb,
        "bb_pct": bp * 100,
        "score": score,
    }


# ---------------------------------------------------------------------------
# Opsiyon Notu keyword analizi (frontend ile birebir)
# ---------------------------------------------------------------------------

def analyze_note_text(text: Optional[str]) -> int:
    """
    Frontend mantığı:
      bull keywords: long, bull, alim, pozitif, yukari, break, kir
      bear keywords: short, bear, satim, negatif, asagi, kirik, dusus
      bull && !bear → +1, bear && !bull → -1, else 0
    """
    if not text:
        return 0
    t = text.lower()
    bull_kw = ["long", "bull", "alim", "pozitif", "yukari", "break", "kir"]
    bear_kw = ["short", "bear", "satim", "negatif", "asagi", "kirik", "dusus"]
    bull = any(k in t for k in bull_kw)
    bear = any(k in t for k in bear_kw)
    if bull and not bear:
        return 1
    if bear and not bull:
        return -1
    return 0


# ---------------------------------------------------------------------------
# Ana fonksiyon — Karar Piramidi
# ---------------------------------------------------------------------------

def compute_pyramid(data: dict,
                    closes_4h: Optional[List[float]] = None,
                    last_note_text: Optional[str] = None) -> dict:
    """
    Frontend buildDecisionLayers'ın birebir Python portu.

    Args:
      data: Backend build_data() output (spot, hvl, gex, vs.)
      closes_4h: Binance 4H close fiyatları (Katman 3 için)
      last_note_text: Supabase option_notes son satır text'i (Katman 4 için)

    Returns:
      {
        "total_score": int,
        "decision": str,
        "blocked": bool,
        "layers": [{"id", "signal", "status", "detail"}, ...]
      }
    """
    layers = []

    spot = data.get("spot") or 0
    hvl = data.get("hvl") or 0
    gex = data.get("total_net_gex") or 0
    regime = data.get("regime") or ""
    gamma = data.get("gamma_regime") or ""
    iv_rank = data.get("iv_rank") or 0
    front_iv = data.get("front_iv") or 0
    term_shape = data.get("term_shape") or ""
    max_pain = data.get("max_pain")

    ga = data.get("gamma_analysis") or {}
    flip_dist = ga.get("flip_distance_pct") or 0
    flip_near = ga.get("flip_near") or False

    expiry = data.get("expiry") or {}
    expiry_day = expiry.get("expiry_day") or False
    days_to_expiry = expiry.get("days_to_expiry")

    # ─── Katman 1: Gamma Rejimi ───
    gamma_ok = (gamma == "LONG_GAMMA") and (spot > hvl)
    l1_signal = 1 if gamma_ok else (0 if flip_near else -1)
    l1_status = "POZİTİF" if gamma_ok else ("FLIP YAKINI" if flip_near else "NEGATİF")
    layers.append({
        "id": 1,
        "title": "Gamma Rejimi",
        "signal": l1_signal,
        "status": l1_status,
        "detail": f"gamma={gamma} spot={spot:.0f} hvl={hvl:.0f} flip_near={flip_near}"
    })

    # ─── Katman 2: Opsiyon Yapısı ───
    gex_ok = gex > 0
    iv_ok = iv_rank < 75
    if gex_ok and iv_ok:
        l2_signal = 1
        l2_status = "BULLISH OI"
    elif not gex_ok:
        l2_signal = -1
        l2_status = "BEARISH"
    else:
        l2_signal = 0
        l2_status = "IV YÜKSEK" if iv_rank >= 75 else "NÖTR"

    layers.append({
        "id": 2,
        "title": "Opsiyon Yapısı",
        "signal": l2_signal,
        "status": l2_status,
        "detail": f"gex={gex:.0f} iv_rank={iv_rank:.0f} front_iv={front_iv:.1f} term={term_shape}"
    })

    # ─── Katman 3: Teknik Sinyal ───
    t4 = compute_tech_score(closes_4h) if closes_4h else None
    if t4:
        tech_score = t4["score"]
        sign = 1 if tech_score > 0 else (-1 if tech_score < 0 else 0)
        if tech_score >= 3:
            status = "GÜÇLÜ LONG"
        elif tech_score >= 1:
            status = "LONG"
        elif tech_score <= -3:
            status = "GÜÇLÜ SHORT"
        elif tech_score <= -1:
            status = "SHORT"
        else:
            status = "NÖTR"
        detail = (f"score={tech_score} ema9={t4['ema9']:.0f} ema21={t4['ema21']:.0f} "
                  f"rsi={t4['rsi']:.1f} hist={t4['hist']:.0f} bb%={t4['bb_pct']:.0f}")
    else:
        sign = 0
        status = "Yükleniyor"
        detail = "Binance verisi yok"

    layers.append({
        "id": 3,
        "title": "Teknik Sinyal",
        "signal": sign,
        "status": status,
        "detail": detail
    })

    # ─── Katman 4: Opsiyon Notu ───
    note_signal = analyze_note_text(last_note_text)
    layers.append({
        "id": 4,
        "title": "Opsiyon Notu",
        "signal": note_signal,
        "status": "BULLISH" if note_signal > 0 else ("BEARISH" if note_signal < 0 else "NÖTR"),
        "detail": (last_note_text or "")[:80] if last_note_text else "not yok"
    })

    # ─── Katman 5: Risk Filtre (basit — flipNear only) ───
    # Yaklaşım A: kill_switch ve expiry_day backtest'te %0 etkisi, sadece flipNear
    risk_score = -1 if flip_near else 0
    layers.append({
        "id": 5,
        "title": "Risk Filtre",
        "signal": risk_score,
        "status": "FLIP YAKINI" if flip_near else "TEMİZ",
        "detail": f"flip_near={flip_near} flip_dist={flip_dist:.2f}%"
    })

    # ─── Katman 6: Taleb Shadow (frontend mantığı) ───
    taleb = data.get("taleb") or {}
    if taleb:
        pin = (taleb.get("pin_risk") or {}).get("pin_score") or 0
        amp = (taleb.get("shadow_gex") or {}).get("gex_amplifier") or 1
        band = (taleb.get("rehedge_band") or {}).get("band_pct") or 0

        if pin >= 7.5:
            t_signal = -1
            t_status = "PIN RİSKİ YÜKSEK"
        elif amp > 1.3:
            t_signal = -1
            t_status = "VOL ETKİSİ BÜYÜK"
        elif pin < 3 and amp < 1.1:
            t_signal = 1
            t_status = "SHADOW NORMAL"
        else:
            t_signal = 0
            t_status = "SHADOW İZLENİYOR"

        layers.append({
            "id": 6,
            "title": "Taleb Shadow",
            "signal": t_signal,
            "status": t_status,
            "detail": f"pin={pin:.1f} amp={amp:.2f} band={band:.2f}%"
        })

    # ─── Toplam skor + karar ───
    total = sum(l["signal"] for l in layers)
    blocked = expiry_day  # kill_switch yok kabul

    if blocked:
        decision = "BLOKE"
    elif total >= 3:
        decision = "LONG AÇILIYOR"
    elif total >= 2:
        decision = "LONG HAZIR"
    elif total <= -3:
        decision = "SHORT AÇILIYOR"
    elif total <= -2:
        decision = "SHORT HAZIR"
    else:
        decision = "BEKLE"

    return {
        "total_score": total,
        "decision": decision,
        "blocked": blocked,
        "layers": layers,
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Test 1: pozitif gamma + bullish OI + bullish technicals + bullish note
    fake_data = {
        "spot": 80000,
        "hvl": 78000,
        "total_net_gex": 15000.0,
        "gamma_regime": "LONG_GAMMA",
        "regime": "BULLISH_HIGH_VOL",
        "iv_rank": 30,
        "front_iv": 28,
        "term_shape": "CONTANGO",
        "max_pain": 76000,
        "gamma_analysis": {"flip_distance_pct": 2.5, "flip_near": False},
        "expiry": {"days_to_expiry": 18, "expiry_day": False},
        "taleb": {"pin_risk": {"pin_score": 2}, "shadow_gex": {"gex_amplifier": 1.05}, "rehedge_band": {"band_pct": 0.5}},
    }

    # Sentetik trend: yukarı eğimli 100 close
    closes = [70000 + i * 100 + (i % 7) * 50 for i in range(100)]

    result = compute_pyramid(fake_data, closes_4h=closes, last_note_text="bullish break, yukari long bias")

    print(f"Test 1 — Bullish ortam")
    print(f"  Total Score: {result['total_score']}")
    print(f"  Decision: {result['decision']}")
    print(f"  Blocked: {result['blocked']}")
    for l in result["layers"]:
        sign_str = f"+{l['signal']}" if l['signal'] > 0 else str(l['signal'])
        print(f"  L{l['id']} {l['title']:18} {sign_str:>3}  {l['status']:18}  {l['detail']}")

    # Test 2: flip_near scenario
    fake_data2 = dict(fake_data)
    fake_data2["gamma_analysis"] = {"flip_distance_pct": 0.4, "flip_near": True}
    result2 = compute_pyramid(fake_data2, closes_4h=closes, last_note_text=None)
    print(f"\nTest 2 — Flip Near")
    print(f"  Total Score: {result2['total_score']}, Decision: {result2['decision']}")

    # Test 3: bearish
    closes_down = [80000 - i * 50 - (i % 5) * 30 for i in range(100)]
    fake_data3 = dict(fake_data)
    fake_data3["gamma_regime"] = "NEGATIVE_GAMMA"
    fake_data3["spot"] = 76000
    fake_data3["hvl"] = 78000
    fake_data3["total_net_gex"] = -5000.0
    result3 = compute_pyramid(fake_data3, closes_4h=closes_down, last_note_text="bearish kirik, asagi")
    print(f"\nTest 3 — Bearish ortam")
    print(f"  Total Score: {result3['total_score']}, Decision: {result3['decision']}")
