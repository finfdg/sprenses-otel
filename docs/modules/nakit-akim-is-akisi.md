# Nakit Akım Modülü — Detaylı İş Akışı Şeması

## 1. Genel Mimari Görünüm

```
┌─────────────────────────────────────────────────────────────────────┐
│                     KAYNAK MODÜLLER (Veri Üreten)                    │
│                                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ Bankalar │ │  Çekler  │ │ Krediler │ │ Avanslar │ │ Cariler  │ │
│  │  (bank)  │ │ (check)  │ │ (credit) │ │(advance) │ │ (vendor) │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ │
│       │             │            │             │            │        │
│  ┌────┴─────┐ ┌─────┴────┐ ┌────┴─────┐                            │
│  │ KK Ekstre│ │  Vergiler│ │Düzenli Öd│ ┌──────────┐ ┌──────────┐ │
│  │(cc_pay)  │ │  (tax)   │ │(recurring│ │   Maaş   │ │   SGK    │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ │ (salary) │ │  (sgk)   │ │
│       │             │            │        └────┬─────┘ └────┬─────┘ │
│       │             │            │             │            │        │
│  ┌────┴──────┐ ┌────┴─────┐ ┌───┴──────┐ ┌────┴─────┐              │
│  │  Stopaj   │ │Al. Kira  │ │Ver. Kira │ │ Temettü  │              │
│  │(withhold.)│ │(rent_inc)│ │(rent_exp)│ │(dividend)│              │
│  └────┬──────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘              │
└───────┼──────────────┼───────────┼─────────────┼────────────────────┘
        │              │           │             │
        ▼              ▼           ▼             ▼
┌─────────────────────────────────────────────────────────────────────┐
│              FinanceEventService (Merkezi Olay Servisi)              │
│                                                                     │
│   upsert_bank_tx()  │  upsert_check()  │  upsert_credit_payment()  │
│   upsert_cc_stmt()  │  upsert_advance()│  upsert_vendor_tx()       │
│   upsert_scheduled_entry()  │  invalidate()  │  match() / unmatch()│
│                                                                     │
│   PostgreSQL INSERT ON CONFLICT (source_type, source_id) DO UPDATE  │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  finance_events TABLOSU (Merkezi Depo)               │
│                                                                     │
│   UniqueConstraint(source_type, source_id)                          │
│   Filtre: is_matched = FALSE  →  Çift sayım engeli                 │
│   Filtre: is_realized = TRUE  →  Gerçekleşmiş işlemler              │
│   8 performans indeksi                                              │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    NAKİT AKIM API ENDPOİNT'LERİ                     │
│                                                                     │
│   GET /cash-flow/              →  Liste (paginated, filtrelenmiş)   │
│   GET /cash-flow/summary       →  Gelir/Gider/Bakiye toplamları     │
│   GET /cash-flow/monthly-summary → Aylık özet                      │
│   GET /cash-flow/mobile-dashboard → Mobil tek istek özet            │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    FRONTEND (Svelte 5 + SvelteKit)                   │
│                                                                     │
│   /dashboard/finans/nakit-akim                                      │
│   ┌──────────────────────────────────────────────────────────┐      │
│   │  Özet Kartları  │  Aylık Akordiyon  │  T Yapısı          │      │
│   │  (gelir/gider)  │  (açılır/kapanır) │  (sol:gider/sağ:  │      │
│   │                 │                   │   gelir)           │      │
│   └──────────────────────────────────────────────────────────┘      │
│   WebSocket dinleme: finance_updated → otomatik yenileme            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Veri Yazma İş Akışı (Kaynak → finance_events)

Her kaynak modül, kendi CRUD işlemi sırasında `finance_events` tablosunu güncel tutar.

### 2.1 Banka Ekstre Yükleme Akışı

```
Kullanıcı Excel ekstre yükler
          │
          ▼
┌─────────────────────────┐
│ banks.py / upload_stmt  │
│ validate_upload_file()  │──→ MIME + boyut + magic bytes kontrolü
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│ Her satır için:                          │
│  1. Mükerrer kontrolü (tarih+tutar+     │
│     bakiye üçlüsü veya hash)            │
│  2. BankTransaction INSERT (db.flush()) │
│  3. finance_event_svc.upsert_bank_tx()  │──→ finance_events tablosuna yaz
│  4. Otomatik eşleştirme dene:           │
│     - Çek eşleşmesi (check_no arama)   │
│     - Kredi eşleşmesi (tutar+tarih)    │
│     - KK eşleşmesi (tutar+tarih)       │
└────────┬────────────────────────────────┘
         │
         ▼
