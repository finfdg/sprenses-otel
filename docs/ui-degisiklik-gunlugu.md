# UI Değişiklik Günlüğü (Tasarımcı Denetim Tarihçesi)

Bu dosya, tasarım sistemi denetimlerinin **tarihsel kaydıdır** — hangi tarihte hangi sapmalar bulundu ve nasıl kapatıldı. **Yaşayan kurallar burada DEĞİLDİR:**

- Uyulması zorunlu UI kuralları + kanonik iskelet + "10-Boyut" standardı → kök [`CLAUDE.md`](../CLAUDE.md) **"UI Tasarım Kuralları"** bölümü
- Detaylı bileşen API'leri + spec → [`ui-kurallari.md`](ui-kurallari.md)
- Modülerlik refactor kayıtları → [`modulerlik-iyilestirmeleri.md`](modulerlik-iyilestirmeleri.md)

Kayıtlar en yeniden eskiye sıralıdır. Yeni bir denetim turunda buraya tarihli madde eklenir; sapma kapatılınca "kapatıldı" olarak işaretlenir. Yaşayan "Tek-standart kuralları" tablosuna yeni madde **eklenmez** — yeni sapma burada izlenir.

---

## 2026-06-20 — Sistem Geneli Tutarsızlık Envanteri

54 sayfa tasarımcı gözüyle tek tek denetlendi (ortalama ~8.2/10; sistem güçlü, kritik P0 yok). 2026-06-19
turu büyük sapmaları kapatmış (native confirm, blue/cyan focus, bg-teal-600 buton, sessiz catch — paylaşılan
katmanda **yok**). Kalan sapmalar **tekrar eden 6 sistem-geneli temada** yoğunlaşıyordu:

1. **StatCard çatallaşması** (en görünür) — bespoke özet kartı kullananlar: `dashboard/+page.svelte` (10 kart + inline SVG — sistemin yüzü, en öncelikli), `finans/nakit-akim` (CashFlowSummaryCards + inline SVG), `finans/krediler` (renk-tint), `finans/butce` (drill-down), `satis/oda-tipleri` (3 kart), `satis/otel-rezervasyon` + `yonetim/panel` (YoY/karşılaştırma rozeti gerekçeli → **StatCard'a `delta`/`deltaLabel` prop'u eklenmeli**), `sistem/sunucu` (StatCard import edilip kullanılmıyor — ölü import).
2. **Segment/Tab primitive'i YOK** — 8+ sayfa kendi tab/chip stilini elle yazıyor (cariler, satis-faturalari, cekler, doviz, talimatlar, fis-icmali, mizan, devam-takip): **5+ farklı görsel dil**. → **Paylaşılan `SegmentedControl`/`Tabs` bileşeni eklenmeli** (eksik primitive).
3. **Inline aksiyon butonu (Button.svelte değil)** — onay-akisi, kalite/formlar, kalite/formlar/[id], `ScheduledModule` onay modalları (emerald/amber AA-sınırı), krediler "Yeniden Aç/Kapat", bankalar/talimatlar PDF modalı (`bg-blue-600` AA-fail), messaging modalları, ConfirmDialog/EmptyState iç butonları. → Button'a taşı (AA + touch-target tek kaynaktan).
4. **`touch-target` ham butonlarda yaygın değil** — `Button` otomatik alıyor ama Button kullanmayan ham satır-aksiyonları (<44px): devam-takip, vardiyalar, mizan, oda-tipleri, otel-rezervasyon satır aksiyonları + paylaşılan `ConfirmDialog`/`EmptyState` CTA/`Pagination` okları/`FileDropzone`/`MessageInput`/Topbar mini-aksiyonlar. → paylaşılan bileşenlere `touch-target` ekle (istisnasız 44px).
5. **Inline SVG / emoji kalıntısı** — dashboard (6), onay-akisi (6), nakit-akim özet (5), krediler (5), cekler (4), audit-loglar (1), Sidebar/Topbar (tamamı inline SVG), NotificationBell (🏦🔔), devam-takip (✅⏱️⏳⚠️), mesajlaşma (😊). → Lucide'a çevir.
6. **İkincil çatallaşmalar:** Form hata deseni (`Field`+`fieldErrors` yalnız avanslar/kullanicilar/oda-tipleri; ScheduledModule+devam-takip+vardiyalar tek `formError`) · loading (doviz/fis-icmali/mizan-modal/stok-maliyet/yonetim/sunucu spinner-metin, diğerleri Skeleton) · modal (audit-loglar bespoke overlay + messaging modalları `Modal.svelte` kullanmıyor) · inline pagination (doviz, bankalar iç-panel) · kalan `text-gray-400` gövde metni (satis-faturalari, fis-icmali/mizan modal, vardiyalar, devam-takip, login placeholder-gray-300).

