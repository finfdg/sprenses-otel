# Finans Modülü Mimarisi

## Genel Bakış

Sprenses finans modülü, otelin tüm para hareketlerini tek bir yerden izlemeyi sağlar.
Altı alt modül bulunur:

| Modül | Kod | Açıklama |
|---|---|---|
| Nakit Akım | `finance.cash_flow` | Tüm para hareketlerinin ana görünümü |
| Bankalar | `finance.banks` | Banka hesapları ve ekstre yönetimi |
| Cariler | `finance.cariler` | Tedarikçi borç takibi |
| Çekler | `finance.checks` | Verilen/alınan çek takibi |
| Krediler | `finance.krediler` | Banka kredileri ve kredi kartları |
| Avanslar | `finance.advances` | Personel avans takibi |
| Döviz | `finance.exchange_rates` | TCMB günlük kur takibi |

---

## Temel Tasarım İlkesi: `finance_events` Merkezi Olay Deposu

### Problem (Eski Mimari)
Nakit akım listesi, 6 farklı tablodan Python'da UNION yapılarak oluşturuluyordu:

```python
# ESKİ (kaldırıldı) — Python'da birleştirme
all_items = []
all_items += bank_transactions
all_items += checks
all_items += credit_payments
all_items += cc_statements
all_items += advances
all_items += vendor_transactions
all_items.sort(key=lambda x: x.event_date, reverse=True)
# Pagination Python seviyesinde — offset öncesinde tüm kayıtlar yükleniyor!
```

**Sorunlar:**
- N kayıt için tüm verinin belleğe yüklenmesi (bellek verimsizliği)
- Python'da sıralama (veritabanı indekslerinden faydalanamıyor)
- Pagination doğruluğu: 500 kayıt varsa `page=5, page_size=20` için 500 kayıt yüklenir, 80-100 arası döner

### Çözüm (Yeni Mimari)
`finance_events` denormalized olay deposu:

```sql
SELECT * FROM finance_events
WHERE is_matched = FALSE
  AND event_date >= '2024-01-01'
ORDER BY event_date DESC, id DESC
LIMIT 20 OFFSET 80;
```

**Avantajlar:**
- Tek SQL sorgusu — veritabanı indeksleri tam kullanım
- `is_matched = FALSE` filtresiyle çift sayım otomatik engellenir
- Gerçek SQL LIMIT/OFFSET — doğru pagination
- Tüm modüllerin veri yapısı tek tabloda normalize edilmiş

---

## `finance_events` Tablo Yapısı

```sql
CREATE TABLE finance_events (
    id              SERIAL PRIMARY KEY,
    -- Kaynak bilgisi
    source_type     VARCHAR(20) NOT NULL,  -- bank, check, credit, cc_payment, advance, vendor_payment
    source_id       INTEGER NOT NULL,
    -- Finansal veriler
    event_date      DATE NOT NULL,
    amount          NUMERIC(15,2) NOT NULL,
    direction       SMALLINT NOT NULL,     -- +1 gelir, -1 gider
    currency        VARCHAR(3),
    amount_try      NUMERIC(15,2),         -- TL karşılığı (döviz kurundan)
    -- Açıklama ve referanslar
    description     TEXT,
    bank_name       VARCHAR(100),
    account_id      INTEGER,               -- bank_accounts.id
    iban            VARCHAR(34),
    receipt_no      VARCHAR(50),
    balance         NUMERIC(15,2),
    payment_method  VARCHAR(20),
    match_number    VARCHAR(50),
    check_no        VARCHAR(50),
    -- Durum
    event_status    VARCHAR(20),           -- pending, paid, cashed, overdue...
    vendor_code     VARCHAR(50),
    -- Etiketleme
    tag_note        TEXT,
    tag_source      VARCHAR(20),
    bank_account_id INTEGER,
    vendor_id       INTEGER,
    category_id     INTEGER,
    category_name   VARCHAR(100),
    category_color  VARCHAR(7),
    -- Flags
    is_realized     BOOLEAN DEFAULT FALSE, -- Gerçekleşti mi?
    is_matched      BOOLEAN DEFAULT FALSE, -- Eşleştirildi mi? (çift sayım önleme)
    matched_event_id INTEGER,              -- Eşleşme karşı tarafı
    -- Audit
    created_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ,
    UNIQUE (source_type, source_id)        -- Idempotent upsert için
);
```

