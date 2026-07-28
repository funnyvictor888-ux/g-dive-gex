# YENI_SISTEM.md — G-DIVE kurulum & değişiklik checklist'i

> Amaç: acele değil. Bu satırlar kafada tutulup her seferinde yeniden
> hatırlanan guard'lar. Her biri gerçek bir hatanın bedeliyle yazıldı.
> Yeni sistem kurarken VE mevcut sisteme değişiklik yaparken çalıştır.

## 1. Supabase / güvenlik (10 saatlik kesinti dersi)
- [ ] Bu proje hangi senaryo? **gdive (BTC)** = A (RLS + REVOKE anon).
      **gdive-spx** = B (anon SELECT açık, iki dashboard okuyor).
      → SPX'te ASLA A bloğunu çalıştırma, iki paneli de öldürür.
- [ ] RLS / güvenlik değişikliğinden ÖNCE: `/root/g-dive-gex/preflight.sh` çalıştır.
      → **GECTI** görmeden RLS/güvenlik işine DOKUNMA. RED verirse ✗ satırını düzelt.
      preflight her wrapper'ın SUPABASE_KEY'ini JWT-decode edip role=service_role doğrular.
      (Neden araç: `eyJ` prefix'i YETMEZ — eski-stil anon key de eyJ ile başlar; ayrım
      JWT içindeki role claim'inde. Manuel grep bunu ayırt edemez, 25 Haz'ı o kaçırdı.)
- [ ] Yeni sistem eklerken: wrapper'ı preflight'ın WRAPPERS listesine ekle (önekli key adı
      da olur, grep `[A-Za-z_]*SUPABASE_KEY=` yakalar).
- [ ] Anon key public'e çıktıysa (deploy/public repo) → Settings→API rotate.

## 2. Logger / veri (gex_z tautoloji dersi)
- [ ] Forward-accumulation logger'da `unique(date, symbol, type)` constraint VAR MI?
      → Non-overlapping gözlem baştan gömülü olmalı. Overlapping window = sahte istatistik güç.
- [ ] Tick-level (5min) ile bar-level (4H) veriyi KARIŞTIRMA — sahte korelasyon.

## 3. Yeni sinyal (5-gate + observe-only)
- [ ] Yeni aday sinyal → önce **observe-only**, trader'a dokunma.
- [ ] Trade gate'e bağlamadan önce **min 20-30 non-overlapping sample**.
- [ ] Bağımsızlık testi: contemporaneous corr yüksekse (gex_z +0.82) = fiyat gölgesi, predictor değil.
- [ ] "Temiz ama işe yaramaz" (VPIN: bağımsız +0.05 ama predictive değil) de eleme sebebi.
- [ ] BTC/Deribit ise: klasik dealer-sign (call+, put−) covered-call yapısında ŞÜPHELİ.
      SPX gamma/vanna formülünü BTC'ye DÜZ KOPYALAMA — sign bozulur.

## 4. Backtest (30 Haziran direktifi)
- [ ] Her zaman position count print et.
- [ ] Değişken tanımlarını canlı sistemin tanımıyla doğrula.
- [ ] Mark-to-market kullan, flat-bar skipping DEĞİL.
- [ ] Ara değişkenleri göster.
- [ ] Sonuç "too good" / "too strange" → SUN'ma, DUR, artefakt ara.
- [ ] Backtest'i canlı kanıt olarak sunma.

## 5. Repo / versiyon
- [ ] `git init` + `.gitignore` doğrula: `.env`, `*.bak*`, `*.log`, JWT'li wrapper hariç.
- [ ] Commit'ten ÖNCE: gerçek service_role JWT staging'de mi? (`git status` + kontrol) → sızmasın.

## 6. Chat / scope
- [ ] Her sistem = ayrı Claude chat, cross-topic drift yok.
- [ ] whoami / CHAT_KIMLIK.md ile onboarding.
- [ ] Yanlış chat'te konu açılırsa → doğru chat'e yönlendir, orada devam etme.

---
*Bu checklist bir "bilgi" değil bir "kontrol" — atlanabilen not değil, geçilmesi gereken satır.*
