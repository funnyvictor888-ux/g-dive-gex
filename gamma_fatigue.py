"""
gamma_fatigue.py
G-DIVE Gamma Fatigue / PUT-Delta Doygunluk Modülü
====================================================
Teorik çerçeve: Glosten-Milgrom (1985) sequential trade modeli + MIT 14.12
(Ian Ball — Bayesian/sinyalleşme oyunları, Lecture 22). Dealer'ın "bu order
flow toksik mi (informed mi)" inancını, ardışık trade'lerin yönünden Bayes
kuralıyla güncelliyoruz. "Options Delta CVD inflection" dediğimiz şey, bu
güncellenen inancın taşıdığı kümülatif akışın trend tersine döndüğü an.

Neden BSM değil shadow gamma: vanna freni BSM gamma ile erken ateşler.
Bu modül oi_weighted_put_delta ve trade_flow_increment girdilerini
taleb_integration_patch.py'deki compute_shadow_gex çıktısından türetilmiş
olarak bekler, ham BSM gamma'dan değil.

İki koşullu sinyal mantığı (tek koşul = bıçak yakalama riski):
  1. OI-ağırlıklı |put Δ| persentil doygunluğu — eşik HARDCODE değil,
     son N gözlemin (put_delta_history) dağılımından her cron'da
     dinamik türetiliyor (percentile_rank).
  2. Options Delta CVD inflection — Bayesian toksisite inancının
     beslendiği kümülatif akışın eğim işareti değiştiği an.
Sinyal = (1) VE (2). Sadece doygunluk varsa ama dönüş yoksa "izlemede
kal" durumudur, henüz sinyal değildir.

DİKKAT — eksik veri pipeline'ı: oi_weighted_put_delta ve
trade_flow_increment şu an Deribit trade print'lerinden gelmiyor, bu
fonksiyon onları hazır bekliyor. Bu fetcher'ı yazmak ayrı bir iş
(RISK_POLICY.md'deki not: "Options Delta CVD = tek yeni data pipeline").

Persisted state (Supabase'de küçük bir state satırı / dosya):
    put_delta_history   (rolling, max 200 nokta)
    cvd_history         (rolling, max 200 nokta)
    toxicity_belief      (tek float, 0-1 arası)
Her cron tick'inde bunlar fonksiyona geri verilir, çıkan "_new_*" alanları
tekrar persist edilir.

Kullanım:
    from gamma_fatigue import compute_gamma_fatigue, should_halt

    result = compute_gamma_fatigue(
        oi_weighted_put_delta=current_value,
        put_delta_history=state["put_delta_history"],
        trade_flow_increment=this_tick_net_put_flow,
        cvd_history=state["cvd_history"],
        prior_toxicity_belief=state["toxicity_belief"],
    )
    state["put_delta_history"] = result["_new_put_delta_history"]
    state["cvd_history"]       = result["_new_cvd_history"]
    state["toxicity_belief"]   = result["_new_toxicity_belief"]

    halt = should_halt(pin_risk_result, result)
"""

from typing import List, Dict


# ---------------------------------------------------------------------------
# 1. BAYESIAN FLOW-TOXICITY BELIEF UPDATE (Glosten-Milgrom tipi)
# ---------------------------------------------------------------------------

def update_belief(
    prior: float,
    trade_direction: int,        # +1 = put alımı baskın, -1 = put satımı baskın, 0 = nötr
    dominant_direction: int = 1,  # sabit konvansiyon: hangi yönü "informed bearish" olarak test ediyoruz
    informed_accuracy: float = 0.65,  # informed trader'ın hipotez yönünde olma oranı
) -> float:
    """
    Tek bir trade gözleminden sonra P(flow toksik / informed) inancını
    günceller.

    Glosten-Milgrom mantığı: informed trader sistematik olarak
    dominant_direction yönünde trade eder (informed_accuracy > 0.5),
    noise trader yön bağımsız (%50/%50).

        posterior = prior*L(d|informed) / [prior*L(d|informed) + (1-prior)*L(d|noise)]
    """
    if trade_direction == 0:
        return prior  # nötr trade, inanç değişmez

    matches_dominant = (trade_direction == dominant_direction)
    likelihood_informed = informed_accuracy if matches_dominant else (1 - informed_accuracy)
    likelihood_noise = 0.5

    numerator = prior * likelihood_informed
    denominator = numerator + (1 - prior) * likelihood_noise
    if denominator <= 0:
        return prior
    return numerator / denominator


