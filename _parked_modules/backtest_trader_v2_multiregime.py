#!/usr/bin/env python3
"""
backtest_trader_v2_multiregime.py

backtest_trader_v2.py'nin çoklu rejim versiyonu.

Aynı trader mantığını (TIME_EXIT + REGIME_EXIT) farklı tarihsel piyasa rejimlerinde
çalıştırır:
  - Bull 2020 (toparlanma + rally)
  - Bull 2021 (peak)
  - Bear 2022 (sustained downtrend)
  - Recovery 2023
  - Bull 2024 (explosion)
  - Choppy 2025 (sideways)
  - Downtrend 2026 (mevcut sample)

Çıktı:
  - Her dönem için ayrı tablo
  - Sonunda karşılaştırma tablosu (Sharpe / DD / CAGR rejim bazlı)

Bu, RISK_POLICY için GERÇEK baseline'ı verir — sistem hangi rejimde nasıl davranıyor.
"""

import urllib.request
import json
import time
from datetime import datetime
from collections import OrderedDict


# ──────────────────────────────────────────────────────────────
# STRATEJİ (sadece C4 — canlı sistem)
# ──────────────────────────────────────────────────────────────
C4_CFG = {
    "name": "C4_Aggressive",
    "atr_stop_mult": 1.5,
    "atr_tp_mult": 6.0,
    "rsi_bull_min": 50, "rsi_bull_max": 75,
    "rsi_bear_min": 25, "rsi_bear_max": 55,
    "dte_exit": 7,
    "trend_confirm_e200": True,
    "base_risk": 0.02,
    "leverage": 2,
}

COST_CONFIG = {
    "taker_fee_rate": 0.0005,
    "funding_rate_daily": 0.00027,
    "slippage_rate": 0.0002,
}

CAPITAL = 10000