┌──────────────────────────────┐
│ db.commit()                   │
│ broadcast_finance_update(     │
│   "banks", "upload"          │──→ WS event → tüm kullanıcılar
│ )                             │
└──────────────────────────────┘
```

### 2.2 Çek Kayıt Akışı

```
Kullanıcı çek kaydı oluşturur/günceller
          │
          ▼
┌─────────────────────────────────────────┐
│ checks.py / create_check                │
│  1. Check INSERT/UPDATE (db.flush())    │
│  2. finance_event_svc.upsert_check(     │
│       db, check, bank_tx=None           │
│     )                                   │
│     → direction = EXPENSE               │
│     → event_date = due_date (vade)      │
│     → is_matched = False (henüz         │
│       bankadan geçmedi)                 │
└────────┬────────────────────────────────┘
         │
         ▼
   Banka Eşleşmesi Olduğunda:
┌─────────────────────────────────────────┐
│ finance_event_svc.match(                │
│   db, "bank", btx_id, "check", chk_id  │
│ )                                       │
│                                         │
│ Sonuç:                                  │
│   bank event  → is_matched = FALSE      │
│                 (görünür kalır)          │
│   check event → is_matched = TRUE       │
│                 (gizlenir)              │
│                                         │
│ Neden? Aynı para hareketi iki kez       │
│ görünmesin. Banka kaydı gerçek çıkışı,  │
│ çek ise beklentiyi temsil eder.         │
└─────────────────────────────────────────┘
```

### 2.3 Cari Ödeme Akışı (FIFO Kırpma)

```
Excel ile cari fatura yüklenir
          │
          ▼
┌─────────────────────────────────────────────┐
│ cariler.py / upload_vendor_excel             │
│  1. Vendor oluştur/güncelle                  │
│  2. VendorTransaction INSERT                 │
│  3. Alacak kayıtları için vade hesapla:      │
│     fatura_tarihi + payment_days + ilk_cuma  │
│  4. sync_vendor_finance_events()             │
└────────┬────────────────────────────────────┘
         │
         ▼
┌───────────────────────────────────────────────────────────────┐
│ sync_vendor_finance_events() — FIFO Net Borç Kırpma           │
│                                                               │
│  1. Net borç hesapla: SUM(alacak) - SUM(borç)                │
│     ├── Net borç ≤ 0 → Cari borçsuz, tüm FE'leri invalidate │
│     └── Net borç > 0 → Devam et                              │
│                                                               │
│  2. Alacak kayıtlarını eskiden yeniye sırala (FIFO)           │
│                                                               │
│  3. Her fatura için:                                          │
│     ├── Kalan borç > fatura tutarı → Tam tutar göster         │
│     ├── Kalan borç < fatura tutarı → Kısmi tutar göster       │
│     └── Kalan borç = 0 → Bu ve sonraki faturaları gizle       │
│                                                               │
│  4. Her gösterilecek fatura için:                             │
│     finance_event_svc.upsert_vendor_tx(db, vtx, vendor, amt) │
│                                                               │
│  5. Vadesi geçmiş fatura → sonraki Cuma'ya kaydır             │
│     effective_due_date() → event_date güncelle                │
└───────────────────────────────────────────────────────────────┘

Örnek FIFO Kırpma:
┌──────────────────────────────────────────────────────────────┐
│ Cari: ABC Tedarik                                             │
│ Toplam Alacak: ₺100.000  │  Toplam Borç: ₺60.000             │
│ Net Borç: ₺40.000                                            │
│                                                               │
│ Fatura #1 (en eski): ₺30.000  → Zaten ödenmiş (FIFO düşüm)  │
│ Fatura #2:           ₺30.000  → ₺30.000'den ₺10.000 ödendi   │
│                                  Kalan: ₺20.000 göster        │
│ Fatura #3:           ₺20.000  → Tam tutar: ₺20.000 göster    │
│ Fatura #4 (en yeni): ₺20.000  → Borç bitti, gösterme          │
│                                                               │
│ Ödeme Planı Toplamı: ₺40.000 = Net Borç ✓                    │
└──────────────────────────────────────────────────────────────┘
```

### 2.4 Kredi Kartı Ekstre Akışı (Çift Sayım Engeli)

```
Kredi kartı ekstresi kaydedilir
          │
          ▼
