# Temettü (Kâr Payı Dağıtımı) Modülü

## Genel Bilgi

- **Modül kodu:** `accounting.dividend` (modül id 258, parent 249 `accounting`)
- **Üst modül:** Muhasebe
- **Frontend rota:** `/dashboard/muhasebe/temettu`
- **Backend prefix:** `/api/accounting/dividend`
- **İzin:** `require_permission("accounting.dividend", "view"|"use")`
- **Tip:** Bespoke parent/child modül — **create_scheduled_router fabrikası DEĞİL** (fis_icmali/mizan gibi carve-out).

Genel kurul kararıyla dağıtılan kâr payı; her pay sahibinin brüt payı, %15 stopaj kesintisi ve
net tutarı hesaplanır. Toplam kâr payı N taksite bölünür, her taksitte **pay sahibi × taksit**
bazında (ör. 12 ortak × 6 taksit = 72) ödeme satırı ayrı takip edilir.

> **Neden bespoke?** Eski temettü, jenerik "planlı ödeme" fabrikasının ince bir örneğiydi (tek tutar
> + sıklık). Pay sahibi/oran/brüt-stopaj-net kavramı yoktu → gerçek kâr payı dağıtım yapısını
> taşıyamıyordu. `finance.krediler` deseni (parent/child + ortak service) izlenerek yeniden yazıldı.

## Veri Modeli — 4 tablo (`app/models/dividend.py`)

- **`dividend_distributions`** (parent): `name`, `decision_date`, `total_gross`, `capital`,
  `withholding_rate`(Num6,4 = 0.15), `installment_count`, `year`, `status`(active/cancelled), `notes`, `created_by`.
- **`dividend_shareholders`** (child CASCADE): `sort_order`, `name`, `share_value`, `share_ratio`(Num9,6),
  `gross_dividend`, `stopaj_amount`, `net_dividend`.
- **`dividend_installments`** (child CASCADE — **nakit akım taşıyan birim**): `installment_no`, `due_date`,
  `label`, `gross_amount`, `stopaj_amount`, `net_amount`. Her taksit **2 finance_event** üretir.
- **`dividend_payments`** (72 satır, 3 FK CASCADE): `installment_id`, `shareholder_id`, `gross/stopaj/net_amount`,
  `is_paid`+`paid_date`, `stopaj_paid`+`stopaj_paid_date`, `notes`.

## Üretim Algoritması (`app/services/dividend_service.py`)

`create_distribution(db, data, actor_id)` — Python `Decimal` + ROUND_HALF_UP, 2 hane:

1. **Pay sahibi:** `denom` = `capital` (yalnız `capital == Σ share_value` ise), yoksa `Σ share_value`.
   `ratio = share_value/denom`, `gross = total_gross × ratio` (q2), `stopaj = gross × rate` (q2), `net = gross − stopaj`.
   **Reconcile YOK** — Excel de reconcile etmez; 12 satırın toplamı headerdan ~1 kuruş sapabilir (aynen korunur;
   Excel Özet TOPLAM = 20.000.000,01).
2. **Taksit:** vadeler `installment_dates` verilirse onlar; yoksa `first_installment_date`'ten aylık **ay-sonları**
   (`_month_ends`). Taksit tutarları **ödemelerden türetilir** (aşağı).
3. **72 ödeme (sahip × taksit):** her sahip için `gross/count` (q2), **son taksit sahip-artığını absorbe eder**;
   `stopaj = gross × rate` (q2), `net = gross − stopaj`. → Excel taksit sheet'leriyle birebir (ör. İSMAİL taksit-6 458.333,35).
4. **Taksit toplamı = Σ ödeme** → `Σ payment == installment` invaryantı garanti.
5. Her taksit için 2 finance_event (net + stopaj).