# ──────────────────────────────────────────────────────────────
# Test dönemleri
# Her dönem: (label, start_iso, end_iso, rejim_description)
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
# Deribit 4H OHLCV (specific period)
# ──────────────────────────────────────────────────────────────
def fetch_period_4h(start_iso, end_iso):
    start_ts = int(datetime.fromisoformat(start_iso).timestamp() * 1000)
    end_ts = int(datetime.fromisoformat(end_iso).timestamp() * 1000)

    # Deribit max 5000 bar per request — paginate
    all_ticks = []
    all_opens = []
    all_highs = []
    all_lows = []
    all_closes = []
    cursor = start_ts
    while cursor < end_ts:
        # 1H bars, ~5000 = 208 days max per request
        chunk_end = min(cursor + 200 * 24 * 3600 * 1000, end_ts)
        url = (f"https://www.deribit.com/api/v2/public/get_tradingview_chart_data"
               f"?instrument_name=BTC-PERPETUAL&resolution=60"
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
        all_opens.extend(result.get("open", []))
        all_highs.extend(result.get("high", []))
        all_lows.extend(result.get("low", []))
        all_closes.extend(result.get("close", []))
        cursor = ticks[-1] + 1
        time.sleep(0.2)  # rate limit nice

    # Aggregate to 4H
    slots = OrderedDict()
    for ts, o, h, l, c in zip(all_ticks, all_opens, all_highs, all_lows, all_closes):
        slot = (ts // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
        if slot not in slots:
            slots[slot] = {"ts": slot, "o": o, "h": h, "l": l, "c": c}
        else:
            bar = slots[slot]
            bar["h"] = max(bar["h"], h)
            bar["l"] = min(bar["l"], l)
            bar["c"] = c

    return list(slots.values())


# ──────────────────────────────────────────────────────────────
# Indicators (v2 ile birebir)
# ──────────────────────────────────────────────────────────────
def ema(prices, period):
    k = 2 / (period + 1)
    e = prices[0]
    result = []
    for p in prices:
        e = p * k + e * (1 - k)
        result.append(e)
    return result


def rsi(prices, period=14):
    gains, losses = [], []
    for i in range(1, len(prices)):
        d = prices[i] - prices[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    if len(gains) < period:
        return [None] * len(prices)
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    result = [None] * period
    rs = ag / al if al > 0 else 100
    result.append(100 - 100 / (1 + rs))
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
        rs = ag / al if al > 0 else 100
        result.append(100 - 100 / (1 + rs))
    return result


def atr_series(candles, period=14):
    trs = []
    for i, c in enumerate(candles):
        prev_c = candles[max(0, i - 1)]["c"]
        tr = max(c["h"] - c["l"], abs(c["h"] - prev_c), abs(c["l"] - prev_c))
        trs.append(tr)
    return ema(trs, period)


def calc_realistic_pnl(entry, exit_price, size, direction, days_held, leverage=1):
    if direction == "LONG":
        gross = (exit_price - entry) * size * leverage
    else:
        gross = (entry - exit_price) * size * leverage
    notional_in = entry * size
    notional_out = exit_price * size
    fee_in = notional_in * COST_CONFIG["taker_fee_rate"]
    fee_out = notional_out * COST_CONFIG["taker_fee_rate"]
    slip_in = notional_in * COST_CONFIG["slippage_rate"]
    slip_out = notional_out * COST_CONFIG["slippage_rate"]
    avg_notional = (notional_in + notional_out) / 2.0
    funding = avg_notional * COST_CONFIG["funding_rate_daily"] * days_held
    total_cost = fee_in + fee_out + slip_in + slip_out + funding
    net_pnl = gross - total_cost
    return {"gross": gross, "net": net_pnl, "cost": total_cost, "days": days_held}


# ──────────────────────────────────────────────────────────────
# Backtest (v2 mantığı birebir)
# ──────────────────────────────────────────────────────────────
def backtest(candles, cfg):
    closes = [c["c"] for c in candles]
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]

    e9 = ema(closes, 9)
    e21 = ema(closes, 21)
    e50 = ema(closes, 50)
    e200 = ema(closes, 200)
    rsis = rsi(closes, 14)
    atrs = atr_series(candles, 14)

    trades = []
    in_trade = False
    open_idx = 0
    entry = stop = tp = 0
    size = 0
    direction = ""
    start_i = max(200, 30)

    for i in range(start_i, len(candles)):
        price = closes[i]
        atr_v = atrs[i] if atrs[i] else 0
        rsi_v = rsis[i] if rsis[i] is not None else 50

        e200_long = price > e200[i] if cfg["trend_confirm_e200"] else True
        e200_short = price < e200[i] if cfg["trend_confirm_e200"] else True

        bull_tech = (e9[i] > e21[i] and
                     cfg["rsi_bull_min"] < rsi_v < cfg["rsi_bull_max"] and
                     price > e50[i] and e200_long)
        bear_tech = (e9[i] < e21[i] and
                     cfg["rsi_bear_min"] < rsi_v < cfg["rsi_bear_max"] and
                     price < e50[i] and e200_short)

        if in_trade:
            bar_high = highs[i]
            bar_low = lows[i]
            bars_held = i - open_idx
            days_held = bars_held / 6.0

            exit_price = None
            exit_reason = None

            if direction == "LONG":
                if bar_low <= stop:
                    exit_price = stop
                    exit_reason = "STOP"
                elif bar_high >= tp:
                    exit_price = tp
                    exit_reason = "TP"
                else:
                    if days_held >= cfg["dte_exit"]:
                        pnl_check = calc_realistic_pnl(entry, price, size, "LONG", days_held, cfg["leverage"])
                        if pnl_check["net"] > 0:
                            exit_price = price
                            exit_reason = "TIME_EXIT"
                    if exit_price is None and bear_tech and not bull_tech:
                        pnl_check = calc_realistic_pnl(entry, price, size, "LONG", days_held, cfg["leverage"])
                        if pnl_check["net"] > 0:
                            exit_price = price
                            exit_reason = "REGIME_EXIT"
            else:
                if bar_high >= stop:
                    exit_price = stop
                    exit_reason = "STOP"
                elif bar_low <= tp:
                    exit_price = tp
                    exit_reason = "TP"
                else:
                    if days_held >= cfg["dte_exit"]:
                        pnl_check = calc_realistic_pnl(entry, price, size, "SHORT", days_held, cfg["leverage"])
                        if pnl_check["net"] > 0:
                            exit_price = price
                            exit_reason = "TIME_EXIT"
                    if exit_price is None and bull_tech and not bear_tech:
                        pnl_check = calc_realistic_pnl(entry, price, size, "SHORT", days_held, cfg["leverage"])
                        if pnl_check["net"] > 0:
                            exit_price = price
                            exit_reason = "REGIME_EXIT"

            if exit_price is not None:
                pnl_data = calc_realistic_pnl(entry, exit_price, size, direction, days_held, cfg["leverage"])
                trades.append({
                    "direction": direction,
                    "exit_reason": exit_reason,
                    "days_held": days_held,
                    "net_pnl": round(pnl_data["net"], 2),
                })
                in_trade = False
                continue

        if in_trade:
            continue

        long_signal = bull_tech and (e9[i] > e21[i])
        short_signal = bear_tech and (e9[i] < e21[i])

        if long_signal:
            entry = price
            stop = entry - atr_v * cfg["atr_stop_mult"]
            tp = entry + atr_v * cfg["atr_tp_mult"]
            risk_dollars = CAPITAL * cfg["base_risk"]
            size = round(risk_dollars / (atr_v * cfg["atr_stop_mult"]), 4)
            direction = "LONG"
            open_idx = i
            in_trade = True
        elif short_signal:
            entry = price
            stop = entry + atr_v * cfg["atr_stop_mult"]
            tp = entry - atr_v * cfg["atr_tp_mult"]
            risk_dollars = CAPITAL * cfg["base_risk"]
            size = round(risk_dollars / (atr_v * cfg["atr_stop_mult"]), 4)
            direction = "SHORT"
            open_idx = i
            in_trade = True

    return trades


# ──────────────────────────────────────────────────────────────
# Metrik hesabı
# ──────────────────────────────────────────────────────────────
def compute_metrics(trades, days):
    if not trades:
        return None
    n = len(trades)
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    net_total = sum(t["net_pnl"] for t in trades)
    win_rate = len(wins) / n * 100
    avg_win = sum(t["net_pnl"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["net_pnl"] for t in losses) / len(losses) if losses else 0
    avg_hold = sum(t["days_held"] for t in trades) / n

    if n > 1:
        mean_pnl = net_total / n
        var = sum((t["net_pnl"] - mean_pnl) ** 2 for t in trades) / (n - 1)
        std = var ** 0.5
        sharpe_per_trade = mean_pnl / std if std > 0 else 0
        trades_per_year = n * (365 / days)
        sharpe_annual = sharpe_per_trade * (trades_per_year ** 0.5)
    else:
        sharpe_annual = 0

    equity = [CAPITAL]
    for t in trades:
        equity.append(equity[-1] + t["net_pnl"])
    peak = equity[0]
    max_dd_pct = 0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak * 100
        if dd > max_dd_pct:
            max_dd_pct = dd

    exit_counts = {}
    for t in trades:
        r = t["exit_reason"]
        exit_counts[r] = exit_counts.get(r, 0) + 1

    final_equity = equity[-1]
    total_return_pct = (final_equity - CAPITAL) / CAPITAL * 100
    cagr = ((final_equity / CAPITAL) ** (365 / days) - 1) * 100 if days > 30 else total_return_pct

    return {
        "n": n,
        "wr": round(win_rate, 1),
        "avg_win": round(avg_win, 0),
        "avg_loss": round(avg_loss, 0),
        "avg_hold": round(avg_hold, 1),
        "net": round(net_total, 0),
        "ret": round(total_return_pct, 1),
        "cagr": round(cagr, 1),
        "dd": round(max_dd_pct, 1),
        "sharpe": round(sharpe_annual, 2),
        "longs": sum(1 for t in trades if t["direction"] == "LONG"),
        "shorts": sum(1 for t in trades if t["direction"] == "SHORT"),
        "exits": exit_counts,
    }


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────
def main():
    results = []

    print(f"{'='*82}")
    print(f"MULTI-REGIME BACKTEST — C4_Aggressive, gerçek trader mantığı (TIME_EXIT + REGIME_EXIT)")
    print(f"{'='*82}")

    for label, start, end, regime in PERIODS:
        print(f"\n▶ {label}  ({start} → {end}, {regime})")
        candles = fetch_period_4h(start, end)
        if len(candles) < 250:
            print(f"  ⚠ Yetersiz veri ({len(candles)} bar), atlandı")
            continue

        first = datetime.fromtimestamp(candles[0]["ts"] / 1000)
        last = datetime.fromtimestamp(candles[-1]["ts"] / 1000)
        days = (last - first).days
        price_chg = (candles[-1]["c"] / candles[0]["c"] - 1) * 100
        print(f"  {len(candles)} bar, {days}g, BTC ${candles[0]['c']:.0f} → ${candles[-1]['c']:.0f} ({price_chg:+.1f}%)")

        trades = backtest(candles, C4_CFG)
        m = compute_metrics(trades, days)
        if m is None:
            print(f"  HİÇ TRADE YOK")
            continue

        exits_str = ", ".join(f"{k}:{v}" for k, v in sorted(m["exits"].items()))
        print(f"  Trade: {m['n']} ({m['longs']}L/{m['shorts']}S)  WR: %{m['wr']}  Hold: {m['avg_hold']}g")
        print(f"  Net: ${m['net']:+.0f}  CAGR: %{m['cagr']:+.1f}  MaxDD: %{m['dd']}  Sharpe: {m['sharpe']}")
        print(f"  Exits: {exits_str}")

        results.append({"label": label, "regime": regime, "btc_chg": price_chg, "days": days, **m})

    # Karşılaştırma tablosu
    print(f"\n{'='*82}")
    print(f"REJİM KARŞILAŞTIRMA TABLOSU")
    print(f"{'='*82}")
    print(f"{'Dönem':<30} {'BTC%':>7} {'Trade':>6} {'WR%':>5} {'CAGR%':>7} {'DD%':>6} {'Sharpe':>7}")
    print(f"{'-'*82}")
    for r in results:
        label_short = r["label"][:30]
        print(f"{label_short:<30} {r['btc_chg']:>+7.1f} {r['n']:>6} {r['wr']:>5} {r['cagr']:>+7.1f} {r['dd']:>6} {r['sharpe']:>7.2f}")

    # Özetleme
    if results:
        avg_sharpe = sum(r["sharpe"] for r in results) / len(results)
        avg_cagr = sum(r["cagr"] for r in results) / len(results)
        worst_dd = max(r["dd"] for r in results)
        worst_dd_period = next(r["label"] for r in results if r["dd"] == worst_dd)
        best_sharpe = max(r["sharpe"] for r in results)
        best_sharpe_period = next(r["label"] for r in results if r["sharpe"] == best_sharpe)
        worst_sharpe = min(r["sharpe"] for r in results)
        worst_sharpe_period = next(r["label"] for r in results if r["sharpe"] == worst_sharpe)

        print(f"\n{'─'*82}")
        print(f"ÖZET — Cross-regime analiz")
        print(f"  Ortalama Sharpe: {avg_sharpe:.2f}")
        print(f"  Ortalama CAGR: %{avg_cagr:+.1f}")
        print(f"  En iyi rejim: {best_sharpe_period} (Sharpe {best_sharpe:.2f})")
        print(f"  En kötü rejim: {worst_sharpe_period} (Sharpe {worst_sharpe:.2f})")
        print(f"  En büyük DD: {worst_dd_period} (%{worst_dd})")


if __name__ == "__main__":
    main()
