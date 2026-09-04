"""Cari modülü paylaşılan yardımcı fonksiyonlar ve sabitler.

(2026-09-02) `_build_tx_response` ve `_build_dept_cat_user_maps` gövdeleri
`app/services/vendor_service.py`'ye BİREBİR taşındı (katman yönü: router → service → model;
parmak izi aynı kaynağı kullanır). Bu modül adları geriye uyumluluk için yeniden dışa verir —
eski `from ._helpers import ...` yolu çözülmeye devam eder.
"""

import logging
import os

from app.paths import uploads_subdir
from app.services.vendor_service import (  # noqa: F401 — geriye uyumluluk: testler/parmak izi bu yoldan import eder (2026-09-02 çıkarımı)
    _build_dept_cat_user_maps,
    _build_tx_response,
)

logger = logging.getLogger(__name__)

UPLOAD_DIR = uploads_subdir("vendor_statements")


def _ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)

