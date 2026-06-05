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
- Şu an **tanımlama** modülüdür (vardiya türleri). Sonraki adım (v2): personele vardiya **atama** +
  puantajda planlanan-vardiya ile gerçek basış karşılaştırması (geç kalma/erken çıkış).
- Modül kaydı: prod'da SQL ile `modules`/`role_module_permissions`; CI parite `tests/ci/02_seed.sql` (id 902).
