# Bankalar Modülü

## Genel Bilgi

| Alan | Değer |
|---|---|
| **Modül kodu** | `finance.banks` |
| **Üst modül** | Finans (`finance`) |
| **Frontend rota** | `/dashboard/finans/bankalar` |
| **Backend prefix** | `/api/finance/banks` |
| **İzin kodu** | `finance.banks` |
| **İzin seviyeleri** | `can_view` (görme), `can_use` (yükleme + düzenleme + silme) |

---

## Dosya Haritası

### Backend
| Dosya | Açıklama |
|---|---|
| `app/routers/finance/banks.py` | Ana router — hesap CRUD, ekstre yükleme, işlem listesi |
| `app/models/bank_account.py` | `BankAccount` modeli |
| `app/models/bank_transaction.py` | `BankTransaction` modeli |
| `app/models/bank_statement.py` | `BankStatement` modeli |
| `app/utils/bank_parser.py` | Excel/PDF ekstre ayrıştırıcı |

### Frontend
| Dosya | Açıklama |
|---|---|
| `src/routes/dashboard/finans/bankalar/+page.svelte` | Ana sayfa — hesap kartları, işlem tablosu |

---

## Veritabanı Şeması

### `bank_accounts`
| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | integer PK | |
| `bank_name` | varchar(100) | Banka adı |
| `branch_name` | varchar(200) | Şube adı |
| `account_no` | varchar(50) | Hesap no |
| `iban` | varchar(34) | IBAN (unique) |
| `currency` | varchar(3) | Para birimi (TRY, USD, EUR) |
| `holder_name` | varchar(300) | Hesap sahibi |
| `blocked_amount` | numeric(15,2) | Bloke tutar |
| `is_active` | boolean | Aktif/pasif |
| `created_by` | integer FK → users | Oluşturan |
| `created_at` | timestamptz | Oluşturma zamanı |

> **Not:** `bank_accounts`'ta ayrı `balance` kolonu **yoktur** — güncel bakiye hesabın son `bank_transactions.balance` değerinden türetilir.

### `bank_transactions`
| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | integer PK | |
| `account_id` | integer FK → bank_accounts | |
| `statement_id` | integer FK → bank_statements | |
| `date` | date | İşlem tarihi |
| `description` | text | Açıklama |
| `amount` | numeric(15,2) | İşlem tutarı (+ giriş, - çıkış) |
| `balance` | numeric(15,2) | İşlem sonrası bakiye |
| `receipt_no` | varchar(50) | Fiş/dekont no |
| `payment_method` | varchar(20) | Ödeme yöntemi (eft, havale, pos, atm) |
| `category_id` | integer FK → transaction_categories | Etiket kategorisi |
| `tag_note` | text | Etiket notu |
| `match_number` | varchar(50) | Eşleştirme numarası |
| `created_at` | timestamptz | |

### `bank_statements`
| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | integer PK | |
| `account_id` | integer FK | |
| `file_name` | varchar(255) | Orijinal dosya adı |
| `file_url` | varchar(500) | Sunucu dosya yolu |
| `period_start` | date | Dönem başlangıç |
| `period_end` | date | Dönem bitiş |
| `total_transactions` | integer | Toplam işlem sayısı |
| `new_transactions` | integer | Yeni eklenen |
| `skipped_transactions` | integer | Mükerrer (atlandı) |
| `uploaded_by` | integer FK → users | |
| `uploaded_at` | timestamptz | |

**İndeksler:** `ix_bank_tx_account_date`, `ix_bank_tx_statement`, `ix_bank_tx_tag_category`

---

## API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| `GET` | `/banks/accounts/` | view | Hesap listesi (bakiye özeti dahil) |
| `POST` | `/banks/accounts/` | use | Yeni hesap oluştur |
| `PATCH` | `/banks/accounts/{id}` | use | Hesap güncelle |
| `DELETE` | `/banks/accounts/{id}` | use | Hesap sil (işlem varsa engellenir) |
| `POST` | `/banks/upload` | use | Ekstre yükle — banka otomatik algıla |
| `POST` | `/banks/accounts/{id}/upload` | use | Belirli hesaba ekstre yükle |
| `POST` | `/banks/accounts/{id}/manual-transaction` | use | **Ekstre-dışı (manuel) hareket** — ekstresi gelmemiş işlemi yansıtır; ekstre yüklenince o tarih aralığında **otomatik silinir** (çift kayıt yok). `source='manual'`, audit'li |
| `GET` | `/banks/accounts/{id}/transactions` | view | İşlem listesi (paginated; yanıt `source`: statement/manual) |
| `GET` | `/banks/accounts/{id}/statements` | view | Ekstre yükleme geçmişi |

