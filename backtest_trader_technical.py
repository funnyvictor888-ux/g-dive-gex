#!/usr/bin/env python3
"""
backtest_trader_technical.py

C1 ve C4 trader stratejilerinin SAF TEKNİK performansını ölçer.
GEX filtresi (line 577) DAHİL DEĞİL — tarihsel GEX yok.
HVL filtresi DAHİL DEĞİL — tarihsel HVL yok.

Yani backtest şu soruyu cevaplar:
  "Eğer trader sadece EMA9/21/50/200 + RSI + ATR ile çalışsaydı,
   son 6 ayda nasıl performans gösterirdi?"

Live trader bu filtrelere ek olarak GEX>0/GEX<0 da istiyor.
Eğer backtest negatif çıkarsa → GEX filtresi muhtemelen koruyor.
Eğer backtest pozitif çıkarsa → GEX filtresi gereksiz kısıtlama yapıyor.

Çalıştır:
  python3 backtest_trader_technical.py
"""

import urllib.request
import json
import time
from datetime import datetime
from collections import OrderedDict


# ──────────────────────────────────────────────────────────────
# STRATEJİ KONFIGÜRASYONLARI (gdive_trader.py'dan birebir)
# ──────────────────────────────────────────────────────────────
STRATEGIES = {
    "C1": {
        "name": "C1_Conservative",
        "atr_stop_mult": 2.25,
        "atr_tp_mult": 6.0,
        "rsi_bull_min": 50, "rsi_bull_max": 72,
        "rsi_bear_min": 30, "rsi_bear_max": 48,
        "dte_exit_bars": 14 * 6,  # 14 gün × 6 (4H bar/gün)
        "trend_confirm_e200": True,
        "base_risk": 0.02,
        "leverage": 2,
        "description": "Sharpe 1.46 | DD %14 | CAGR %56 (claimed)",
    },
    "C4": {
        "name": "C4_Aggressive",
        "atr_stop_mult": 1.5,
        "atr_tp_mult": 6.0,
        "rsi_bull_min": 50, "rsi_bull_max": 75,
        "rsi_bear_min": 25, "rsi_bear_max": 55,
        "dte_exit_bars": 7 * 6,   # 7 gün × 6 bar
        "trend_confirm_e200": True,
        "base_risk": 0.02,
        "leverage": 2,
        "description": "Sharpe 1.12 | DD %24 | CAGR %108 (claimed)",
    },
}

# Realistic PnL cost config (gdive_trader.py ile birebir)
COST_CONFIG = {
    "taker_fee_rate": 0.0005,
    "funding_rate_daily": 0.00027,
    "slippage_rate": 0.0002,
}

# Backtest parametreleri
DAYS = 180         # 6 ay
CAPITAL = 10000    # Başlangıç sermayesi


