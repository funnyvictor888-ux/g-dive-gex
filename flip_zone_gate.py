"""
flip_zone_gate.py
G-DIVE Flip-Zone Filter — Vol-aware dealer-regime transition guard

Mantık:
  flip_dist_pct = |spot - flip_price| / spot
  atr_pct       = ATR(14, 4H) / spot
  ratio         = flip_dist_pct / atr_pct

  DANGER : ratio < 0.5   -> BEKLE (1 mumda geçilebilir)
  CAUTION: 0.5 <= r < 2  -> pozisyon × 0.5, flip-kırma trade'i veto
  CLEAR  : ratio >= 2    -> normal

Tasarım notları:
  - Sabit % eşik yerine ATR-relative kullanılır → vol rejimine adapte.
  - Backtest gelene kadar interim default'lar: danger=0.5, caution=2.0.
  - Yapı: tek pure fonksiyon evaluate_flip_zone() + ATR fetcher.
"""

from dataclasses import dataclass
from typing import Literal, Optional
import requests

Zone = Literal["DANGER", "CAUTION", "CLEAR"]
Decision = Literal["BEKLE", "REDUCE", "OK", "VETO"]


@dataclass
class FlipZoneResult:
    zone: Zone
    decision: Decision
    position_multiplier: float       # 0.0, 0.5, 1.0
    flip_dist_pct: float             # ham mesafe (0.005 = %0.5)
    atr_pct: float                   # 4H ATR / spot
    flip_dist_atr_ratio: float       # flip_dist_pct / atr_pct
    reason: str
    override_pyramid: bool           # True → karar piramidi sonucu yok sayılır


# ---------------------------------------------------------------------------
# ATR fetcher
# ---------------------------------------------------------------------------

def fetch_atr_4h(symbol: str = "BTCUSDT", period: int = 14) -> Optional[float]:
    """
    Binance Public API'den 4H ATR yüzdesi hesapla.
    Dönüş: ATR / son kapanış (0.012 = %1.2). Hata olursa None.
    """
    try:
        url = "https://api.binance.com/api/v3/klines"
        r = requests.get(
            url,
            params={"symbol": symbol, "interval": "4h", "limit": period + 1},
            timeout=8
        )
        klines = r.json()

        if not isinstance(klines, list) or len(klines) < period + 1:
            print(f"[flip_zone] Binance ATR: yetersiz veri ({len(klines) if isinstance(klines, list) else 'N/A'})")
            return None

        # [open_time, open, high, low, close, volume, ...]
        trs = []
        prev_close = float(klines[0][4])
        for k in klines[1:]:
            high = float(k[2])
            low = float(k[3])
            close = float(k[4])
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
            prev_close = close

        atr = sum(trs) / len(trs)
        last_close = float(klines[-1][4])
        return atr / last_close

    except Exception as e:
        print(f"[flip_zone] ATR fetch error: {e}")
        return None


# ---------------------------------------------------------------------------
# Gate logic
# ---------------------------------------------------------------------------

