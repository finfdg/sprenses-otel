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
├── listing.py          # GET / (sayfalanmış liste)
├── summary.py          # GET /summary (KPI + dağılımlar + doluluk metrikleri)
├── occupancy.py        # GET /daily-occupancy?month=YYYY-MM (aylık drill-down)
└── _helpers.py         # _apply_filters, _parse_date, _resolve_date_range, _month_days_in_range, UPLOAD_DIR
```

## İptal Tespiti — Kapsam Dışı Orphan Temizliği (26 Mayıs 2026)

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

### İlk Çalıştırma (26 Mayıs 2026)
İlk uygulamadan önce 100 hayalet kayıt 2026 dönemi içinde "Definite" olarak duruyordu
(toplam ~100.270 EUR, ALLTOURS D / W2M / BYEBYE D ağırlıklı). Manuel SQL DELETE +
audit log JSON snapshot ile temizlendi; sonraki yüklemelerde aynı durum bu yeni
akıştan otomatik tetiklenecek.

## Acente Gruplama (22 Mayıs 2026 → 23 Mayıs 2026 güncellendi)

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
- Liste görünümü: tüm gruplar üye chip'leriyle + ✏ düzenle / 🗑 sil ikonları + "+ Yeni Grup" butonu
- Form görünümü: grup adı + üye arama/ekleme (autocomplete sadece `summary.by_agency`'de görünen ve başka gruba ait olmayan acenteleri önerir) + üye chip'lerinden X ile çıkarma
- Modal kapanışında `$effect` ile state otomatik temizlenir (kapanış yolundan bağımsız)
- Footer slotu yok — butonlar içerik bölümünün altına `border-t` ile ayrılmış flex div'de
