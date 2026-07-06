# Otel Rezervasyon Modülü

## Genel Bilgi
- **Modül kodu:** `sales.hotel_reservation`
- **Frontend rota:** `/dashboard/satis/otel-rezervasyon`
- **Backend prefix:** `/api/sales/reservations`

## Dosya Yapısı

Backend router'ı 4 alt dosyaya bölündü (önceki tek dosya 1030 satıra ulaşmıştı). Her alt-router kendi `APIRouter()` tanımlar, `__init__.py` `prefix="/reservations"` ile birleştirir.

```
app/routers/sales/reservations/
├── __init__.py         # Alt router'ları birleştirir (prefix="/reservations")
├── uploads.py          # POST /upload, GET /uploads, DELETE /uploads/{id}, POST /bulk-delete + _compute_removal_candidates
├── sedna_import.py     # POST /sedna-import, GET /sedna-status + run_reservation_import (SednaPrenses önbüro senkronu)
├── listing.py          # GET / (sayfalanmış liste)
├── summary.py          # GET /summary (KPI + dağılımlar + doluluk metrikleri) + GET /years (yıl filtresi seçenekleri)
├── occupancy.py        # GET /daily-occupancy?month=YYYY-MM (aylık drill-down)
└── _helpers.py         # _apply_filters, _parse_date, _resolve_date_range, _month_days_in_range, UPLOAD_DIR
```

### Frontend (modal bileşenleri — 2026-06-22, D1-3)

Sayfa `+page.svelte` 2232→1916 satıra indirildi; 4 modal ayrı **sunum bileşenlerine** çıkarıldı.
State + handler + veri yükleme parent'ta kalır, bileşene `$bindable` prop + callback ile geçer
(davranış birebir korunur — 8-ajan parite incelemesiyle doğrulandı). Ortak tipler `$lib/types/reservation.ts`
(`UploadHistory`/`RemovalCandidate`/`UploadResult`/`ApiGroup`) — parent + bileşenler tek kaynaktan kullanır.

```
frontend/src/lib/components/sales/otel-rezervasyon/
├── ResultModal.svelte          # Yükleme sonucu (özet + "Kayıtları İncele")
├── RemovalReviewModal.svelte   # Silme adayları seç/sil (toggle mantığı bileşende)
├── UploadsHistoryModal.svelte  # Yükleme geçmişi tablosu + sil
└── AgencyGroupModal.svelte     # Acente grupları (liste+form tek modal) — reset $effect parent'ta kalır
```

> **Not (AgencyGroupModal):** Modal kapanışında gm* state'i sıfırlayan `$effect` ve `gmSuggestions`
> `$derived`'i **parent'ta** tutuldu (`+page.svelte`). `bind:show` iki-yönlü olduğundan kapanış reset'i
> bileşenden de doğru tetiklenir; `gmSearch` yazımı parent derived'i yeniden hesaplatır.

## Yıl Filtresi Seçenekleri — `GET /reservations/years` (2026-07-06)

Sayfa üstündeki yıl dropdown'ı (`availableYears`) **rezervasyon verisinde gerçekten geçen
yıllardan** üretilir: `GET /sales/reservations/years` → `{ years: [2027, 2026, 2025] }`
(check-in **VE** check-out yıllarının `DISTINCT` birleşimi, DESC).

- **Neden değişti (bug):** Önceden `availableYears` yükleme periyotlarından (`period_checkin_start`/
  `period_checkin_end`) yalnız **başlangıç ve bitiş yılını** ekliyordu. Bir yükleme periyodu
  2026-01-01 → 2030-12-05 olduğunda listeye yalnız 2026 ve 2030 giriyor, **aradaki 2027/2028/2029
  atlanıyordu** → 2027 check-in'li 28 rezervasyon (+ yıl sınırına taşan 119 konaklama) hiç
  seçilemiyor/gösterilemiyordu. Ayrıca verisi olmayan 2030 (periyot artığı) listede kalıyordu.
- **Çözüm:** Yıllar artık rezervasyon tablosundan türetilir → yalnız verisi olan yıllar (2025–2027),
  yıl atlaması yok. Check-in + check-out birleşimi sayesinde yıl sınırına taşan konaklamalar
  (ör. 26 Ara → 3 Oca) her iki yılda da seçilebilir; o yılın görünümü ilgili aya düşen geceleri gösterir.
