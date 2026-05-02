"""
taleb_integration_patch.py
===========================
Bu dosyayı gdive_server.py'nin sonuna ekle (veya import et).
Taleb Shadow GEX, Rehedge Band ve Pin Risk hesaplamalarını
mevcut /data endpoint'ine ekler.

Kullanım (gdive_server.py içinde):
    from taleb_integration_patch import compute_taleb_metrics
    # /data response'una ekle:
    data["taleb"] = compute_taleb_metrics(options_data, spot, atm_iv, rv_7g)
"""

import math


# ─────────────────────────────────────────────────────────────────
# 1. SHADOW GEX (Taleb Dynamic Hedging, Chapter 8, s.138-140)
#    Shadow_Gamma = BSM_Gamma + Vanna × (dσ/dS)
#    BTC'de spot düşünce vol yükselir → dσ/dS negatif
#    Bu gerçek dealer hedge yükünü BSM'den daha doğru ölçer
# ─────────────────────────────────────────────────────────────────

def compute_vanna(S, K, T, r, sigma):
    """
    Vanna = ∂Delta/∂σ = ∂Vega/∂S
    Standart BSM formülü.
    """
    if T <= 0 or sigma <= 0:
        return 0.0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        nd1 = math.exp(-0.5 * d1 ** 2) / math.sqrt(2 * math.pi)
        vanna = -nd1 * d2 / sigma
        return vanna
    except (ValueError, ZeroDivisionError):
        return 0.0


def compute_shadow_gex(
    options_data: list[dict],
    spot: float,
    dsigma_dS: float = -0.002,   # BTC tipik: vol her $1K düşüşte ~%0.2 artar
) -> dict:
    """
    Tüm opsiyon pozisyonları için Shadow GEX hesaplar.

    options_data: [
        {
            "strike": float,
            "expiry_days": float,       # kalan gün
            "oi_btc": float,            # açık pozisyon BTC
            "type": "C" | "P",
            "iv": float,                # mark IV (0-100 arası)
            "gamma": float,             # BSM gamma
        },
        ...
    ]
    """
    r = 0.05  # risksiz faiz yaklaşımı
    shadow_gex_by_strike: dict[float, float] = {}
    bsm_gex_by_strike: dict[float, float] = {}

    for opt in options_data:
        try:
            K = float(opt["strike"])
            T = max(float(opt.get("expiry_days", 1)), 0.001) / 365
            oi = float(opt.get("oi_btc", 0))
            opt_type = opt.get("type", "C")
            iv = float(opt.get("iv", 50)) / 100
            bsm_gamma = float(opt.get("gamma", 0))

            # Vanna hesapla
            vanna = compute_vanna(spot, K, T, r, iv)

            # Shadow Gamma = BSM Gamma + Vanna × (dσ/dS)
            shadow_gamma = bsm_gamma + vanna * dsigma_dS

            # GEX = Gamma × OI × Spot²  (notional bazlı)
            # Put için işaret tersine çevrilir (dealer puts short → negatif gamma)
            sign = 1.0 if opt_type == "C" else -1.0
            bsm_gex   = sign * bsm_gamma    * oi * spot * spot / 100
            shadow_gex = sign * shadow_gamma * oi * spot * spot / 100

            strike_key = round(K / 1000) * 1000  # 1K gruplama

            shadow_gex_by_strike[strike_key] = (
                shadow_gex_by_strike.get(strike_key, 0) + shadow_gex
            )
            bsm_gex_by_strike[strike_key] = (
                bsm_gex_by_strike.get(strike_key, 0) + bsm_gex
            )
        except (KeyError, ValueError, TypeError):
            continue

    # Toplam net GEX farkı
    total_shadow = sum(shadow_gex_by_strike.values())
    total_bsm    = sum(bsm_gex_by_strike.values())
    gex_amplifier = (total_shadow / total_bsm) if total_bsm != 0 else 1.0

    # Strike bazlı karşılaştırma (sadece yakın bölge, ±20%)
    comparison = []
    for strike in sorted(shadow_gex_by_strike.keys()):
        if abs(strike - spot) / spot > 0.20:
            continue
        comparison.append({
            "strike": strike,
            "bsm_gex_m":    round(bsm_gex_by_strike.get(strike, 0) / 1e6, 3),
            "shadow_gex_m": round(shadow_gex_by_strike.get(strike, 0) / 1e6, 3),
            "diff_m":       round(
                (shadow_gex_by_strike.get(strike, 0) - bsm_gex_by_strike.get(strike, 0)) / 1e6, 3
            ),
        })

    return {
        "total_bsm_gex_m":    round(total_bsm    / 1e6, 2),
        "total_shadow_gex_m": round(total_shadow  / 1e6, 2),
        "gex_amplifier":      round(gex_amplifier, 3),   # >1 = vol etkisi GEX'i büyütüyor
        "dsigma_dS":          dsigma_dS,
        "by_strike":          comparison,
        "regime": (
            "SHADOW_POSITIVE" if total_shadow > 0
            else "SHADOW_NEGATIVE"
        ),
    }