def evaluate_flip_zone(
    spot: float,
    flip_price: float,
    pyramid_direction: str,                # "long" | "short" | "neutral"
    atr_pct: Optional[float] = None,
    danger_mult: float = 0.5,              # ATR çarpanı eşikleri (backtest'le değişecek)
    caution_mult: float = 2.0,
    fallback_atr_pct: float = 0.012        # ATR fetch başarısız → BTC tipik 4H ATR ~%1.2
) -> FlipZoneResult:
    """
    Karar piramidini flip-zone filtresinden geçir.
    Interim default eşikleri: danger 0.5×ATR, caution 2.0×ATR.
    Backtest sonrası optimize edilecek.
    """
    if atr_pct is None or atr_pct <= 0:
        atr_pct = fallback_atr_pct

    flip_dist_pct = abs(spot - flip_price) / spot
    ratio = flip_dist_pct / atr_pct

    # --- Bölge tespiti
    if ratio < danger_mult:
        zone: Zone = "DANGER"
    elif ratio < caution_mult:
        zone = "CAUTION"
    else:
        zone = "CLEAR"

    # --- DANGER: hard gate
    if zone == "DANGER":
        return FlipZoneResult(
            zone="DANGER",
            decision="BEKLE",
            position_multiplier=0.0,
            flip_dist_pct=flip_dist_pct,
            atr_pct=atr_pct,
            flip_dist_atr_ratio=ratio,
            reason=(f"DANGER: flip mesafesi %{flip_dist_pct*100:.2f} "
                    f"< {danger_mult:.2f}×ATR (%{atr_pct*100:.2f}). "
                    f"Dealer rejimi geçiş anında."),
            override_pyramid=True
        )

    # --- CAUTION: yön uyumu kontrolü
    if zone == "CAUTION":
        below_flip = spot < flip_price
        is_break_trade = (
            (below_flip and pyramid_direction == "long") or
            (not below_flip and pyramid_direction == "short")
        )

        if is_break_trade:
            return FlipZoneResult(
                zone="CAUTION",
                decision="VETO",
                position_multiplier=0.0,
                flip_dist_pct=flip_dist_pct,
                atr_pct=atr_pct,
                flip_dist_atr_ratio=ratio,
                reason=(f"CAUTION + flip kırma: spot "
                        f"{'<' if below_flip else '>'} flip, sinyal "
                        f"{pyramid_direction.upper()}. Flip-kırma trade'i veto."),
                override_pyramid=True
            )

        return FlipZoneResult(
            zone="CAUTION",
            decision="REDUCE",
            position_multiplier=0.5,
            flip_dist_pct=flip_dist_pct,
            atr_pct=atr_pct,
            flip_dist_atr_ratio=ratio,
            reason=(f"CAUTION: flip %{flip_dist_pct*100:.2f} uzakta "
                    f"({ratio:.2f}×ATR). Pozisyon yarıya indirildi."),
            override_pyramid=False
        )

    # --- CLEAR: normal işleyiş
    return FlipZoneResult(
        zone="CLEAR",
        decision="OK",
        position_multiplier=1.0,
        flip_dist_pct=flip_dist_pct,
        atr_pct=atr_pct,
        flip_dist_atr_ratio=ratio,
        reason=(f"CLEAR: flip %{flip_dist_pct*100:.2f} uzakta "
                f"({ratio:.2f}×ATR). Normal işleyiş."),
        override_pyramid=False
    )


def to_dict(result: FlipZoneResult) -> dict:
    """API response için JSON-serializable dict."""
    return {
        "zone": result.zone,
        "decision": result.decision,
        "position_multiplier": result.position_multiplier,
        "flip_dist_pct": round(result.flip_dist_pct * 100, 3),   # frontend için %'ye çevrildi
        "atr_pct": round(result.atr_pct * 100, 3),
        "flip_dist_atr_ratio": round(result.flip_dist_atr_ratio, 2),
        "reason": result.reason,
        "override_pyramid": result.override_pyramid
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== flip_zone_gate self-test ===\n")

    test_cases = [
        # (spot, flip, direction, beklenen_zone)
        (81694, 82000, "long",  "DANGER"),   # şu anki dashboard durumu
        (80500, 82000, "long",  "CAUTION"),  # %1.8 uzaklık + flip-kırma
        (80500, 82000, "short", "CAUTION"),  # %1.8 uzaklık + uyumlu
        (78000, 82000, "long",  "CLEAR"),    # %4.9 uzak
    ]

    atr = 0.012  # %1.2 — BTC tipik 4H ATR

    for spot, flip, dir_, expected in test_cases:
        res = evaluate_flip_zone(spot, flip, dir_, atr_pct=atr)
        ok = "✓" if res.zone == expected else "✗"
        print(f"{ok} spot=${spot} flip=${flip} dir={dir_:5} → "
              f"{res.zone}/{res.decision} mult={res.position_multiplier}")
        print(f"  {res.reason}\n")
