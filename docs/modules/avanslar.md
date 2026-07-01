# Alınan Avanslar Modülü

## Genel Bilgi

| Alan | Değer |
|---|---|
| **Modül Kodu** | `finance.avanslar` |
| **Üst Modül** | `finance` (Finans) |
| **Frontend Rota** | `/dashboard/finans/avanslar` |
| **Backend Prefix** | `/api/finance/avanslar` |
| **İzin Kodu** | `finance.avanslar` (view/use) |

## Dosya Haritası

### Backend
| Dosya | Açıklama |
|---|---|
| `backend/app/models/advance.py` | SQLAlchemy model |
| `backend/app/schemas/advance.py` | Pydantic şemaları |
| `backend/app/routers/finance/advances.py` | API router |

### Frontend
| Dosya | Açıklama |
|---|---|
| `frontend/src/routes/dashboard/finans/avanslar/+page.svelte` | Ana sayfa |

## Veritabanı Şeması

### `advances` Tablosu

| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | `SERIAL PRIMARY KEY` | Birincil anahtar |
| `agency_name` | `VARCHAR(200)` | Acente/Operatör adı |
| `amount` | `NUMERIC(15,2)` | Avans tutarı |
| `currency` | `VARCHAR(5)` | Para birimi (EUR/USD/TRY) |
| `advance_date` | `DATE` | Beklenen avans tarihi |
| `status` | `VARCHAR(20)` | Durum: pending/received/cancelled |
| `notes` | `TEXT` | Notlar (isteğe bağlı) |
| `bank_transaction_id` | `INTEGER FK` | Banka eşleştirme (opsiyonel) |
| `received_date` | `DATE` | Gerçek alınma tarihi |
| `received_amount` | `NUMERIC(15,2)` | Gerçek alınan tutar |
| `created_by` | `INTEGER FK` | Oluşturan kullanıcı |
| `created_at` | `TIMESTAMPTZ` | Oluşturulma zamanı |
| `updated_at` | `TIMESTAMPTZ` | Güncellenme zamanı |

**İndeksler:** `ix_advances_date`, `ix_advances_status`

## API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| `GET` | `/avanslar/` | view | Liste (sayfalı, filtrelenebilir) |
| `GET` | `/avanslar/summary` | view | Özet (para birimine göre) |
| `GET` | `/avanslar/sedna-reconciliation` | view | Sedna 340 hesap mutabakatı (isim+para birimi eşleştirme skoru) |
| `POST` | `/avanslar/` | use | Yeni avans oluştur |
| `PATCH` | `/avanslar/{id}` | use | Avans güncelle |
| `DELETE` | `/avanslar/{id}` | use | Avans sil (sadece pending) |
| `POST` | `/avanslar/{id}/match` | use | Banka eşleştirme (alındı) |

## Nakit Akım Entegrasyonu

- `status != "cancelled"` ve `bank_transaction_id IS NULL` olan avanslar nakit akıma `source="advance"`, `type="income"` olarak eklenir
- Banka eşleşmesi olan avanslar nakit akımda banka tarafından gösterilir (çift sayım engellenir)

## Audit Log Entegrasyonu

| entity_type | Eylemler |
|---|---|
| `advance` | create, update, delete |

## Geliştirme Kuralları

- Alınmış (`received`) avanslar silinemez
- İptal edilmiş (`cancelled`) avanslar eşleştirilemez
- Avans tarihi, beklenen giriş tarihidir; gerçek alınma tarihi `received_date` alanındadır