**8 Performans İndeksi:**
```sql
CREATE INDEX ix_fe_date         ON finance_events(event_date DESC);
CREATE INDEX ix_fe_source       ON finance_events(source_type, source_id);
CREATE INDEX ix_fe_is_matched   ON finance_events(is_matched) WHERE is_matched = FALSE;
CREATE INDEX ix_fe_currency     ON finance_events(currency);
CREATE INDEX ix_fe_direction    ON finance_events(direction);
CREATE INDEX ix_fe_vendor       ON finance_events(vendor_id) WHERE vendor_id IS NOT NULL;
CREATE INDEX ix_fe_bank_account ON finance_events(bank_account_id) WHERE bank_account_id IS NOT NULL;
CREATE INDEX ix_fe_category     ON finance_events(category_id) WHERE category_id IS NOT NULL;
```

---

## `FinanceEventService` — Upsert/Invalidate/Match

Tüm `finance_events` yazmaları `app/utils/finance_event_service.py` üzerinden yapılır.

### Temel Metodlar

```python
finance_event_svc.upsert_bank_tx(db, bank_tx, account)
finance_event_svc.upsert_check(db, check, bank_tx=None)
finance_event_svc.upsert_credit_payment(db, payment, product)
finance_event_svc.upsert_cc_statement(db, statement, product)
finance_event_svc.upsert_advance(db, advance)
finance_event_svc.upsert_vendor_tx(db, vendor_tx, vendor, amount_try)
finance_event_svc.invalidate(db, source_type, source_id)
finance_event_svc.match(db, type_a, id_a, type_b, id_b)
finance_event_svc.unmatch(db, source_type, source_id)
finance_event_svc.sync_tag(db, tx_id, category_id, ...)
finance_event_svc.update_amount_try(db, target_date, rates)
```

### Upsert Mekanizması

`INSERT ON CONFLICT (source_type, source_id) DO UPDATE SET ...` kullanılır.
Bu sayede:
- Aynı kayıt için birden fazla çağrı güvenli (idempotent)
- Güncelleme durumunda otomatik `updated_at` set edilir
- `db.flush()` sonrası çağrılır, transaction commit öncesinde

### Çift Sayım Önleme (is_matched)

Banka işlemi bir çek veya kredi ödemesiyle eşleştiğinde:

```python
finance_event_svc.match(db, "bank", btx_id, "check", check_id)
```

Bu çağrı:
1. `check` kaydının `is_matched = True` yapılır (nakit akımdan gizlenir)
2. `bank` kaydı aktif kalır (`is_matched = False`)
3. `matched_event_id` her iki yönde set edilir

**Neden çek gizlenir?**
Banka ekstresi zaten gerçek para çıkışını gösterir (banka tutarı).
Çek vade tarihi ilerideki beklenen çıkışı temsil eder.
Eşleşme sonrası çekin banka işlemiyle çakışması çift sayıma yol açar.

---

## `vendor_balances` Materialized View (P2)

Cari hesap bakiye özetleri için performanslı görünüm:

```sql
CREATE MATERIALIZED VIEW vendor_balances AS
SELECT
    v.id AS vendor_id,
    v.code,
    v.name,
    COALESCE(SUM(vt.borc), 0) AS total_borc,
    COALESCE(SUM(vt.alacak), 0) AS total_alacak,
    COALESCE(SUM(vt.alacak) - SUM(vt.borc), 0) AS net_debt,
    COUNT(CASE WHEN vt.payment_due_date IS NOT NULL AND vt.alacak > 0 THEN 1 END) AS pending_invoice_count,
    COALESCE(SUM(CASE WHEN vt.payment_due_date IS NOT NULL THEN vt.alacak ELSE 0 END), 0) AS pending_invoice_amount
FROM vendors v
LEFT JOIN vendor_transactions vt ON v.id = vt.vendor_id
GROUP BY v.id, v.code, v.name;

CREATE UNIQUE INDEX ON vendor_balances(vendor_id);
```

**Yenileme:** `REFRESH MATERIALIZED VIEW CONCURRENTLY vendor_balances;`
Büyük veri setlerinde `CONCURRENTLY` ile okuma kilitlemeden güncelleme.

---

## `amount_try` Ön Hesaplama (P3)

Dövizli işlemlerin TL karşılığı TCMB günlük kur güncellenmesi sırasında otomatik hesaplanır:

```python
# cron_fetch_exchange_rates.py
finance_event_svc.update_amount_try(db, target_date, rates)
```

