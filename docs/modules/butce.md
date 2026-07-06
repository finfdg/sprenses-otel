# Bütçe Modülü

## Genel Bilgi

| Alan | Değer |
|---|---|
| Modül kodu | `finance.butce` |
| Üst modül | `finance` |
| Frontend rota | `/dashboard/finans/butce` |
| Backend prefix | `/api/finance/butce` |
| İzin kodu | `finance.butce` (view/use) |

## Dosya Haritası

### Backend
| Dosya | Açıklama |
|---|---|
| `app/models/budget.py` | `BudgetCategory`, `Budget` modelleri |
| `app/models/department.py` | `Department` modeli (ilişki) |
| `app/schemas/budget.py` | Pydantic şemaları |
| `app/routers/finance/butce.py` | Router — CRUD + özet endpoint'leri |

## Veritabanı Şeması

### budget_categories
| Kolon | Tip | Açıklama |
|---|---|---|
| id | int (PK) | |
| name | varchar(100) | Kategori adı |
| type | varchar(10) | "income" veya "expense" |
| is_active | boolean | Aktif mi |
| sort_order | int | Sıralama |
| created_at | timestamptz | |

Unique constraint: `(name, type)`

### budgets
| Kolon | Tip | Açıklama |
|---|---|---|
| id | int (PK) | |
| department_id | int (FK) | Departman |
| category_id | int (FK) | Bütçe kategorisi |
| year | int | Yıl |
| month | int | Ay (1-12) |
| planned_amount | numeric(15,2) | Planlanan tutar |
| actual_amount | numeric(15,2) | Gerçekleşen tutar |
| currency | varchar(5) | Para birimi (varsayılan TRY) |
| notes | text | Notlar |
| created_by | int (FK) | Oluşturan kullanıcı |
| created_at | timestamptz | |
| updated_at | timestamptz | |

Unique constraint: `(department_id, category_id, year, month)`

## API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | /kategoriler | view | Kategori listesi (type filtresi) |
| POST | /kategoriler | use | Kategori oluştur |
| PATCH | /kategoriler/{cat_id} | use | Kategori güncelle |
| DELETE | /kategoriler/{cat_id} | use | Kategori sil (kullanım kontrolü) |
| GET | / | view | Bütçe listesi (yıl zorunlu, ay/departman opsiyonel) |
| POST | / | use | Bütçe upsert (tek kayıt) |
| POST | /bulk | use | Toplu bütçe upsert |
| DELETE | /{budget_id} | use | Bütçe kaydı sil |
| GET | /years | view | Bütçe kaydı olan distinct yıllar (yıl seçici — sabit dizi değil) |
| GET | /summary | view | Yıllık departman bazlı özet |
| GET | /monthly-summary | view | 12 aylık gelir/gider dağılımı |

## Audit Log Entegrasyonu

| entity_type | Eylemler |
|---|---|
| `budget_category` | create, update, delete |
| `budget` | create, update, delete |

## Geliştirme Kuralları

### Upsert Mantığı
- Bütçe kaydı `(department_id, category_id, year, month)` dörtlüsüne göre unique
- POST `/` ve POST `/bulk` upsert yapar: kayıt varsa `planned_amount` güncellenir, yoksa yeni oluşturulur
- Upsert sırasında `actual_amount` değiştirilmez (gerçekleşen tutar fatura/ödeme entegrasyonuyla güncellenir)
- **Her ikisi de `budget_service.upsert_budget` (kompozit-anahtar) kullanır** — router + onay executor ORTAK; elle `Budget()` insert/update yoktur (çift-bütçe drift'i engellenir)
- **Onay akışı:** Hem POST `/` hem POST `/bulk` `check_approval`'dan geçer (bulk grid'deki her hücre kaydının normal yoludur, operasyonel içe-aktarma değil → onaydan muaf DEĞİL). Executor `_target="bulk"` dalı bulk payload'ını birebir yeniden uygular. (2026-07-01 denetim düzeltmesi.)

### Kategori Silme
- Bütçe kaydında veya cari işleminde kullanılan kategori silinemez
- Silme öncesi `budgets` ve `vendor_transactions` (`budget_category_id`) tablolarında kullanım kontrolü yapılır

### finance_events Entegrasyonu
- Bütçe modülü şu an `finance_events` tablosuna yazmaz (para hareketi değil, planlama verisi)
- İleride gerçekleşen bütçe ile nakit akım karşılaştırması yapılabilir

### Yıl seçici — dinamik (2026-07-06 hata düzeltmesi)
- Yıl açılır menüsü eskiden **`[2025, 2026, 2027, 2028]` sabit dizisiydi** → dizinin dışındaki
  (gelecek) yıllara ait bütçe menüde görünmüyor, erişilemiyordu (SGK'da yaşanan gizli-yıl hatasının aynısı).
- **Çözüm — veriden türet:** `GET /finance/butce/years` distinct `Budget.year` döner. Budget'ta
  GET `/{id}` rotası yok (yalnız DELETE) → yıl rotası ÖZET bölümünde tanımlı; yine de path-param
  çakışması olmadan güvenli.
- Frontend `loadYears()` bu endpoint'i çeker, **cari yıl ±1 + `selectedYear`** penceresiyle birleştirir
  (`yearOptions`); `onMount` + `finance_updated` WS event'inde yenilenir; fetch hata verirse base
  pencereye düşer. Referans desen: `ScheduledModule.svelte` / `docs/modules/muhasebe-ik.md` "Yıl seçici — dinamik".
