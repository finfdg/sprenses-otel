# Hak Ediş Takibi

## Genel Bilgi
- **Modül kodu:** `finance.hakedis` (üst modül: `finance`, modül id: 920)
- **Frontend rota:** `/dashboard/finans/hakedis`
- **Backend prefix:** `/api/finance/hakedis`
- **İzin kodu:** `finance.hakedis` (view/use)

## İş Akışı (neden var)
Rezervasyon → misafir konaklar → **çıkışta fatura kesilir = HAK EDİŞ** (acenteden alacağımız).
Anlaşma gereği firma **30 veya 45 gün** içinde ödemeli. Bu modül firma bazlı açık hak edişleri,
vadeleri ve gecikmeleri takip eder.

## Mimari Karar — Sedna'da vade YOK (2026-07-02 keşfi)
Sedna'nın tüm veritabanları incelendi (29 DB): PMS `Invoice.DueDate` her zaman `InvoiceDate`'e eşit,
`Agency.Days` tüm acentelerde 0 → **Sedna gerçek vade takibi yapmıyor.** Bu yüzden:
- **Veri kaynağı:** Muhasebe 120.* hesapları — zaten `finance.sales_invoices` modülünce import edilir
  (fatura=borç, tahsilat=alacak) ve FIFO ile eşlenir (`sales_invoice_service._compute_cached`).
  **PMS'ten ayrı import YOK** (finansal tek doğru kaynak muhasebe; mükerrer import yaratılmaz).
- **Vade katmanı yerel:** `receivable_terms` tablosu (customer_code → term_days). Tanımsız firma
  **varsayılan 30 gün** (`DEFAULT_TERM_DAYS`). 45 günlük anlaşmalılar sayfadan düzenlenir.

## Dosya Haritası
| Katman | Dosya |
|---|---|
| Model | `backend/app/models/receivable_term.py` (`receivable_terms`) |
| Schema | `backend/app/schemas/receivable.py` |
| Servis | `backend/app/services/receivable_service.py` — vade+yaşlandırma hesabı; `upsert_term` router+executor ORTAK |
| Router | `backend/app/routers/finance/hakedis.py` |
| Executor | `approval_executor._handle_finance_hakedis` (ortak service çağırır) |
| Migration | `alembic/versions/f4a8c2d6e9b1_receivable_terms.py` (tablo + modül 920 + Admin izni) |
| Frontend | `frontend/src/routes/dashboard/finans/hakedis/+page.svelte` |
| Test | `backend/tests/test_hakedis.py` + `test_approval_system.py::test_hakedis_term_via_approval_regression` |

## Veritabanı Şeması — `receivable_terms`
| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | integer PK | |
| `customer_code` | varchar(50) unique | 120.* cari kodu (doğal anahtar) |
| `term_days` | integer (default 30) | Sözleşme vadesi (gün, 0-365) |
| `notes` | varchar(300) | Anlaşma notu |
| `created_at` / `updated_at` | timestamptz | |

## API Endpoint'leri
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/hakedis/` | view | Firma bazlı açık hak ediş + yaşlandırma + özet (tek çağrı; aggregate — pagination yok) |
| GET | `/hakedis/firms/{customer_code}/invoices` | view | Firmanın açık/kısmi faturaları (vade, gecikme, kalan native+TL) |
| PATCH | `/hakedis/terms/{customer_code}` | use | Vade tanımı upsert — `check_approval` + audit |

## Hesaplama Kuralları
- Fatura vadesi = `invoice_date + term_days` (firma tanımı yoksa 30).
- **Ödendi (FIFO)** faturalar ve kalanı ≤ 0,01 TL olanlar listeye girmez.
- Yaşlandırma kovaları: `not_due` · `overdue_1_7` · `overdue_8_30` · `overdue_30_plus`.
- Firma sıralaması: geciken tutar (TL) azalan, eşitlikte açık tutar azalan.
- Tutarlar kart/toplamada **TL karşılığı**; fatura detayında native (EUR/USD) + TL birlikte.
- `summary.due_7d_tl`: 7 gün içinde vadesi dolacak (henüz gecikmemiş) toplam.

## Onay Akışı
- `PATCH /terms/{code}` `check_approval(db, "finance.hakedis", term_id|0, ...)` — payload'da
  `customer_code` taşınır; executor **doğal-anahtar upsert** yapar (budget deseni, çift kayıt yok).
- Executor router ile AYNI `receivable_service.upsert_term`'i çağırır (D1-2).
- GET'ler salt-okuma → onaydan muaf. Vade tanımı silinmez (30'a çekilir) → delete dalı yok.

## Audit Log
- `entity_type`: `receivable_term` — `action`: create/update (customer_code + term_days detayı).

## Frontend UI
- Kanonik iskelet: PageHeader → StatCard×4 (Açık/Vadesi Geçen/7 Gün İçinde/30+ Gün) → filtre
  (arama debounce 300ms + "yalnız vadesi geçenler") → tablo (satır genişlet → fatura detayı) → Modal.
- Gecikme rozeti: `StatusBadge` success(vadesinde)/warning(≤7g)/error(>7g). Mobil `<sm` kart görünümü.
- Vade düzenleme: Modal + `Field`/`Input type=number` (gün — para değil, MoneyInput gerekmez;
  bilinçli istisnalar listesindeki "vade günü" deseni).
- WS: `finance_updated` event'inde yeniden yükler (Sedna sync sonrası güncel).

## Geliştirme Kuralları
- Veri tazeliği `finance.sales_invoices` import'una bağlıdır (Topbar "Sedna" butonu / merkezi sync).
- v2 adayları (bilinçli ertelendi): vadesi geçenler için günlük bildirim (Notification+push),
  Excel export, firma takip notu geçmişi.
