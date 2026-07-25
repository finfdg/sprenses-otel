"""logging katmanını error_logs tablosuna köprüler (LOG-001, 2026-07-25).

Denetim bulgusu: kodda 100+ `logger.error/exception/critical` çağrısı var ama
`error_logs` tablosuna yalnızca iki yer yazıyordu (main.py global exception handler
ve sedna_sync adım hataları). Yani `logger.error(...)` çağrıları journald + dosya
loguna düşüyor, "Hata Logları" UI'ında ise görünmüyordu — log ile kayıt katmanı kopuk.

Çözüm: root logger'a bu handler eklenir. ERROR ve üstü her log kaydı `error_logs`
tablosuna yazılır → tüm logger.error/exception/critical çağrıları UI'da görünür.

Tasarım notları:
- **Re-entrancy koruması:** DB yazımı sırasında bir ERROR loglanırsa (ör. SQLAlchemy)
  sonsuz özyineleme olmasın diye thread-local bayrak kullanılır; hata durumunda
  asla logging katmanına geri düşülmez, yalnızca stderr'e yazılır.
- **Ayrı session:** Her yazım taze `SessionLocal()` ile yapılır (çağıran isteğin
  session'ını/transaction'ını kirletmesin, rollback'ten etkilenmesin). Best-effort:
  yazım patlarsa uygulama akışını asla düşürmez (dosya logu zaten yazıldı).
- **Çift kayıt önleme:** `extra={"_skip_db_log": True}` ile loglanan kayıtlar atlanır
  (ör. global exception handler zaten zengin bağlamla kendi ErrorLog'unu yazar).
- **Test kirlenmesi önleme:** Prod yolu (varsayılan SessionLocal) pytest sırasında
  yazmaz — testler kendi transaction'larına bağlı bir `session_factory` enjekte eder.
"""
import logging
import os
import sys
import threading
import traceback as _tb
from typing import Callable, Optional

_reentry = threading.local()


class DBLogHandler(logging.Handler):
    """ERROR ve üstü log kayıtlarını error_logs tablosuna yazan handler."""

    def __init__(
        self,
        session_factory: Optional[Callable] = None,
        level: int = logging.ERROR,
    ) -> None:
        super().__init__(level)
        # None → prod: her yazımda taze SessionLocal aç ve kapat.
        # Enjekte edilirse (test): dönen session çağırana ait, handler kapatmaz.
        self._session_factory = session_factory

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "_skip_db_log", False):
            return
        # Prod global handler: pytest sırasında gerçek DB'ye yazma (test kirlenmesi).
        # Enjekte session (test) bu kapıdan muaf — testler kasıtlı yazar.
        if self._session_factory is None and os.environ.get("PYTEST_CURRENT_TEST"):
            return
        # Re-entrancy: DB yazımı sırasında oluşan ERROR logları özyinelemeyi tetiklemesin.
        if getattr(_reentry, "active", False):
            return
        _reentry.active = True
        try:
            self._write(record)
        except Exception:  # noqa: BLE001 — log yazımı asla uygulamayı düşürmesin
            # Logging katmanına GERİ DÜŞME (recursion) — doğrudan stderr'e yaz.
            try:
                sys.stderr.write("[DBLogHandler] error_logs yazımı başarısız\n")
            except Exception:
                pass
        finally:
            _reentry.active = False

    def _write(self, record: logging.LogRecord) -> None:
        from app.models.error_log import ErrorLog

        own_session = self._session_factory is None
        if own_session:
            from app.database import SessionLocal
            db = SessionLocal()
        else:
            db = self._session_factory()

        traceback_text = None
        if record.exc_info:
            traceback_text = "".join(_tb.format_exception(*record.exc_info))[:5000]

        try:
            db.add(ErrorLog(
                level=record.levelname[:20],
                source=(record.name or "root")[:100],
                message=record.getMessage()[:2000],
                traceback=traceback_text,
            ))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            if own_session:
                db.close()
