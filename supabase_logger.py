"""
supabase_logger.py
Flip-zone karar verilerini Supabase'e logla.
Backtest için temel veri kaynağı olacak.
"""

import os
from typing import Optional

try:
    from supabase import create_client, Client
except ImportError:
    print("[supabase_logger] 'supabase' paketi yüklenmemiş. "
          "pip install supabase")
    create_client = None
    Client = None


_supabase: Optional["Client"] = None


def get_supabase() -> Optional["Client"]:
    """Lazy singleton. ENV'de SUPABASE_URL & SUPABASE_KEY olmalı."""
    global _supabase
    if _supabase is not None:
        return _supabase

    if create_client is None:
        return None

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")

    if not (url and key):
        print("[supabase_logger] SUPABASE_URL/KEY env'de yok, log atlanacak.")
        return None

    _supabase = create_client(url, key)
    return _supabase


def log_flip_zone_decision(payload: dict, raw_decision: str) -> None:
    """
    Karar üretildikten sonra çağrılır.
    payload: gdive_server.py'nin ürettiği son dict (flip_zone alanı dahil)
    raw_decision: flip-zone override öncesi karar (örn. "LONG HAZIR")
    """
    sb = get_supabase()
    if sb is None:
        return

    fz = payload.get("flip_zone", {}) or {}
    pyramid = payload.get("pyramid", {}) or {}
    market = payload.get("market", {}) or {}

    row = {
        "spot": market.get("btc_spot"),
        "flip_price": market.get("flip_price"),
        "flip_dist_pct": fz.get("flip_dist_pct"),
        "atr_pct": fz.get("atr_pct"),
        "flip_dist_atr_ratio": fz.get("flip_dist_atr_ratio"),
        "zone": fz.get("zone"),
        "decision": fz.get("decision"),
        "position_multiplier": fz.get("position_multiplier"),
        "pyramid_total": pyramid.get("total"),
        "pyramid_direction": pyramid.get("direction", "neutral"),
        "pyramid_decision_raw": raw_decision,
        "pyramid_decision_final": pyramid.get("final_decision"),
        "override_pyramid": fz.get("override_pyramid", False),
        "reason": fz.get("reason")
    }

    # Boş alanları temizle (Supabase NOT NULL constraint'lerini bozmasın)
    row = {k: v for k, v in row.items() if v is not None}

    try:
        sb.table("flip_zone_log").insert(row).execute()
    except Exception as e:
        print(f"[supabase_logger] insert error: {e}")
