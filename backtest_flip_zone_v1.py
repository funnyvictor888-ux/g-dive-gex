#!/usr/bin/env python3
"""
backtest_flip_zone_v1.py
G-DIVE Flip-Zone preliminary backtest.

Yapılanlar:
  1. Supabase 'snapshots' tablosundan flip_zone DOLU satırları çek
  2. Forward returns hesapla (1h, 4h, 24h)
  3. "Trade alma" momentleri tespit et (basit proxy: spot HVL'i geçtiği anlar)
  4. Filtre AÇIK vs KAPALI karşılaştır
  5. Grid search: farklı (danger_mult, caution_mult) kombinasyonları

Önemli not — Sen "pyramid_total" backend'de yok dedin. Bu yüzden sinyal
oluşumunu "gamma_regime + spot vs hvl" üzerinden yaklaşık modelliyoruz:
  - LONG_GAMMA + spot > hvl  → +1 (LONG sinyali)
  - LONG_GAMMA + spot < hvl  → -1 (SHORT sinyali, transition zone)
  - NEGATIVE_GAMMA           → -1 (SHORT bölge)
  - DEAD_ZONE / TRANSITION   → 0

Bu yaklaşık ama anlamlı; gerçek karar piramidi mantığına benzer.

Kullanım:
  python backtest_flip_zone_v1.py
"""

import os
import sys
import json
import urllib.request
from collections import defaultdict
from datetime import datetime

SUPABASE_URL = "https://gigkmjutnucssgwcnegn.supabase.co"
SUPABASE_KEY = "sb_publishable_jiFBPVGeFXKl1myvEjTI8g_KKUenCmW"

# Backtest parametreleri
FORWARD_HOURS = [1, 4, 24]   # ileri bakış pencereleri
FALLBACK_ATR_PCT = 1.2       # Supabase'de ATR yoksa default
MIN_ROWS_FOR_BACKTEST = 100


# ---------------------------------------------------------------------------
# Veri çekme
# ---------------------------------------------------------------------------

def fetch_snapshots():
    """Tüm flip_zone dolu snapshot'ları çek."""
    select = "id,timestamp,spot,hvl,total_net_gex,gamma_regime,regime,flip_zone"
    url = f"{SUPABASE_URL}/rest/v1/snapshots?select={select}&order=id.asc&limit=5000&flip_zone=not.is.null"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        rows = json.loads(resp.read())
    print(f"✓ {len(rows)} snapshot çekildi (flip_zone dolu)")
    return rows


# ---------------------------------------------------------------------------
# Sinyal modelleme — gerçek karar piramidi yokken proxy
# ---------------------------------------------------------------------------

def signal_direction(row):
    """
    Snapshot'tan kaba sinyal yönü (+1 LONG, -1 SHORT, 0 NEUTRAL).
    Frontend karar piramidi mantığına yakın bir proxy.
    """
    gamma = row.get("gamma_regime", "")
    regime = row.get("regime", "")
    spot = row.get("spot", 0)
    hvl = row.get("hvl", 0)

    if not spot or not hvl:
        return 0

    # Pozitif gamma + spot HVL üstü → LONG bias
    if gamma == "LONG_GAMMA" and spot > hvl:
        return 1
    # Negatif gamma → SHORT bias
    if gamma in ("NEGATIVE_GAMMA", "SHORT_GAMMA"):
        return -1
    # IDEAL_LONG regime → LONG
    if "LONG" in (regime or "").upper():
        return 1
    if "SHORT" in (regime or "").upper():
        return -1
    return 0


# ---------------------------------------------------------------------------
# Forward returns
# ---------------------------------------------------------------------------

def parse_ts(s):
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def compute_forward_returns(rows):
    """Her satıra fwd_ret_Nh ekle (N = 1, 4, 24)."""
    # Snapshot'ları timestamp'a göre sırala
    rows = sorted(rows, key=lambda r: parse_ts(r["timestamp"]))

    # Her satır için, N saat sonraki en yakın spot'u bul
    n = len(rows)
    for i, r in enumerate(rows):
        ts_i = parse_ts(r["timestamp"])
        spot_i = r.get("spot")
        if not spot_i:
            continue

        for hours in FORWARD_HOURS:
            target_ts = ts_i.timestamp() + hours * 3600
            # i+1'den sonra hedef timestamp'a en yakın satırı bul
            for j in range(i + 1, n):
                tj = parse_ts(rows[j]["timestamp"]).timestamp()
                if tj >= target_ts:
                    spot_j = rows[j].get("spot")
                    if spot_j:
                        r[f"fwd_ret_{hours}h"] = (spot_j - spot_i) / spot_i
                    break

    return rows


# ---------------------------------------------------------------------------
# Filtre simülasyonu — eşik grid search
# ---------------------------------------------------------------------------

