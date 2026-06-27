"""
regime_logger.py
G-DIVE EP Chan / Hurst Regime Logger
======================================
EP Chan "Algorithmic Trading" kitabından Hurst Exponent + ADF testi ile
piyasa rejimini her trade açılışında ve günlük snapshot'ta loglar.

Supabase'deki mevcut regime_log tablosu kolonlarına birebir uygun:
    id, timestamp, trigger_type, trade_id, trade_direction,
    hurst_4h_100, hurst_regime, adf_pvalue, adf_stationary,
    btc_price, trade_pnl, trade_win, created_at

REGIME_POLICY.md eşikleri (EP Chan standardı):
    H < 0.45  -> MEAN_REVERTING
    H > 0.55  -> TRENDING
    arası     -> RANDOM

Entegrasyon kriteri (henüz trade_gate'e bağlanmıyor):
    min 30 tamamlanmış trade + mean-reverting avg PnL >= $30 fazla +
    Mann-Whitney p < 0.10 -> o zaman sleeve_gate'e bağlanır.

Kullanim (gdive_server.py icinde):
    from regime_logger import log_regime, update_regime_pnl

    # Trade acilisinda:
    log_regime(
        trigger_type="trade_open",
        btc_price=data["spot"],
        trade_id=str(trade["id"]),
        trade_direction=trade["direction"],
        prices=prices_series,   # pd.Series, son 100 mum kapanisi
    )

    # Trade kapanisinda PnL guncelle:
    update_regime_pnl(
        trade_id=str(trade["id"]),
        trade_pnl=closed_pnl,
        trade_win=(closed_pnl > 0),
    )

    # Gunluk snapshot (GitHub Actions cron'unda, trade yoksa da calisir):
    log_regime(
        trigger_type="daily_snapshot",
        btc_price=data["spot"],
        prices=prices_series,
    )
"""

import json
import math
import os
import urllib.request
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# HURST EXPONENT (R/S analizi, EP Chan Chapter 2)
# ---------------------------------------------------------------------------

def compute_hurst(series) -> float:
    """
    Hurst Exponent'i R/S analizi ile hesaplar.
    series: list veya pd.Series, min 20 eleman gerekli.
    Donus: 0.0-1.0 arasi float, hata durumunda 0.5 (random varsayim).
    """
    try:
        import numpy as np
        s = list(series)
        n = len(s)
        if n < 20:
            return 0.5

        lags = [2, 4, 8, 16, 32]
        lags = [l for l in lags if l < n // 2]
        if len(lags) < 3:
            return 0.5

        rs_vals = []
        for lag in lags:
            segments = [s[i:i+lag] for i in range(0, n - lag, lag)]
            rs_seg = []
            for seg in segments:
                mean = sum(seg) / len(seg)
                deviations = [x - mean for x in seg]
                cumdev = [sum(deviations[:i+1]) for i in range(len(deviations))]
                R = max(cumdev) - min(cumdev)
                std = (sum((x - mean)**2 for x in seg) / len(seg)) ** 0.5
                if std > 0:
                    rs_seg.append(R / std)
            if rs_seg:
                rs_vals.append((math.log(lag), math.log(sum(rs_seg) / len(rs_seg))))

        if len(rs_vals) < 3:
            return 0.5

        x = [v[0] for v in rs_vals]
        y = [v[1] for v in rs_vals]
        n_pts = len(x)
        x_mean = sum(x) / n_pts
        y_mean = sum(y) / n_pts
        slope = (
            sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n_pts)) /
            sum((x[i] - x_mean) ** 2 for i in range(n_pts))
        )
        return round(max(0.0, min(1.0, slope)), 4)

    except Exception:
        return 0.5


# ---------------------------------------------------------------------------
# ADF TESTI (durağanlık, EP Chan Chapter 2)
# ---------------------------------------------------------------------------

