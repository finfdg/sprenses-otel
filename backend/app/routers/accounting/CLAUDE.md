# Muhasebe Modülü — Geliştirici Rehberi

Muhasebe alt modüllerinden `taxes`, `recurring`, `rent_income`, `rent_expense`
ortak **fabrika deseni** ile üretilir. `dividend` (Temettü) **bespoke**tir (fabrika DIŞI —
aşağıdaki carve-out); `fis_icmali`/`mizan` de fabrika dışıdır. Bu dosya muhasebe modülüne
katkı kurallarını içerir.

## Mimari — Fabrika Deseni

`__init__.py` her alt modülü tek satırla üretir:

```python
from app.constants import BroadcastModule, SourceType
from app.routers.scheduled_base import create_scheduled_router

taxes_router = create_scheduled_router(
    source_type=SourceType.TAX,
    permission_code="accounting.taxes",
    entity_label="Vergi",
    broadcast_module=BroadcastModule.ACCOUNTING,
)
```

- **Tüm CRUD + summary + giriş üretimi** `routers/scheduled_base.py` içinde tek yerde.
  Bir düzeltme 5 muhasebe + 3 İK modülünü birden düzeltir.
- **İzin + onay + audit + finance_event + broadcast** fabrikada gömülüdür — alt modülün
  ayrıca eklemesi gerekmez.
- `direction`: gelir modülleri (`rent_income`) `+1`, gider modülleri `-1`.

## Sabitler (2026-06-04)

- `source_type` ve `broadcast_module` değerleri **literal yazılmaz**; `app/constants.py`
  içindeki `SourceType.*` / `BroadcastModule.*` sabitleri kullanılır.
- `SourceType` değerleri DB'de saklanır (`scheduled_definitions.source_type`) —
  **değiştirilemez**, yalnızca isimli referans. Yeni source_type = migration.

## Onay (Approval) Entegrasyonu

- CRUD onay kontrolü `scheduled_base.py` içinde `check_approval()` ile yapılır.
- Onaylanan talepler `utils/approval_executor.py` → `_make_scheduled_handler` fabrikasıyla
  uygulanır; `_SCHEDULED_SOURCE_MAP` modül kodunu `(SourceType.*, direction)` ile eşler.
- Yeni planlı modül eklerken: `_SCHEDULED_SOURCE_MAP`'e satır ekle — handler otomatik gelir.

## Cari Senkronu — Düzenli Ödemeler (2026-06-06)

Düzenli Ödemeler (`recurring`) fabrikada `enable_vendor_sync=True` ile üretilir → `POST
/recurring/sync-vendors` endpoint'i + `scheduled_definitions.vendor_id` cari bağlantısı aktif.
Cari-bağlı kalemlerin (Elektrik→CK, Su→ASAT) **tahmini** tutarları, carinin **gerçek** aylık
faturası + FIFO ödeme durumuyla senkronlanır; senkron ayda recurring finance_event silinir
(cari `vendor_payment` temsil eder → çift sayım yok). Motor: `utils/recurring_vendor_sync.py`
(`sync_recurring_from_vendors` saf mantık; `run_recurring_vendor_sync` commit+audit sarmalı).
Tetikleme: merkezi Sedna butonu (`sedna_sync.py:_STEPS` → `recurring_sync` adımı, cari adımından
sonra) **veya** sayfadaki "Cari ile Senkronize" butonu. Detay: `docs/modules/muhasebe-ik.md`
(Cari Senkronu bölümü). **Diğer planlı modüller `enable_vendor_sync` almaz** (yalnız recurring).

## Yeni Planlı Modül Ekleme — Kontrol Listesi