def evaluate_zone(flip_dist_pct, atr_pct, danger_mult, caution_mult):
    """Eşiklere göre zone döndür. flip_dist_pct yüzde (0.46 = %0.46)."""
    if atr_pct <= 0:
        return "CLEAR"
    ratio = flip_dist_pct / atr_pct
    if ratio < danger_mult:
        return "DANGER"
    if ratio < caution_mult:
        return "CAUTION"
    return "CLEAR"


def position_multiplier(zone, signal, spot, hvl):
    """Pozisyon çarpanı. CAUTION'da flip-kırma trade veto."""
    if zone == "DANGER":
        return 0.0
    if zone == "CAUTION":
        below = spot < hvl
        # Flip kırma trade'i: spot altta + LONG, ya da spot üstte + SHORT
        is_break = (below and signal == 1) or (not below and signal == -1)
        return 0.0 if is_break else 0.5
    return 1.0


def run_grid_search(rows):
    """Farklı (danger, caution) kombinasyonlarını dene."""
    danger_mults = [0.3, 0.4, 0.5, 0.6, 0.75, 1.0]
    caution_mults = [1.5, 2.0, 2.5, 3.0]

    results = []

    for d in danger_mults:
        for c in caution_mults:
            if c <= d:
                continue

            unfilt_trades = []   # filtre kapalıyken alınan tüm trade'ler
            filt_trades = []     # filtre açıkken alınan trade'ler (mult dahil)

            for r in rows:
                sig = signal_direction(r)
                if sig == 0:
                    continue

                fz = r.get("flip_zone") or {}
                flip_dist = fz.get("flip_dist_pct", 999)
                atr = fz.get("atr_pct", FALLBACK_ATR_PCT)
                spot = r.get("spot", 0)
                hvl = r.get("hvl", 0)

                zone = evaluate_zone(flip_dist, atr, d, c)
                mult = position_multiplier(zone, sig, spot, hvl)

                # 24h ileri getiri
                fwd = r.get("fwd_ret_24h")
                if fwd is None:
                    continue

                pnl_unfilt = sig * fwd
                pnl_filt = sig * fwd * mult

                unfilt_trades.append(pnl_unfilt)
                if mult > 0:
                    filt_trades.append(pnl_filt)

            if not unfilt_trades:
                continue

            n_unf = len(unfilt_trades)
            n_flt = len(filt_trades)

            wr_unf = sum(1 for p in unfilt_trades if p > 0) / n_unf * 100
            wr_flt = (sum(1 for p in filt_trades if p > 0) / n_flt * 100) if n_flt else 0

            avg_unf = sum(unfilt_trades) / n_unf
            avg_flt = (sum(filt_trades) / n_flt) if n_flt else 0

            sum_unf = sum(unfilt_trades)
            sum_flt = sum(filt_trades)

            # Sharpe yaklaşımı
            def sharpe(arr):
                if len(arr) < 2:
                    return 0
                m = sum(arr) / len(arr)
                v = sum((x - m) ** 2 for x in arr) / len(arr)
                return m / (v ** 0.5) if v > 0 else 0

            results.append({
                "danger_mult": d,
                "caution_mult": c,
                "n_unfilt": n_unf,
                "n_filt": n_flt,
                "reduction_pct": (1 - n_flt / n_unf) * 100,
                "wr_unfilt": wr_unf,
                "wr_filt": wr_flt,
                "wr_delta_pp": wr_flt - wr_unf,
                "avg_ret_unfilt": avg_unf * 100,
                "avg_ret_filt": avg_flt * 100,
                "sum_ret_unfilt": sum_unf * 100,
                "sum_ret_filt": sum_flt * 100,
                "sharpe_unfilt": sharpe(unfilt_trades),
                "sharpe_filt": sharpe(filt_trades)
            })

    return results


# ---------------------------------------------------------------------------
# Baseline analiz
# ---------------------------------------------------------------------------