**Önerilen yeni paylaşılan primitive'ler (modüller-arası tutarlılığı kökten artırır):** (a) `SegmentedControl`/`Tabs`
(8+ sayfadaki elle tab/chip'i birleştirir), (b) `StatCard`'a `delta`/`deltaLabel` prop'u (otel-rezervasyon + yonetim
KPI panolarını StatCard'a taşır, YoY dilini birleştirir). Bu ikisi yapılınca 1. ve 2. tema büyük ölçüde kapanır.

**Kapatma (2026-06-20 — backlog uygulandı):** Yukarıdaki 6 tema büyük ölçüde kapatıldı (svelte-check 0 hata, vitest 274 ✓, build ✓, canlıya alındı).

- **Yeni primitive'ler:** `SegmentedControl.svelte` (options/value/onchange/count/icon, aktif=teal-700, touch-target, ARIA tablist) — cariler/cekler/satis-faturalari/doviz/talimatlar/fis-icmali/mizan/devam-takip elle tab/chip'leri buna taşındı. `StatCard`'a `delta`/`deltaText`/`deltaLabel`/`deltaInvert` (YoY rozeti) + `href` (tıklanabilir kart) + `class` (layout) prop'ları eklendi.
- **StatCard benimseme:** dashboard/+page (10 kart), CashFlowSummaryCards, krediler, oda-tipleri, sunucu, otel-rezervasyon (7 KPI, delta ile) StatCard'a taşındı. **Bilinçli istisna kalan:** butce departman kartları (çok-metrikli drill-down), krediler tip kartları tinted→StatCard yapıldı; yonetim/panel zaten StatCard (backend YoY verisi yok → delta eklenmedi).
- **Paylaşılan touch-target:** `Button`/`ConfirmDialog`/`EmptyState`/`Pagination`/`FileDropzone` + `SegmentedControl` iç butonlarına gömüldü → 44px artık istisnasız (Button kullanmayan satır-aksiyonları da devam-takip/vardiyalar/mizan/oda-tipleri/otel-rezervasyon'da `touch-target` aldı).
- **Inline buton→Button:** onay-akisi, kalite/formlar(+[id]), ScheduledModule onay modalları, krediler, talimatlar PDF modalı, PaymentInstructions, butce/cariler modalları.
- **Inline SVG/emoji→Lucide:** dashboard, onay-akisi, cekler, krediler, nakit-akim, CashFlowSummaryCards, Sidebar/Topbar (krom), NotificationBell, devam-takip (✅⏱️⏳→Lucide), otel-rezervasyon, oda-tipleri. (Sidebar'ın `navigation.ts`-güdümlü ikonları + login bespoke form ikonları bilinçli inline kaldı.)
- **İkincil:** ConfirmDialog/Modal benimseme (audit-loglar bespoke→Modal, onay-akisi→ConfirmDialog); inline pagination→Pagination (doviz, bankalar); loading→TableSkeleton (doviz/fis-icmali/mizan/stok-maliyet/yonetim/sunucu); `Field`+`fieldErrors` (ScheduledModule/devam-takip/vardiyalar); gray-400→500 + login placeholder + login buton AA; kalite/sablonlar logo `accept`'inden SVG çıkarıldı (güvenlik).
- **Açık kalan (veri/küçük):** kalite/formlar durum StatCard'ları (backend durum-sayım endpoint'i yok); yonetim/panel YoY (backend verisi yok); birkaç dekoratif `—`/`·` placeholder gray-400 (bilinçli).

---

## 2026-06-19 — Denetim sonrası kapatma

**`Button.svelte`'e `touch-target` gömüldü** → tüm Button-tabanlı satır-aksiyonları dokunmatik cihazlarda (pointer:coarse) otomatik 44×44px (masaüstü yoğunluğu etkilenmez; `@media (pointer: coarse)`). Bu tek değişiklik 49 sayfanın aksiyonlarını mobil-uyumlu yaptı. **cariler** gerçek mobil aksiyonları (IBAN varsayılan-yıldız/sil, vade kaydet/iptal) `touch-target`'e alındı + `gray-300→400` (AA). **Elle bg-teal/bg-rose butonlar → Button.svelte** (krediler detay+modal, otel-rezervasyon, cariler IBAN/upload/dept, onay modal) + buton-içi `animate-spin` → `<Button loading>`. **Elle spinner → Loader2/Skeleton** (doviz, kalite/sablonlar). **cariler 23 inline `<svg>` → Lucide** (dosyada 0 inline SVG kaldı). **cariler özet kartları → StatCard**. **stok/urunler·depolar·hareketler'e `sm:hidden` mobil kart** eklendi. **Gerçek gövde-metni `gray-400→500`** (mizan/krediler/cariler/devam-takip; em-dash placeholder + dekoratif ikon korundu). **Bilinçli atlanan StatCard dönüşümleri (sapma DEĞİL):** otel-rezervasyon KPI (YoY karşılaştırma rozeti — StatCard tek-değer modeline sığmaz), butce (tıklanabilir drill-down + çok-metrikli + progress-bar), krediler (tip-bazlı renk-kodlu tinted kart). Doğrulama: `svelte-check` 0 hata, `npm run build` ✓, 274 vitest ✓.

---

## 2026-06-18 — Form-kontrol primitive geçişi

160+ elle `<input>/<select>/<textarea>` (aynı `border rounded-lg … focus:ring-teal-500` dizisini kopyalayan) **4 yeni primitive'e** taşındı — `Input.svelte` (metin/tarih/sayı/arama), `Select.svelte`, `Textarea.svelte`, `Field.svelte` (label+`*`+hata+ARIA sarmalayıcı). Stil/odak-halkası/hata-kenarlığı artık **tek kaynak**. 43 dosya, ~126 kontrol örneği (76 Input + 33 Select + 8 Textarea + 9 Field). Primitive'ler `svelte/elements` (`HTMLInputAttributes`/`HTMLSelectAttributes`/`HTMLTextareaAttributes`) ile tiplenir → `onkeydown`/`onchange` olay parametreleri otomatik tipli (`(e)=>` implicit-any vermez; bu sınıf hatası geçiş sırasında butce/PaymentInstructions'ta yakalanıp primitive tarafında kökten çözüldü). "Soft" desen (bg-gray-50 + ring-teal-100; moduller/roller/mesajlaşma) ve sapkın odak-halkaları (red/amber/cyan/teal-100) standarda (border-gray-300 + ring-teal-500) **normalize edildi**. Doğrulama: `svelte-check` 0 hata, `npm run build` ✓, 274 vitest ✓. Detay: [`ui-kurallari.md`](ui-kurallari.md) (Form Field Pattern + primitive tablosu). **Bilinçli istisna (primitive'e alınmadı):** Login sayfası (`/+page.svelte`) bespoke auth tasarımı (px-4 py-3.5 rounded-xl, bg-gray-50→white, custom ikon+göster/gizle); `MessageInput.svelte` sohbet bestecisi (autogrow textarea + özel davranış); checkbox/radio/file (primitive yok); para → `MoneyInput`, dosya → `FileDropzone`.

---

## 2026-06-17 — Mobil/tasarım geçişi sapma kapatma

emoji-as-icon → Lucide [cariler ödeme-yöntemi rozetleri 🏦💳💵📄📜 → Landmark/CreditCard/Banknote/FileText/Scroll; mizan lejant 📖 → "defter ikonu" (BookOpen zaten satır-aksiyonunda); otel-rezervasyon 👥 → Users]; mizan + fiş-icmali yükleme/lejant metinleri `text-gray-400` → `text-gray-500` (AA). **Denetim düzeltmesi:** önceki mobil denetimin "15 sayfa kart görünümü yok" bulgusu büyük ölçüde **yanlış pozitifti** — cekler/cariler/butce/audit-loglar/onay-akisi/otel-rezervasyon **zaten `sm:hidden` kart bloğuna sahip** (grep `overflow-x-auto`'yu görüp komşu kart bloğunu kaçırmış). **krediler de gerçek kart eksiği DEĞİL** (ikinci doğrulama): ana listesi zaten kart-tabanlı + responsive (başlıkta `hidden sm:inline` ile ikincil bilgi mobilde gizli), tek tablosu açılan **KMH/taksit çizelgesi** (8 sütun yoğun matris → yatay-scroll doğru kalıp, mizan/fiş-icmali gibi). Sonuç: **hiçbir liste sayfasında kart-görünümü rewrite gerekmiyor**. **Yapıldı (2026-06-17):** krediler 5 aksiyon butonuna (`+Taksit/Düzenle/Kapat/Yeniden Aç/Sil`) `touch-target` (mobil 44×44).

---

## 2026-06-09 — İlk sapma envanteri (12 madde)

**12 maddenin TAMAMI aynı gün kapatıldı.** Kapatma kapsamı: 2× native `confirm()` → ConfirmDialog; ~14 sayfaya PageHeader; ScheduledModule tam standardizasyon (PageHeader+StatCard+iskelet sırası+Button+toast, 7 sayfayı birden düzeltti); tüm inline spinner'lar → TableSkeleton/`Loader2`; paylaşılan bileşenlerdeki `bg-teal-600` → teal-700 (EmptyState/Pagination/FileDropzone/mesajlaşma); elle aksiyon butonları → Button; krediler oran girişleri → MoneyInput; devam-takip mobil tablo→kart; AA kontrast düzeltmeleri (gray-400→500, amber rozet, teal-600 tab/heatmap→700, kiosk metni); manuel pagination'lar → Pagination; eksik EmptyState'ler; hata-loglar inline modal → Modal; cyan/blue focus ring'ler → teal-500; `EmptyState message=` prop hatası → `description=` (3 dosya).