def compute_adf(series) -> tuple:
    """
    ADF testi için statsmodels kullanır. Yoksa basit variance-ratio proxy.
    Donus: (pvalue: float, stationary: bool)
    """
    try:
        from statsmodels.tsa.stattools import adfuller
        s = list(series)
        if len(s) < 20:
            return (1.0, False)
        result = adfuller(s, maxlag=1, autolag=None)
        pvalue = round(float(result[1]), 4)
        return (pvalue, pvalue < 0.05)
    except ImportError:
        # statsmodels yoksa variance-ratio proxy (kaba tahmın)
        s = list(series)
        n = len(s)
        if n < 20:
            return (1.0, False)
        returns = [s[i] - s[i-1] for i in range(1, n)]
        var1 = sum(r**2 for r in returns) / len(returns)
        returns2 = [s[i] - s[i-2] for i in range(2, n)]
        var2 = sum(r**2 for r in returns2) / len(returns2)
        vr = var2 / (2 * var1) if var1 > 0 else 1.0
        pvalue = round(abs(vr - 1.0), 4)
        return (pvalue, pvalue > 0.3)
    except Exception:
        return (1.0, False)


# ---------------------------------------------------------------------------
# REGIME SINIFLANDIRMA
# ---------------------------------------------------------------------------

def classify_hurst(h: float) -> str:
    if h < 0.45:
        return "MEAN_REVERTING"
    elif h > 0.55:
        return "TRENDING"
    return "RANDOM"


# ---------------------------------------------------------------------------
# SUPABASE YARDIMCI
# ---------------------------------------------------------------------------

def _headers():
    key = os.environ["SUPABASE_KEY"]
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


# ---------------------------------------------------------------------------
# ANA FONKSİYONLAR — gdive_server.py'den çağrılır
# ---------------------------------------------------------------------------

def log_regime(
    trigger_type: str,          # "trade_open" | "daily_snapshot"
    btc_price: float,
    prices,                      # pd.Series veya list, son 100 bar kapanış
    trade_id: str = None,
    trade_direction: str = None, # "LONG" | "SHORT" | None
) -> None:
    """
    regime_log tablosuna bir satır yazar.
    trade_id ve trade_direction: sadece trigger_type="trade_open" için.
    """
    try:
        price_list = list(prices) if hasattr(prices, '__iter__') else []
        hurst = compute_hurst(price_list)
        adf_p, adf_stat = compute_adf(price_list)
        regime = classify_hurst(hurst)

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trigger_type": trigger_type,
            "trade_id": trade_id,
            "trade_direction": trade_direction,
            "hurst_4h_100": hurst,
            "hurst_regime": regime,
            "adf_pvalue": adf_p,
            "adf_stationary": adf_stat,
            "btc_price": btc_price,
            "trade_pnl": None,
            "trade_win": None,
        }

        url = f"{os.environ['SUPABASE_URL']}/rest/v1/regime_log"
        req = urllib.request.Request(
            url,
            data=json.dumps(entry).encode(),
            headers=_headers(),
            method="POST",
        )
        urllib.request.urlopen(req)
        print(f"[REGIME] {trigger_type} H={hurst} ({regime}) ADF_p={adf_p} stat={adf_stat}")

    except Exception as e:
        print(f"[REGIME] log_regime HATA: {e}")


def update_regime_pnl(
    trade_id: str,
    trade_pnl: float,
    trade_win: bool,
) -> None:
    """
    Trade kapanışında ilgili trade_open satırına PnL sonucunu yazar.
    trade_id ile eşleşen en son satırı PATCH'ler.
    """
    try:
        url = (
            f"{os.environ['SUPABASE_URL']}/rest/v1/regime_log"
            f"?trade_id=eq.{trade_id}&trigger_type=eq.trade_open"
            f"&order=timestamp.desc&limit=1"
        )
        payload = json.dumps({
            "trade_pnl": round(trade_pnl, 2),
            "trade_win": trade_win,
        }).encode()
        req = urllib.request.Request(
            url, data=payload, headers=_headers(), method="PATCH"
        )
        urllib.request.urlopen(req)
        print(f"[REGIME] update_pnl trade_id={trade_id} pnl={trade_pnl:.2f} win={trade_win}")

    except Exception as e:
        print(f"[REGIME] update_regime_pnl HATA: {e}")