def baseline_analysis(rows):
    """Mevcut eşiklerle (0.5 / 2.0) detaylı analiz."""
    by_zone = defaultdict(list)
    by_decision = defaultdict(list)

    for r in rows:
        fz = r.get("flip_zone") or {}
        zone = fz.get("zone")
        decision = fz.get("decision")
        sig = signal_direction(r)
        fwd = r.get("fwd_ret_24h")

        if zone is None or fwd is None:
            continue

        # Sinyal yönünde getiri
        pnl = sig * fwd if sig != 0 else None

        if pnl is not None:
            by_zone[zone].append(pnl)
            by_decision[decision].append(pnl)

    print("\n=== BASELINE — Mevcut Eşikler (DANGER<0.5×ATR, CAUTION<2.0×ATR) ===")
    print(f"{'Zone':10} {'N':5} {'Win%':>7} {'Avg Ret':>9} {'Sum Ret':>9}")
    for zone in ["DANGER", "CAUTION", "CLEAR"]:
        arr = by_zone.get(zone, [])
        if not arr:
            print(f"{zone:10} {0:5} {'-':>7} {'-':>9} {'-':>9}")
            continue
        n = len(arr)
        wr = sum(1 for p in arr if p > 0) / n * 100
        avg = sum(arr) / n * 100
        s = sum(arr) * 100
        print(f"{zone:10} {n:5} {wr:6.1f}% {avg:8.3f}% {s:8.2f}%")

    print(f"\n{'Decision':10} {'N':5} {'Win%':>7} {'Avg Ret':>9}")
    for dec in ["OK", "REDUCE", "VETO", "BEKLE"]:
        arr = by_decision.get(dec, [])
        if not arr:
            continue
        n = len(arr)
        wr = sum(1 for p in arr if p > 0) / n * 100
        avg = sum(arr) / n * 100
        print(f"{dec:10} {n:5} {wr:6.1f}% {avg:8.3f}%")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("G-DIVE Flip-Zone Backtest v1 (preliminary)")
    print("=" * 70)

    rows = fetch_snapshots()
    if len(rows) < MIN_ROWS_FOR_BACKTEST:
        print(f"\n⚠ Yetersiz veri ({len(rows)} < {MIN_ROWS_FOR_BACKTEST}).")
        print("  Daha fazla snapshot biriktikten sonra çalıştır.")
        return

    print(f"\n→ Forward returns hesaplanıyor ({FORWARD_HOURS}h)...")
    rows = compute_forward_returns(rows)

    # Forward return olan satır sayısı
    n_24h = sum(1 for r in rows if r.get("fwd_ret_24h") is not None)
    print(f"  24h forward return: {n_24h} satır")

    # Sinyal dağılımı
    sigs = defaultdict(int)
    for r in rows:
        sigs[signal_direction(r)] += 1
    print(f"\nSinyal dağılımı:")
    for s, label in [(1, "LONG"), (-1, "SHORT"), (0, "NEUTRAL")]:
        n = sigs[s]
        print(f"  {label:8} {n:5} ({n/len(rows)*100:.1f}%)")

    # Baseline analiz
    baseline_analysis(rows)

    # Grid search
    print("\n=== GRID SEARCH — Eşik Optimizasyonu ===")
    results = run_grid_search(rows)

    if not results:
        print("⚠ Grid search sonuç vermedi.")
        return

    # En iyi Sharpe + en iyi sum return + en iyi WR delta
    by_sharpe = sorted(results, key=lambda x: x["sharpe_filt"], reverse=True)
    by_sum = sorted(results, key=lambda x: x["sum_ret_filt"], reverse=True)
    by_wr_delta = sorted(results, key=lambda x: x["wr_delta_pp"], reverse=True)

    def print_table(label, sorted_results, n=5):
        print(f"\n--- TOP {n} — {label} ---")
        print(f"{'D':>5} {'C':>5} {'N_unf':>6} {'N_flt':>6} {'Red%':>6} "
              f"{'WR_unf':>7} {'WR_flt':>7} {'ΔWR':>6} "
              f"{'Sum_unf':>9} {'Sum_flt':>9} {'Sharpe':>7}")
        for r in sorted_results[:n]:
            print(f"{r['danger_mult']:5.2f} {r['caution_mult']:5.2f} "
                  f"{r['n_unfilt']:6} {r['n_filt']:6} {r['reduction_pct']:5.1f}% "
                  f"{r['wr_unfilt']:6.1f}% {r['wr_filt']:6.1f}% {r['wr_delta_pp']:+5.1f} "
                  f"{r['sum_ret_unfilt']:+8.2f}% {r['sum_ret_filt']:+8.2f}% "
                  f"{r['sharpe_filt']:+6.3f}")

    print_table("Sharpe (filtreli)", by_sharpe)
    print_table("Sum Return (filtreli)", by_sum)
    print_table("Win Rate Improvement (Δ pp)", by_wr_delta)

    # Mevcut eşiklere göre kıyas
    current = next((r for r in results if r["danger_mult"] == 0.5 and r["caution_mult"] == 2.0), None)
    if current:
        print(f"\n=== MEVCUT EŞİKLER (0.5 / 2.0) ===")
        print(f"  Trade reduction: %{current['reduction_pct']:.1f}")
        print(f"  WR: %{current['wr_unfilt']:.1f} → %{current['wr_filt']:.1f} (Δ {current['wr_delta_pp']:+.1f} pp)")
        print(f"  Sum return: %{current['sum_ret_unfilt']:+.2f} → %{current['sum_ret_filt']:+.2f}")
        print(f"  Sharpe filtreli: {current['sharpe_filt']:+.3f}")

    print("\n" + "=" * 70)
    print("Not: 162 snapshot ile bu PRELIMINARY backtest.")
    print("Eşik değişikliği için 250+ snapshot biriktiğinde tekrar çalıştır.")
    print("=" * 70)


if __name__ == "__main__":
    main()
