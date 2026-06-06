# Vardiyalar (Shift) Modülü

Otel 7/24 çalıştığı için çalışanlar vardiyalara bölünür. Bu modül **vardiya tanımlarını**
(Sabah / Akşam / Gece / Split) yönetir.

## Genel Bilgi
- **Modül kodu:** `hr.shifts` (üst modül: `hr` / İnsan Kaynakları)
- **Frontend rota:** `/dashboard/ik/vardiyalar` · **İzin:** `hr.shifts`
- **Backend prefix:** `/api/hr/shifts`
- **İzin verilen roller (varsayılan):** Admin, İk Müdürü, Finans Müdürü (view+use)

## Vardiya Düzenleri (otel standardı)
| Vardiya | Tipik Saat | Açıklama |
|---|---|---|
| Sabah | 07:00–15:00 / 08:00–16:00 | Resepsiyon, Kat Hizmetleri, kahvaltı servisi |
| Akşam | 14:00–22:00 / 15:00–23:00 | Akşam yemeği, yoğun check-in/out |
| Gece | 23:00–07:00 / 22:00–08:00 | Night Audit, Güvenlik, Temizlik (gün aşar) |
| Split | ör. 07:00–11:00 + 18:00–22:00 | Restoran / banquet (iki segment) |

Migration 3 örnek seed eder (Sabah/Akşam/Gece).