# ─────────────────────────────────────────────────────────────────
# 2. REHEDGE BAND (Taleb Dynamic Hedging, Chapter 11-14)
#    Band_Width = k × σ × √(Γ × TC)
#    k ≈ 1.5–2.0, TC = transaction cost fraction
# ─────────────────────────────────────────────────────────────────

def compute_rehedge_band(
    spot: float,
    atm_iv: float,          # 0-100 arası
    net_gamma: float,       # normalize gamma (~0.001 tipik)
    transaction_cost: float = 0.0005,  # %0.05 = maker fee tipik
    k: float = 1.75,        # Taleb'in önerdiği orta değer
    vol_regime: str = "normal",  # "low" | "normal" | "high"
) -> dict:
    """
    Dealer'ın ne zaman hedge yapacağını belirleyen dinamik bant.
    Sabit ±%0.5 yerine vol rejimine göre genişler/daralır.
    """
    sigma = atm_iv / 100
    gamma = abs(net_gamma) if net_gamma != 0 else 1e-6

    # k'yı vol rejimine göre ayarla
    k_adjusted = {
        "low":    k * 0.75,
        "normal": k,
        "high":   k * 1.35,
    }.get(vol_regime, k)

    # Band genişliği (fiyat yüzdesi olarak)
    try:
        band_pct = k_adjusted * sigma * math.sqrt(abs(gamma) * transaction_cost)
    except (ValueError, ZeroDivisionError):
        band_pct = 0.005  # fallback %0.5

    band_pct = max(0.001, min(band_pct, 0.05))  # %0.1 - %5 arası sınırla

    upper = spot * (1 + band_pct)
    lower = spot * (1 - band_pct)

    return {
        "band_pct":     round(band_pct * 100, 3),   # yüzde olarak
        "upper_band":   round(upper, 0),
        "lower_band":   round(lower, 0),
        "k_used":       round(k_adjusted, 3),
        "vol_regime":   vol_regime,
        "sigma":        round(sigma, 4),
        "gamma_input":  round(gamma, 6),
        "interpretation": (
            "Dar bant — sık hedge, düşük TC toleransı"
            if band_pct < 0.008 else
            "Geniş bant — seyrek hedge, yüksek TC toleransı"
            if band_pct > 0.025 else
            "Normal bant"
        ),
    }


# ─────────────────────────────────────────────────────────────────
# 3. PIN RISK (Taleb Dynamic Hedging, Chapter 14, s.286)
#    "The skew is hedgeable, the pin is not"
#    Pin Risk = f(Max Pain, expiry gün sayısı, OI konsantrasyonu)
# ─────────────────────────────────────────────────────────────────

