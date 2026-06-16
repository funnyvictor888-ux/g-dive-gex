"""
rehedge_band.py
G-DIVE Rehedge Band — Backward Induction Optimal-Stopping Modeli
===================================================================
MIT 14.12 (Ian Ball, Lecture 8: Backward Induction) çerçevesi: dealer'ın
"şimdi hedge et mi, bekle mi" kararı sonlu ufuklu bir optimal durma
(optimal stopping) problemi. Mevcut compute_rehedge_band
(taleb_integration_patch.py) Whalley-Wilmott tipi kapalı-form sqrt
formülü kullanıyor — sabit, veriden bağımsız bir yaklaşım. Burada onun
yerine gerçek bir N-adımlı backward induction çözüyoruz, çünkü bu
şekilde band'i gamma_fatigue.py'nin toxicity_belief çıktısıyla dinamik
besleyebiliyoruz: inanç yüksekse (informed/toksik flow olasılığı
yüksek), beklenen ters hareket büyür → optimal band daralır (erken
hedge); inanç düşükse (flow noise gibi), band genişler (seyrek hedge,
düşük transaction cost).

Bu modül RISK_POLICY.md'deki "rehedge_band parked — dealer-hedge
observable proxy gerekiyor" notunun karşılığı: proxy =
gamma_fatigue.compute_gamma_fatigue()'nin toxicity_belief çıktısı.
Sıra önemli — önce gamma_fatigue, sonra bu modül.

Model:
  Durum: d = son hedge noktasından spot'un uzaklığı (fiyat yüzdesi,
         0..d_max arası bir grid üzerinde)
  Karar: HEDGE (transaction_cost öde, d sıfırlanır) veya BEKLE
         (risk_cost(d) öde, d bir adım stokastik hareket eder —
         yön olasılığı toxicity_belief'e göre çarpık)
  Terminal: V_T(d) = risk_cost(d)  [ufuk sonunda hâlâ açık pozisyon cezası]
  Backward: V_t(d) = min( hedge_cost + V_{t+1}(0),
                           risk_cost(d) + E[V_{t+1}(d')] )
  Çözüm: her t için bir eşik d*_t — d bunu geçerse HEDGE optimal.
  d küçükten büyüğe tarandığında hedge_value (d'den bağımsız, sabit)
  continuation'ı (d'de monoton artan) ilk geçtiği nokta = eşik.

ROLLOUT DİSİPLİNİ: Bunu canlı trade mantığına direkt sokmadan önce,
Taleb Shadow modülünde yapıldığı gibi observe-only logla — bu modülün
ürettiği band_pct'i mevcut statik compute_rehedge_band'in band_pct'iyle
yan yana kaydet, gerçek hedge maliyeti/PnL'e etkisini gör, sonra
kalibre et. gamma_cost_scalar=2000 varsayılanı, statik modelin
band aralığıyla (%0.1-%5) örtüşecek şekilde elle ayarlandı — gerçek bir
kalibrasyon DEĞİL, sadece çalışır bir başlangıç noktası. drift_sensitivity
da aynı şekilde kaba varsayılan. İkisi de canlı veriyle yeniden
kalibre edilmeli.

Kullanım:
    from rehedge_band import solve_rehedge_band

    result = solve_rehedge_band(
        sigma=atm_iv / 100,
        gamma=net_gamma,
        toxicity_belief=gamma_fatigue_result["toxicity_belief"],
        transaction_cost=0.0005,
    )
    # result["band_pct"] -> şu an için optimal eşik (yüzde)
"""

from typing import Dict, List


def risk_cost(d: float, gamma_cost_coef: float) -> float:
    """Hedge edilmemiş pozisyonun gamma riski — d'nin karesiyle büyür
    (standart market-making envanter riski varsayımı)."""
    return gamma_cost_coef * d ** 2


def solve_rehedge_band(
    sigma: float,
    gamma: float,
    toxicity_belief: float = 0.5,
    transaction_cost: float = 0.0005,
    n_steps: int = 6,
    d_max: float = 0.03,
    n_grid: int = 31,
    drift_sensitivity: float = 0.6,
    gamma_cost_scalar: float = 2000.0,
) -> Dict:
    """
    N-adımlı backward induction ile optimal rehedge eşiklerini çözer.
    Dönen thresholds_by_step_pct[0] = şu an (t=0) için eşik.
    """
    gamma_cost_coef = abs(gamma) * gamma_cost_scalar * max(sigma, 1e-6)
    step_size = d_max / (n_grid - 1)
    grid = [i * step_size for i in range(n_grid)]

    # toxicity_belief yüksekse d'nin büyümeye devam etme olasılığı artar
    p_up = min(0.95, max(0.05, 0.5 + (toxicity_belief - 0.5) * drift_sensitivity))
    hedge_cost = transaction_cost

    V = [risk_cost(d, gamma_cost_coef) for d in grid]  # terminal değer
    thresholds_reversed: List[float] = []

    for _t in range(n_steps - 1, -1, -1):
        V_next = V
        new_V = []
        threshold = None
        for i, d in enumerate(grid):
            up_idx = min(i + 1, n_grid - 1)
            down_idx = max(i - 1, 0)
            continuation = risk_cost(d, gamma_cost_coef) + (
                p_up * V_next[up_idx] + (1 - p_up) * V_next[down_idx]
            )
            hedge_value = hedge_cost + V_next[0]

            new_V.append(min(continuation, hedge_value))
            if threshold is None and hedge_value <= continuation:
                threshold = d
        V = new_V
        thresholds_reversed.append(threshold if threshold is not None else d_max)

    thresholds = list(reversed(thresholds_reversed))  # t=0 .. t=n_steps-1

    return {
        "band_pct": round(thresholds[0] * 100, 3),
        "thresholds_by_step_pct": [round(t * 100, 3) for t in thresholds],
        "p_up_used": round(p_up, 3),
        "toxicity_belief": round(toxicity_belief, 3),
        "n_steps": n_steps,
        "interpretation": (
            "Dar bant — toksik flow inancı yüksek, erken hedge önerilir"
            if toxicity_belief > 0.65 else
            "Geniş bant — flow noise gibi görünüyor, seyrek hedge yeterli"
            if toxicity_belief < 0.35 else
            "Normal bant"
        ),
    }


def compare_with_static(
    backward_induction_result: Dict,
    static_band_result: Dict,
) -> Dict:
    """
    Observe-only karşılaştırma yardımcı fonksiyonu. İki modelin
    band_pct'ini yan yana koyar — taleb_observe_log.jsonl tarzı bir
    log satırı üretmek için.
    """
    bi_pct = backward_induction_result["band_pct"]
    static_pct = static_band_result["band_pct"]
    return {
        "backward_induction_band_pct": bi_pct,
        "static_band_pct": static_pct,
        "diff_pct": round(bi_pct - static_pct, 3),
        "toxicity_belief": backward_induction_result["toxicity_belief"],
    }
