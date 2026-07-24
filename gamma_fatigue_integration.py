"""
gamma_fatigue_integration.py
G-DIVE Gamma Fatigue — Supabase State Persistence + Cron Wiring Taslagi
===========================================================================
NEDEN SUPABASE GEREKLI (jsonl DEGIL): gdive_server.py GitHub Actions
cron'unda calisiyor — her tick FRESH bir runner (ubuntu-latest), yerel
disk kalici DEGIL. Hetzner'daki taleb_observe_log.jsonl yaklasimi (PM2,
surekli ayakta tek process) burada calismaz, her 5 dakikada diskteki
her sey sifirlanir. Bu yuzden gamma_fatigue.py'nin rolling state'i
(put_delta_history, cvd_history, toxicity_belief, last_check_ms)
Supabase'de tek-satirlik bir state tablosunda tutulmali.

────────────────────────────────────────────────────────────────────
1) ONCE SUPABASE SQL EDITOR'DE TABLOLARI OLUSTUR
────────────────────────────────────────────────────────────────────

-- Tek satirlik rolling state (id hep 1)
create table gamma_fatigue_state (
    id integer primary key default 1,
    last_check_ms bigint default 0,
    put_delta_history jsonb default '[]'::jsonb,
    cvd_history jsonb default '[]'::jsonb,
    toxicity_belief float8 default 0.5,
    updated_at timestamptz default now()
);
insert into gamma_fatigue_state (id) values (1);

-- Observe-only log (taleb_shadow_log ile ayni mantik, ama bu kez
-- backfill sorgusunu DOGRU yaziyoruz: lte, gte degil)
create table gamma_fatigue_observe_log (
    id bigint generated always as identity primary key,
    timestamp timestamptz default now(),
    spot float8,
    fatigue_signal boolean,
    saturation_pct float8,
    cvd_inflected boolean,
    toxicity_belief float8,
    backward_induction_band_pct float8,
    static_band_pct float8,
    spot_1h_later float8,
    pct_move float8,
    direction_correct boolean
);

────────────────────────────────────────────────────────────────────
2) STATE PERSISTENCE FONKSIYONLARI
────────────────────────────────────────────────────────────────────
"""

import json
import time
import urllib.request
import os
from datetime import datetime, timezone


def _headers():
    key = os.environ["SUPABASE_KEY"]
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def load_gamma_fatigue_state() -> dict:
    """id=1 satirini okur. Tablo bossa varsayilan state doner (ilk calistirma)."""
    url = f"{os.environ['SUPABASE_URL']}/rest/v1/gamma_fatigue_state?id=eq.1&select=*"
    req = urllib.request.Request(url, headers=_headers())
    rows = json.loads(urllib.request.urlopen(req).read())
    if not rows:
        return {"last_check_ms": 0, "put_delta_history": [], "cvd_history": [], "toxicity_belief": 0.5}
    row = rows[0]
    return {
        "last_check_ms": row.get("last_check_ms", 0),
        "put_delta_history": row.get("put_delta_history") or [],
        "cvd_history": row.get("cvd_history") or [],
        "toxicity_belief": row.get("toxicity_belief", 0.5),
    }


