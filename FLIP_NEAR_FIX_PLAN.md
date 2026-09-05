# flip_near Fix Planı — LONG-live Tetiğine Bağlı

**Durum:** HAZIR, deploy edilmedi. RISK_POLICY 5-gate PASS sonrası, LONG-live tetiği paketinde (momentum filter + alert layer + bu fix birlikte).

**Hazırlık tarihi:** 5 Eylül 2026  
**Beklenen deploy tarihi:** Sample eşiği n≥20 + Grup A/B stabil + filter 5-gate PASS

---

## Sorun (18 Jul'den beri, 5 Eylül canlı doğrulama)

`gdive_trader.py` line 747:
```python
flip_near = flip_info.get("flip_near", False) or abs(price-hvl)/price*100 < 0.5
```

**İki OR koşulu da bug'lı:**
1. `flip_info.get("flip_near")` — MenthorQ state'inden geliyor, `build_menthorq_state()` `gex_by_strike` HİÇ dönmüyor → hvl fallback devrede → hvl=spota en yakın pozitif node → **spot>hvl otomatik True** → flip_near=True her tick
2. `abs(price-hvl)/price<0.5%` — hvl fallback yüzünden bu koşul da hep True

**Sonuç:** bull_tech=True + momentum bull + long_ok=True olsa bile trader line 937 return yapıyor. LONG imkansız (Haz 30'dan beri sıfır canlı LONG).

**Canlı kanıt (5 Eyl):** spot=$79,766, gerçek flip=$68,341, dist=%14.32. Ama trader "Flip yakın — bekle" diyor.

---

## Fix — line 747 değişiklik

```python
# ÖNCESİ (bug'lı):
flip_near = flip_info.get("flip_near", False) or abs(price-hvl)/price*100 < 0.5

# SONRASI (real-flip'e bağlı, güvenli fallback ile):
gamma_analysis = d.get("gamma_analysis") if isinstance(d.get("gamma_analysis"), dict) else {}
long_ok_real = gamma_analysis.get("long_ok_real")
in_positive_real = gamma_analysis.get("in_positive_real")

if long_ok_real is not None and in_positive_real is not None:
    # Gerçek flip mantığı: LONG uygunsa flip_near=False
    flip_near = not (long_ok_real and in_positive_real)
else:
    # Fallback: eski mantık (gamma_analysis yoksa, ör. eski snapshot)
    flip_near = flip_info.get("flip_near", False) or abs(price-hvl)/price*100 < 0.5
```

---

## Deploy Prosedürü (LONG-live günü)

**Ön koşullar:**
- [x] Sample n ≥ 20 kapalı ghost
- [x] Grup A/B momentum ★★ n=20'de stabil
- [x] Momentum filter kanıtı: filtreli WR baseline'dan +%10 üstü
- [x] RISK_POLICY 5-gate — 5/5 PASS

**Sıra (aynı gün, 3 iş birlikte):**

### 1. Momentum filter (long_edge_shadow.py)
```python
# open_ghost() içinde ekle:
if momentum_score < 1.5:
    return None  # filter, ghost açma
```

### 2. flip_near fix (gdive_trader.py line 747)
Yukarıdaki fix uygulanır.

### 3. Alert layer (Gmail SMTP + msmtp)
- `apt install msmtp msmtp-mta`
- `~/.msmtprc` config
- `heartbeat_check.sh` cron `*/10 * * * *`
- Snapshot >15dk stale → mail
- cron.log 401 spam → mail
- DD > %10 → mail uyarı
- DD > %20 → MANUAL_HALT otomatik + mail

**Deploy komutları:**
```bash
# Fix'ler
cd ~/gdive-dashboard/
# ... değişiklikleri yap
git add gdive_trader.py long_edge_shadow.py
git commit -m "feat: LONG-live enablement — flip_near real-flip + momentum filter"
git push origin main

# Hetzner'a
scp gdive_trader.py long_edge_shadow.py root@178.105.37.173:/root/g-dive-gex/

# Test
ssh root@178.105.37.173 "/root/g-dive-gex/run_c4_cron.sh"
ssh root@178.105.37.173 "/root/g-dive-gex/run_edge_shadow_cron.sh"

# Alert layer
scp heartbeat_check.sh root@178.105.37.173:/root/g-dive-gex/
ssh root@178.105.37.173 "chmod +x /root/g-dive-gex/heartbeat_check.sh"
# Cron entry ekle: */10 * * * * /root/g-dive-gex/heartbeat_check.sh
```

**24 saat izleme:**
- İlk LONG açılışı → gerçek para
- Trader cron.log her saat kontrol
- Ghost cadence artışı (yeni LONG'lar açılmalı)
- Alert layer test — kasıtlı stale simulate et, mail geliyor mu

---

## Rollback

Sorun çıkarsa:
```bash
git revert HEAD  # commit'i geri al
git push origin main
scp gdive_trader.py long_edge_shadow.py root@178.105.37.173:/root/g-dive-gex/
```

Fallback zaten güvenli: gamma_analysis yoksa eski davranışa döner, çift emniyet.

---

## Yan etkiler

**flip_shadow eski sistem ölecek:** Line 924 `if flip_near:` bloğu artık ateşlenmiyor. Bu **istenen** — edge_shadow (yeni sistem, long_ok_real mantığı) canlı trader ile senkron olur. flip_shadow ghost'ları arşiv kalır, yeni açılış olmaz.

**SHORT etkilenmez:** Line 937 sadece LONG'u bloke ediyor. SHORT karar akışı ayrı (long_signal/short_signal ayrı hesaplar).

**Canlı trader ve ghost aynı sinyali görür:** Edge_shadow'un öğrendiği filtre (momentum ≥ 1.5) canlı trader'a da uygulanır. Ghost = trader shadow (tam anlamıyla).
