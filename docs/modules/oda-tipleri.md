# Oda Tipleri Modülü

> **2026-07-09 — MODÜL BİRLEŞTİRİLDİ:** Bu kabiliyet artık ayrı bir modül DEĞİL;
> **Acente Mahsup & Nakit Akım** (`sales.acente_mahsup`) birleşik satış sayfasının bir
> sekmesidir. Eski modül kodu/rotası kaldırıldı (migration `b3c9d5e7f1a2`); backend
> endpoint path'leri aynı kaldı, izinler `sales.acente_mahsup` view/use oldu.
> Genel bakış: `docs/modules/acente-mahsup.md`. Aşağıdaki teknik detaylar geçerliliğini korur.

## Genel Bilgi

| Alan | Değer |
|---|---|
| **Modül kodu** | `sales.acente_mahsup` (eski: `sales.room_types`) |
| **Üst modül** | `sales` (Satış) |
| **Frontend** | `/dashboard/satis/acente-mahsup?tab=oda` (`lib/components/sales/RoomTypesPanel.svelte`) |
| **Backend prefix** | `/api/sales/room-types` |
| **İzin seviyeleri** | `view` (sayfayı gör) · `use` (oda tipi ekle/düzenle/sil) |
| **Onay akışı** | Var — POST/PATCH/DELETE `check_approval` üzerinden geçer |

## Amaç

Otelin **fiziksel oda envanterini** tutar. Otel Rezervasyon modülündeki
`reservations.room_type` değeri burada tanımlanan `code` ile eşleşir.
`total_rooms` toplamı, doluluk (occupancy) hesabında **payda** olarak kullanılır:

```
doluluk_% = total_room_nights / (Σ aktif_tip.total_rooms × gün_sayısı) × 100
```

Bu modül **olmadan otel rezervasyon dashboard'undaki doluluk metrikleri %0** görünür.

## Dosya Haritası