1. `modules` tablosuna kod + izin (ör. `accounting.yeni`).
2. `app/constants.py` → `SourceType.YENI` ekle (DB'ye yeni source_type giriyorsa migration).
3. `__init__.py` → `create_scheduled_router(...)` + `include_router(..., prefix="/yeni")`.
4. `approval_executor.py` → `_SCHEDULED_SOURCE_MAP`'e `"accounting.yeni": (SourceType.YENI, -1)`.
5. Frontend: `ScheduledModule.svelte` kullanan sayfa + `navigation.ts`'e NavItem.
6. `docs/modules/muhasebe-ik.md` güncelle.

Detay: `docs/modules/muhasebe-ik.md`, `docs/modulerlik-iyilestirmeleri.md`.

## Temettü (Kâr Payı Dağıtımı) — Fabrika Dışı (bespoke parent/child)

`dividend` (Temettü) artık planlı-gider fabrikasının **parçası değildir** — `finance.krediler`
deseni gibi bespoke bir parent/child modüldür (dağıtım → pay sahipleri + taksitler + 72 ödeme).
Router paketi `accounting/dividend/` (`distributions.py`/`payments.py`/`_helpers.py`), ortak
service `app/services/dividend_service.py` (router + onay executor `_handle_accounting_dividend`
ORTAK). `_SCHEDULED_SOURCE_MAP`'te YOKtur; `_HANDLERS`'a AÇIK kayıtlıdır. Nakit akım: taksit başına
`dividend` (net) + `dividend_stopaj` (ertesi ay 26 muhtasar) finance_events. Detay:
`docs/modules/temettu.md`.

## Canlı Sedna Modülleri — Fabrika Dışı (salt-okunur)

`fis_icmali` (Kullanıcı Fiş İcmali) ve `mizan` (Geçici Mizan) planlı-gider fabrikasının **parçası
değildir** — `create_scheduled_router` kullanmazlar. İkisi de **canlı Sedna muhasebe sorgusu**
(yerel model/migration/finance_event/onay/audit YOK; salt-okunur rapor). `__init__.py`'de kendi
`router`'ları ayrı `include_router` ile bağlanır (`/fis-icmali`, `/mizan`).

- **fis_icmali:** `AccountingOwner.RecordUser` → kim ne zaman fiş kesmiş (üretkenlik). Detay:
  `docs/modules/fis-icmali.md`.
- **mizan:** `AccountingTrans` borç/alacak → hesap kademe bazında dönem mizanı + drill-down (alt
  hesap → defter). 60sn TTL cache; Türkçe-duyarsız arama (`_search_norm`); `code`/`parent`
  `[A-Za-z0-9.]` doğrulanır (SQL gömme güvenliği). Detay: `docs/modules/mizan.md`.

**Yeni canlı-Sedna rapor modülü** eklerken bu deseni izle (fabrika değil): `sedna_client.py`'ye
`fetch_*` + ayrı router + RBAC modülü + `tests/ci/02_seed.sql` + `navigation.ts`. `require_permission`
ile korunur; mutasyon olmadığından onay/audit gerekmez.

## Sedna Mutabakat (`accounting.mutabakat`) — Uyuşmayan Veriler

Banka ↔ Sedna 102 defteri mutabakat modülü; fabrika dışı. Router `mutabakat.py`, motor
`services/sedna_recon_service.py` (router + onay executor `_handle_accounting_mutabakat` ORTAK).
Kural: **banka verisi HER ZAMAN otorite** — motor banka satırını değiştirmez, yalnız sınıflar;
Sedna girilince/düzeltilince kayıt otomatik kapanır. Tam anlatım: `docs/modules/sedna-mutabakat.md`.

**Faz B eklemeleri (2026-07-11):**
- `GET /mutabakat/fx-revaluation` — aylık kur değerlemesi raporu (bizim ay sonu bakiye ×
  `fx_service.ledger_rate` ↔ Sedna Type=4 fişi yan yana). **Salt rapor — deftere/finance_events'e
  YAZMAZ** (kullanıcı kararı). `ledger_rate` = `exchange_rates(tarih−1).forex_buying` (Sedna
  "geçerlilik" vs bizim "yayın" tarihi — 1 gün kayma).
- `GET /mutabakat/fx-differences` — kur farkı kayıtları (646/656 eşleniği; çapraz-para
  eşleşmelerden `fx_differences` tablosunda birikir; FE'ye kalem yazılmaz).
- `GET /mutabakat/items` artık `entity_type` (`bank|check|vendor_tx`) filtresi alır (`bank` =
  entity_type'ı NULL banka satırları için takma değer — frontend tür filtresi "Banka" seçeneği); yanıt satırında
  `entity_type`/`entity_id`. Yeni durum **`ReconStatus.SEDNA_DIFF`** (`sedna_diff`): eşleşmiş/
  KORUNAN yerel çek/cari kaydında Sedna farkı — yerel kayıt otomatik DEĞİŞTİRİLMEZ, importlar
  `report_entity_diff` ile buraya yazar; giderilince `close_stale_entity_diffs` otomatik kapatır.
  `sedna_diff` kritik durum kümesindedir (`_CRITICAL_STATUSES`).