**İki toplam görünümü (Excel'de de tutarsız, ~3 kuruş):** headline `total_net`/`total_stopaj` **pay sahibi (Özet)**
görünümünden gelir (Excel Özet TOPLAM ile birebir: net 17.000.000,01). Taksit/ödeme satırları taksit sheet'leriyle
birebir (Σ = 16.999.999,98). İki görünüm de kendi Excel karşılığıyla eşleşir.

## Nakit Akım (finance_events) — ÖDEME (kişi-kişi) bazlı Net + Stopaj

**finance_event TAKSİT değil ÖDEME satırı (`dividend_payments`, `payment.id`) anahtarlıdır** (2026-07-05
kullanıcı kararı). Her ödeme (pay sahibi × taksit) **2 ayrı çıkış** üretir → nakit akımda **her ortak
ayrı satır**, kısmi ödemeler ayırt edilir (ör. 12×6 dağıtım = 72 net + 72 stopaj FE):

| Kalem | source_type | event_date | tutar | durum |
|---|---|---|---|---|
| Net (ortağa) | `dividend` | **gerçek ödeme tarihi** (`paid_date`) — yoksa taksit `due_date` | ödemenin net'i | `is_paid` |
| Stopaj (vergi dairesi) | `dividend_stopaj` | net'in **efektif ödeme ayının ertesi ayı 26** (muhtasar) — stopaj ödendiyse `stopaj_paid_date` | ödemenin stopajı | `stopaj_paid` |

`_payment_events(db, payment, shareholder, installment, distribution)` (`dividend_service.py`) →
`upsert_dividend_net`/`upsert_dividend_stopaj` (`finance_event_service.py`). **Kritik kural:** net
gerçek ödeme tarihine kayarsa (ör. 30.06 planlı → 03.07 fiili, ay geçer) **stopaj da bir sonraki aya
sarkar** (Haziran değil Temmuz ödemesi → Ağustos 26 muhtasar). Ödeme roll-up YOK — her ödeme bağımsız;
kısmi ödeme yapılan ortak "paid", diğerleri "pending" görünür. `stopaj_amount == 0` → stopaj olayı invalidate.

**Banka eşleştirme (çift sayım engeli, 2026-07-05):** `dividend_payments.bank_transaction_id` — net
ödemenin yapıldığı banka hareketi. Doluysa `upsert_dividend_net` **is_matched=True** yapar → net
finance_event nakit akımda **gizlenir**, gerçek banka çıkışı (bank FE) sayılır (çek/kredi deseniyle
aynı; migration `e1a4c7f9b2d6`). Ödeme yine Temettü modülünde "ödendi" görünür (durum `is_paid`'ten).
`PATCH /payments/{id}` body'sine `bank_transaction_id` verilerek bağlanır. Stopaj bacağı ayrı bir
yükümlülük (muhtasar) olduğundan **eşleştirilmez** — kendi ödeme tarihine kadar bekler.

## API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/accounting/dividend/` | view | Liste (page/page_size/year/status/search; N+1'siz özet) |
| GET | `/accounting/dividend/years` | view | Dağıtımı olan distinct yıllar (yıl seçici; **`/{id}`'den ÖNCE tanımlı**) |
| GET | `/accounting/dividend/{id}` | view | Detay (sahipler + taksitler + 72 ödeme) |
| POST | `/accounting/dividend/` | use | Dağıtım oluştur (header + shareholders[name,share_value]) |
| PATCH | `/accounting/dividend/{id}` | use | Metadata (name/decision_date/status/notes); status=cancelled → FE kaldırır |
| DELETE | `/accounting/dividend/{id}` | use | Sil (FE invalidate + CASCADE) |
| PATCH | `/accounting/dividend/payments/{id}` | use | Ödeme net/stopaj ödendi işaretle (`_target=payment`) |

Tüm mutasyonlar: `require_permission` + `check_approval` + `log_action` + `broadcast_finance_update(ACCOUNTING)`.
**Finansal alanlar patch'lenmez** — değişim = sil + yeniden oluştur (kısmi-regen bug'ı önlenir).

## Onay Akışı

Router + onay executor **ORTAK** `dividend_service` çağırır (D1-2). Handler `_handle_accounting_dividend`
(`approval_executor.py`) `_target` ile dağıtım/ödeme ayırır; `_HANDLERS["accounting.dividend"]` açık kayıtlı
(AST testi `test_all_approval_callers_have_executor_handler` şartı). Temettü `_SCHEDULED_SOURCE_MAP`'te **YOK**.

## Frontend UI

`temettu/+page.svelte` — bespoke sayfa (tasarım sistemi): PageHeader + filtre barı + dağıtım akordeonu.
Genişletince StatCard (Brüt/Net/Stopaj/Ödeme ilerlemesi) + pay sahipleri tablosu + taksitler; taksit
genişletince 12 sahip satırı, her birinde "Net Ödendi" + "Stopaj Ödendi" onay kutusu. **Oluştur modalı**:
dinamik pay sahibi satırları + **canlı önizleme** (istemci tarafı oran/brüt/stopaj/net + toplam; sunucu
yeniden hesaplar). WS `finance_updated` (module=accounting) → yeniden yükle.

## Audit Log

- `entity_type`: `dividend_distribution` (create/update/delete), `dividend_payment` (update)

## Geliştirme Kuralları

- Para hesabı **Decimal + ROUND_HALF_UP**; float aritmetiği yok. Yanıtta `float()` (Numeric→float).
- Rota sırası: `payments` (`/payments/{id}`) `distributions` (`/{id}`) wildcard'ından **önce** mount.
- **`GET /years` `/{distribution_id}` path-param'ından ÖNCE tanımlı** (`distributions.py`) — aksi halde
  FastAPI "years"i int'e çözmeye çalışır → 422 (test: `test_dividend.py::TestYears::test_years_route_not_shadowed_by_detail`).
- Ödeme mutasyonu `{"_target":"payment"}` gönderir; dağıtım mutasyonu göndermez.
- Yeni `source_type` = migration (DB'de saklanır, değiştirilemez).

### Yıl seçici — dinamik (2026-07-06 hata düzeltmesi)
Frontend yıl menüsü eskiden **`[2024..2028]` sabit dizisiydi** → gelecekteki yıllara ait dağıtım
gizli/erişilemez (SGK gizli-yıl hatasının aynısı). Çözüm: `GET /accounting/dividend/years` (distinct
`DividendDistribution.year`); `temettu/+page.svelte` `loadYears()` cari yıl ±1 penceresiyle birleştirip
(`YEARS`) hem filtre hem oluştur-modalı dropdown'unu doldurur; `onMount` + `finance_updated` WS'te
yenilenir, fetch hata verirse base pencereye düşer. Referans: `docs/modules/muhasebe-ik.md` "Yıl seçici — dinamik".

## Test

- `tests/test_dividend.py` — üretim (RECEP ÖZDEN 3.150.000/472.500/2.677.500; İSMAİL taksit-6 458.333,35;
  ay-sonu taksitler; Σ invaryant), 6 net + 6 stopaj FE (net=due_date, stopaj=ertesi ay 26), toggle roll-up,
  silme invalidate+CASCADE, cancel FE kaldırma, RBAC 403.
- `tests/test_approval_system.py` — `test_dividend_create_via_approval_*` + `test_dividend_payment_toggle_via_approval`.

## Migration

`c7e2a9f4b6d1_dividend_module` (down_revision `a6fb877d2af1`): 4 tablo + indeksler + **eski
`source_type='dividend'` verisi temizliği** (finance_events + scheduled_entries + scheduled_definitions).
Temizlik ZORUNLU (çakışma: eski FE scheduled_entries.id, yeni FE installment.id ile aynı 'dividend'
anahtarını paylaşır) ve geri alınamaz.