Bu çağrı:
1. `target_date` tarihindeki tüm `finance_events` kayıtlarını alır
2. Para birimine göre kur lookup
3. `amount_try = amount × rate` hesaplanır
4. Toplu güncelleme (`UPDATE ... WHERE event_date = target_date`)

Avantaj: Nakit akım sorgusu sırasında JOIN veya hesaplama yapılmaz.

---

## WS Broadcast Debounce (P5)

Toplu Excel yüklemelerinde (500 satır → 500 muhtemel broadcast) aşırı WebSocket trafiğini önler.

```python
# app/utils/finance_broadcast.py
_pending_modules: Set[str] = set()
_debounce_lock = asyncio.Lock()

async def _debounced_send(module: str, action: str) -> None:
    await asyncio.sleep(0.5)   # 500ms bekle
    async with _debounce_lock:
        if module not in _pending_modules:
            return  # Başkası gönderdi, atla
        _pending_modules.discard(module)
    await manager.send_to_all({"type": "finance_updated", ...})
```

Aynı modül için 500ms içinde gelen birden fazla broadcast → tek bir WS event'e indirgenir.

---

## Dosya Yükleme Güvenliği (P8)

Tüm Excel/PDF yüklemeleri `app/utils/file_validation.py` üzerinden yapılır:

| Doğrulama | Açıklama |
|---|---|
| **Uzantı** | Sadece izin verilen uzantılar (`.xlsx`, `.xls`, `.pdf`) |
| **Magic bytes** | Dosya içeriği gerçek formatla eşleşiyor mu? |
| **Boyut limiti** | Excel: 10 MB, PDF: 25 MB |
| **Boşluk kontrolü** | Boş dosya reddedilir |

Magic bytes referansı:
```
Excel .xlsx: \x50\x4B\x03\x04  (ZIP başlığı)
Excel .xls:  \xD0\xCF\x11\xE0  (OLE2 başlığı)
PDF:         %PDF
```

---

## Gerçek Zamanlılık — WebSocket Event Akışı

```
Kullanıcı işlem yapar (yükleme, güncelleme, silme)
          ↓
Backend: finance_event_svc.upsert_*(...)
          ↓
Backend: broadcast_finance_update(background_tasks, module, action)
          ↓
500ms debounce
          ↓
manager.send_to_all({"type": "finance_updated", "module": "banks", "action": "upload"})
          ↓
Frontend (tüm açık sekmeler): onWsEvent('finance_updated', () => { reload() })
```

**Kural:** `setInterval` ile HTTP polling **yasaktır**. Tüm gerçek zamanlı veri WS event-driven.

---

## TCMB Kur Güncelleme Akışı

```
cron_fetch_exchange_rates.py (günlük/saatlik çalışır)
          ↓
TCMB XML API'den kurlar çekilir
          ↓
exchange_rates tablosuna kaydedilir
          ↓
finance_event_svc.update_amount_try(db, today, rates)
  → finance_events tablosundaki dövizli kayıtların amount_try güncellenir
          ↓
HTTP POST http://127.0.0.1:8001/api/internal/broadcast-finance-update
  (X-Internal-Secret header + localhost kısıtı)
          ↓
Tüm bağlı kullanıcılara: {"type": "finance_updated", "module": "exchange_rates"}
          ↓
Frontend döviz sayfası yenilenir
```

---

## Haftalık Push Bildirimi (P9)

Her Pazartesi 08:30'da `cron_weekly_push.py` çalışır:

```
Bu haftaki vadeli çekler (TL toplamı)
+ Bu haftaki cari ödemeler
+ Gecikmiş kredi kartı ödemeleri
+ Güncel nakit bakiyesi
          ↓
push aboneliği olan tüm kullanıcılara bildirim gönderilir
```

Crontab:
```
30 8 * * 1 ec2-user cd /home/ec2-user/otel/backend && source venv/bin/activate && python cron_weekly_push.py >> /var/log/cron_weekly_push.log 2>&1
```

---

## Mobil Dashboard Endpoint (P6)

`GET /api/finance/cash-flow/mobile-dashboard`

```json
{
  "bank_balance": 1250000.00,
  "pending_checks": { "count": 5, "total": 85000.00 },
  "weekly_vendor_payments": { "count": 3, "total": 45000.00 },
  "overdue_credits": { "count": 1, "total": 12500.00 },
  "monthly_chart": [
    { "month": "2026-01", "income": 500000, "expense": 450000, "balance": 50000 },
    ...
  ]
}
```