def compute_pin_risk(
    spot: float,
    max_pain: float,
    expiry_days: float,
    oi_concentration: float,   # En yoğun strike'ın toplam OI'ye oranı (0-1)
    front_oi_usd: float = 0,   # Front vade OI $
    total_oi_usd: float = 1,   # Toplam OI $
) -> dict:
    """
    Pin Risk Skoru: 0 (düşük) → 10 (kritik)

    Yüksek skor = expiry günü spot'un büyük strike'a yapışma riski yüksek.
    """
    if expiry_days <= 0:
        expiry_days = 0.01

    # Bileşen 1: Max Pain'e mesafe (yakın = yüksek risk)
    distance_pct = abs(spot - max_pain) / spot
    proximity_score = max(0, 10 * (1 - distance_pct / 0.05))  # %5 içinde tam puan

    # Bileşen 2: Zamana yakınlık (2 gün içinde kritik)
    time_score = max(0, 10 * (1 - expiry_days / 5))  # 5 günde sıfırlanır

    # Bileşen 3: OI konsantrasyonu
    concentration_score = oi_concentration * 10

    # Bileşen 4: Front vade ağırlığı
    front_weight = (front_oi_usd / total_oi_usd) if total_oi_usd > 0 else 0
    front_score = front_weight * 10

    # Ağırlıklı ortalama
    pin_score = (
        proximity_score    * 0.35 +
        time_score         * 0.30 +
        concentration_score * 0.20 +
        front_score        * 0.15
    )
    pin_score = min(10, round(pin_score, 1))

    return {
        "pin_score":           pin_score,
        "max_pain":            round(max_pain, 0),
        "spot_to_max_pain_pct": round(distance_pct * 100, 2),
        "expiry_days":         round(expiry_days, 1),
        "oi_concentration":    round(oi_concentration, 3),
        "components": {
            "proximity": round(proximity_score, 1),
            "time":      round(time_score, 1),
            "concentration": round(concentration_score, 1),
            "front_weight":  round(front_score, 1),
        },
        "risk_level": (
            "KRİTİK"    if pin_score >= 7.5 else
            "YÜKSEK"    if pin_score >= 5.0 else
            "ORTA"      if pin_score >= 2.5 else
            "DÜŞÜK"
        ),
        "action": (
            "Expiry saatlerinde pozisyon alma. Spot yapışabilir, opsiyonlar sert hareket yapar."
            if pin_score >= 7.5 else
            "Expiry gününde dikkatli ol. Stop'ları yakın tut."
            if pin_score >= 5.0 else
            "Normal izleme yeterli."
        ),
    }


# ─────────────────────────────────────────────────────────────────
# 4. ANA FONKSİYON — gdive_server.py'den çağrılır
# ─────────────────────────────────────────────────────────────────

def compute_taleb_metrics(
    options_data: list[dict],
    spot: float,
    atm_iv: float,
    rv_7g: float,
    net_gamma: float,
    max_pain: float,
    expiry_days: float,
    front_oi_usd: float = 0,
    total_oi_usd: float = 1,
) -> dict:
    """
    Tüm Taleb metriklerini hesaplar ve tek dict olarak döner.
    gdive_server.py'deki /data endpoint response'una eklenir:

        data["taleb"] = compute_taleb_metrics(...)
    """
    # Vol rejimi belirle (IV-RV farkına göre)
    iv_rv_spread = atm_iv - rv_7g
    if iv_rv_spread < -15:
        vol_regime = "high"    # gerçek vol çok yüksek → geniş band
    elif iv_rv_spread > 10:
        vol_regime = "low"     # gerçek vol düşük → dar band
    else:
        vol_regime = "normal"

    # OI konsantrasyonu (basit yaklaşım: ön vade ağırlığı)
    oi_concentration = min(1.0, (front_oi_usd / total_oi_usd) if total_oi_usd > 0 else 0.3)

    shadow = compute_shadow_gex(options_data, spot)
    rehedge = compute_rehedge_band(
        spot, atm_iv, net_gamma,
        vol_regime=vol_regime
    )
    pin = compute_pin_risk(
        spot, max_pain, expiry_days,
        oi_concentration, front_oi_usd, total_oi_usd
    )

    return {
        "shadow_gex":   shadow,
        "rehedge_band": rehedge,
        "pin_risk":     pin,
        "vol_regime":   vol_regime,
        "iv_rv_spread": round(iv_rv_spread, 2),
        # Özet sinyal: dashboard için tek bakışta okunabilir
        "summary": {
            "shadow_regime":  shadow["regime"],
            "gex_amplifier":  shadow["gex_amplifier"],
            "rehedge_band_pct": rehedge["band_pct"],
            "pin_score":      pin["pin_score"],
            "pin_level":      pin["risk_level"],
            "alert": (
                "⚠️ YÜKSEK PIN RİSKİ — Expiry saatlerinde dikkat!"
                if pin["pin_score"] >= 7.5 else
                "⚡ Shadow GEX BSM'den farklı — vol etkisi büyük"
                if abs(shadow["gex_amplifier"] - 1) > 0.3 else
                None
            ),
        },
    }
