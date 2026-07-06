# UI Tutarlılık Kuralları

Tüm frontend sayfalar bu dokümandaki şablona ve bileşen API'lerine uyar. Yeni modül eklerken bu spec rehber alınır.

## 0. Referans Sayfa & Temel Primitive'ler

> **Yeni/yeniden tasarlanan her liste sayfası `finans/avanslar`'ı örnek almalıdır.** Bu sayfa tasarım sisteminin kanonik uygulamasıdır: PageHeader + Button + StatCard + StatusBadge + Pagination + ConfirmDialog + MoneyInput'u doğru, kontrast-güvenli (WCAG AA) ve form-ARIA'lı biçimde kullanır.

**Zorunlu primitive'ler (inline kopya yazma):**
| Bileşen | Ne için | Kural |
|---|---|---|
| `Button.svelte` | Tüm butonlar | Primary rengin **tek kaynağı**. `variant` (primary/secondary/danger/ghost), `size`, `loading`, `fullWidth`. Elle `bg-teal-* ... rounded-lg` buton yazma. AA-uyumlu (teal-700). `class` prop'u **yalnızca layout** (ör. `w-full sm:w-auto`, `mt-2`) içindir — renk/stil variant'tan gelir, sona eklenir, ezmez. |
| `PageHeader.svelte` | Sayfa başlığı | `<h1>` + açıklama + `{#snippet actions()}`. Her sayfada başlık zorunlu. |
| `StatCard.svelte` | Özet kartları | `label`/`value` + opsiyonel `icon`/`accent`/`hint`. Inline stat kartı yazma. |
| `StatusBadge.svelte` | Durum rozetleri | `type` (success/warning/error/info/neutral). Semantik renk sabit; inline `rounded-full` rozet yazma. |
| `Pagination.svelte` | Sayfalama | Sayfa numaraları + boyut seçici + `aria-current`. Inline "Önceki/Sonraki" yazma. |
| `ConfirmDialog.svelte` | Silme/onay | Native `confirm()` **yasak**. |
| `MoneyInput.svelte` | Para girişi | `<input type=number/text>` para için yasak. Form hatası için `ariaInvalid`/`ariaDescribedby`. |
| `Input.svelte` | Metin/tarih/sayı/arama girişi | Tüm `<input>` (text/date/month/number/search/email/password) **tek kaynağı**. `size` (sm/md), `invalid`, `fullWidth`, `icon` (Lucide, arama), `clearable`. `class` **yalnızca layout** (genişlik/boşluk). Elle `border rounded-lg … focus:ring-teal-500` yazma. Para → MoneyInput, dosya → FileDropzone, checkbox/radio hariç. |
| `Select.svelte` | Açılır liste | Tüm `<select>` tek kaynağı. `<option>`'lar children. `size`/`invalid`/`fullWidth`/`class` + native attrs (`onchange`). |
| `Textarea.svelte` | Çok satırlı metin | Tüm `<textarea>` tek kaynağı. `rows`, `resize` (varsayılan kapalı), `invalid`. |
| `Field.svelte` | Form alanı sarmalayıcı | label + zorunlu `*` + hata/ipucu + `aria-invalid`/`aria-describedby` kablolaması. `children` snippet'i `{ id, invalid, describedby }` verir → kontrol bunları kullanır. Referans: `finans/avanslar`. |

**Erişilebilirlik tabanı:** İkincil metin `text-gray-500` (gray-400/300 değil — AA kontrast). Form alan hataları `aria-invalid` + `aria-describedby` ile bağlanır. İkon-only butonlar `aria-label` taşır. Select'lere `aria-label`. `app.css` `prefers-reduced-motion` destekler.

## 1. Global Sistem

### İkon Kütüphanesi
- **Lucide** (`lucide-svelte`) — tüm ikonlar buradan import edilir
- Kurulum: `npm install lucide-svelte`
- Kullanım:
  ```svelte
  import { Pencil, Trash2, Plus, Download } from 'lucide-svelte';
  <Pencil size={18} />
  ```
- Emoji ya da inline SVG yeni kod için kullanılmaz — mevcut yerler zamanla Lucide'a geçirilir

