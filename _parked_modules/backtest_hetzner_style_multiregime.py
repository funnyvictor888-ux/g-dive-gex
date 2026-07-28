#!/usr/bin/env python3
"""
backtest_hetzner_style_multiregime.py

Hetzner'in run_shadow_live.py mantığını bizim 8 rejimde test eder.
Amaç: Aynı dönemlerde Hetzner saf-trend mantığı nasıl performans verirdi?

Hetzner mantığı (run_shadow_live.py'dan birebir):
  signal = 0.6 * trend_signal(BTC) + 0.4 * eth_relative(BTC, ETH)
  
  trend_signal(BTC) = tanh((SMA20 - SMA50) / SMA50 * 5)  → [-1, +1]
  
  Burada ETH bileşeni atlanıyor (Hetzner'de zaten eth=0.0 disabled).
  
  target_position = signal * POSITION_SIZE  (continuous, fractional)
  
Sermaye yönetimi:
  - Pozisyon delta_qty = target_position - current_position
  - Her bar'da rebalance
  - Fee 0.04%, slippage 0.05% (Hetzner config birebir)

Bu, BİZİM EMA cross discrete sistemimizin AYNI 8 rejimde nasıl olduğu
ile karşılaştırılır.

NOT: Hetzner sistemi DAILY timeframe kullanıyor (run_shadow_live.py SYMBOL=BTCUSDT INTERVAL=1d).
Biz 4H bar kullanıyoruz. Adil karşılaştırma için Hetzner'i de DAILY çalıştırıyoruz.
"""

import urllib.request
import json
import time
import math
from datetime import datetime
from collections import OrderedDict


# ──────────────────────────────────────────────────────────────
# Hetzner config (run_shadow_live.py birebir)
# ──────────────────────────────────────────────────────────────
HETZNER_CFG = {
    "position_size": 1.0,       # POSITION_SIZE = 1.0 (full sermaye)
    "fee_rate": 0.0004,         # 0.04% taker fee
    "slippage": 0.0005,         # 0.05% slippage
    "trend_smoothing": 5.0,     # tanh çarpanı
    "sma_fast": 20,
    "sma_slow": 50,
}

CAPITAL = 10000


# ──────────────────────────────────────────────────────────────
# Test dönemleri (8 rejim, multi-regime ile birebir)
# ──────────────────────────────────────────────────────────────
PERIODS = [
    ("2020 Bull (Covid recovery)",      "2020-04-01", "2020-12-31", "Bull"),
    ("2021 Peak (rally + correction)",   "2021-01-01", "2021-12-31", "Bull peak"),
    ("2022 Bear (sustained downtrend)",  "2022-01-01", "2022-12-31", "Bear"),
    ("2023 Recovery",                    "2023-01-01", "2023-12-31", "Recovery"),
    ("2024 Bull (explosion)",            "2024-01-01", "2024-12-31", "Bull"),
    ("2025 H1 (correction)",             "2025-01-01", "2025-06-30", "Düzeltme"),
    ("2025 H2 (choppy)",                 "2025-07-01", "2025-12-31", "Choppy"),
    ("2026 H1 (downtrend, mevcut)",      "2026-01-01", "2026-06-22", "Downtrend"),
]


