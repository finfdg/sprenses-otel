"""LOG-001 regresyon testleri — logging katmanı → error_logs köprüsü.

Denetim bulgusu (2026-07-25, Boyut 12): kodda 100+ logger.error/exception/critical
çağrısı var ama error_logs'a hiçbiri düşmüyordu — log ile kayıt katmanı kopuk.
Kapanış kriteri: bir logger.error çağrısı error_logs'ta kayıt üretmeli.

Bu testler geri alınınca (main.py'de handler kaydı silinince VEYA _write bozulunca)
kırmızıya döner.
"""
import logging

import pytest

from app.models.error_log import ErrorLog
from app.utils.db_log_handler import DBLogHandler


@pytest.fixture(autouse=True)
def _wipe_error_logs(db):
    """Her test başında error_logs'u temizle — temiz sayım."""
    db.query(ErrorLog).delete()
    db.flush()
    yield


@pytest.fixture
def bridged_logger(db):
    """Test transaction'ına bağlı bir DBLogHandler'ı root logger'a iliştirir.

    Prod handler'ı (SessionLocal) pytest sırasında kasıtlı yazmaz; burada test
    session'ına enjekte edilmiş bir handler ile gerçek propagation yolu
    (logger.error → root handler → error_logs) test edilir.
    """
    handler = DBLogHandler(session_factory=lambda: db)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield logging.getLogger("test.log001")
    finally:
        root.removeHandler(handler)


# ─── Kapanış kriteri ────────────────────────────────────────────


def test_logger_error_creates_error_log(bridged_logger, db):
    """KAPANIŞ KRİTERİ: bir logger.error çağrısı error_logs'ta kayıt üretir."""
    bridged_logger.error("Köprü testi: kritik iş hatası %s", "X42")

    rows = db.query(ErrorLog).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.level == "ERROR"
    assert row.source == "test.log001"
    assert row.message == "Köprü testi: kritik iş hatası X42"


def test_logger_exception_captures_traceback(bridged_logger, db):
    """logger.exception traceback'i error_logs.traceback'e yazar."""
    try:
        raise ValueError("patladı")
    except ValueError:
        bridged_logger.exception("İşlem başarısız")

    row = db.query(ErrorLog).one()
    assert row.level == "ERROR"
    assert row.message == "İşlem başarısız"
    assert row.traceback is not None
    assert "ValueError: patladı" in row.traceback


def test_critical_is_captured(bridged_logger, db):
    """CRITICAL seviye de yazılır."""
    bridged_logger.critical("Sistem kritik durumda")
    row = db.query(ErrorLog).one()
    assert row.level == "CRITICAL"


# ─── Gürültü kontrolü ───────────────────────────────────────────


def test_info_and_warning_not_written(bridged_logger, db):
    """INFO/WARNING error_logs'a düşmez (handler seviyesi ERROR)."""
    bridged_logger.info("bilgi")
    bridged_logger.warning("uyarı")
    assert db.query(ErrorLog).count() == 0


def test_skip_db_log_flag_respected(bridged_logger, db):
    """extra={'_skip_db_log': True} olan kayıt atlanır (çift kayıt önleme)."""
    bridged_logger.error("Bu atlanmalı", extra={"_skip_db_log": True})
    assert db.query(ErrorLog).count() == 0


def test_write_failure_does_not_raise(db):
    """DB yazımı patlarsa handler istisna fırlatmaz (best-effort)."""
    def _boom():
        raise RuntimeError("session açılamadı")

    handler = DBLogHandler(session_factory=_boom)
    record = logging.LogRecord(
        name="test", level=logging.ERROR, pathname=__file__, lineno=1,
        msg="mesaj", args=(), exc_info=None,
    )
    # İstisna sızmamalı
    handler.emit(record)


# ─── Prod bağlantısı (wiring) ───────────────────────────────────


def test_handler_registered_on_root_logger():
    """main.py root logger'a DBLogHandler ekler — köprü canlıda kurulu.

    Bu testin varlığı, düzeltmenin main.py'den silinmesini yakalar.
    """
    import app.main  # noqa: F401 — kayıt import'ta yapılır

    root = logging.getLogger()
    assert any(isinstance(h, DBLogHandler) for h in root.handlers)
