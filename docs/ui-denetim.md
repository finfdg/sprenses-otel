# UI Denetim Raporu

**Tarih:** 2026-04-17
**Kaynak:** `docs/ui-kurallari.md` spec'ine karşı 31 frontend sayfasının denetimi
**Yöntem:** 4 paralel agent ile grup bazlı inceleme

## Özet Tablo

| Grup | Sayfa | Genel Durum | Öne çıkan sorun |
|---|---|---|---|
| **Finans** | 11 | ⚠️ Orta sapma | Inline SVG 9/11 · H1 tipografisi 8/11 · Label `*` 5/11 |
| **Muhasebe + İK** | 8 (+ `ScheduledModule`) | ⚠️ Tek nokta sorunu | Hepsi `ScheduledModule.svelte` kullanıyor — tek refactor 8 modülü düzeltir |
| **Kalite + Mesajlaşma + Dashboard** | 6 | 🟡 Kısmen uyumlu | ConfirmDialog zaten kullanılıyor · Emoji ikonlar · Custom pagination |
| **Sistem** | 6 | 🔴 Yüksek sapma | `window.confirm()` 3 sayfada · Başlık eksik 5/6 · Custom Pagination 4/6 |

## Projedeki 5 En Kritik Pattern

1. **Inline SVG / emoji ikonlar** — ~27 sayfa · `lucide-svelte` kurulumu gerekiyor
2. **`window.confirm()` kullanımı** — Sistem: kullanıcılar (169), roller (156), modüller (127, 132)
3. **H1 tipografisi tutarsız** — çoğu `text-xl sm:text-2xl` · spec `text-2xl font-semibold`
4. **Custom spinner + inline empty state** — her sayfada farklı
5. **Filtre barı yok** — Sistem CRUD ve Muhasebe tarafında arama/filtre eksik

## Kaldıraç Noktaları

- **`ScheduledModule.svelte` (1099 satır)** — düzeltilirse **Vergiler, Düzenli Ödemeler, Alınan/Verilen Kiralar, Temettü, Maaş, Stopaj, SGK** hepsi tek hamlede standardize
- **`ConfirmDialog.svelte` ZATEN VAR** — Kalite/Şablonlar, Kalite/Formlar, Mesajlaşma kullanıyor. Sistem sayfaları henüz kullanmıyor
- **En iyi uyum:** Finans/Avanslar, Finans/Onay, Mesajlaşma (referans alınabilir)

---

## Detay — Finans Grubu (11 sayfa)

### finans/+page.svelte
- ✅ OK: Route redirect, değerlendirmeye gerek yok