# ──────────────────────────────────────────────────────────────
# Deribit DAILY OHLCV (Hetzner daily timeframe ile uyumlu)
# ──────────────────────────────────────────────────────────────
def fetch_period_daily(start_iso, end_iso):
    start_ts = int(datetime.fromisoformat(start_iso).timestamp() * 1000)
    end_ts = int(datetime.fromisoformat(end_iso).timestamp() * 1000)

    all_ticks = []
    all_closes = []
    cursor = start_ts
    while cursor < end_ts:
        chunk_end = min(cursor + 200 * 24 * 3600 * 1000, end_ts)
        # resolution=1D (1440 min)
        url = (f"https://www.deribit.com/api/v2/public/get_tradingview_chart_data"
               f"?instrument_name=BTC-PERPETUAL&resolution=1D"
               f"&start_timestamp={cursor}&end_timestamp={chunk_end}")
        req = urllib.request.Request(url, headers={"User-Agent": "backtest/2.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
        except Exception as e:
            print(f"  ⚠ fetch error: {e}")
            break
        result = data.get("result", {})
        ticks = result.get("ticks", [])
        if not ticks:
            break
        all_ticks.extend(ticks)
        all_closes.extend(result.get("close", []))
        cursor = ticks[-1] + 1
        time.sleep(0.2)

    # Tek liste — duplikat slot'ları temizle
    seen = set()
    bars = []
    for ts, c in zip(all_ticks, all_closes):
        if ts not in seen:
            seen.add(ts)
            bars.append({"ts": ts, "c": c})
    return bars


# ──────────────────────────────────────────────────────────────
# Hetzner trend signal (run_shadow_live.py birebir)
# ──────────────────────────────────────────────────────────────
def sma(values, window):
    """Simple Moving Average — son `window` değerin ortalaması."""
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def trend_signal_hetzner(prices):
    """Hetzner'in trend_signal fonksiyonu birebir."""
    fast = sma(prices, HETZNER_CFG["sma_fast"])
    slow = sma(prices, HETZNER_CFG["sma_slow"])
    if fast is None or slow is None or slow == 0:
        return 0.0
    return math.tanh((fast - slow) / slow * HETZNER_CFG["trend_smoothing"])


# ──────────────────────────────────────────────────────────────
# Hetzner BACKTEST (continuous position rebalance)
# ──────────────────────────────────────────────────────────────
def backtest_hetzner(bars):
    closes = [b["c"] for b in bars]
    n = len(closes)
    if n < HETZNER_CFG["sma_slow"] + 5:
        return None

    equity = CAPITAL
    position_qty = 0.0  # BTC
    last_price = None
    
    history = []  # bar bazlı equity + signal
    trades_count = 0  # her rebalance bir "trade" sayılır

    start_i = HETZNER_CFG["sma_slow"]

    for i in range(start_i, n):
        price = closes[i]
        prices_so_far = closes[:i+1]

        # PnL update — önceki barda açık olan pozisyonun mark-to-market
        pnl = 0.0
        if last_price is not None and position_qty != 0:
            pnl = position_qty * (price - last_price)
            equity += pnl

        # Signal hesap
        signal = trend_signal_hetzner(prices_so_far)

        # Target position (notional based on equity)
        target_notional = signal * HETZNER_CFG["position_size"] * equity
        target_qty = target_notional / price if price > 0 else 0.0

        # Delta = trade büyüklüğü
        delta_qty = target_qty - position_qty

        # Cost: fee + slippage
        if abs(delta_qty) > 0:
            notional = abs(delta_qty) * price
            fee_cost = notional * HETZNER_CFG["fee_rate"]
            slip_cost = notional * HETZNER_CFG["slippage"]
            equity -= (fee_cost + slip_cost)
            trades_count += 1

        position_qty = target_qty
        last_price = price

        history.append({
            "i": i,
            "price": price,
            "signal": signal,
            "position": position_qty,
            "equity": equity,
        })

    return history, trades_count


# ──────────────────────────────────────────────────────────────
# Metrik hesabı
# ──────────────────────────────────────────────────────────────
def compute_metrics(history, trades_count, days):
    if not history or len(history) < 2:
        return None

    equity_curve = [h["equity"] for h in history]
    
    # Daily returns
    rets = []
    for i in range(1, len(equity_curve)):
        if equity_curve[i-1] > 0:
            rets.append((equity_curve[i] - equity_curve[i-1]) / equity_curve[i-1])

    if not rets:
        return None

    final_equity = equity_curve[-1]
    total_return = (final_equity - CAPITAL) / CAPITAL * 100
    cagr = ((final_equity / CAPITAL) ** (365 / days) - 1) * 100 if days > 30 else total_return

    # Daily Sharpe (annualized) — daily timeframe
    if len(rets) > 1:
        mean_r = sum(rets) / len(rets)
        var = sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1)
        std = var ** 0.5
        # Daily timeframe: annualize sqrt(365)
        sharpe = (mean_r / std * (365 ** 0.5)) if std > 0 else 0
    else:
        sharpe = 0

    # Max DD
    peak = equity_curve[0]
    max_dd = 0
    for e in equity_curve:
        if e > peak:
            peak = e
        if peak > 0:
            dd = (peak - e) / peak * 100
            if dd > max_dd:
                max_dd = dd

    # Signal stats
    signals = [h["signal"] for h in history]
    avg_abs_signal = sum(abs(s) for s in signals) / len(signals)
    avg_position = sum(h["position"] for h in history) / len(history)

    return {
        "ret": round(total_return, 1),
        "cagr": round(cagr, 1),
        "sharpe": round(sharpe, 2),
        "dd": round(max_dd, 1),
        "trades": trades_count,
        "final_equity": round(final_equity, 0),
        "avg_abs_signal": round(avg_abs_signal, 2),
        "avg_position": round(avg_position, 4),
    }


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────
def main():
    results = []

    print(f"{'='*82}")
    print(f"MULTI-REGIME BACKTEST — HETZNER-STYLE (continuous trend signal, daily)")
    print(f"signal = tanh((SMA20 - SMA50) / SMA50 * 5)  →  target_qty = signal × equity / price")
    print(f"{'='*82}")

    for label, start, end, regime in PERIODS:
        print(f"\n▶ {label}  ({start} → {end}, {regime})")
        bars = fetch_period_daily(start, end)
        if len(bars) < 60:
            print(f"  ⚠ Yetersiz daily bar ({len(bars)}), atlandı")
            continue

        first = datetime.fromtimestamp(bars[0]["ts"] / 1000)
        last = datetime.fromtimestamp(bars[-1]["ts"] / 1000)
        days = (last - first).days
        price_chg = (bars[-1]["c"] / bars[0]["c"] - 1) * 100
        print(f"  {len(bars)} daily bar, {days}g, BTC ${bars[0]['c']:.0f} → ${bars[-1]['c']:.0f} ({price_chg:+.1f}%)")

        result = backtest_hetzner(bars)
        if result is None:
            print(f"  ⚠ Backtest çalışmadı")
            continue
        history, trades_count = result

        m = compute_metrics(history, trades_count, days)
        if m is None:
            print(f"  ⚠ Metrik hesaplanamadı")
            continue

        print(f"  Rebalance: {m['trades']}  Avg|signal|: {m['avg_abs_signal']}  Avg pos: {m['avg_position']} BTC")
        print(f"  Final equity: ${m['final_equity']}  Net: %{m['ret']:+.1f}")
        print(f"  CAGR: %{m['cagr']:+.1f}  MaxDD: %{m['dd']}  Sharpe: {m['sharpe']}")

        results.append({
            "label": label,
            "regime": regime,
            "btc_chg": price_chg,
            "days": days,
            **m,
        })

    # Karşılaştırma
    print(f"\n{'='*82}")
    print(f"HETZNER-STYLE REJİM KARŞILAŞTIRMA TABLOSU")
    print(f"{'='*82}")
    print(f"{'Dönem':<30} {'BTC%':>7} {'Rebal':>6} {'CAGR%':>7} {'DD%':>6} {'Sharpe':>7}")
    print(f"{'-'*82}")
    for r in results:
        label_short = r["label"][:30]
        print(f"{label_short:<30} {r['btc_chg']:>+7.1f} {r['trades']:>6} {r['cagr']:>+7.1f} {r['dd']:>6} {r['sharpe']:>7.2f}")

    # Özet
    if results:
        avg_sharpe = sum(r["sharpe"] for r in results) / len(results)
        avg_cagr = sum(r["cagr"] for r in results) / len(results)
        worst_dd = max(r["dd"] for r in results)
        worst_dd_period = next(r["label"] for r in results if r["dd"] == worst_dd)
        best_sharpe = max(r["sharpe"] for r in results)
        best_sharpe_period = next(r["label"] for r in results if r["sharpe"] == best_sharpe)
        worst_sharpe = min(r["sharpe"] for r in results)
        worst_sharpe_period = next(r["label"] for r in results if r["sharpe"] == worst_sharpe)
        positive = sum(1 for r in results if r["sharpe"] > 0)

        print(f"\n{'─'*82}")
        print(f"ÖZET — Hetzner-style continuous trend")
        print(f"  Ortalama Sharpe:  {avg_sharpe:.2f}")
        print(f"  Ortalama CAGR:    %{avg_cagr:+.1f}")
        print(f"  Pozitif Sharpe:   {positive}/{len(results)}")
        print(f"  En iyi rejim:     {best_sharpe_period} (Sharpe {best_sharpe:.2f})")
        print(f"  En kötü rejim:    {worst_sharpe_period} (Sharpe {worst_sharpe:.2f})")
        print(f"  En büyük DD:      {worst_dd_period} (%{worst_dd})")

        # Bizim sistemle karşılaştırma (memory'den hatırlanan)
        print(f"\n{'─'*82}")
        print(f"BİZİM EMA CROSS SİSTEMİYLE KARŞILAŞTIRMA")
        print(f"{'─'*82}")
        print(f"{'Metrik':<25} {'Bizim (EMA)':<15} {'Hetzner (tanh)':<15} {'Fark':<10}")
        our_data = {
            "Ortalama Sharpe": 0.63,
            "Ortalama CAGR%": 48.6,
            "Pozitif/Toplam": "6/8",
            "En kötü Sharpe": -0.66,
            "En büyük DD%": 54.9,
        }
        hetzner_data = {
            "Ortalama Sharpe": avg_sharpe,
            "Ortalama CAGR%": avg_cagr,
            "Pozitif/Toplam": f"{positive}/{len(results)}",
            "En kötü Sharpe": worst_sharpe,
            "En büyük DD%": worst_dd,
        }
        for k in our_data:
            ours = our_data[k]
            hetz = hetzner_data[k]
            if isinstance(ours, (int, float)) and isinstance(hetz, (int, float)):
                diff = hetz - ours
                print(f"{k:<25} {ours:<15} {hetz:<15.2f} {diff:+.2f}")
            else:
                print(f"{k:<25} {ours:<15} {hetz:<15}")


if __name__ == "__main__":
    main()
