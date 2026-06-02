# Çekler Modülü

## Genel Bilgi

| Alan | Değer |
|---|---|
| **Modül kodu** | `finance.checks` |
| **Üst modül** | Finans (`finance`) |
| **Frontend rota** | `/dashboard/finans/cekler` |
| **Backend prefix** | `/api/finance/checks` |
| **İzin kodu** | `finance.checks` |
| **İzin seviyeleri** | `can_view` (görme), `can_use` (yükleme + durum güncelleme + silme) |

---

## Dosya Haritası

### Backend
| Dosya | Açıklama |
|---|---|
| `app/routers/finance/checks.py` | Ana router — yükleme, listeleme, durum güncelleme, banka eşleştirme |
| `app/models/check.py` | `Check`, `CheckUpload` modelleri |
| `app/utils/check_parser.py` | Excel çek dosyası ayrıştırıcı |
| `app/schemas/check.py` | Pydantic şemalar |

### Frontend
| Dosya | Açıklama |
|---|---|
| `src/routes/dashboard/finans/cekler/+page.svelte` | Ana sayfa — çek tablosu, yükleme, durum güncelleme |

---

## Veritabanı Şeması

### `checks`
| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | integer PK | |
| `upload_id` | integer FK → check_uploads | Hangi yüklemeden geldi |
| `check_type` | varchar(20) | Çek türü (verilecek, alınacak) |
| `sequence_no` | varchar(50) | Sıra numarası |
| `check_no` | varchar(50) | Çek numarası |
| `vendor_code` | varchar(50) | Cari kodu |
| `vendor_name` | varchar(200) | Cari adı |
| `description` | text | Açıklama |
| `city` | varchar(100) | Şehir |
| `due_date` | date | Vade tarihi |
| `amount_tl` | numeric(15,2) | TL tutarı |
| `currency` | varchar(3) | Döviz kodu |
| `amount_currency` | numeric(15,2) | Döviz tutarı |
| `transaction_type` | varchar(50) | İşlem tipi |
| `status` | varchar(20) | Durum: pending, cashed, returned, cancelled |
| `bank_transaction_id` | integer FK → bank_transactions | Banka eşleşmesi |
| `created_at` | timestamptz | |

### `check_uploads`
| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | integer PK | |
| `file_name` | varchar(255) | Orijinal dosya adı |
| `file_url` | varchar(500) | Sunucu dosya yolu |
| `total_checks` | integer | Toplam çek sayısı |
| `new_checks` | integer | Yeni eklenen |
| `skipped_checks` | integer | Mükerrer (atlandı) |
| `uploaded_by` | integer FK → users | |
| `uploaded_at` | timestamptz | |

**İndeksler:** `ix_check_due_date`, `ix_check_vendor`, `ix_check_status`, unique `(check_no, vendor_code, due_date)`

---

## API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| `POST` | `/checks/upload` | use | Excel çek dosyası yükle |
| `GET` | `/checks/uploads` | view | Yükleme geçmişi |
| `DELETE` | `/checks/uploads/{id}` | use | Yükleme sil (çekler geri alınır) |
| `GET` | `/checks/` | view | Çek listesi (paginated, durum/tarih filtresi) |
| `GET` | `/checks/summary` | view | Özet (toplam tutar, durum bazlı) |
| `PATCH` | `/checks/{id}/status` | use | Durum güncelle (cashed, returned, cancelled) |
| `POST` | `/checks/match-bank` | use | Banka işlemleriyle otomatik eşleştir |

---

## Dosya Yükleme Güvenliği

- **MIME doğrulaması:** `app/utils/file_validation.py` ile magic bytes kontrolü
- **Boyut limiti:** Maksimum 10 MB
- **Uzantı kontrolü:** Yalnızca `.xlsx`, `.xls`
- **Mükerrer kontrolü:** `(check_no, vendor_code, due_date)` unique üçlüsüyle

---

## Nakit Akım Entegrasyonu

Çekler, vade tarihlerinde nakit akımda gösterilir:

- **Verilen çek** → `direction = -1` (gider), `event_date = due_date`
- **Alınan çek** → `direction = +1` (gelir), `event_date = due_date`
- `is_realized = False` — henüz gerçekleşmemiş (ilerideki nakit çıkışı)
- Banka eşleşmesi sonrası `is_realized = True` olarak güncellenir

---

## Banka Eşleştirme Algoritması

`_match_checks_to_bank(db)` fonksiyonu (checks.py):

1. `status = "pending"` ve `bank_transaction_id IS NULL` olan çekleri al
2. Her çek için, banka işlemleri arasında:
   - Tarih farkı ≤ 5 gün
   - Tutar farkı ≤ %2 (veya 100 TL)
   olan en yakın işlemi bul
3. Eşleşme bulunursa:
   - `check.bank_transaction_id = best_match.id`
   - `check.status = "cashed"`
   - `finance_event_svc.match(db, "bank", btx_id, "check", check_id)` çağrılır

---

## finance_events Entegrasyonu

```python
finance_event_svc.upsert_check(db, check, bank_tx=None)
```

| finance_events alanı | Değer |
|---|---|
| `source_type` | `"check"` |
| `source_id` | `check.id` |
| `direction` | `-1` (verilen çek = gider) |
| `amount` | `check.amount_tl` |
| `currency` | `check.currency` |
| `event_date` | `check.due_date` |
| `event_status` | `check.status` |
| `vendor_code` | `check.vendor_code` |
| `check_no` | `check.check_no` |
| `is_realized` | `True` (cashed/returned) veya `False` (pending) |
| `is_matched` | `True` (banka eşleşmesi varsa) |

---

## Durum Geçişleri

```
pending → cashed    (banka işlemi eşleşti)
pending → returned  (çek iade edildi)
pending → cancelled (iptal edildi)
cashed  → (nihai durum)
```

Durum değişikliğinde `finance_event_svc.upsert_check(db, check)` yeniden çağrılır.

---

## Audit Log Entegrasyonu

| entity_type | Kaydedilen eylem |
|---|---|
| `check_upload` | create (yükleme), delete |
| `check` | update (durum değişikliği) |

---

## Geliştirme Kuralları

1. **Silme:** Çek silmek yerine `cancelled` durumuna getir — geçmişi korur
2. **Para birimi:** Dövizli çeklerde `amount_tl` zorunludur (yükleme anında hesaplanmış olmalı)
3. **Mükerrer:** `(check_no, vendor_code, due_date)` kombinasyonu unique — aynı çek iki kez yüklenemez
4. **WS broadcast:** `broadcast_finance_update(background_tasks, "checks", "upload"/"update")`
5. **Eşleştirme toleransı:** Tarih ±5 gün, tutar ±%2 (banka değerleme farkları için)
