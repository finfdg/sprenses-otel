# İnsan Kaynakları Modülü — Geliştirici Rehberi

İK alt modülleri (`salary`, `withholding`, `sgk`) muhasebe ile **aynı fabrika desenini**
(`create_scheduled_router`) kullanır. Bu dosya İK modülüne özel kuralları içerir.

## Mimari — Fabrika Deseni

`__init__.py`:

```python
from app.constants import BroadcastModule, SourceType
from app.routers.scheduled_base import create_scheduled_router

salary_router = create_scheduled_router(
    source_type=SourceType.SALARY,
    permission_code="hr.salary",
    entity_label="Maaş",
    broadcast_module=BroadcastModule.HR,
)
```

- Tüm CRUD/summary/giriş üretimi `routers/scheduled_base.py` içinde ortaktır.
- İzin + onay + audit + finance_event + broadcast fabrikada gömülüdür.
- İK modülleri **gider**dir (`direction=-1`, varsayılan).

## İK'ya Özel İş Kuralı — Ödeme Tarihi Kayması

Maaş/SGK/stopaj **ertesi ay** ödenir. `utils/entry_generator.py` içindeki
`_SHIFT_NEXT_MONTH_SOURCES` kümesi (`salary`, `sgk`, `withholding`) bu kaymayı yönetir:
Ocak dönemi girişi → Şubat ödeme tarihi. Yeni bir "ertesi ay ödenen" İK modülü eklerken
bu kümeye de eklenmelidir.

## Sabitler (2026-06-04)

- `source_type` / `broadcast_module` literal yazılmaz; `app/constants.py` →
  `SourceType.*` / `BroadcastModule.HR` kullanılır.
- `SourceType.SALARY/WITHHOLDING/SGK` değerleri DB'de saklanır — değiştirilemez.

## Onay (Approval) Entegrasyonu

- Muhasebe ile aynı: `approval_executor.py` → `_SCHEDULED_SOURCE_MAP` modül kodunu
  `(SourceType.*, direction)` ile eşler; handler fabrikadan otomatik üretilir.

Detay: `docs/modules/muhasebe-ik.md`, `docs/modulerlik-iyilestirmeleri.md`.
