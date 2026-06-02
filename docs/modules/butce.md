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

### Kategori Silme
- Bütçe kaydında veya faturada kullanılan kategori silinemez
- Silme öncesi `budgets` ve `invoices` tablolarında kullanım kontrolü yapılır

### finance_events Entegrasyonu
- Bütçe modülü şu an `finance_events` tablosuna yazmaz (para hareketi değil, planlama verisi)
- İleride gerçekleşen bütçe ile nakit akım karşılaştırması yapılabilir