# ──────────────────────────────────────────────────────────────
# Deribit'ten 4H OHLCV çek (1H'tan aggregate)
# ──────────────────────────────────────────────────────────────
def fetch_deribit_4h_ohlcv(days):
    """Son `days` günlük 4H OHLCV verisi — 1H'tan aggregate."""
    now = int(time.time() * 1000)
    start = now - days * 24 * 3600 * 1000
    url = (f"https://www.deribit.com/api/v2/public/get_tradingview_chart_data"
           f"?instrument_name=BTC-PERPETUAL&resolution=60"
           f"&start_timestamp={start}&end_timestamp={now}")
    req = urllib.request.Request(url, headers={"User-Agent": "backtest/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    result = data.get("result", {})
    ticks = result.get("ticks", [])
    opens = result.get("open", [])
    highs = result.get("high", [])
    lows = result.get("low", [])
    closes = result.get("close", [])

    # 4H slot bazlı aggregation
    slots = OrderedDict()
    for ts, o, h, l, c in zip(ticks, opens, highs, lows, closes):
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
# Indicators (gdive_trader.py ile birebir)
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
    """ATR — gdive_trader.py'daki gibi EMA bazlı."""
    trs = []
    for i, c in enumerate(candles):
        prev_c = candles[max(0, i - 1)]["c"]
        tr = max(c["h"] - c["l"], abs(c["h"] - prev_c), abs(c["l"] - prev_c))
        trs.append(tr)
    return ema(trs, period)


# ──────────────────────────────────────────────────────────────
# Realistic PnL (gdive_trader.py ile birebir)
# ──────────────────────────────────────────────────────────────
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
# BACKTEST — bir strateji için tüm sinyalleri yakala, exit simüle et
# ──────────────────────────────────────────────────────────────
def backtest(candles, cfg):
    closes = [c["c"] for c in candles]
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]

    # Indicators
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

    # 200+ bar warmup gerekli (EMA200 için)
    start_i = max(200, 30)

    for i in range(start_i, len(candles)):
        price = closes[i]
        atr_v = atrs[i] if atrs[i] else 0
        rsi_v = rsis[i] if rsis[i] is not None else 50

        # ─── Açık trade yönetimi ───
        if in_trade:
            bar_high = highs[i]
            bar_low = lows[i]
            bars_held = i - open_idx
            days_held = bars_held / 6.0  # 4H bar → günde 6 bar

            exit_price = None
            exit_reason = None

            if direction == "LONG":
                if bar_low <= stop:
                    exit_price = stop
                    exit_reason = "STOP"
                elif bar_high >= tp:
                    exit_price = tp
                    exit_reason = "TP"
                elif bars_held >= cfg["dte_exit_bars"] and price > entry:
                    # TIME_EXIT: sure doldu VE karda (canli gdive_trader.py birebir).
                    # Zararda ise pozisyonu TUT, stop'a birak.
                    exit_price = price
                    exit_reason = "TIME_EXIT"
            else:  # SHORT
                if bar_high >= stop:
                    exit_price = stop
                    exit_reason = "STOP"
                elif bar_low <= tp:
                    exit_price = tp
                    exit_reason = "TP"
                elif bars_held >= cfg["dte_exit_bars"] and price < entry:
                    # TIME_EXIT: sure doldu VE karda (SHORT icin price < entry).
                    exit_price = price
                    exit_reason = "TIME_EXIT"

            if exit_price is not None:
                pnl_data = calc_realistic_pnl(entry, exit_price, size, direction, days_held, cfg["leverage"])
                trades.append({
                    "open_idx": open_idx,
                    "close_idx": i,
                    "direction": direction,
                    "entry": entry,
                    "exit": exit_price,
                    "stop": stop,
                    "tp": tp,
                    "size": size,
                    "exit_reason": exit_reason,
                    "days_held": days_held,
                    "gross_pnl": round(pnl_data["gross"], 2),
                    "net_pnl": round(pnl_data["net"], 2),
                    "cost": round(pnl_data["cost"], 2),
                })
                in_trade = False
                continue

        # ─── Yeni sinyal ara (açık trade yoksa) ───
        if in_trade:
            continue

        # bull_tech / bear_tech (gdive_trader.py line 393-399 birebir)
        e200_long = price > e200[i] if cfg["trend_confirm_e200"] else True
        e200_short = price < e200[i] if cfg["trend_confirm_e200"] else True

        bull_tech = (e9[i] > e21[i] and
                     cfg["rsi_bull_min"] < rsi_v < cfg["rsi_bull_max"] and
                     price > e50[i] and e200_long)
        bear_tech = (e9[i] < e21[i] and
                     cfg["rsi_bear_min"] < rsi_v < cfg["rsi_bear_max"] and
                     price < e50[i] and e200_short)

        # Sinyal — line 576/577 ama GEX ve HVL filtresiz
        # Live trader: bull_tech AND e9>e21 AND price>hvl AND gex>0
        # Backtest:    bull_tech (zaten e9>e21 içeriyor) — saf teknik
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
# İSTATİSTİKLER
# ──────────────────────────────────────────────────────────────
def analyze(trades, label):
    if not trades:
        print(f"\n{label} — HİÇ TRADE YOK")
        return

    n = len(trades)
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    longs = [t for t in trades if t["direction"] == "LONG"]
    shorts = [t for t in trades if t["direction"] == "SHORT"]

    gross_total = sum(t["gross_pnl"] for t in trades)
    net_total = sum(t["net_pnl"] for t in trades)
    cost_total = sum(t["cost"] for t in trades)

    win_rate = len(wins) / n * 100
    avg_win = sum(t["net_pnl"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["net_pnl"] for t in losses) / len(losses) if losses else 0
    expectancy = net_total / n

    # Sharpe (basit — günlük getiriyle değil trade getiriyle)
    if n > 1:
        mean_pnl = net_total / n
        var = sum((t["net_pnl"] - mean_pnl) ** 2 for t in trades) / (n - 1)
        std = var ** 0.5
        sharpe_per_trade = mean_pnl / std if std > 0 else 0
        # Yıllık Sharpe yaklaşımı — trade sıklığına göre scale
        trades_per_year = n * (365 / DAYS)
        sharpe_annual = sharpe_per_trade * (trades_per_year ** 0.5)
    else:
        sharpe_annual = 0

    # Max drawdown (equity curve üzerinden)
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

    # Exit reason dağılımı
    exit_reasons = {}
    for t in trades:
        r = t["exit_reason"]
        exit_reasons.setdefault(r, []).append(t["net_pnl"])

    final_equity = equity[-1]
    total_return_pct = (final_equity - CAPITAL) / CAPITAL * 100
    cagr = ((final_equity / CAPITAL) ** (365 / DAYS) - 1) * 100

    print(f"\n{'='*70}")
    print(f"{label}")
    print(f"{'='*70}")
    print(f"  Trade sayısı:        {n}  ({len(longs)} LONG, {len(shorts)} SHORT)")
    print(f"  Win rate:            {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"  Avg kazanç:          ${avg_win:+.2f}")
    print(f"  Avg kayıp:           ${avg_loss:+.2f}")
    print(f"  Avg kayıp/kazanç:    {abs(avg_loss/avg_win) if avg_win else 0:.2f}×")
    print(f"  Expectancy/trade:    ${expectancy:+.2f}")
    print(f"")
    print(f"  Gross P&L:           ${gross_total:+.2f}")
    print(f"  Costs (fee+fund+sl): ${cost_total:.2f}")
    print(f"  NET P&L:             ${net_total:+.2f}")
    print(f"")
    print(f"  Total return:        {total_return_pct:+.1f}%")
    print(f"  CAGR (annualized):   {cagr:+.1f}%")
    print(f"  Max DD:              {max_dd_pct:.1f}%")
    print(f"  Sharpe (annual):     {sharpe_annual:.2f}")
    print(f"")
    print(f"  Exit sebepleri:")
    for r, pnls in sorted(exit_reasons.items()):
        avg = sum(pnls) / len(pnls)
        print(f"    {r:6}: {len(pnls):>3} trade, avg ${avg:+.2f}, sum ${sum(pnls):+.2f}")


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────
def main():
    print(f"Deribit'ten {DAYS} günlük 4H veri çekiliyor...")
    candles = fetch_deribit_4h_ohlcv(DAYS)
    print(f"✓ {len(candles)} 4H bar geldi")
    if candles:
        first = datetime.fromtimestamp(candles[0]["ts"] / 1000)
        last = datetime.fromtimestamp(candles[-1]["ts"] / 1000)
        print(f"  Dönem: {first} → {last}")
        print(f"  Fiyat: ${candles[0]['c']:.0f} → ${candles[-1]['c']:.0f} "
              f"({(candles[-1]['c']/candles[0]['c']-1)*100:+.1f}%)")

    if len(candles) < 250:
        print(f"⚠ Veri çok az ({len(candles)}), backtest atlanıyor")
        return

    print(f"\n{'='*70}")
    print(f"BACKTEST — Saf Teknik Filtre")
    print(f"GEX ve HVL filtresi DAHİL DEĞİL (tarihsel veri yok)")
    print(f"Live trader BU teknikere EK olarak GEX>0/GEX<0 da bekliyor")
    print(f"{'='*70}")

    all_results = {}
    for code, cfg in STRATEGIES.items():
        trades = backtest(candles, cfg)
        analyze(trades, f"{code} — {cfg['name']}  ({cfg['description']})")
        all_results[code] = trades

    # Karşılaştırma tablosu
    print(f"\n{'='*70}")
    print(f"KARŞILAŞTIRMA")
    print(f"{'='*70}")
    print(f"{'Strateji':<25} {'Trade':>6} {'WR%':>6} {'Net P&L':>10} {'CAGR%':>8} {'DD%':>7} {'Sharpe':>7}")
    for code, trades in all_results.items():
        if not trades:
            print(f"{code:<25} {'(no trades)'}")
            continue
        n = len(trades)
        wins = sum(1 for t in trades if t["net_pnl"] > 0)
        net = sum(t["net_pnl"] for t in trades)
        equity = [CAPITAL]
        for t in trades:
            equity.append(equity[-1] + t["net_pnl"])
        cagr = ((equity[-1] / CAPITAL) ** (365 / DAYS) - 1) * 100
        peak = equity[0]
        max_dd = 0
        for e in equity:
            if e > peak:
                peak = e
            dd = (peak - e) / peak * 100
            if dd > max_dd:
                max_dd = dd
        mean_pnl = net / n
        var = sum((t["net_pnl"] - mean_pnl) ** 2 for t in trades) / (n - 1) if n > 1 else 0
        std = var ** 0.5
        sharpe = (mean_pnl / std * (n * 365 / DAYS) ** 0.5) if std > 0 else 0
        wr = wins / n * 100
        print(f"{code+' '+STRATEGIES[code]['name']:<25} {n:>6} {wr:>6.1f} ${net:>+9.2f} {cagr:>+7.1f} {max_dd:>6.1f} {sharpe:>7.2f}")


if __name__ == "__main__":
    main()
