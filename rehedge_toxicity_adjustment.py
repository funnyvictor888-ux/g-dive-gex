"""
rehedge_toxicity_adjustment.py
G-DIVE Rehedge Band — Toxicity-Belief ile ASIMETRIK Bant Kaydirma
=============================================================================
MIT 18.S096/18.642 (Kempthorne/Strela) dersine bakinca: mevcut statik
compute_rehedge_band'in sqrt(gamma*transaction_cost) formulu zaten
surekli-zaman teorisinden geliyor (Whalley-Wilmott 1993 "no-transaction
band" asimptotigi). Bu formul band genisligini SIGMA (diffusion/varyans)
ile olceklendiriyor — yuksek volatilitede band GENISLER, cunku gurultulu
piyasada sik hedge etmek orantisiz transaction cost'a yol acar. Bu
teorik olarak doğru.

ILK DENEMEM HATALIYDI: toxicity_belief'i sigma'ya enjekte etmeye
calistim (adjusted_atm_iv = atm_iv * carpan). Test edince gordum ki bu
band'i belief yukseldikce DARALTMIYOR, GENISLETIYOR — cunku sigma'yi
yukseltmek formulun "yuksek varyans = genis band" mantigini tetikliyor.
Sorun: informed/toksik flow bir DRIFT (yonlu sapma) hipotezi, sigma ise
SIMETRIK varyansi temsil ediyor — ikisini sigma uzerinden karistirmak
kavramsal olarak hatali.

DOGRU YAKLASIM: band'i simetrik buyutup kucultmek degil, ASIMETRIK
KAYDIRMAK. gamma_fatigue.py'nin zaten takip ettigi dominant_direction
(varsayilan: bearish/put-alimi hipotezi) yonundeki esigi yakinlastir
(erken tepki), ters yondeki esigi uzaklastir (sabir — o yondeki hareket
muhtemelen noise/mean-reversion). Sigma-driven taban genislik
DEGISMIYOR, sadece ust/alt simetri bozuluyor.

    skew = skew_sensitivity * (toxicity_belief - 0.5) * 2   # -1..+1
    dominant_direction=1 (bearish hipotez):
        lower_pct = base_band * (1 - skew)   # belief yuksek -> daralir
        upper_pct = base_band * (1 + skew)   # belief yuksek -> genisler

ROLLOUT: rehedge_band.py'nin discrete lattice'i de saklaniyor —
observe-log'da static / sigma-adjusted(v1, hatali, KULLANMA) yerine
artik static / asymmetric-skew / backward-induction ucu yan yana.

Kullanim:
    from rehedge_toxicity_adjustment import compute_skewed_band
    result = compute_skewed_band(
        spot=spot, atm_iv=front_iv, net_gamma=net_gamma,
        toxicity_belief=gf_result["toxicity_belief"],
    )
"""

from taleb_integration_patch import compute_rehedge_band


def compute_skewed_band(
    spot: float,
    atm_iv: float,
    net_gamma: float,
    toxicity_belief: float = 0.5,
    dominant_direction: int = 1,   # gamma_fatigue.py ile ayni sabit konvansiyon
    transaction_cost: float = 0.0005,
    k: float = 1.75,
    vol_regime: str = "normal",
    skew_sensitivity: float = 0.5,
) -> dict:
    """
    Tabandaki sigma-driven genislik DEGISMIYOR (compute_rehedge_band
    aynen cagriliyor) — sadece toxicity_belief'e gore asimetrik kaydirma
    ekleniyor.
    """
    base = compute_rehedge_band(
        spot=spot, atm_iv=atm_iv, net_gamma=net_gamma,
        transaction_cost=transaction_cost, k=k, vol_regime=vol_regime,
    )
    band_pct = base["band_pct"] / 100  # decimal'e cevir

    skew = skew_sensitivity * (toxicity_belief - 0.5) * 2  # -1..+1
    if dominant_direction == 1:
        lower_pct = band_pct * (1 - skew)
        upper_pct = band_pct * (1 + skew)
    else:
        lower_pct = band_pct * (1 + skew)
        upper_pct = band_pct * (1 - skew)

    lower_pct = max(0.0005, lower_pct)
    upper_pct = max(0.0005, upper_pct)

    base["lower_band"] = round(spot * (1 - lower_pct), 0)
    base["upper_band"] = round(spot * (1 + upper_pct), 0)
    base["lower_band_pct"] = round(lower_pct * 100, 3)
    base["upper_band_pct"] = round(upper_pct * 100, 3)
    base["toxicity_belief"] = round(toxicity_belief, 3)
    base["dominant_direction"] = dominant_direction
    base["skew_applied"] = round(skew, 3)
    return base


if __name__ == "__main__":
    for belief in [0.2, 0.5, 0.8]:
        r = compute_skewed_band(
            spot=65784, atm_iv=45.0, net_gamma=0.05, toxicity_belief=belief,
        )
        print(
            f"belief={belief} -> base_band={r['band_pct']}%  "
            f"lower={r['lower_band_pct']}%  upper={r['upper_band_pct']}%  "
            f"skew={r['skew_applied']}"
        )
