"""
deribit_flow_fetcher.py
G-DIVE Options Delta CVD + OI-Weighted Put Delta Fetcher
============================================================
gamma_fatigue.py'nin ihtiyac duydugu iki gercek girdiyi Deribit public
API'sinden ceken modul:
  1. oi_weighted_put_delta  -> compute_gamma_fatigue(oi_weighted_put_delta=...)
  2. trade_flow_increment    -> compute_gamma_fatigue(trade_flow_increment=...)

ONEMLI — TEST DURUMU: Bu script'i Deribit'in canli API'sine karsi
calistiramadim, sandbox'imin network allowlist'i deribit.com'u
icermiyor (sadece github/pypi/npm gibi paket kaynaklarina cikis var).
Asagidaki alan adlari (instrument_name, direction, amount, iv,
greeks.delta, open_interest) docs.deribit.com'da dogrulandi ama gercek
response sekli (ozellikle ticker'in "greeks" objesinin tam yapisi)
senin tarafinda calistirip dogrulanmali. __main__ blogundaki test
kismini once izole calistir, ham JSON'u yazdir, alan adlari tutmazsa
duzelt.

KAPSAM SINIRLAMASI: Tum opsiyon zincirini taramiyoruz (yuzlerce
instrument => rate limit riski). Sadece on N vade (max_pain/pin_risk
ile ayni "front-expiry" konvansiyonu, taleb_integration_patch.py'deki
mantik) ve spot'a yakin strike'lar (varsayilan +-%25) taraniyor.

Persisted state: gamma_fatigue.py'nin put_delta_history / cvd_history
gibi, bu fetcher'in da "son kontrol zamani" (since_ms) bir yerde
persist edilmeli (Supabase'de tek satirlik bir state objesi en kolayi)
— her cron tick'inde bir onceki tick'in zamanini buraya verirsin.

Kullanim (gdive_server.py cron icinde):
    from deribit_flow_fetcher import DeribitFlowFetcher
    from gamma_fatigue import compute_gamma_fatigue

    fetcher = DeribitFlowFetcher(currency="BTC")
    oi_data = fetcher.fetch_oi_weighted_put_delta()
    flow_data = fetcher.fetch_trade_flow_increment(since_ms=state["last_check_ms"])

    result = compute_gamma_fatigue(
        oi_weighted_put_delta=oi_data["oi_weighted_put_delta"],
        put_delta_history=state["put_delta_history"],
        trade_flow_increment=flow_data["trade_flow_increment"],
        cvd_history=state["cvd_history"],
        prior_toxicity_belief=state["toxicity_belief"],
    )
    state["last_check_ms"] = int(time.time() * 1000)
    # result["_new_*"] alanlarini state'e geri yaz (gamma_fatigue.py'deki gibi)
"""

import json
import math
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Optional, Dict, List

DERIBIT_BASE = "https://www.deribit.com/api/v2"


def _rpc(method: str, params: dict) -> dict:
    """Deribit public REST-RPC cagrisi (GET, public endpoint'ler icin)."""
    query = urllib.parse.urlencode(params)
    url = f"{DERIBIT_BASE}/{method}?{query}"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    if "error" in data:
        raise RuntimeError(f"Deribit API error ({method}): {data['error']}")
    return data["result"]


def parse_instrument_name(name: str) -> Optional[Dict]:
    """
    'BTC-24APR26-72000-C' -> {currency, strike, expiry, option_type}
    Future/perpetual gibi opsiyon olmayan instrument'lar icin None doner.
    """
    parts = name.split("-")
    if len(parts) != 4:
        return None
    currency, expiry_str, strike_str, opt_type = parts
    if opt_type not in ("C", "P"):
        return None
    try:
        strike = float(strike_str)
        expiry = datetime.strptime(expiry_str, "%d%b%y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return {
        "currency": currency,
        "strike": strike,
        "expiry": expiry,
        "option_type": "put" if opt_type == "P" else "call",
    }


