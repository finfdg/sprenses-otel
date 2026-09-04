"""Krediler paketinde paylaşılan yardımcı fonksiyonlar.

(2026-09-02) `_build_product_response` ve `_batch_payment_stats` gövdeleri
`app/services/credit_service.py`'ye BİREBİR taşındı (katman yönü: router → service → model;
onay executor + parmak izi aynı kaynağı kullanır). Bu modül adları geriye uyumluluk için
yeniden dışa verir — eski `from ._helpers import ...` yolu çözülmeye devam eder.
"""

from app.services.credit_service import (  # noqa: F401 — geriye uyumluluk: testler/parmak izi bu yoldan import eder (2026-09-02 çıkarımı)
    _batch_payment_stats,
    _build_product_response,
)