---

## Internal API Güvenliği (P7)

`/api/internal/broadcast-finance-update` endpoint'i:
- **Yalnızca localhost** (127.0.0.1, ::1) IP'lerinden erişilebilir
- `X-Internal-Secret` header zorunlu (`.env` → `INTERNAL_SECRET`)
- Dış ağdan erişim 403 Forbidden döner

---

## Modül Dosya Haritası (Tamamı)

### Backend
```
app/
├── models/
│   ├── bank_account.py         # BankAccount
│   ├── bank_transaction.py     # BankTransaction
│   ├── bank_statement.py       # BankStatement
│   ├── check.py                # Check, CheckUpload
│   ├── credit_product.py       # CreditProduct
│   ├── credit_payment.py       # CreditPayment
│   ├── credit_card_statement.py # CreditCardStatement, CreditCardTransaction
│   ├── vendor.py               # Vendor
│   ├── vendor_upload.py        # VendorUpload
│   ├── vendor_transaction.py   # VendorTransaction
│   ├── advance.py              # Advance
│   ├── exchange_rate.py        # ExchangeRate
│   ├── transaction_category.py # TransactionCategory
│   └── finance_event.py        # FinanceEvent (merkezi olay deposu)
├── routers/finance/
│   ├── banks.py                # Banka hesapları + ekstre
│   ├── checks.py               # Çekler
│   ├── krediler.py             # Krediler + kart ürünleri
│   ├── cc_statements.py        # Kredi kartı ekstresi
│   ├── cariler.py              # Cari hesaplar
│   ├── advances.py             # Avanslar
│   ├── cash_flow.py            # Nakit akım (finance_events üzerinden)
│   ├── exchange_rates.py       # Döviz kurları
│   └── transaction_tags.py     # İşlem etiketleme
└── utils/
    ├── finance_event_service.py # Merkezi upsert/match servisi
    ├── finance_broadcast.py     # WS broadcast + debounce
    ├── file_validation.py       # MIME + boyut doğrulaması
    ├── bank_parser.py           # Excel/CSV ekstre ayrıştırıcı
    ├── check_parser.py          # Çek Excel ayrıştırıcı
    ├── vendor_parser.py         # Cari Excel ayrıştırıcı
    ├── cc_statement_parser.py   # PDF ekstre ayrıştırıcı
    └── tcmb.py                  # TCMB XML kur çekici
```

### Frontend
```
src/routes/dashboard/finans/
├── bankalar/+page.svelte       # Banka işlemleri + etiketleme
├── cariler/+page.svelte        # Cari hesaplar + ödeme planı
├── cekler/+page.svelte         # Çek takibi
├── krediler/+page.svelte       # Krediler + kart ekstresi
├── avanslar/+page.svelte       # Personel avansları
├── doviz/+page.svelte          # Döviz kurları
└── nakit-akis/+page.svelte     # Nakit akım ana görünümü
```

### Cron Scripts
```
backend/
├── cron_fetch_exchange_rates.py  # Günlük TCMB kur güncellemesi
└── cron_weekly_push.py           # Haftalık Pazartesi push bildirimi
```

---

## Performans Özeti

| Senaryo | Eski | Yeni |
|---|---|---|
| Nakit akım listesi (1000 kayıt) | 6 tablo JOIN + Python sort | Tek SQL, indeksli |
| Bulk Excel yükleme (500 satır) | 500 WS broadcast | 1 WS broadcast (debounce) |
| Cari bakiye hesabı | Her istek SUM | Materialized view |
| Döviz hesaplama | Sorgu sırasında JOIN | Önceden hesaplanmış `amount_try` |
| Pagination | Python slice | SQL LIMIT/OFFSET |

---

## Geliştirme Kuralları

1. **Yeni para hareketi modeli:** `finance_events` tablosuna da yazmak için `FinanceEventService` extend edilmeli
2. **Yeni dosya yükleme:** `validate_upload_file()` zorunlu (MIME + boyut kontrolü)
3. **WS broadcast:** Her CRUD işleminden sonra `broadcast_finance_update()` çağrılmalı
4. **Çift sayım:** İki tablo arasında eşleştirme varsa `is_matched` kullanılmalı
5. **Döviz:** `amount_try` manuel set edilmemeli — `update_amount_try` cron'u günceller
6. **Dokümantasyon:** `docs/modules/` altına modül `.md` dosyası oluşturulmalı