def compute_bsm_delta(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """
    Standart BSM delta. taleb_integration_patch.compute_vanna ile ayni
    d1 formulu kullanilir (tutarlilik icin).
    Call delta = N(d1), Put delta = N(d1) - 1
    """
    if T <= 0 or sigma <= 0:
        return 0.0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        n_d1 = 0.5 * (1 + math.erf(d1 / math.sqrt(2)))
        return n_d1 if option_type == "call" else n_d1 - 1
    except (ValueError, ZeroDivisionError):
        return 0.0


class DeribitFlowFetcher:
    def __init__(
        self,
        currency: str = "BTC",
        risk_free_rate: float = 0.0,
        atm_window_pct: float = 0.25,   # spot'un +-%25'i icindeki strike'lar
        max_expiries: int = 2,           # front-expiry konvansiyonu
    ):
        self.currency = currency
        self.r = risk_free_rate
        self.atm_window_pct = atm_window_pct
        self.max_expiries = max_expiries

    def _get_spot(self) -> float:
        idx = _rpc("public/get_index_price", {"index_name": f"{self.currency.lower()}_usd"})
        return idx.get("index_price", 0) or 0

    # -----------------------------------------------------------------
    # 1. OI-AGIRLIKLI |PUT DELTA| — anlik durum, ticker uzerinden
    # -----------------------------------------------------------------
    def fetch_oi_weighted_put_delta(self) -> Dict:
        instruments = _rpc("public/get_instruments", {
            "currency": self.currency, "kind": "option", "expired": "false",
        })
        spot = self._get_spot()
        if spot <= 0:
            return {"oi_weighted_put_delta": 0.0, "n_instruments": 0, "n_errors": 0, "spot": spot}

        expiries = sorted({i["expiration_timestamp"] for i in instruments})[: self.max_expiries]
        candidates = [
            i for i in instruments
            if i["expiration_timestamp"] in expiries
            and i.get("option_type") == "put"
            and abs(i["strike"] - spot) / spot <= self.atm_window_pct
        ]

        weighted_sum = 0.0
        oi_sum = 0.0
        errors = 0
        for inst in candidates:
            try:
                t = _rpc("public/ticker", {"instrument_name": inst["instrument_name"]})
            except Exception:
                errors += 1
                continue
            oi = t.get("open_interest", 0) or 0
            delta = (t.get("greeks") or {}).get("delta")
            if delta is None or oi <= 0:
                continue
            weighted_sum += oi * abs(delta)
            oi_sum += oi
            time.sleep(0.05)  # kaba rate-limit koruma

        oi_weighted_put_delta = (weighted_sum / oi_sum) if oi_sum > 0 else 0.0

        return {
            "oi_weighted_put_delta": round(oi_weighted_put_delta, 4),
            "n_instruments": len(candidates),
            "n_errors": errors,
            "spot": spot,
        }

    # -----------------------------------------------------------------
    # 2. OPTIONS DELTA CVD ARTISI — son trade'lerden
    # -----------------------------------------------------------------
    def fetch_trade_flow_increment(self, since_ms: int) -> Dict:
        """
        since_ms'den simdiye kadarki put trade'lerini cekip delta-agirlikli
        isaretli net akisi (bu tick'in trade_flow_increment'i) hesaplar.
        direction='buy' -> +1 (put alimi, bearish-informed hipotezi),
        direction='sell' -> -1.
        """
        trades = _rpc("public/get_last_trades_by_currency_and_time", {
            "currency": self.currency,
            "kind": "option",
            "start_timestamp": since_ms,
            "end_timestamp": int(time.time() * 1000),
            "count": 1000,
        }).get("trades", [])

        spot = self._get_spot()

        net_flow = 0.0
        n_used = 0
        for tr in trades:
            parsed = parse_instrument_name(tr["instrument_name"])
            if not parsed or parsed["option_type"] != "put":
                continue
            T = max((parsed["expiry"] - datetime.now(timezone.utc)).total_seconds(), 0) / (365 * 24 * 3600)
            sigma = (tr.get("iv") or 0) / 100
            delta = compute_bsm_delta(spot, parsed["strike"], T, self.r, sigma, "put")
            direction_sign = 1 if tr.get("direction") == "buy" else -1
            net_flow += direction_sign * abs(delta) * tr.get("amount", 0)
            n_used += 1

        return {
            "trade_flow_increment": round(net_flow, 4),
            "n_trades_used": n_used,
            "n_trades_total": len(trades),
            "window_start_ms": since_ms,
        }


if __name__ == "__main__":
    # Manuel test — once burayi izole calistir, ham ciktiyi kontrol et.
    fetcher = DeribitFlowFetcher(currency="BTC")

    print("--- OI-weighted put delta ---")
    print(json.dumps(fetcher.fetch_oi_weighted_put_delta(), indent=2, default=str))

    print("--- Trade flow (son 1 saat) ---")
    one_hour_ago_ms = int(time.time() * 1000) - 3600 * 1000
    print(json.dumps(fetcher.fetch_trade_flow_increment(one_hour_ago_ms), indent=2, default=str))