## Veritabanı — `shift_definitions`
- id, **name**, **color** (#hex), **start_time**, **end_time** (Time),
- **start_time2** / **end_time2** (Time, nullable — split vardiya 2. segment),
- description, is_active, sort_order, created_at.

## Süre / Gece Mantığı
- **Süre** = segment(start→end) [+ segment2]. `_seg_minutes`: `end <= start` ise +24sa (gece yarısını geçer).
- **`crosses_midnight`** = `end_time <= start_time` (ör. Gece 23:00–07:00 → True).
- **`is_split`** = start_time2 & end_time2 dolu.
- Yanıtta `duration_minutes` + `duration_hours` döner.

## API
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/hr/shifts` | hr.shifts view | Vardiya tanımları (süre/gece/split dahil) |
| POST | `/hr/shifts` | hr.shifts use | Yeni vardiya (onay akışına tabi) |
| PATCH | `/hr/shifts/{id}` | hr.shifts use | Güncelle |
| DELETE | `/hr/shifts/{id}` | hr.shifts use | Sil |

## Frontend
- Renk-kodlu **kart ızgarası** (üst şerit = renk): ad + saat aralığı (+2. segment) + süre + "Gece"/"Split"/"Pasif" rozetleri + açıklama.
- Ekle/Düzenle modalı: ad, renk seçici (8 renk), başlangıç/bitiş (`type="time"`), **split toggle** → 2. segment, açıklama, aktif.
- Stat kart: Toplam Vardiya · Aktif.

## Onay Akışı
- POST/PATCH/DELETE → `check_approval(db, "hr.shifts", …)`. Aktif workflow + requestor rolü varsa **202 → onaya düşer**.
- Onay executor: `approval_executor._handle_shifts` (create/update/delete; zaman alanları "HH:MM:SS" string → time parse).

## Audit Log
- entity_type: `shift`. Eylemler: create/update/delete.

## Geliştirme Notları
- Bu modül **vardiya tanımlamasıdır** (türler). Personele tarih bazlı **atama** ayrı bir
  modülde yapılır → aşağıdaki **Vardiya Çizelgesi (Rota)**. Sonraki adım (v3): puantajda
  planlanan-vardiya ile gerçek basış karşılaştırması (geç kalma/erken çıkış).
- Modül kaydı: prod'da SQL ile `modules`/`role_module_permissions`; CI parite `tests/ci/02_seed.sql` (id 902).

---

# Vardiya Çizelgesi (Rota) Modülü

Tarih bazlı rota: **hangi gün kim hangi vardiyada**. Vardiya *tanımlarını* kullanır,
personele gün gün vardiya atar. Haftalık grid üzerinden planlanır.

## Genel Bilgi
- **Modül kodu:** `hr.shift_schedule` (üst modül: `hr`)
- **Frontend rota:** `/dashboard/ik/vardiya-cizelgesi` · **İzin:** `hr.shift_schedule`
- **Backend prefix:** `/api/hr/shift-schedule`
- **İzin verilen roller (varsayılan):** Admin, İk Müdürü, Finans Müdürü (view+use)
- **Modül id:** 903 (prod + CI seed)

## Veri Modeli — `shift_assignments`
- id, **personnel_id** (FK personnel, CASCADE), **shift_id** (FK shift_definitions, CASCADE),
  **work_date** (Date), note, created_by (FK users, SET NULL), created_at, updated_at.
- **Benzersiz:** `(personnel_id, work_date)` → bir personel bir günde **tek** vardiyada
  (split vardiya tek tanımdır, iki segmenti vardır). **Kayıt yoksa o gün izinli/boş.**
- Personel veya vardiya tanımı silinirse atamalar DB düzeyinde CASCADE ile gider.
- İndeksler: work_date, shift_id (+ unique composite personnel_id'yi karşılar).

## İş Kuralları
- **Hücre = bir personelin bir gündeki vardiyası.** Atama upsert'tir: aynı (personel, gün)
  için tekrar atama vardiyayı değiştirir (yeni satır açmaz, `id` sabit kalır).
- **GET aralığı en fazla 45 gün** (haftalık/aylık görünüm; aşılırsa 400).
- **Toplu işlem en fazla 2000 hücre** (personel × tarih).
- GET yanıtı **kendi içinde yeterli**: aktif vardiyalar + aktif personel + atamalar +
  departman listesi (filtre dropdown'ı için) tek çağrıda döner → sayfa yalnızca
  `hr.shift_schedule` iznine ihtiyaç duyar (personel listesi için `hr.attendance` gerekmez).

## API
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/hr/shift-schedule?start&end&department` | view | Aralık rota (shifts+personnel+assignments+departments) |
| POST | `/hr/shift-schedule` | use | Tek hücre ata (upsert) — **onay akışına tabi** |
| DELETE | `/hr/shift-schedule/{id}` | use | Hücreyi sil (çıkar) — **onay akışına tabi** |
| POST | `/hr/shift-schedule/bulk` | use | Toplu ata/temizle (shift_id=null → sil) — **onaydan muaf** |
| POST | `/hr/shift-schedule/copy-week` | use | Kaynak haftayı hedefe kopyala — **onaydan muaf** |

## Onay Akışı
- **Tek hücre** atama (POST) ve çıkarma (DELETE) `check_approval(db, "hr.shift_schedule", …)`
  ile onay kontrolünden geçer. Aktif workflow + requestor rolü varsa **202 → onaya düşer**;
  onaylanınca executor `_handle_shift_schedule` upsert/siler. POST create entity_id=0 (upsert).
- **Toplu işlemler** (`/bulk`, `/copy-week`) onay akışından **muaftır** — CLAUDE.md'nin
  "toplu işlem" istisnası. Rota bir planlama yüzeyidir; çoğu kurulumda buna workflow konmaz.

## Gerçek Zamanlılık (polling yok)
- Mutasyonlardan sonra `WSEvent.SHIFT_SCHEDULE_UPDATED` yayınlanır; açık çizelge ekranları
  **600 ms debounce** ile tazelenir. Onaylanınca `APPROVAL_STATUS_CHANGED` (module_code=
  `hr.shift_schedule`) da tazeler. Sabit: `constants.py` ↔ `realtime.ts` (birebir).

## Frontend (haftalık grid)
- **PageHeader** + hafta navigasyonu (‹ Bu Hafta ›) + arama (debounce'suz, in-memory) +
  departman dropdown. Stat kartlar: Personel · Aktif Vardiya · Atanan · **Doluluk %**.
- **Grid (md+):** sticky personel sütunu + 7 gün; hücre = renkli vardiya çipi (kontrast-bilinçli
  metin rengi `textOn`) veya boş `+`. Bugün/haftasonu sütunları vurgulu. Gün başlığında
  "{n} kişi".
- **Mobil (`<md`):** geniş grid yerine **tek-gün liste görünümü** — üstte yatay kaydırılan gün
  seçici (Pzt…Paz + kişi sayısı), altında seçili günün personel listesi (ad + vardiya çipi).
  Satıra dokun → fırça uygula / hücre modalı (grid ile aynı `onCell`). "Günü doldur" kısayolu.
  Fırça çubuğu mobilde de görünür; arama/departman tam genişlik.
- **Fırça (boyama) modu:** üstte vardiya çipleri + "Seçim" + "İzinli/Sil". Fırça seçiliyken
  hücreye tıkla → anında uygula (optimistik). Fırça "Seçim"deyse → hücre modalı (vardiya seç).
- **Toplu doldur:** gün başlığına tıkla → o günü tüm görünür personele uygula (onaylı diyalog);
  personel satırındaki fırça → o kişinin tüm haftası. **Geçen Haftayı Kopyala** butonu.
- Tasarım sistemi: Button/PageHeader/StatCard/Modal/ConfirmDialog/EmptyState, Lucide, teal-700, AA.

## Audit Log
- entity_type: `shift_assignment`. Eylemler: create / delete / bulk.

## Test
- `backend/tests/test_shift_schedule.py` (9 test): izin geçitleri, GET yapısı, atama/upsert/
  silme, 404, toplu ata/temizle, hafta kopyalama, aralık + boş-toplu doğrulaması.
- Executor handler `tests/test_approval_system.py::TestExecutorImportIntegrity` (AST) ile doğrulanır.
