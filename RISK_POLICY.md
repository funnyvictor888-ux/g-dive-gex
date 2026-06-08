# G-DIVE Risk Policy

Sistem değişiklik prensipleri. Yeni modül eklemek, parametre değiştirmek
veya filter kaldırmak/eklemek isteyen herkesin (gelecekteki Kai dahil)
önce bu dökümana bakması beklenir.

Bu doküman Hetzner alpha_v3 sisteminin RISK_BRAIN_POLICY'sinden uyarlandı
ve g-dive-gex'in bağlamına özelleştirildi.

## Çekirdek prensip

**Yeni modül core alpha'yı bastırmamalıdır.**

Filtre eklemek, parametre sıkmak, yeni veto katmanı koymak — bunların
hepsi *gerçek bir kazanç sinyalini engelleme* riski taşır. Defensive
gözükür ama sistemi geri zekalı yapar.

## Modül kabul kriterleri

Bir modül (filtre, overlay, gate, sinyal kaynağı) **canlıya** alınabilir
ANCAK aşağıdaki 5 maddenin **hepsi** karşılanırsa:

### 1. Sharpe daha kötü olmamalı
Modül eklenmeden önceki Sharpe oranı, modül eklendikten sonra **aynı veya
daha iyi** olmalı. Statistical significance için minimum 20 trade veya
3 aylık veri penceresi.

### 2. MaxDD iyileşmeli veya değişmemeli
Drawdown büyürse, modül *risk yöneten* değil *risk yaratan* bir şey
yapıyor demek. Geri çek.

### 3. Trend yakalama korunmalı
Modül, sistemin en güçlü trade'lerini de filtrelememeli. Örneğin
"GEX < 0 olunca SHORT açma" gibi bir kural eklersek, **gerçek SHORT
fırsatlarının %X'ini kaçırıp kaçırmadığımızı** ölçmek zorundayız.

### 4. Core sinyal sistematik bastırılmamalı
Modül, belirli bir rejimde **tüm** trade'leri engelliyorsa
(örn: BULLISH_HIGH_VOL'de hiç SHORT açılamıyor), bu **görünmez bir
veto** demek. Şeffaf değil — geri çek.

### 5. En az bir rejimde pozitif katkı olmalı
Modülün katma değeri *en az bir piyasa rejiminde* sayısal olarak
ispatlanabilir olmalı. "Olabilir" yetmiyor. "Şu trade'i engelleseydi
şu kadar para kazanırdık" diye somut.

## Kararsızlık kuralı

**Eğer 5 kriterden herhangi biri belirsizse: SHADOW MODE'da kal.**

Shadow mode = modül çalışır, hesap yapar, log alır, ama **karar vermez**.
Trader'ın gerçek sinyalini etkilemez. Sadece bir paralel günlüğe
"benim olsa şunu derdim" yazar. 2-4 hafta sonra A/B karşılaştırılır.

## Sample size disiplini

Hiçbir karar **15 trade altında** verilemez. Hiçbir parametre
değişikliği **2 hafta altı** verisiyle yapılamaz.

Backtest sonuçları "ipucu" sayılır, "kanıt" değil. Live trade verisi
ise "kanıt" sayılır.

## Cherry-picking / overfitting uyarısı

Backtest'i tekrar tekrar çalıştırıp parametreleri "daha iyi sonuç gelene
kadar" deneme **yasak**. Bu **data dredging**.

Bir backtest sonucu çıkar — gece düşünülür — ertesi gün karar verilir.
Aksi takdirde her parametre kombinasyonu için 1/20 ihtimalle yanlış
pozitif çıkar, sen 20 deneme yaparsan kesin "çalışan" bir parametre
bulursun ama gerçekte çalışmaz.

## Mevcut sistem baseline (2026-06-08)

- 9 closed trade, +$87 paper P&L
- 1 açık SHORT trade #441813 (~+$190 unrealized, partial TP zaten)
- Pyramid backend port deployed (cb8054c)
- Flip-zone v1 deployed (aa73b6f)
- Deribit 4H aggregate fallback (dbb8058)
- Realistic PnL with fee+funding+slippage (338cdc5)
- Backtest (180 gün saf teknik): C4 +%40 CAGR, %20 DD, Sharpe 0.58

**Sample yetersiz.** Gerçek backtest 3-4 hafta sonra, ~20+ trade
biriktiğinde yapılacak.

## Filtre değiştirme/ekleme prosedürü

Bir filtre değiştirmek istiyorsak (örn: GEX>0 kuralını kaldır):

1. **Önce shadow logger ekle** — yeni mantığı paralel olarak log'la
2. **2-4 hafta paralel çalıştır** — hem mevcut hem yeni karar mantığını yan yana izle
3. **A/B karşılaştır** — yukarıdaki 5 kriterle değerlendir
4. **Belge yaz** — bu RISK_POLICY.md'ye karar gerekçesini ekle
5. **Sonra promote et** — yeni mantığı production'a al

## Anti-patterns — bunları yapma

- ❌ "Bu mantıklı görünüyor, ekleyelim" — sezgisel ekleme
- ❌ "Backtest 5 kez denedim, en iyi sonuç bu parametre" — overfit
- ❌ "Sadece son hafta kötü gidiyor, parametre değiştirelim" — recency bias
- ❌ "X stratejisi şu anda %50 CAGR yapıyor, geçiş yap" — sample size yetersiz
- ❌ "Bu filtre fırsat kaçırıyor, kaldıralım" — kanıtsız iddia
- ❌ "Şu modül sistemi defensive yapıyor" — kanıtsız (önce ölç)

## Acil durum istisnası

Yalnızca **gerçek bir bug** veya **veri kaynağı failure** acil müdahaleyi
haklı kılar. Örnekler:
- Trader fallback moduna düşmüş ve yanlış sinyaller üretiyor (Deribit fix
  geçmişinde olduğu gibi)
- Snapshot hatalı veri yazıyor (örn: NULL pyramid_total)
- Auth/API failure'lar sistemi durdurmuş

Bu durumlar 5-kriter testinden muaftır. Sistem **kırık**, "iyileştirme"
değil "tamir" yapıyoruz.

## Değişiklik kaydı

Bu döküman değiştirilirse, **neden değiştirildiği** burada belgelenmeli.

- 2026-06-08: İlk versiyon (Hetzner RISK_BRAIN_POLICY'sinden uyarlandı)