┌─────────────────────────────────────────────┐
│ finance_event_svc.upsert_cc_statement()      │
│                                              │
│  kalan = toplam_borç - paid_amount           │
│                                              │
│  ┌──── Vadesi geçmiş mi? ────┐              │
│  │                           │               │
│  ▼ EVET                     ▼ HAYIR          │
│  is_matched = TRUE          is_matched=FALSE │
│  (gizle — ödeme             (göster — henüz  │
│   banka kaydında)            ödenmemiş)      │
│                                              │
│  Tutar: Kalan borç                           │
│  (toplam değil — banka kısmi ödemeleri       │
│   zaten nakit akımda görünüyor)              │
└──────────────────────────────────────────────┘
```

### 2.5 Planlı Gider Akışı (Vergi, Maaş, SGK, Kira, Temettü...)

```
Kullanıcı planlı gider tanımı oluşturur
          │
          ▼
┌─────────────────────────────────────────┐
│ ScheduledDefinition oluştur             │
│ ScheduledEntry kayıtları otomatik üret  │
│ (ör: 12 aylık vergi girişleri)          │
└────────┬────────────────────────────────┘
         │
         ▼  Her entry için:
┌─────────────────────────────────────────────────┐
│ finance_event_svc.upsert_scheduled_entry(        │
│   db, entry,                                     │
│   direction = EXPENSE  (vergi, maaş, sgk, kira)  │
│             = INCOME   (alınan kira)              │
│ )                                                │
│                                                  │
│ source_type otomatik:                             │
│   entry.source_type → "tax" / "salary" / "sgk"   │
│                       "rent_income" / "dividend"  │
│                                                  │
│ event_status:                                     │
│   is_paid = True  → "paid"                        │
│   is_paid = False → "pending"                     │
│                                                  │
│ Ödendi olarak işaretlendiğinde:                   │
│   is_realized = True                              │
└──────────────────────────────────────────────────┘
```

---

## 3. Veri Okuma İş Akışı (finance_events → Kullanıcı)

### 3.1 Nakit Akım Listesi

```
Frontend: GET /api/finance/cash-flow/?page=1&page_size=100&type=expense
          │
          ▼