def save_gamma_fatigue_state(state: dict) -> None:
    """id=1 satirini PATCH ile guncelle (satir setup'ta bir kez INSERT edilmis olmali)."""
    from datetime import datetime, timezone
    url = f"{os.environ['SUPABASE_URL']}/rest/v1/gamma_fatigue_state?id=eq.1"
    payload = json.dumps({
        "last_check_ms": state["last_check_ms"],
        "put_delta_history": state["put_delta_history"],
        "cvd_history": state["cvd_history"],
        "toxicity_belief": state["toxicity_belief"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).encode()
    headers = {**_headers(), "Prefer": "return=minimal"}
    req = urllib.request.Request(url, data=payload, headers=headers, method="PATCH")
    try:
        urllib.request.urlopen(req)
    except Exception as e:
        print(f"[GAMMA_FATIGUE] save_state HATA: {e}")


def log_gamma_fatigue_observe(entry: dict) -> None:
    """gamma_fatigue_observe_log'a tek satir POST eder (taleb_shadow_log pattern'iyle ayni)."""
    url = f"{os.environ['SUPABASE_URL']}/rest/v1/gamma_fatigue_observe_log"
    headers = {**_headers(), "Prefer": "return=minimal"}
    req = urllib.request.Request(url, data=json.dumps(entry).encode(), headers=headers, method="POST")
    urllib.request.urlopen(req)


def backfill_gamma_fatigue_observe(current_spot: float) -> None:
    """
    1 saat onceki kayitlari guncelle (band isabeti / pct_move).
    operator 'lte', order=timestamp.asc (taleb hatasini tekrarlamiyoruz).
    current_spot: cron'da elde olan data["spot"].
    """
    if not current_spot:
        return
    one_hour_ago = (datetime.now(timezone.utc) - __import__("datetime").timedelta(hours=1)).isoformat()
    url = (
        f"{os.environ['SUPABASE_URL']}/rest/v1/gamma_fatigue_observe_log"
        f"?timestamp=lte.{one_hour_ago[:19]}&spot_1h_later=is.null&order=timestamp.asc&limit=5"
    )
    req = urllib.request.Request(url, headers=_headers())
    old_rows = json.loads(urllib.request.urlopen(req).read())
    if not old_rows:
        return

    updated = 0
    for row in old_rows:
        old_spot = row.get("spot") or 0
        if not old_spot:
            continue
        pct_move = (current_spot - old_spot) / old_spot * 100.0
        # fatigue isabeti: fatigue_signal=True iken static_band'i asan hareket
        # olduysa "yakaladi" say; fatigue yoksa None (notr).
        fatigue = row.get("fatigue_signal", False)
        static_band = row.get("static_band_pct") or 0.1
        correct = (abs(pct_move) > static_band) if fatigue else None
        patch = {
            "spot_1h_later": round(current_spot, 2),
            "pct_move": round(pct_move, 3),
            "direction_correct": correct,
        }
        purl = f"{os.environ['SUPABASE_URL']}/rest/v1/gamma_fatigue_observe_log?id=eq.{row['id']}"
        preq = urllib.request.Request(
            purl,
            data=json.dumps(patch).encode(),
            headers={**_headers(), "Prefer": "return=minimal"},
            method="PATCH",
        )
        urllib.request.urlopen(preq)
        updated += 1
    if updated:
        print(f"[GAMMA_FATIGUE] backfill: {updated} eski kayit guncellendi")


# ────────────────────────────────────────────────────────────────────
# 3) CRON WIRING — gdive_server.py'nin run_cron() icine eklenecek
#    Yerlestirme noktasi: mevcut taleb_shadow_log POST/print bloğunun
#    HEMEN ALTI (satır ~1496, "Shadow log kaydedildi" print'inden sonra).
#    run_cron() icinde zaten su degiskenler hazir: data, pin, shadow_gex,
#    rehedge, taleb (compute_taleb_metrics ciktisi parcalari).
# ────────────────────────────────────────────────────────────────────

def run_gamma_fatigue_tick(data: dict, pin: dict, shadow_gex: dict, rehedge: dict) -> dict:
    """
    run_cron() icinden cagrilacak tek fonksiyon. Observe-only —
    sonuc trade mantigina henuz girmiyor, sadece logluyor.
    """
    from deribit_flow_fetcher import DeribitFlowFetcher
    from gamma_fatigue import compute_gamma_fatigue
    from rehedge_band import solve_rehedge_band
    from rehedge_toxicity_adjustment import compute_skewed_band

    state = load_gamma_fatigue_state()
    fetcher = DeribitFlowFetcher(currency="BTC")

    oi_data = fetcher.fetch_oi_weighted_put_delta()
    since_ms = state["last_check_ms"] or (int(time.time() * 1000) - 3600 * 1000)
    flow_data = fetcher.fetch_trade_flow_increment(since_ms=since_ms)

    gf_result = compute_gamma_fatigue(
        oi_weighted_put_delta=oi_data["oi_weighted_put_delta"],
        put_delta_history=state["put_delta_history"],
        trade_flow_increment=flow_data["trade_flow_increment"],
        cvd_history=state["cvd_history"],
        prior_toxicity_belief=state["toxicity_belief"],
    )

    rb_result = solve_rehedge_band(
        sigma=(data.get("front_iv") or 50.0) / 100,
        gamma=(data.get("total_net_gex") or 0) / 1e6,
        toxicity_belief=gf_result["toxicity_belief"],
    )

    skewed_result = compute_skewed_band(
        spot=data.get("spot"),
        atm_iv=data.get("front_iv") or 50.0,
        net_gamma=(data.get("total_net_gex") or 0) / 1e6,
        toxicity_belief=gf_result["toxicity_belief"],
    )

    save_gamma_fatigue_state({
        "last_check_ms": int(time.time() * 1000),
        "put_delta_history": gf_result["_new_put_delta_history"],
        "cvd_history": gf_result["_new_cvd_history"],
        "toxicity_belief": gf_result["_new_toxicity_belief"],
    })

    log_gamma_fatigue_observe({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "spot": data.get("spot"),
        "fatigue_signal": gf_result["fatigue_signal"],
        "saturation_pct": gf_result["saturation_pct"],
        "cvd_inflected": gf_result["cvd_inflected"],
        "toxicity_belief": gf_result["toxicity_belief"],
        "backward_induction_band_pct": rb_result["band_pct"],
        "static_band_pct": rehedge.get("band_pct"),  # mevcut statik modelle yan yana
        "skewed_lower_band_pct": skewed_result["lower_band_pct"],
        "skewed_upper_band_pct": skewed_result["upper_band_pct"],
        "near_atm_flow": flow_data.get("near_atm_flow"),
        "near_atm_net_gamma": oi_data.get("near_atm_net_gamma"),
    })

    print(
        f"[GAMMA_FATIGUE] signal={gf_result['fatigue_signal']} "
        f"sat={gf_result['saturation_pct']}% belief={gf_result['toxicity_belief']} "
        f"bi_band={rb_result['band_pct']}% static_band={rehedge.get('band_pct')}%"
    )

    try:
        backfill_gamma_fatigue_observe(current_spot=data.get("spot", 0))
    except Exception as _e:
        print(f"[GAMMA_FATIGUE] backfill hata: {_e}")

    return {"gamma_fatigue": gf_result, "rehedge_backward_induction": rb_result}