### Tarih & Para
- **Tarih:** `DD.MM.YYYY` — native `<input type="date">` (browser lokalizasyonuna bırakılır)
- **Tarih + saat:** `DD.MM.YYYY HH:mm` — sadece gerektiğinde (audit log vb.)
- **Para:** `MoneyInput.svelte` — TR format `1.234,56` (detaylı API root `CLAUDE.md`'de)

### Toast
- Pozisyon: **sağ üst**
- Süre: **3 saniye**
- Store: `$lib/stores/toast.ts`
- Çeşitler: `success` (yeşil) · `error` (kırmızı) · `info` (mavi) · `warning` (sarı)

### Loading
- **Skeleton ekran** kullanılır — spinner yok
- Tablo için: `TableSkeleton` (3-5 satır placeholder)
- Form için: `FormSkeleton`
- Re-fetch sırasında: buton disabled + içinde küçük spinner

### Badge / Durum Rozeti (StatusBadge.svelte)
Semantik sabit renkler — her modülde aynı anlam:

| Renk | Anlam | Örnek durumlar |
|---|---|---|
| 🟢 Yeşil | Başarılı / Aktif / Ödenmiş | paid, approved, active, completed, success |
| 🔴 Kırmızı | Hata / Gecikmiş / Reddedilmiş | overdue, rejected, failed, error, danger |
| 🟡 Sarı | Bekliyor / Uyarı | pending, waiting, warning, in_progress |
| 🔵 Mavi | Bilgi / Yeni / Taslak | new, info, draft |
| ⚪ Gri | Pasif / İptal | inactive, cancelled, archived |

```svelte
import StatusBadge from '$lib/components/StatusBadge.svelte';
<StatusBadge type="success">Ödendi</StatusBadge>
<StatusBadge type="warning">Bekliyor</StatusBadge>
```

### Klavye Kısayolları
- **Esc** → açık modal'ı kapat (iptal)
- **Enter** → modal'ın primary action'ı (tipik: Kaydet)
- Bu iki davranış `Modal.svelte` tarafından merkezi sağlanır, her kullanımda çalışır

## 2. Sayfa İskeleti

Her liste sayfası aşağıdaki sırayla dizilir:

```
┌───────────────────────────────────────────────────┐
│ Breadcrumb (yalnızca iç sayfalarda)              │
│ Sayfa Başlığı                                     │
├───────────────────────────────────────────────────┤
│ [Stat Card]  [Stat Card]  [Stat Card]  (opsiyonel)│
├───────────────────────────────────────────────────┤
│ [🔍 Ara...]  [Filtre ▼]  [Durum ▼]    [⬇]  [+ Yeni]│
├───────────────────────────────────────────────────┤
│ Tablo (desktop)  /  Kart listesi (<md)           │
│ ☐ Ad ▲   Tarih    Tutar    Durum   [✏ 🗑 hover]   │
│ ☐ ...                                             │
├───────────────────────────────────────────────────┤
│ Sayfa 1 / 10    [1][2][3]...[10]   Sayfa [50 ▼]  │
└───────────────────────────────────────────────────┘
```

### Başlık Bölümü
- Başlık tipografisi: `text-2xl font-semibold text-gray-900`
- Breadcrumb:
  - Yalnızca **iç sayfalarda** (ör: Finans / Bankalar / Talimatlar)
  - Ana modül liste sayfalarında gösterilmez (Topbar geri butonu yeterli)
  - Bileşen: `Breadcrumb.svelte` — SvelteKit route'tan türetilir

### Filtre Barı
- **Sol**: Arama kutusu
  - Debounce 300ms (yazılırken otomatik aramayı başlatır)
  - Sağ iç kenarda `✕` ile temizleme butonu
  - Placeholder: `"Ara..."` veya modüle özel (`"Cari adı, vergi no..."`)
- **Yanında**: Filtre chip/dropdown'ları (durum, tarih aralığı, kategori vs.)
- **Sağ**:
  - `⬇` Export ikon butonu — tıklanınca Excel/PDF menüsü açılır
  - `+ Yeni` butonu (cyan/teal, primary)

### İstatistik Kartları (Stat Cards)
- İçerik modüle özel (toplamlar, sayaçlar, değerler)
- **Modül içinde tutarlı olmalı** — aynı yükseklik, aynı font, aynı padding
- Standart layout: sol Lucide ikon + büyük rakam + alt etiket
- Tıklanabilirse: `cursor-pointer` + hover efekti → ilgili filtreye yönlendirir

## 3. Tablolar & Listeler

### Yoğunluk
Modül tipine göre seçilir ama modül içinde tutarlı kalır:
- **Kompakt** (`py-2`) — finans/liste ağırlıklı (nakit akım, cariler)
- **Standart** (`py-3`) — kullanıcılar, roller, modüller
- **Kart görünümü** — içerik zengini modüller (kalite formları)

### Satır Aksiyonları
- **Varsayılanda gizli**
- Satıra hover olunca sağda ikon butonlar belirir:
  - `<Pencil size={18} />` — Düzenle (hover'da teal)
  - `<Trash2 size={18} />` — Sil (hover'da red-500)
- **Mobilde her zaman görünür** (hover etkisi olmadığı için)

### Kolon Sıralama (SortableHeader.svelte)
- Sıralanabilir kolon başlığına `<SortableHeader>` uygulanır
- Tıklama: `kapalı → asc ▲ → desc ▼ → kapalı` (3-state toggle)
- Tek anda bir kolon aktif
- Server-side sıralama: `?sort_by=field&sort_dir=asc|desc` — `sort_by` **whitelist'li** (regex pattern ile sabit alan kümesi; keyfi kolon sıralaması engellenir). Referans: `checks.py`, `cariler/vendors.py`

### Toplu Seçim (BulkActionsBar.svelte)
- Her satır başında checkbox
- Seçim yapılınca **başlık barı dönüşür**:
  ```
  "3 kayıt seçildi"  [İptal]  [Sil]  [Export]  ...
  ```
- Mevcut filtre/arama bar'ının yerini alır, seçim temizlenince geri döner

### Pagination (Pagination.svelte)
- Yapı: `[◀]  [1] [2] [3] ... [10]  [▶]    Sayfa boyutu: [50 ▼]`
- page_size seçenekleri: **25, 50, 100, 200**
- Backend response formatı: `{ items, total, page, page_size, pages }`
- URL params: `?page=1&page_size=50`

### Boş Durum (EmptyState.svelte)
- İçerik: Lucide ikon + mesaj + (opsiyonel) CTA butonu
- İki senaryo:
  - Filtre/arama uygulanmışsa: `"Aramaya uygun kayıt bulunamadı"` (CTA yok)
  - Filtre yoksa: `"Henüz kayıt yok"` + `[+ Yeni Ekle]` CTA

### Mobil Davranış (< md breakpoint)
- Tablo → **kart görünümü**: her satır ayrı kart olur
- Kart içinde: en önemli 3-4 alan + aksiyon butonları
- Tailwind: `md:table` / `max-md:grid` veya ayrı template bloku

### Mobil Belge Kilidi — `app-shell-lock` (2026-07-06, Topbar takılma düzeltmesi)
- **Belirti:** iOS'ta (Safari sekmesi + PWA standalone) Topbar bazen sayfayla yukarı kayıp
  ekran dışında **takılı** kalıyordu. İki kök neden: (1) kök layout `min-h-screen` (100vh =
  iOS büyük viewport) > dashboard kabuğu `h-dvh` → belge araç-çubuğu farkı kadar kaydırılabilir;
  iç scroller ucundaki rubber-band belgeye zincirlenir. (2) iOS klavyesi input odağında
  `overflow-hidden`'a RAĞMEN belgeyi kaydırır ve kapanınca geri almaz.
- **Mekanizma:** `dashboard/+layout.svelte` onMount'ta `<html>`'e **`app-shell-lock`** sınıfı
  ekler (app.css: `height:100%; overflow:hidden; overscroll-behavior:none`) + klavye kapanınca
  (`visualViewport resize` + `focusout`, event-driven — polling DEĞİL) odak form alanında değilse
  `window.scrollTo(0,0)` ile ofseti sıfırlar. Cleanup'ta ikisi de kaldırılır.
- **Kural:** Dashboard içi sayfalar belgeyi (window/document) KAYDIRMAMALI — scroll yalnız iç
  `<main>` / container'larda. `scrollIntoView` kullanan sayfa, çağrının kullanıcı eylemiyle
  tetiklendiğinden emin olmalı (WS event'i ile eylemsiz kaydırma YASAK — bankalar sayfasındaki
  `bank_statement_uploaded` handler'ı yalnız **yükleyenin kendi sekmesinde** hesabı açar+kaydırır,
  `uploader_id === authState.user.id` guard'ı). Login/kiosk (`/devam`) doğal akışta kalır (kilit yok).

## 4. CRUD & Formlar

### Modal (Modal.svelte)
- Varsayılan boyut: **`md` (600px)**
- Override seçenekleri:
  - `sm` (400px) — onay/kısa form modal'ları
  - `lg` (800px) — detay/tablo içeren form'lar
- Kullanım:
  ```svelte
  <Modal bind:show={showForm} title="Yeni Cari" maxWidth="md">
    <!-- form içeriği -->
  </Modal>
  ```

### Form Field Pattern
- **Kontroller primitive'dir:** metin/tarih/sayı/arama → `Input.svelte`, açılır liste → `Select.svelte`, çok satırlı → `Textarea.svelte`, para → `MoneyInput.svelte`. Elle `<input>/<select>/<textarea>` + sınıf dizisi **yazılmaz** (checkbox/radio/file istisna — primitive yok). `Input`/`Select`/`Textarea` `svelte/elements` HTML attribute tipleriyle tiplenir → `onkeydown`/`onchange` gibi olay parametreleri otomatik tiplidir (`(e) =>` implicit-any vermez).
- Label **üstte**, kontrolün hemen üzerinde; zorunlu alanda label sonuna kırmızı yıldız.
- **Tercih edilen kalıp — `Field.svelte` sarmalayıcı** (label + `*` + hata + ARIA tek yerde):
  ```svelte
  <Field label="Acente Adı" required for="agency_name" error={fieldErrors.agency_name}>
    {#snippet children({ id, invalid, describedby })}
      <Input {id} {invalid} aria-describedby={describedby} bind:value={form.agency_name} />
    {/snippet}
  </Field>
  ```
  Hata varken `Field` `invalid={true}` geçer → `Input`/`Select`/`Textarea` `border-red-400` + `aria-invalid` uygular; hata metni `role="alert"` ile `aria-describedby`'ye bağlanır. Para alanında snippet içinde `MoneyInput` (`ariaInvalid`/`ariaDescribedby`).
- Filtre barı kontrolleri: `size="sm" fullWidth={false}` + genişlik `class`'ta (ör. `class="flex-1 sm:flex-none"`).
- Helper: `$lib/utils/validation.ts` + form state'inde `fieldErrors: Record<string,string>`. Referans uygulama: `finans/avanslar`.

### Uzun Formları Tab'lara Böl
- 3+ alan grubu olan form'lar tab'lara bölünür
- Modal başlığı altında yatay tab bar: `[Genel]  [İletişim]  [Ödeme]`
- Her tab kendi alan grubunu içerir
- Validation hatası olan tab'a kırmızı nokta badge'i eklenir

### Silme / Kritik Onay (ConfirmDialog.svelte)
- Native `window.confirm()` **kesinlikle kullanılmaz**
- Bileşen: `ConfirmDialog.svelte` (mevcut) — Türkçe, projeye özel
- Props: `show` (bindable), `title`, `message`, `confirmText`, `cancelText`, `danger` (bool), `onConfirm`, `onCancel`
- Pattern: bileşen sayfanın altına yerleşir, state ile tetiklenir — async fonksiyon değil
- Kullanım:
  ```svelte
  <script>
    import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';

    let showDeleteConfirm = $state(false);
    let deleteTarget = $state<Item | null>(null);

    function askDelete(item: Item) {
      deleteTarget = item;
      showDeleteConfirm = true;
    }

    async function handleDelete() {
      if (!deleteTarget) return;
      await api.delete(`/items/${deleteTarget.id}`);
      // refetch / toast
    }
  </script>

  <!-- sayfa sonunda -->
  <ConfirmDialog
    bind:show={showDeleteConfirm}
    title="Kalemi Sil"
    message="{deleteTarget?.name} kalemini silmek istediğinize emin misiniz?"
    confirmText="Sil"
    danger={true}
    onConfirm={handleDelete}
  />
  ```

### Dosya Yükleme (FileDropzone.svelte)
- Görünüm: kesik çizgili geniş alan + Lucide `Upload` ikon + `"Dosyayı buraya sürükleyin veya tıklayın"` + `"Göz at"` butonu
- Yüklenirken: progress bar + "İptal" butonu
- Props:
  - `accept`: MIME tipleri (`".xlsx,.xls"`, `"image/*,.pdf"` vb.)
  - `maxSize`: bytes cinsinden sınır
  - `multiple`: çoklu dosya
- Sunucu validation her zaman: `backend/app/utils/file_validation.py`

## 5. Dashboard

- Route: `/dashboard/+page.svelte`
- İçerik: kullanıcının izinli olduğu her modül için bir **özet kartı**
- Her kart tıklanabilir → ilgili modüle yönlendirir
- İzin yoksa kart hiç render edilmez
- Örnek kartlar:
  - **Mesajlaşma** → okunmamış mesaj sayısı
  - **Onay** → bekleyen onay sayısı
  - **Nakit Akım** → bugünkü bakiye + gün içi değişim
  - **Cariler** → 7 gün içindeki yaklaşan vade toplamı
  - **Çekler** → ödenmemiş çek toplamı (bugüne kadar)
  - **Krediler** → yaklaşan taksit
  - **Kalite** → dolum bekleyen form sayısı

## 6. Paylaşılan Bileşen Envanteri

`frontend/src/lib/components/`:

| Bileşen | Durum | Açıklama |
|---|---|---|
| `Modal.svelte` | ✅ mevcut | `md` varsayılan modal |
| `MoneyInput.svelte` | ✅ mevcut | TR para formatı |
| `Input.svelte` | ✅ mevcut | Metin/tarih/sayı/arama girişi tek kaynağı (`size`/`invalid`/`fullWidth`/`icon`/`clearable`); `svelte/elements` ile tipli |
| `Select.svelte` | ✅ mevcut | Açılır liste tek kaynağı (`<option>` children); `svelte/elements` ile tipli |
| `Textarea.svelte` | ✅ mevcut | Çok satırlı metin tek kaynağı (`rows`/`resize`/`invalid`) |
| `Field.svelte` | ✅ mevcut | Form alanı sarmalayıcı: label + `*` + hata + ARIA; `children({id,invalid,describedby})` |
| `StatCard.svelte` | ✅ mevcut | Dashboard istatistik kartı |
| `Sidebar.svelte` | ✅ mevcut | Sol menü |
| `Topbar.svelte` | ✅ mevcut | Üst bar + geri butonu |
| `ConfirmDialog.svelte` | ✅ mevcut | Silme/kritik onay — `bind:show` + `onConfirm` |
| `EmptyState.svelte` | ✅ mevcut | Boş durum (ikon + mesaj + CTA) |
| `TableSkeleton.svelte` | ✅ mevcut | Tablo loading iskelet |
| `FormSkeleton.svelte` | ✅ mevcut | Form loading iskelet (fields + submit) |
| `StatusBadge.svelte` | ✅ mevcut | 5 semantik durum rozeti (success/error/warning/info/neutral) |
| `Pagination.svelte` | ✅ mevcut | Klasik sayfalama + page_size + `getPageNumbers` helper |
| `FileDropzone.svelte` | ✅ mevcut | Drag-drop dosya yükleme + `formatSize` + `validateFiles` helper |
| `Breadcrumb.svelte` | ✅ mevcut | Yol göstergesi (iç sayfalar) — `items` array |
| `SortableHeader.svelte` | ✅ mevcut | Tablo kolon sort başlığı (3-state) + `getNextSort` helper |
| `BulkActionsBar.svelte` | ✅ mevcut | Toplu seçim aksiyon barı (`count` + `onClear` + children snippet) |
| `PdfPreviewModal.svelte` | ✅ mevcut | iOS Safari uyumlu PDF önizleme (iframe + Yazdır/İndir/Kapat). Blob'lu PDF'te **tek doğru desen** — `<a download>`/yeni-sekme blob iPad'de "WebKitBlobResource hatası 1" verir. Kullanım: `pdfModal?.open(blob, dosyaAdi)` |

## 7. Renk Paleti

- **Ana (primary):** Cyan/Teal → `cyan-500`, `teal-500` (butonlar, active state, link)
- **Nötr:** Gray → `gray-50` → `gray-900` (arka plan, metin, border)
- **Tehlike:** Red → `red-500`, `red-600` (silme, hata, kritik)
- **Uyarı:** Amber → `amber-500`, `yellow-500` (bekleyen, warning)
- **Başarı:** Green → `green-500`, `emerald-500` (onay, ödendi, active)
- **Bilgi:** Blue → `blue-500` (info, yeni, draft)

Kartlar: `bg-white border border-gray-200 rounded-xl shadow-sm`
Butonlar:
- Primary: `bg-cyan-600 hover:bg-cyan-700 text-white`
- Danger: `bg-red-600 hover:bg-red-700 text-white`
- Ghost: `bg-white border border-gray-300 hover:bg-gray-50`

## 8. Uygulama Fazları

- [ ] **Faz 1 — Altyapı bileşenleri** (`🔜 yeni` listesindekiler + Lucide kurulumu + Vitest testleri)
- [ ] **Faz 2 — Denetim**: 30 mevcut sayfada spec sapmalarının checklist'i
- [ ] **Faz 3 — Refactor**: trafiği yüksek modülden başla (Nakit Akım → Cariler → Bankalar → Çekler → Krediler → ...)
- [ ] **Faz 4 — Scope'lu rehber**: `frontend/CLAUDE.md` (kısa, bileşen kullanım örnekleri)