┌──────────────────────────────────────────────────────────┐
│ cash_flow.py / list_cash_flows()                          │
│                                                          │
│ TEK SQL SORGUSU:                                          │
│                                                          │
│   SELECT * FROM finance_events                            │
│   WHERE is_matched = FALSE          ← Çift sayım engeli  │
│     AND event_date >= '2026-01-01'  ← MIN_DATE filtresi   │
│     AND direction = -1              ← type=expense        │
│   ORDER BY event_date DESC, id DESC                       │
│   LIMIT 100 OFFSET 0               ← SQL pagination      │
│                                                          │
│ Eski mimari: 6 tablodan Python UNION + Python sort        │
│ Yeni mimari: 1 tablo, 1 sorgu, DB indeksleri              │
└────────┬─────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│ Response:                                                │
│ {                                                        │
│   "items": [                                             │
│     {                                                    │
│       "id": 1234,                                        │
│       "date": "2026-04-11",                              │
│       "description": "ABC Tedarik",                      │
│       "amount": 15000.00,                                │
│       "type": "expense",                                 │
│       "source": "vendor_payment",  ← Hangi modülden      │
│       "currency": "TRY",                                 │
│       "bank_name": null,                                 │
│       "vendor_name": "ABC Tedarik",                      │
│       "check_status": null,                              │
│       "payment_method": "cari",                          │
│       ...                                                │
│     }                                                    │
│   ],                                                     │
│   "total": 1523,                                         │
│   "page": 1,                                             │
│   "page_size": 100,                                      │
│   "pages": 16                                            │
│ }                                                        │
└──────────────────────────────────────────────────────────┘
```

### 3.2 Özet ve Bakiye Hesaplama

```
┌──────────────────────────────────────────────────┐
│ GET /cash-flow/summary                            │
│                                                  │
│ Toplam Gelir  = SUM(amount) WHERE type=income    │
│ Toplam Gider  = SUM(amount) WHERE type=expense   │
│ Net Bakiye    = Gelir - Gider                    │
│ Bekleyen Çek  = SUM(amount) WHERE status=pending │
│ Cari Borç     = SUM(net_borç) WHERE net > 0      │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│ GET /cash-flow/monthly-summary                    │
│                                                  │
│ GROUP BY (year, month)                            │
│ Her ay için: gelir, gider, bakiye                 │
│ Sıralama: en yeni ay üstte                       │
└──────────────────────────────────────────────────┘
```

---

## 4. Çift Sayım Engelleme Mekanizması

Bu sistem, aynı para hareketinin birden fazla kaynaktan geldiğinde nakit akımda tek kez görünmesini sağlar.

```
┌─────────────────────────────────────────────────────────────────┐
│                    ÇİFT SAYIM SENARYOLARI                        │
│                                                                 │
│  Senaryo 1: Banka İşlemi + Çek                                 │
│  ─────────────────────────────                                  │
│  Çek vadesi geldi, bankadan tahsil edildi.                       │
│  Hem BankTransaction hem Check aynı parayı temsil ediyor.       │
│                                                                 │
│  Çözüm: match("bank", btx_id, "check", chk_id)                │
│    → bank FE: is_matched = FALSE (GÖRÜNÜR — gerçek çıkış)       │
│    → check FE: is_matched = TRUE  (GİZLİ — beklenti idi)        │
│                                                                 │
│  Senaryo 2: Banka İşlemi + Kredi Taksiti                       │
│  ────────────────────────────────────────                        │
│  Kredi taksiti ödendi, bankadan düştü.                           │
│  Hem BankTransaction hem CreditPayment aynı para.               │
│                                                                 │
│  Çözüm: match("bank", btx_id, "credit", payment_id)            │
│    → bank FE: is_matched = FALSE (GÖRÜNÜR)                      │
│    → credit FE: is_matched = TRUE (GİZLİ)                       │
│                                                                 │
│  Senaryo 3: Kredi Kartı Ekstre + Banka Ödeme                   │
│  ──────────────────────────────────────────                      │
│  KK borcu bankadan ödendi.                                      │
│  Banka işlemi nakit akımda görünüyor.                           │
│  KK ekstresi tutarı: kalan = toplam - paid_amount               │
│                                                                 │
│  Çözüm:                                                         │
│    → Vadesi geçmiş CC ekstresi: is_matched = TRUE (GİZLİ)       │
│    → Kısmi ödeme varsa: CC tutarı = sadece kalan borç           │
│                                                                 │
│  Senaryo 4: Cari + Banka Eşleştirme                             │
│  ──────────────────────────────────                               │
│  Cari fatura bankadan ödendi (EFT/havale).                       │
│  Banka işlemi cari ile eşleştirildi (tag).                       │
│                                                                 │
│  Kural: Cari eşleştirmesi is_matched'ı DEĞİŞTİRMEZ!            │
│    → bank FE: is_matched = FALSE (GÖRÜNÜR — hâlâ)               │
│    → vendor FE: match_number atanır ama is_matched değişmez      │
│    → Neden? Cari ödeme planı farklı bir perspektif sunar         │
│                                                                 │
│  Senaryo 5: Avans Alındı                                        │
│  ────────────────────────                                        │
│  Avans bankaya yattı (received).                                 │
│  Hem Advance hem BankTransaction var.                            │
│                                                                 │
│  Çözüm: Avans status="received" → is_matched = TRUE             │
│    → Banka kaydı yeterli, avans gizlenir                         │
└─────────────────────────────────────────────────────────────────┘

Nakit Akım Sorgusu:
  WHERE is_matched = FALSE
  → Yalnızca aktif, eşleşmemiş kayıtlar döner
  → Çift sayım otomatik engellenir