---

## Dosya Yükleme Güvenliği

- **MIME doğrulaması:** `app/utils/file_validation.py` ile Excel magic bytes kontrolü (`\x50\x4B\x03\x04` xlsx, `\xD0\xCF\x11\xE0` xls)
- **Boyut limiti:** Maksimum 10 MB (Excel)
- **Uzantı kontrolü:** Yalnızca `.xlsx`, `.xls`
- **Mükerrer kontrolü:** `(account_id, transaction_date, amount, receipt_no)` üçlü unique kontrolü

---

## Çekler ve Kredilerle Eşleştirme

Ekstre yüklenince otomatik eşleştirme tetiklenir:

```python
# banks.py → _notify_bank_upload → background task
_match_checks_to_bank(db)   # checks.py
_match_credits_to_bank(db)  # krediler.py
```

Eşleştirme sonucu `finance_events` tablosunda `is_matched=True` olarak işaretlenir.
Eşleşen işlemler nakit akımda çift sayılmaz (birisi gizlenir).

---

## finance_events Entegrasyonu

Yeni banka işlemi eklendiğinde:

```python
finance_event_svc.upsert_bank_tx(db, db_tx, account)
```

| finance_events alanı | Değer |
|---|---|
| `source_type` | `"bank"` |
| `source_id` | `bank_transaction.id` |
| `direction` | `+1` (giriş) veya `-1` (çıkış) |
| `amount` | İşlem tutarı |
| `currency` | Hesap para birimi |
| `amount_try` | TL karşılığı (günlük kurdan hesaplanır) |
| `bank_name` | Hesabın banka adı |
| `bank_account_id` | Hesap ID |
| `iban` | Hesap IBAN |

---

## Audit Log Entegrasyonu

| entity_type | Kaydedilen eylem |
|---|---|
| `bank_account` | create, update, delete |
| `bank_statement` | create (yükleme), delete |

---

## Geliştirme Kuralları

1. **Bakiye:** `bank_accounts.balance` her zaman son banka ekstresindeki kapanış bakiyesidir — işlemlerden hesaplanmaz
2. **Para birimi:** Hesap para birimi değiştirilemez (işlem varsa)
3. **Ekstre silme:** İlgili tüm `bank_transactions` silinir, `finance_events` invalidate edilir
4. **WS broadcast:** `broadcast_finance_update(background_tasks, "banks", "upload")` her yüklemede tetiklenir
5. **Eşleştirme:** Banka ID'si IBAN'dan çözümlenir — ekstre dosyasında IBAN yoksa manuel seçim gerekir

---

## Aynı Gün İçi İşlem Sıralama (2026-04-15 Düzeltmesi)

### Sorun
TEB PDF ekstreleri işlemleri **ters kronolojik** sırada listeler (yeni → eski). `_ensure_chronological_order` fonksiyonu çok günlü ekstrelerde `first_date > last_date` kontrolü ile doğru sıralıyordu. Ancak **aynı güne ait tüm işlemler** olduğunda bakiye zinciri her iki yönde de eşit puan alıyordu → sıra değişmiyordu → son bakiye yanlış görünüyordu.

**Örnek:** TEB EUR hesabı 15/04/2026 — 16:10'da havale (+70.000), 16:12'de çek ödemesi (-70.000). PDF ters sırada listeliyor → parser son bakiyeyi 70.003,86 olarak kaydediyordu (gerçekte 3,86).

### Çözüm
`ParsedTransaction` modeline `time: Optional[str]` alanı eklendi. `_detect_columns` "saat" kolonunu algılıyor, `_try_parse_mapped_row` saat bilgisini çıkarıyor.

`_ensure_chronological_order`'a 3 seviyeli tiebreaker eklendi:
1. **Bakiye zinciri puanı** (mevcut — `_balance_chain_score`)
2. **Saat bilgisi** — ilk işlemin saati > son işlemin saatiyse → ters sıra → reverse
3. **Dekont numarası** — ilk dekont > son dekont ise → ters sıra → reverse

Bu düzeltme tüm banka formatlarını etkiler ama sadece saat veya dekont bilgisi olan bankalar (TEB vb.) için aktif olur.
