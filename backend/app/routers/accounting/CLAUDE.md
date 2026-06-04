# Muhasebe Modülü — Geliştirici Rehberi

Muhasebe alt modülleri (`taxes`, `recurring`, `rent_income`, `rent_expense`, `dividend`)
ortak **fabrika deseni** ile üretilir. Bu dosya muhasebe modülüne katkı kurallarını içerir.

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

## Yeni Planlı Modül Ekleme — Kontrol Listesi

1. `modules` tablosuna kod + izin (ör. `accounting.yeni`).
2. `app/constants.py` → `SourceType.YENI` ekle (DB'ye yeni source_type giriyorsa migration).
3. `__init__.py` → `create_scheduled_router(...)` + `include_router(..., prefix="/yeni")`.
4. `approval_executor.py` → `_SCHEDULED_SOURCE_MAP`'e `"accounting.yeni": (SourceType.YENI, -1)`.
5. Frontend: `ScheduledModule.svelte` kullanan sayfa + `navigation.ts`'e NavItem.
6. `docs/modules/muhasebe-ik.md` güncelle.

Detay: `docs/modules/muhasebe-ik.md`, `docs/modulerlik-iyilestirmeleri.md`.