```

---

## 5. Gerçek Zamanlılık Akışı (WebSocket)

```
┌──────────────┐     ┌──────────────────────┐     ┌──────────────────┐
│  Kullanıcı A  │     │       Backend         │     │  Kullanıcı B     │
│  (Banka yükle)│     │                      │     │  (Nakit akım     │
│               │     │                      │     │   sayfasında)    │
└──────┬───────┘     │                      │     └────────┬─────────┘
       │              │                      │              │
       │ POST /upload │                      │              │
       │─────────────>│                      │              │
       │              │ 1. Kayıtları işle    │              │
       │              │ 2. finance_events    │              │
       │              │    tablosuna yaz     │              │
       │              │ 3. db.commit()       │              │
       │              │                      │              │
       │              │ broadcast_finance_   │              │
       │              │ update("banks",      │              │
       │              │        "upload")     │              │
       │              │                      │              │
       │              │    ┌─────────────┐   │              │
       │              │    │ 500ms       │   │              │
       │              │    │ debounce    │   │              │
       │              │    └──────┬──────┘   │              │
       │              │           │          │              │
       │              │    WS: finance_      │              │
       │              │    updated           │ WS event     │
       │  200 OK      │───────────────────── │─────────────>│
       │<─────────────│                      │              │
       │              │                      │  onWsEvent   │
       │              │                      │  → loadData()│
       │              │                      │              │
       │              │                      │  GET /cash-  │
       │              │                      │  flow/       │
       │              │                      │<─────────────│
       │              │                      │  yeni veri   │
       │              │                      │─────────────>│
       │              │                      │              │
       │              │                      │  UI güncelle │
```

**Önemli:** `setInterval` ile HTTP polling **kesinlikle yasaktır**. Tüm güncellemeler WS event-driven.

---

## 6. Döviz Kuru Entegrasyonu

```
┌──────────────────────────────────────────────────────────┐
│ Günlük Cron: cron_fetch_exchange_rates.py                 │
│                                                          │
│  1. TCMB XML API'den kurları çek (EUR, USD, GBP...)      │
│  2. exchange_rates tablosuna kaydet                       │
│  3. finance_event_svc.update_amount_try(db, today, rates)│
│     → Dövizli finance_events kayıtlarının                │
│       amount_try alanını güncelle                         │
│     → amount_try = amount × kur                          │
│  4. Internal broadcast → WS event                        │
│     → Frontend döviz sayfası yenilenir                   │
└──────────────────────────────────────────────────────────┘

Ödeme planında EUR karşılığı:
  Frontend: formatEur(tryAmount)
  Kaynak: /api/finance/exchange-rates/latest
  Paralel yükleme: Ödeme planı + döviz kuru aynı anda
```

---

## 7. Vadesi Geçmiş Kayıt Yönetimi (Roll-over)

```
┌──────────────────────────────────────────────────────────────┐
│ Vadesi Geçmiş Cari Faturaları — Otomatik Kaydırma             │
│                                                              │
│ Koşul: payment_due_date < bugün  VE  match_number IS NULL    │
│         (ödenmemiş fatura)                                   │
│                                                              │
│ İşlem:                                                       │
│   effective_due_date()                                       │
│   → Bugünden itibaren en yakın Cuma'yı bul                   │
│   → finance_events.event_date = yeni_cuma                    │
│                                                              │
│ Neden?                                                       │
│   Geçmiş haftanın ödeme planında takılı kalmamalı.           │
│   Bir sonraki haftanın bütçesine dahil olmalı.               │
│                                                              │
│ Tetiklenme:                                                  │
│   /payment-schedule GET çağrısı sırasında                    │
│   sync_vendor_finance_events() otomatik çalışır              │
│                                                              │
│ Örnek:                                                       │
│   Fatura vadesi: 4 Nisan 2026 (Cumartesi — geçmiş)          │
│   Bugün: 12 Nisan 2026 (Cumartesi)                           │
│   Yeni vade: 17 Nisan 2026 (Cuma — gelecek hafta)            │
└──────────────────────────────────────────────────────────────┘
```

---

## 8. Mobil Dashboard — Tek İstek Özet

```
GET /cash-flow/mobile-dashboard
          │
          ▼