- Salt-okuma GET (`sales.hotel_reservation` view) → onay/broadcast kapsam dışı.

## Canlı Doluluk Senkronu — SednaPrenses Önbüro DB'si (2026-06-07)

Rezervasyonlar artık XLS yüklemeye ek olarak **doğrudan SednaPrenses önbüro/PMS DB'sinden**
canlı çekilir (ters SSH tüneli `127.0.0.1:11433`; muhasebe DB'sinden `SednaPrensesMhs2026`
**ayrı** bir DB, aynı `prenses\btadmin` login'i ikisini de okur — `config.py:sedna_pms_database`).
Böylece kişi başı maliyet / CPOR / doluluk KPI'ları (Maliyet Kontrol + Yönetim Paneli) **elle
dosya yüklemeden** hep güncel kalır.

- **Endpoint:** `POST /reservations/sedna-import` (finance.* gibi tekil; merkezi Sedna butonu da
  çağırır) + `GET /reservations/sedna-status`. İzin: `sales.hotel_reservation` use, audit'li,
  onaydan muaf. Tünel kapalıysa 503.
- **Merkezi sync adımı:** `sedna_sync.py:_STEPS` → `reservations` (`run_reservation_import`).
  Topbar'daki tek "Sedna" butonu otomatik kapsar — **sayfa-içi ayrı buton yok**.
- **Eşleme (`utils/sedna_client.py:fetch_reservations` + `Reservation` join `Agency`):**
  | Bizim alan | Sedna kaynağı |
  |---|---|
  | `rec_id` | `Reservation.RecId` (XLS ile **aynı ID uzayı** → mükerrer yapmaz) |
  | `agency` | `Agency.Name` (AgencyId join) |
  | `nation` | `NationalityMarketCode` (DEU/RUS/GBR — XLS ile aynı 3-harf) |
  | `guests` | `Reservation.Guests` (XLS ile aynı "Mr AD,Mrs AD" formatı) |
  | `adult` / `child_paid` / `child_free` / `baby` | `Pax` / `PaidChild` / `FreeChild` / `Baby` |
  | `rooms` | sabit **1** (Sedna'da her Reservation satırı = 1 oda) |
  | `nights` | `CheckOutDate − CheckinDate` (checkout exclusive) |
  | `net_amount` / `currency` | `RoomPrice` (sözleşme para biriminde) / **`Contrack.Currency`** (EUR/TL/USD) |
  | `eur_total` | `RoomPrice` → **EUR'ya çevrilir** (TL/USD son TCMB `forex_selling` ile) |
  | `status` | `Status` 1→Reservation, 2→InHouse, 3→CheckOut |

- **Para birimi (kritik — ciro hatası düzeltmesi, 7 Haz 2026):** `RoomPrice` sözleşmenin para
  biriminde tutulur ve bu **milliyet değil `Contrack.Currency`** ile belirlenir (yerli/WEBRES
  rezervasyonları **TL** sözleşmeli; `RoomCon` ve `DailyRoomLocalPrice` güvenilmez — boş/0). İlk
  sürüm hepsini EUR sayıyordu → 331 TL sözleşme (₺5,9M) ciroyu **~2× şişiriyordu** (€11,4M görünüyordu,
  gerçek ~€5,6M). Düzeltme: `Contrack` join + `_currency_to_eur_factors()` ile TL/USD → EUR (TCMB
  `forex_selling`, `unit` dikkate alınır). EUR kuru yoksa yalnız EUR sözleşmeler sayılır (şişme yok).

- **Pencere:** `checkin_date >= cari yıl 1 Ocak` (geçmiş yıllar XLS'ten dokunulmadan kalır;
  cari yıl + ileri rezervasyonlar senkronlanır).
- **Aktif-yalnız değişmezliği (kritik):** `occupancy_metrics` rez_status'a **bakmaz** — tablodaki
  HER kaydı sayar. Senkron bu değişmezliği korur: pencere içinde **aktif rezervasyonları upsert**
  (Status≠−1, CancelDate boş), **aktif-olmayan her kaydı siler** (iptal Status=−1 **veya** kaynakta
  silinmiş = fetch'te yok) → tablo Sedna aktif rezervasyonlarının **birebir aynası** olur. XLS'in
  `removal_candidates` akışı yedek olarak korunur.
- **Test:** `tests/test_reservation_sedna.py` (8 test — upsert + iptal silme + süpürme + pencere +
  uçtan uca occupancy_metrics gecelemesi). Orchestrator: `tests/test_sedna_sync.py`.
- **Canlı (7 Haz 2026, 2026+):** 5.788 aktif rezervasyon · 48.651 oda-gece · 105.210 geceleme ·
  net ciro **€5,6M** (EUR 5.456 rez €5,5M + TL 331 rez ₺5,9M→€111K + USD 2) · ADR €116.

## İptal Tespiti — Kapsam Dışı Orphan Temizliği (2026-05-26)

Crystal Reports XLS dosyaları iptal edilen rezervasyonları **listeden tamamen düşürür**
(ayrı bir "Cancelled" status'u ile değil). Önceki sürümde upload akışı yalnızca
upsert (insert/update) yaptığından, kaynakta iptal edilen kayıtlar DB'de hayalet olarak
kalıyor ve dashboard / doluluk metriklerine "aktif rezervasyon" olarak sayılıyordu.

### Akış
1. `POST /reservations/upload` yanıtına `removal_candidates: RemovalCandidate[]` eklenir
   (`routers/sales/reservations/uploads.py:_compute_removal_candidates`)
2. Frontend yükleme sonucu modalında uyarı bloğu gösterir + "Kayıtları İncele" butonu
3. Modal: checkbox listesi (varsayılan: hepsi seçili), seçili toplam EUR'yu canlı gösterir
4. Onaylı silme `POST /reservations/bulk-delete` çağrısı ile yapılır

### Kapsam (Diff Kapsamı)
Aday tespiti **iki katmanlı kısıt** kullanır — yanlış silmeyi engeller:
- **Check-in scope:** `parsed.checkin_start ↔ checkin_end`
- **Record scope:** `parsed.record_start ↔ record_end`

Yüklenen dosyanın *iki tarih aralığına da* düşen DB kayıtlarından dosyadaki `rec_id`
setinde olmayanlar aday gösterilir. Tek yıllık dosya başka yılı etkilemez; "son 3 ay"
dosyası daha eski kayıtlara dokunmaz.

### `POST /reservations/bulk-delete`
- **İzin:** `sales.hotel_reservation` use
- **Body:** `{ ids: int[] }` (rezervasyon `id`'leri — `rec_id` değil)
- **Yanıt:** `{ deleted, skipped, skipped_reasons[] }`
- **DoS koruma:** tek seferde max **5000 ID**, fazlası 400
- **Audit log:** `entity_type=reservation`, `action=bulk_delete`, details JSON:
  `{deleted, skipped, total_eur, context}`
- **WS broadcast:** silme tamamlanırsa `broadcast_sales_update("hotel_reservation", "delete")`

### Korumalı Kayıt Yok (Şimdilik)
Cariler modülünde olduğu gibi `match_number`, `dept_status`, `finance_events` gibi
korumalar burada yok — rezervasyon kayıtlarının başka tabloya bağlanması (örn.
ödeme/banka eşleştirmesi) henüz tasarımda mevcut değil. İlerde
"rezervasyon ↔ fatura" bağı eklenirse `_compute_removal_candidates` ve `bulk-delete`
endpoint'ine korumalı kayıt filtresi eklenmeli.

### Geri Yükleme
Bulk-delete **hard delete** yapar — `bulk_delete` audit log kaydında silinen kayıt
sayısı + toplam EUR saklanır. Kayıt-seviye geri yükleme için daha sonra
`details` alanına tam JSON snapshot eklenebilir (bu sürümde yok; düşük öncelik).

### Test Kapsamı (`tests/test_reservations.py`)
- `test_upload_returns_removal_candidates` — kapsam içi orphan response'a dahil olur
- `test_upload_no_candidates_when_all_present` — aynı dosya 2× → aday boş
- `test_upload_orphan_outside_scope_not_candidate` — kapsam dışı orphan adaylığa girmez
- `test_bulk_delete_removes_records` — verilen ID'ler silinir
- `test_bulk_delete_partial_with_missing_ids` — bulunmayan ID'ler `skipped` sayılır
- `test_bulk_delete_empty_ids` — boş liste no-op
- `test_bulk_delete_over_5000_rejected` — DoS limiti
- `test_bulk_delete_unauthorized` — auth zorunlu

### İlk Çalıştırma (2026-05-26)
İlk uygulamadan önce 100 hayalet kayıt 2026 dönemi içinde "Definite" olarak duruyordu
(toplam ~100.270 EUR, ALLTOURS D / W2M / BYEBYE D ağırlıklı). Manuel SQL DELETE +
audit log JSON snapshot ile temizlendi; sonraki yüklemelerde aynı durum bu yeni
akıştan otomatik tetiklenecek.

## Acente Gruplama (2026-05-22 → 2026-05-23 güncellendi)

Acente Dağılımı bileşenine **Bireysel / Gruplu** toggle ve **Grupları Yönet** modalı eklendi.
Gruplar veritabanında saklanır (`agency_groups` tablosu) — sabit kod yok.

### Veritabanı
**Tablo:** `agency_groups`
- `id` (PK), `name` (UNIQUE 100), `members` (JSON array of agency names), `created_at`, `updated_at`
- Migration: `7d052738619a_add_agency_groups_table.py` — 7 başlangıç grubu seed eder
  (ALLTOURS, ANEX, BYEBYE, CORAL, WEBRES, MUNFERIT, LIBERO)

### Backend Endpoint'leri (`/api/sales/agency-groups/`)
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/` | view | Tüm grupları listele |
| POST | `/` | use | Yeni grup oluştur |
| PATCH | `/{id}` | use | Grup adı/üyeleri güncelle |
| DELETE | `/{id}` | use | Grubu sil |
| POST | `/assign` | use | **Atomik atama** — acenteyi gruba ekle / gruptan çıkar (drag-drop için) |

`/assign` body: `{ agency_name: str, target_group_id: int \| null }`
- `target_group_id` verildiyse: acenteyi varsa mevcut grubundan çıkar, hedefe ekle
- `target_group_id=null`: acenteyi tüm gruplardan çıkar (bireysel yap)
- Aynı gruptaysa no-op
- Dönüş: güncellenmiş tüm grupların listesi (frontend tek istekle state'i tazeler)
- Audit: `entity_type='agency_group_assign'`, details: `{agency_name, target_group_id, target_group_name, removed_from[]}`

### Frontend State
- `agencyGroups: ApiGroup[]` — API'den yüklenen gruplar (`onMount` → `loadAgencyGroups()`)
- `agencyToGroup: Record<string, string>` — `$derived` ad→isim eşlemesi
- `agencyToGroupId: Record<string, number>` — `$derived` ad→id eşlemesi
- `groupedAgencies()` — `$derived` hesaplanmış liste; her eleman `type: 'group' | 'individual'`
- `agencyViewMode: 'individual' | 'grouped'`
- `expandedGroups: Set<string>` — açık grupları tutar

### Drag & Drop (Mouse/Trackpad)
**HTML5 native DnD** — `draggable={true}` + `ondragstart/over/drop`. Touch cihazlarda çalışmaz; mobil/tablet kullanıcılar Grupları Yönet modalını kullanır.
- Drag source: hem bireysel acenteler hem grup üyeleri (her satırın solunda `GripVertical` ikonu)
- Drop targets:
  1. **Grup satırı** → acenteyi o gruba ekle (`assignAgencyToGroup(name, groupId)`)
  2. **"Gruptan çıkar" alanı** → yalnızca gruba ait acente sürüklenirken görünür; bırakınca acenteyi tüm gruplardan çıkarır
- Görsel geri bildirim: sürüklenen satır `opacity-40`, drop hedefi `ring-2 ring-teal-300` (gruplar) veya `border-rose-400` (çıkar zone)
- Tek API çağrısı (`POST /assign`) — backend mevcut grubu tespit edip atomik günceller, race-condition yok
- Toast bildirim: başarıda `{acente} → {grup} grubuna eklendi` veya `gruptan çıkarıldı`

### Grupları Yönet Modal
- Liste görünümü: tüm gruplar üye chip'leriyle + Lucide `Settings2` (düzenle) / `Trash2` (sil) ikonları + "+ Yeni Grup" butonu
- Form görünümü: grup adı + üye arama/ekleme (autocomplete sadece `summary.by_agency`'de görünen ve başka gruba ait olmayan acenteleri önerir) + üye chip'lerinden X ile çıkarma
- Modal kapanışında `$effect` ile state otomatik temizlenir (kapanış yolundan bağımsız)
- Footer slotu yok — butonlar içerik bölümünün altına `border-t` ile ayrılmış flex div'de