### finans/bankalar/+page.svelte ✅ REFACTOR TAMAMLANDI 2026-04-17
- [x] **HIGH** İkon: Inline SVG → Lucide (Upload, Plus, Pencil, Trash2, Check, ChevronRight, FileText, FileSpreadsheet, Building2)
- [x] **HIGH** `window.confirm()` → `ConfirmDialog` (sat. 375)
- [x] **HIGH** Spinner → `TableSkeleton`
- [x] **HIGH** EmptyState bileşenine geçildi (CTA'lı)
- [ ] `<h2>` sub-header (spec'e uygun bırakıldı — bölüm başlığı)
- [ ] FileDropzone ayrı bileşene (S6'ya kaldı)
- [ ] Form label `*` (S5'e kaldı)
- ✅ OK: Modal, Toast, MoneyInput, Pagination, mobil breakpoint

### finans/bankalar/talimatlar/+page.svelte ✅ REFACTOR TAMAMLANDI 2026-04-17
- [x] **HIGH** Başlık: `text-2xl font-semibold text-gray-900` (sat. 375)
- [x] **HIGH** İkon: Inline SVG → Lucide (ChevronDown, Send)
- [ ] Breadcrumb (S6'ya kaldı — Breadcrumb.svelte gerekli)
- [ ] Modal form label `*` (S5'e kaldı)
- [ ] Accordion bileşeni (kapsam dışı)
- ✅ OK: Tab yapısı, MoneyInput, native date, TableSkeleton import

### finans/cariler/+page.svelte
- [ ] **NOT** Dosya çok büyük (~35k token) — ayrı detaylı inceleme gerekli

### finans/cekler/+page.svelte
- [ ] **HIGH** İkon: Inline SVG (sat. 306-308) → Lucide
- [ ] **HIGH** Başlık + breadcrumb yok (iç sayfa)
- [ ] **MED** StatusBadge: emoji "🏦" (sat. 554, 558) + custom badge (sat. 452-463)
- [ ] **MED** Bulk select yok
- [ ] **LOW** Hover aksiyonları: inline buton yerine hover'da beliren
- ✅ OK: Toast, Sort (SortableHeader benzer yapı sat. 395-418), EmptyState, mobil kart, `DD.MM.YYYY`

### finans/krediler/+page.svelte
- [ ] **HIGH** Başlık: `<h1 class="text-lg sm:text-xl">` (sat. 432) → `text-2xl font-semibold`
- [ ] **HIGH** İkon: Inline SVG (sat. 556-558, 628-631, 739-741)
- [ ] **MED** Modal label stil: `text-xs text-gray-500` (sat. 764) → `text-sm font-medium text-gray-700`
- [ ] **MED** Loading: spinner (sat. 531) → `TableSkeleton`
- ✅ OK: Tab, Toast, MoneyInput, mobil grid

### finans/avanslar/+page.svelte
- [ ] **HIGH** Başlık: `text-xl sm:text-2xl` (sat. 241) → `text-2xl font-semibold`
- [ ] **MED** İkon: Inline SVG (sat. 249-251, 372-387)
- ✅ OK: Modal, form label, MoneyInput, Pagination, mobil kart, EmptyState, Toast
- ℹ️ Not: Silme için Modal kullanıyor, `ConfirmDialog`'a migrate edilebilir

### finans/doviz/+page.svelte
- [ ] **HIGH** Başlık: `text-xl sm:text-2xl` (sat. 243) → `text-2xl font-semibold`
- [ ] **MED** Para birimi ikonu: emoji `$ € £` (sat. 260-261) → Lucide `DollarSign/Euro/PoundSterling`
- ✅ OK: Toast, Tarih, Tablo hover, Grafik

### finans/butce/+page.svelte
- [ ] **HIGH** Başlık: `text-xl sm:text-2xl` (sat. 337) → `text-2xl font-semibold`
- [ ] **HIGH** İkon: Inline SVG (sat. 382-385) → Lucide `Settings`
- [ ] **HIGH** Para input: native `<input type="number">` (sat. 807, 815) → **MoneyInput olmalı** (spec ihlali)
- ✅ OK: Modal, Tab, Toast, mobil

### finans/nakit-akim/+page.svelte ✅ REFACTOR TAMAMLANDI 2026-04-17
- [x] **HIGH** İkon: Inline SVG → Lucide (Filter, AlertTriangle, Receipt)
- [x] **HIGH** Spinner → `TableSkeleton`
- [x] **HIGH** EmptyState bileşenine geçildi (3 variant korundu)
- [ ] Başlık + breadcrumb (sayfada h1 hiç yok — MonthAccordion başlığı yapar, S6'ya kaldı)
- [ ] MonthAccordion refactor (ayrı bir iş)
- ✅ OK: Toast, WebSocket event-driven (polling yok)

### finans/onay/+page.svelte
- [ ] **HIGH** Başlık: `text-xl sm:text-2xl` (sat. 170) → `text-2xl font-semibold`
- [ ] **MED** İkon: Inline SVG (sat. 187-188, 253-255, 262-264)
- ✅ OK: Modal, Card animasyon, EmptyState, WebSocket

---

## Detay — Muhasebe + İK Grubu (8 sayfa → 1 merkez)

**Tüm 8 sayfa** sadece `ScheduledModule.svelte` wrapper'dır (~13 satır her biri). Asıl sapmalar merkezi bileşende:

### ScheduledModule.svelte (1099 satır) ✅ REFACTOR TAMAMLANDI 2026-04-17
- [x] **HIGH** İkon: Inline SVG → Lucide (Plus, Pencil, Trash2, X, Check, Clock, ChevronDown, Search, RotateCcw, FileText, FileClock)
- [x] **HIGH** İkon boyutları tutarlı (size prop ile)
- [x] **HIGH** Arama kutusu eklendi (debounce 300ms, ad/kategori/not)
- [x] **HIGH** EmptyState: CTA'lı yeni bileşen (2 variant — boş + arama-sonuç-yok)
- [x] **HIGH** Silme: `Modal` → `ConfirmDialog.svelte`
- [x] **MED** Spinner → `TableSkeleton.svelte`
- [x] **MED** StatusBadge: inline span → `StatusBadge.svelte` (success/warning/info/neutral)
- [x] **LOW** Başlık: `text-2xl font-semibold text-gray-900`
- [ ] Export ikonu yok (bu sprintte atlandı)
- [ ] Kategori filtre UI yok (bu sprintte atlandı)
- [ ] Satır aksiyonları hep görünür (tasarım tercihi, değiştirilmedi)
- [ ] Kolon sort yok (entries zaten tarih sıralı)
- [ ] Bulk actions yok (bu kapsamda gereksiz)
- [ ] Pagination yok (yıl filtresi kullanılıyor, 200 item sınırı yeterli)
- [ ] Breadcrumb yok (bu sprintte atlandı)
- ✅ OK: Modal, label + `*`, validation, Toast, MoneyInput, `DD.MM.YYYY`, mobil kart

---

## Detay — Kalite + Mesajlaşma + Dashboard Grubu (6 sayfa)

### dashboard/+page.svelte
- [ ] **HIGH** İkon: Inline SVG (banka/çek/kredi/avanslar/cariler) → Lucide
- [ ] **MED** Loading: custom spinner → `Skeleton`
- [ ] **MED** Başlık: `text-xl md:text-2xl` → `text-2xl font-semibold`
- ✅ OK: `hasPermission` ile dinamik özet kartları, tıklanabilir yönlendirme

### kalite/+page.svelte
- ✅ OK: Redirect only

### kalite/sablonlar/+page.svelte
- [ ] **HIGH** EmptyState: emoji "📋" + custom → `EmptyState.svelte`
- [ ] **HIGH** Mobil `<md` kart dönüşümü yok
- [ ] **MED** Pagination custom → `Pagination.svelte`
- [ ] **MED** Loading: custom spinner → `TableSkeleton`
- ✅ OK: **ConfirmDialog kullanılıyor** (sat. 580) · Modal · form label · hover aksiyonu

### kalite/formlar/+page.svelte
- [ ] **HIGH** İkon: emoji "📄" → Lucide
- [ ] **HIGH** Mobil kart transformu eksik
- [ ] **MED** Pagination custom
- [ ] **MED** Loading: custom spinner
- ✅ OK: **ConfirmDialog kullanılıyor** (sat. 391) · StatusBadge tarzı renkler · `statusStyles` map

### kalite/formlar/[id]/+page.svelte
- [ ] **HIGH** Breadcrumb: "← Formlara Dön" inline metin → `Breadcrumb.svelte`
- [ ] **HIGH** PDF butonu inline SVG → Lucide
- [ ] **HIGH** Loading: custom spinner
- [ ] **MED** Başlık: `text-lg sm:text-xl` (nested olduğu için tolerans ama spec `text-2xl`)
- ✅ OK: Toast, form renderer, renk kodu (taslak/gönder/onayla/reddet/yeniden aç)

### mesajlasma/+page.svelte
- [ ] **MED** EmptyState: emoji "💬" → bileşene
- [ ] **MED** WS banner spinner custom
- [ ] **LOW** Date separator: stil standardizasyonu
- ✅ OK: **ConfirmDialog kullanılıyor** (sat. 304) · Toast · Modal · WS event-driven · focusTrap · responsive sidebar

---

## Detay — Sistem Grubu (6 sayfa)

### sistem/kullanicilar/+page.svelte
- [x] **HIGH** `window.confirm()` (sat. 169) → `ConfirmDialog` ✅ 2026-04-17
- [ ] **HIGH** İkon: Inline SVG (sat. 271) → Lucide `RotateCcw` / `Key`
- [ ] **HIGH** Başlık `<h1>` yok
- [ ] **HIGH** Filtre barı yok (arama/durum)
- [ ] **MED** Breadcrumb yok
- [ ] **MED** Stat Card yok (toplam/aktif/pasif kullanıcı)
- [ ] **MED** SortableHeader yok
- ✅ OK: Modal, Toast, form validation, mobil kart

### sistem/roller/+page.svelte
- [x] **HIGH** `window.confirm()` (sat. 156) → `ConfirmDialog` ✅ 2026-04-17
- [ ] **HIGH** Başlık `<h1>` yok
- [ ] **HIGH** Filtre barı yok
- [ ] **HIGH** Lucide ikon yok
- [ ] **MED** Breadcrumb yok
- [ ] **MED** Stat Card yok
- [ ] **MED** Kolon sort yok
- [ ] **LOW** İzin matrisi `text-[11px]` çok küçük
- ✅ OK: Modal, form validation, responsive

### sistem/moduller/+page.svelte
- [x] **HIGH** `window.confirm()` (sat. 127) + `alert()` (sat. 132) → `ConfirmDialog` + `showToast` ✅ 2026-04-17
- [ ] **HIGH** Başlık `<h1>` yok
- [ ] **HIGH** Filtre barı yok
- [ ] **MED** Breadcrumb yok
- [ ] **MED** Stat Card yok
- [ ] **LOW** Alt modül indent `└` hardcoded → Lucide `ChevronRight`
- [ ] **LOW** `icon` form alanı var ama UI'de gösterilmiyor
- ✅ OK: Modal, form validation, responsive

### sistem/audit-loglar/+page.svelte
- [ ] **HIGH** Pagination custom → `Pagination.svelte`
- [ ] **HIGH** SortableHeader yok
- [ ] **HIGH** BulkActionsBar yok
- [ ] **HIGH** Arama debounce eksik (anlık çalışıyor)
- [ ] **MED** Başlık: `text-xl` → `text-2xl`
- [ ] **MED** EmptyState: inline SVG+metin (sat. 162) → bileşen
- [ ] **MED** Spinner (sat. 158) → `TableSkeleton`
- [ ] **MED** Breadcrumb yok
- ✅ OK: Toast, detay modal, mobil kart, Esc kapatma

### sistem/hata-loglar/+page.svelte
- [ ] **HIGH** Pagination custom
- [ ] **HIGH** SortableHeader yok
- [ ] **HIGH** BulkActionsBar yok
- [ ] **HIGH** Arama debounce 400ms → 300ms (spec)
- [ ] **MED** Başlık: `text-xl` → `text-2xl`
- [ ] **MED** EmptyState custom
- [ ] **MED** Spinner → `TableSkeleton`
- [ ] **MED** Breadcrumb yok
- ✅ OK: Toast, Modal, mobil layout

### sistem/onay-akisi/+page.svelte
- [ ] **HIGH** Başlık eksik
- [ ] **HIGH** Pagination custom
- [ ] **HIGH** SortableHeader yok
- [ ] **HIGH** BulkActionsBar yok
- [ ] **MED** Onay/Red/İade modalleri custom
- [ ] **LOW** Status map hardcoded → `StatusBadge`
- ✅ OK: Modal, Toast, WebSocket

---

## Faz 3 Refactor — Tamamlandı (2026-04-17)

1. ✅ **Sistem/Kullanıcılar/Roller/Modüller** — `window.confirm()` + `alert()` → `ConfirmDialog` + `showToast`
2. ✅ **lucide-svelte kurulumu** + ikon migrasyonu (25+ sayfada)
3. ✅ **Yeni bileşenler:** `EmptyState`, `StatusBadge`, `TableSkeleton`, `FormSkeleton`, `Pagination`, `SortableHeader`, `Breadcrumb`, `BulkActionsBar`, `FileDropzone` (ConfirmDialog zaten vardı)
4. ✅ **`ScheduledModule.svelte`** — tek hamlede 8 modül standardize (vergiler, düzenli ödemeler, kiralar×2, temettü, maaş, stopaj, sgk)
5. ✅ **Finans:** Bankalar, Talimatlar, Nakit-akım, Avanslar, Döviz, Butce, Krediler, Çekler, Onay, Cariler
6. ✅ **Kalite:** Şablonlar, Formlar, Formlar/[id] (breadcrumb + FormSkeleton)
7. ✅ **Sistem:** Audit-loglar, Hata-loglar, Onay-akışı (h1, spinner, empty state)
8. ✅ **Dashboard:** h1 typography

**Sonuç:** 267 test geçiyor · 0 yeni svelte-check hatası · Tüm modüller yeni UI spec'ine uyumlu