┌────────────────────────────────────────────────────────┐
│ 5 bağımsız sorgu TEK endpoint'te birleştirilir:        │
│                                                        │
│ 1. Banka Bakiyesi                                      │
│    → Her hesabın son işlem bakiyesi (subquery JOIN)     │
│    → TRY hesapları toplanır                            │
│                                                        │
│ 2. Bekleyen Çekler                                     │
│    → Adet + toplam tutar (vadesi gelmemiş)              │
│    → Vadesi geçmiş ayrı gösterilir                     │
│                                                        │
│ 3. Bu Haftaki Cari Ödemeler                            │
│    → Bugün ↔ bugün+7 gün arasındaki                    │
│      eşleşmemiş alacak kayıtları                       │
│                                                        │
│ 4. Vadesi Geçmiş Kredi Taksitleri                      │
│    → is_paid=FALSE ve due_date < bugün                 │
│                                                        │
│ 5. Son 6 Ay Grafik Verisi                              │
│    → Aylık gelir/gider/bakiye                          │
│    → GROUP BY (year, month)                            │
└────────────────────────────────────────────────────────┘
```

---

## 9. Frontend UI İş Akışı

```
┌──────────────────────────────────────────────────────────────────┐
│ Sayfa Yükleme Sırası                                              │
│                                                                  │
│  1. onMount()                                                     │
│     ├── GET /cash-flow/         → items (sayfalı liste)          │
│     ├── GET /cash-flow/summary  → özet kartları                  │
│     └── GET /cash-flow/monthly-summary → aylık akordiyon         │
│                                                                  │
│  2. WS bağlantısı kurulu                                          │
│     └── onWsEvent('finance_updated', () => loadData())           │
│                                                                  │
│  3. UI Render                                                     │
│     ┌────────────────────────────────────────────────┐            │
│     │           ÖZET KARTLARI (3 kart)                │            │
│     │  ┌──────────┐  ┌──────────┐  ┌──────────┐     │            │
│     │  │ Toplam   │  │ Toplam   │  │   Net    │     │            │
│     │  │  Gelir   │  │  Gider   │  │  Bakiye  │     │            │
│     │  │ emerald  │  │   rose   │  │ blue/red │     │            │
│     │  └──────────┘  └──────────┘  └──────────┘     │            │
│     └────────────────────────────────────────────────┘            │
│                                                                  │
│     ┌────────────────────────────────────────────────┐            │
│     │           AYLIK AKORDİYON                       │            │
│     │  ┌─ Nisan 2026 ──────────────────────────┐     │            │
│     │  │  Gelir: ₺xxx  Gider: ₺xxx  Net: ₺xxx │     │            │
│     │  │                                       │     │            │
│     │  │  GİDERLER (rose)  │  GELİRLER (green) │     │            │
│     │  │  ────────────────────────────────────  │     │            │
│     │  │  ABC Tedarik ₺15K │  Oda Geliri ₺25K  │     │            │
│     │  │  Vergi      ₺8K  │  Avans     ₺10K   │     │            │
│     │  │  Maaş       ₺12K │                    │     │            │
│     │  │              ▲    │        ▲           │     │            │
│     │  │          T çizgisi (blue-500)          │     │            │
│     │  └───────────────────────────────────────┘     │            │
│     │                                                │            │
│     │  ┌─ Mart 2026 ─────── (kapalı, tıkla aç) ┐   │            │
│     │  └────────────────────────────────────────┘    │            │
│     └────────────────────────────────────────────────┘            │
│                                                                  │
│  4. Filtreler                                                     │
│     ├── type: income / expense                                    │
│     ├── source: bank / check / credit / vendor_payment / ...     │
│     ├── category_id: Kategori filtresi                           │
│     ├── vendor_id: Cari filtresi                                 │
│     ├── payment_method: Ödeme yöntemi                            │
│     └── tagged: Etiketli / Etiketsiz                             │
│                                                                  │
│  5. Odak Modu (focusMode)                                         │
│     ├── "balanced" — Gelir ve gider eşit genişlikte              │
│     ├── "expense"  — Gider sütunu genişler                       │
│     └── "income"   — Gelir sütunu genişler                       │
└──────────────────────────────────────────────────────────────────┘
```

---

## 10. Kaynak Tiplerine Göre Veri Akışı Özet Tablosu

| Kaynak | source_type | direction | Upsert Metodu | Çift Sayım Kuralı |
|---|---|---|---|---|
| Banka İşlemi | `bank` | income/expense | `upsert_bank_tx()` | Eşleşme karşı tarafı görünür kalır |
| Çek | `check` | expense | `upsert_check()` | Banka eşleşmesi → gizle |
| Kredi Taksiti | `credit` | expense | `upsert_credit_payment()` | Banka eşleşmesi → gizle |
| KK Ekstresi | `cc_payment` | expense | `upsert_cc_statement()` | Vadesi geçmiş → gizle, kalan borç göster |
| Avans | `advance` | income | `upsert_advance()` | received → gizle |
| Cari Ödeme | `vendor_payment` | expense | `upsert_vendor_tx()` | match_number → gizle (FIFO kırpılmış) |
| Vergi | `tax` | expense | `upsert_scheduled_entry()` | — |
| Düzenli Ödeme | `recurring` | expense | `upsert_scheduled_entry()` | — |
| Maaş | `salary` | expense | `upsert_scheduled_entry()` | — |
| Stopaj | `withholding` | expense | `upsert_scheduled_entry()` | — |
| Alınan Kira | `rent_income` | income | `upsert_scheduled_entry()` | — |
| Verilen Kira | `rent_expense` | expense | `upsert_scheduled_entry()` | — |
| SGK | `sgk` | expense | `upsert_scheduled_entry()` | — |
| Temettü | `dividend` | expense | `upsert_scheduled_entry()` | — |

---

## 11. Hata ve Güvenlik Akışları

```
┌──────────────────────────────────────────────────┐
│ İzin Kontrolü                                     │
│                                                  │
│ Her endpoint:                                     │
│   require_permission("finance.cash_flow", "view") │
│   require_permission("finance.cash_flow", "use")  │
│                                                  │
│ JWT → HttpOnly cookie → middleware → izin matrisi │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│ Rate Limiting                                     │
│                                                  │
│ Liste endpoint'i:                                 │
│   heavy_limiter.check(f"cashflow-{user_id}")     │
│                                                  │
│ Amaç: Büyük veri setlerinde spam sorguyu önle     │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│ Veritabanı Rollback Koruması                      │
│                                                  │
│ try:                                              │
│   db.flush()                                      │
│   finance_event_svc.upsert_*(...)                │
│   db.commit()                                     │
│ except:                                           │
│   db.rollback()                                   │
│   raise                                           │
│                                                  │
│ broadcast_finance_update()                        │
│ ↑ Her zaman try bloğunun DIŞINDA                  │
│   (rollback sonrası yanlış WS bildirimi önlenir) │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│ Audit Logging                                     │
│                                                  │
│ Tüm CRUD işlemleri:                               │
│   log_action(db, user_id, "create",              │
│     "cash_flow", entity_id, details, ip)         │
│                                                  │
│ entity_type: "cash_flow"                          │
│ Eylemler: create, update, delete                  │
└──────────────────────────────────────────────────┘
```

---

## 12. Uçtan Uca Tam Senaryo: Banka Ekstre Yüklemesinden Nakit Akım Görüntülemeye

```
1. Kullanıcı A → Bankalar sayfasında Excel ekstre yükler
2. Backend → validate_upload_file() ile güvenlik kontrolü
3. Backend → Her satır için BankTransaction oluşturur
4. Backend → Her BankTransaction için finance_event_svc.upsert_bank_tx()
5. Backend → Otomatik eşleştirme dener:
   a. Çek numarası eşleşmesi → match() çağrısı → çek FE gizlenir
   b. Kredi taksiti eşleşmesi → match() çağrısı → kredi FE gizlenir
   c. KK ekstre eşleşmesi → upsert_cc_statement() → kalan borç güncellenir
6. Backend → db.commit()
7. Backend → broadcast_finance_update("banks", "upload")
8. 500ms debounce sonrası → WS: {"type": "finance_updated", "module": "banks"}
9. Kullanıcı B → Nakit akım sayfasında WS event'i alır
10. Frontend → otomatik GET /cash-flow/ çağrısı
11. Backend → finance_events tablosundan WHERE is_matched=FALSE ile sorgu
12. Frontend → T yapısında gelir/gider olarak gösterir
13. Özet kartları güncellenir (gelir, gider, net bakiye)
```

---

*Bu belge Nakit Akım modülünün tüm iş akışlarını, veri akışını ve mimari kararlarını kapsamaktadır.*
*Son güncelleme: 2026-04-12*
