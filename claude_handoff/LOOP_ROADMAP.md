# G-DIVE Loop Engineering Roadmap
# Kaynak: @phosphenq thread (21 Haz 2026) — "Loop Engineering"
# Bu dosya Binance API + order execution hazır olduğunda devreye alınacak.

---

## MEVCUT DURUM (Haziran 2026)

| Piece | Thread Tanımı | G-DIVE Karşılığı | Durum |
|-------|--------------|-----------------|-------|
| State | remember across runs | `claude_handoff/` dizini | ✅ Var |
| Automations | run on a schedule | GitHub Actions cron + PM2 | ✅ Var |
| Worktrees | isolate parallel agents | - | ❌ Yok |
| Skills | codify your intent | `RISK_POLICY.md`, `REGIME_POLICY.md` | 🔶 Kısmi |
| Connectors | touch your real tools | Supabase MCP | 🔶 Kısmi |
| Sub-agents | split maker from checker | - | ❌ Yok |

**En kritik eksik: Brakes (frenler).** Hiçbir sistemde step cap, budget ceiling veya circuit breaker yok.

---

## FAZ 0 — HEMEN YAPILABİLİR (Binance beklenmez)

### 0.1 Heartbeat + Dead-man Check
- `gdive_server.py` her cron çalışmasında `claude_handoff/STATUS.md`'ye timestamp yazar
- Format: `last_heartbeat`, `run_count`, `last_action`
- Amaç: loop sessizce ölmüşse sabah görünür olsun

### 0.2 Step Cap — gdive-options cron
- `/root/gdive-options/` cron'una max iteration sayacı ekle
- Paper kapital olsa bile alışkanlık olarak zorunlu
- Öneri: 3 consecutive hata → cron kendini durdurur, log yazar

### 0.3 STATUS.md Standardizasyonu
```
## Done
- [x] ...
## In Progress  
- [ ] ...
## Next
- [ ] ...
## Never (loop dokunamaz)
- infra/ değişiklikleri human approval olmadan
- live order gönderme (paper horizon bitene kadar)
```

---

## FAZ 1 — BİNANCE API GELINCE

### 1.1 Maker / Checker Ayrımı
- **Maker agent**: sinyal üretir, order draft eder
- **Checker agent**: farklı model (Haiku), sadece "geçer mi geçmez mi" der
- Checker'ın maker'ın kendi kodu hakkında karar vermesine izin yok
- Referans: thread section 7 "Sub-agents keep the maker away from the checker"

### 1.2 Brakes Paketi (order execution'dan önce zorunlu)
```
- step cap:       --max-turns 50
- budget ceiling: her session max $X token harcaması
- blast radius:   tek worktree, tek branch, read-only prod
- circuit breaker: aynı tool + aynı args 3x üst üste → dur
- dead-man check: her phase'de STATUS.md'ye heartbeat yaz
```
**Kural: Engine'i ship etmeden önce brake pedal'ı ship et.**

### 1.3 Worktree İzolasyonu
- Paralel agent çalışıyorsa her biri kendi branch'inde
- g-dive-gex + g-dive-alpha aynı dosyaya yazmamalı
- `git worktree add` — Claude Code pattern ile aynı

### 1.4 /goal Benzeri Stop Condition
- "Make it better" geçersiz stop condition
- "Sharpe > 1.5 AND max_drawdown < 10% AND 20+ trade" geçerli
- Her backtest run'ı bu contract'a göre değerlendirilir

---

## FAZ 2 — OLGUNLAŞINCA (20+ live trade sonrası)

### 2.1 Triage Automation
- Her sabah otomatik: overnight Supabase log oku, anomali bul, STATUS.md'ye yaz
- g-dive-gex sinyal kalitesi günlük otomatik raporlanır

### 2.2 Regime → Sleeve Gate Bağlantısı
- g-dive-gex'ten gamma_regime/Pyramid → gdive-options sleeve seçimi
- BULLISH → Long Call, BEARISH → Long Put, NEUTRAL → skip/spread
- Min 20 trade sample sonrası (şu an hardcode Long Call kalır)

### 2.3 Natenberg Risk Module Entegrasyonu
- Multi-leg stratejiye geçildiğinde devreye al
- `natenberg_risk.py` → `gdive_server.py` → `/api/risk-report`

---

## MALİYET GERÇEKLİĞİ (thread'den)

| Örnek | Maliyet | Sebep |
|-------|---------|-------|
| 259 PR / ay | Yönetilebilir | Tek engineer, capped loop |
| $47,000 / 11 gün | Felaket | Step cap yok, stop condition yok |
| ~$1.3M / ay | Sponsored | 100-agent fleet, OpenAI ödüyor |

**G-DIVE için hedef: $20-200/ay bütçeyle çalışan, küçük, capped, tek işe odaklı loop.**

---

## ÖNCE YAPILACAKLAR (bu dosyayı açtığında)

1. [ ] FAZ 0.1 — heartbeat yaz
2. [ ] FAZ 0.2 — gdive-options step cap
3. [ ] FAZ 0.3 — STATUS.md standardize et
4. [ ] Binance API → FAZ 1 başlat