# ---------------------------------------------------------------------------
# 2. OPTIONS DELTA CVD + INFLECTION TESPİTİ
# ---------------------------------------------------------------------------

def detect_inflection(cvd_history: List[float], lookback: int = 5) -> bool:
    """
    CVD eğiminin yön değiştirdiği anı tespit eder (eğim işareti
    değişimi — basitleştirilmiş 2. türev testi). lookback son N nokta
    üzerinden eğim hesaplanır.
    """
    if len(cvd_history) < lookback * 2:
        return False
    recent_slope = cvd_history[-1] - cvd_history[-lookback]
    prior_slope = cvd_history[-lookback] - cvd_history[-lookback * 2]
    return (recent_slope * prior_slope) < 0


# ---------------------------------------------------------------------------
# 3. DİNAMİK PERSENTİL — HARDCODE EŞİK YOK
# ---------------------------------------------------------------------------

def percentile_rank(value: float, history: List[float]) -> float:
    """value'nun history içindeki persentilini döner (0-100). Eşik yok,
    sadece dağılım — saturation_threshold_pct çağıran tarafta seçilir."""
    if not history:
        return 50.0
    below = sum(1 for h in history if h <= value)
    return 100 * below / len(history)


# ---------------------------------------------------------------------------
# 4. ANA FONKSİYON — gdive_server.py'den çağrılır
# ---------------------------------------------------------------------------

def compute_gamma_fatigue(
    oi_weighted_put_delta: float,
    put_delta_history: List[float],
    trade_flow_increment: float,
    cvd_history: List[float],
    prior_toxicity_belief: float = 0.5,
    saturation_threshold_pct: float = 85.0,
    inflection_lookback: int = 5,
    informed_accuracy: float = 0.65,
    max_history: int = 200,
) -> Dict:
    """Tek cron tick'i için Gamma Fatigue durumunu hesaplar."""

    # --- Koşul 1: doygunluk ---
    pct = percentile_rank(oi_weighted_put_delta, put_delta_history)
    saturated = pct >= saturation_threshold_pct

    # --- CVD güncelle + inflection ---
    last_cvd = cvd_history[-1] if cvd_history else 0.0
    new_cvd_history = (cvd_history + [last_cvd + trade_flow_increment])[-max_history:]
    inflected = detect_inflection(new_cvd_history, inflection_lookback)

    # --- Koşul 2: Bayesian toksisite inancı güncelle ---
    trade_direction = 0 if trade_flow_increment == 0 else (1 if trade_flow_increment > 0 else -1)
    new_belief = update_belief(
        prior_toxicity_belief, trade_direction,
        dominant_direction=1, informed_accuracy=informed_accuracy,
    )

    # --- İKİ KOŞUL BİRDEN (tek koşul bıçak yakalar) ---
    fatigue_signal = saturated and inflected

    new_put_delta_history = (put_delta_history + [oi_weighted_put_delta])[-max_history:]

    return {
        "fatigue_signal":   fatigue_signal,
        "saturation_pct":   round(pct, 1),
        "saturated":        saturated,
        "cvd_inflected":    inflected,
        "toxicity_belief":  round(new_belief, 3),
        "interpretation": (
            "DOYGUNLUK + DÖNÜŞ — dealer hedge yükü kritik, rejim değişebilir"
            if fatigue_signal else
            "Doygunluk var ama CVD dönmedi — henüz erken, izlemede kal"
            if saturated else
            "Doygunluk yok — normal rejim"
        ),
        "_new_put_delta_history": new_put_delta_history,
        "_new_cvd_history":       new_cvd_history,
        "_new_toxicity_belief":   new_belief,
    }


# ---------------------------------------------------------------------------
# 5. PIN-RISK HALT ENTEGRASYONU — TASLAK, kalibrasyon gerekir
# ---------------------------------------------------------------------------

def should_halt(pin_risk_result: Dict, gamma_fatigue_result: Dict) -> bool:
    """
    taleb_integration_patch.compute_pin_risk çıktısıyla bu modülün
    çıktısını birleştiren basit bir halt mantığı taslağı.
    Eşikler (7.5 / 5.0) compute_pin_risk'teki risk_level sınırlarıyla
    aynı — gerçek kalibrasyon canlı veri biriktikten sonra yapılmalı.
    """
    pin_score = pin_risk_result.get("pin_score", 0)
    if pin_score >= 7.5:
        return True
    if gamma_fatigue_result.get("fatigue_signal") and pin_score >= 5.0:
        return True
    return False