### Backend
| Dosya | Açıklama |
|---|---|
| `backend/app/models/room_type.py` | `RoomType` ORM modeli (code unique, check constraint'ler) |
| `backend/app/schemas/room_type.py` | `RoomTypeCreate/Update/Response/ListResponse` Pydantic şemaları |
| `backend/app/routers/sales/room_types.py` | CRUD endpoint'leri |
| `backend/alembic/versions/e9f3b7d2c5a4_add_room_types_module.py` | Tablo + modül + Admin yetkisi + 9 oda tipi seed |
| `backend/tests/test_room_types.py` | CRUD + doluluk hesabı testleri (13 test) |

### Frontend
| Dosya | Açıklama |
|---|---|
| `frontend/src/lib/components/sales/RoomTypesPanel.svelte` | CRUD sekmesi — tablo + modal + canlı toplam doğrulama |
| `frontend/src/lib/components/Sidebar.svelte` | Satış grubunda menü öğesi |

## Veritabanı Şeması

### `room_types`

| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | int PK | |
| `code` | varchar(40) UNIQUE | Rezervasyon XLS'indeki Type sütunuyla eşleşmeli (örn. `STD KARA`, `J.SUITE`) |
| `name` | varchar(120) | İnsanın okuyabileceği isim (örn. `Standart Kara Manzaralı`) |
| `total_rooms` | int, default 0, **CK ≥ 0** | Bu tipte fiziksel oda sayısı |
| `max_occupancy` | int, default 2, **CK ≥ 1** | Maks. kişi (yetişkin + çocuk + bebek) |
| `sort_order` | int, default 0, indexed | Liste sıralama |
| `is_active` | bool, default true, indexed | Pasif tipler doluluk hesabına dahil edilmez |
| `description` | text | Opsiyonel açıklama |
| `created_at`, `updated_at` | timestamptz | |

### Seed (migration ile)

Migration `e9f3b7d2c5a4` toplam **341 oda**'lık tahmini dağılımı seed eder:

| Code | Name | total_rooms | max_occupancy |
|---|---|---|---|
| STD KARA | Standart Kara Manzaralı | 126 | 3 |
| STD DNZ | Standart Deniz Manzaralı | 96 | 3 |
| SIDE SEA V | Side Deniz Manzaralı | 52 | 3 |
| FAM DNZ | Aile Odası Deniz Manzaralı | 21 | 4 |
| DBP | Dubleks | 16 | 4 |
| J.SUITE | Junior Suite | 14 | 4 |
| DBL POOL V | Çift Yataklı Havuz Manzaralı | 14 | 3 |
| SUIT DNZ | Suite Deniz Manzaralı | 1 | 4 |
| TERASLI S. | Teraslı Suite | 1 | 4 |
| **TOPLAM** | | **341** | |

Bu değerler rezervasyon hacmine orantılı tahmindir. Gerçek otel envanteriyle
uyumsuz olabilir; CRUD sayfasından düzeltilmesi beklenir. Sayfa üst kısmındaki
"Hedef 341 / Toplam X / Fark Y" göstergesi tutarlılığı izler.

## API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/api/sales/room-types/?include_inactive=false` | view | Liste + `total_capacity` (aktif tiplerin toplamı) + `active_count` |
| GET | `/api/sales/room-types/{id}` | view | Tek kayıt detayı |
| POST | `/api/sales/room-types/` | use | Yeni oda tipi (code uppercase + strip ile normalize edilir) |
| PATCH | `/api/sales/room-types/{id}` | use | Kısmi güncelleme — `exclude_unset` |
| DELETE | `/api/sales/room-types/{id}` | use | Sil — bağlı rezervasyon varsa **400** (pasif yapma önerisi) |

### Response örneği — `GET /`

```json
{
  "items": [
    { "id": 1, "code": "STD KARA", "name": "Standart Kara Manzaralı",
      "total_rooms": 126, "max_occupancy": 3, "sort_order": 10,
      "is_active": true, "description": null,
      "created_at": "2026-05-21T09:00:00+03:00",
      "updated_at": "2026-05-21T09:00:00+03:00" },
    ...
  ],
  "total_capacity": 341,
  "active_count": 9
}
```

## Doluluk Hesabı Entegrasyonu

### `/api/sales/reservations/summary` — eklenen alanlar

**`KpiData`** içine 3 alan eklendi:

```jsonc
{
  "kpi": {
    "total_capacity": 341,          // SUM(room_types.total_rooms WHERE is_active)
    "date_range_days": 318,         // Filtreden veya rezervasyonların min/max'ından
    "occupancy_pct": 41.72,         // total_room_nights / (capacity × days) × 100
    // ... mevcut alanlar
  }
}
```

**`MonthlyRow`** içine `capacity_nights`, `empty_nights`, `occupancy_pct` eklendi:

```jsonc
{ "month": "2026-05", "room_nights": 8270, "capacity_nights": 10571,
  "empty_nights": 2301, "occupancy_pct": 78.23, ... }
```

- `capacity_nights` = `total_capacity × _month_days_in_range(y, m, range_start, range_end)` — o ayın toplam mevcut oda-gece sayısı
- `empty_nights` = `max(capacity_nights - room_nights, 0)` — bar grafiğinde gri kısım
- Filtre dışına taşan aylar (`capacity_nights = 0`) listeden **atlanır** — örn. filtre `2026` ise 2027-01'e taşan birkaç gün gösterilmez

Frontend bar grafiği `occupancy_pct` bazlı çizilir (0-100% arası), etikette dolu/boş oda-gece + ciro birlikte görünür.

**`TypeRow`** içine `total_rooms` + `occupancy_pct` eklendi — tip başına:

```jsonc
{ "name": "STD KARA", "total_rooms": 126, "room_nights": 16950,
  "occupancy_pct": 42.3, ... }
```

Tip başına doluluk: `type_room_nights / (type_capacity × date_range_days) × 100`.

### Tarih aralığı çözümü (`_resolve_date_range`)

1. Filtreden hem `start_date` hem `end_date` verildi → `(end - start + 1)` gün
2. Filtre kısmi/yoksa → rezervasyonların `min(checkin) ↔ max(checkout)` aralığı
3. Hiç rezervasyon yoksa → (None, None, 0)

`checkout` exclusive (rezervasyonlar konaklamanın son gecesinden sonraki gün ayrılır),
gün sayısı = `(max_checkout - min_checkin).days`.

## Frontend UI Yapısı

| Bölüm | Açıklama |
|---|---|
| **Header** | Başlık + "Pasif tipleri göster" toggle + "Yeni Tip" butonu (use yetkisi) |
| **Stat kartları** | Toplam Oda · Aktif Tip · Hedef (341 → uyum kontrolü) |
| **Tablo** | code (mono) · name · total_rooms (teal badge) · max_occupancy · is_active (yeşil/gri) · İşlemler (Düzenle/Sil) |
| **Tfoot** | Aktif tiplerin total_rooms toplamı (canlı) |
| **Modal — Oluştur/Düzenle** | code (auto-uppercase) · name · total_rooms · max_occupancy · sort_order · is_active checkbox · description |
| **Projeksiyon banner** | Kayıttan sonraki toplam: `X / 341 ✓` veya fark gösterimi (yeşil/sarı/gri) |
| **ConfirmDialog** | Silme onayı + rezervasyon engeli mesajı |

### Renkler
- Toplam Oda: `bg-white` + `text-teal-700` (ana metrik)
- Hedef kartı: `text-amber-600` (uyumsuzsa dikkat çekici)
- total_rooms badge: `bg-teal-50 text-teal-700`
- max_occupancy badge: `bg-gray-50`
- is_active: yeşil (aktif) / gri (pasif)

## Audit Log

- `entity_type=room_type`, `action=create` — details: `"{code} — {name} ({total_rooms} oda)"`
- `entity_type=room_type`, `action=update` — details: aynı format
- `entity_type=room_type`, `action=delete` — details: `"{code} — {name}"`

## Geliştirme Kuralları

1. **`code` ile `reservations.room_type` arasındaki eşleşme zorunludur.** XLS'teki yeni bir tip kodu varsa, doluluk hesabında 0 oda olarak görünür → CRUD ekranından eklenmesi gerekir. Yeni tip eşleşmediği için doluluk %0 göstermesi tipik hata kaynağı — kullanıcıyı uyaracak bir badge eklenebilir.
2. **`is_active=false` olan tipler doluluk hesabından düşülür.** Mevsimlik kapatılan blok için kullanılabilir. Pasifken o tipte rezervasyon olursa `by_room_type`'da tip görünür ama `total_rooms=0`, `occupancy_pct=0` döner.
3. **Silme yerine pasif yap:** Endpoint, bağlı rezervasyon olduğunda 400 döner ve pasif yapmayı önerir. Frontend ConfirmDialog mesajında da belirtilir.
4. **Unique constraint:** `code` global benzersizdir. Multi-tenant'a geçişte `(hotel_id, code)` composite unique olmalı.
5. **Onay akışı:** Tüm CRUD `check_approval` çağrısıyla sarılı — onay workflow'u tanımlıysa 202 döner.

## Test

13 test (`tests/test_room_types.py`):

**CRUD (10 test)**
- Liste — boş, aktif toplam, include_inactive
- Oluştur — başarılı (code uppercase normalize), duplicate engellenir, validation hataları
- Güncelle — başarılı, 404
- Sil — başarılı, rezervasyon varsa engellenir
- Yetki — auth gerekli

**Doluluk entegrasyonu (3 test)**
- `test_summary_occupancy_calculations` — KPI + tip başına doluluk doğruluğu
- `test_summary_occupancy_no_room_types` — room_types boşken hata vermez, %0 döner
- `test_summary_occupancy_monthly_distribution` — aylar arası uzayan rez için ay başına doluluk hesabı

Çalıştırma:
```bash
cd backend && source venv/bin/activate
DATABASE_URL=postgresql://...:.../sprenses_test pytest tests/test_room_types.py -v
```

Conftest fixture: `_REQUIRED_MODULE_CODES`'a `sales.room_types` eklenmiştir — conftest yeni modülü test DB'de otomatik oluşturur ve admin'e yetki verir. Her test başında `_wipe_room_types` autouse fixture'ı tabloyu temizler (migration seed'iyle bağımsızlık).
