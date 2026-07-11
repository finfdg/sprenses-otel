"""Test yapılandırması ve fixture'lar.

Her test fonksiyonu bir DB transaction içinde çalışır ve test bitince
otomatik rollback yapılır — production DB'ye kalıcı veri yazılmaz.
"""

import os
import sys
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

# Test DB zorunlu — prod DB'ye sızmayı önlemek için DATABASE_URL set edilmeli ve "_test" içermeli.
# Bypass için ALLOW_PROD_DB_TESTS=1 (kullanılması önerilmez).
_db_url = os.environ.get("DATABASE_URL")
if not _db_url:
    sys.stderr.write(
        "\n[conftest] DATABASE_URL set edilmedi. Test için ayrı bir DB kullan:\n"
        "  export DATABASE_URL=postgresql://sprenses:PASS@127.0.0.1:5432/sprenses_test\n\n"
    )
    pytest.exit("DATABASE_URL gerekli", returncode=2)

if "_test" not in _db_url and not os.environ.get("ALLOW_PROD_DB_TESTS"):
    sys.stderr.write(
        f"\n[conftest] DATABASE_URL prod gibi görünüyor: {_db_url}\n"
        "Test DB adı '_test' içermeli. Bilerek prod-benzeri DB kullanıyorsanız\n"
        "ALLOW_PROD_DB_TESTS=1 ile bypass edin.\n\n"
    )
    pytest.exit("DATABASE_URL test DB'sine işaret etmeli", returncode=2)

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-minimum-32-characters-long")
# TestClient HTTP kullandığından secure cookie gönderilmez — CORS_ORIGINS'i http yaparak secure=False sağla
os.environ["CORS_ORIGINS"] = "http://testserver"

from app.database import Base, get_db
from app.main import app
from app.middleware.rate_limit import (
    login_limiter,
    register_limiter,
    message_limiter,
    upload_limiter,
    search_limiter,
    heavy_limiter,
    runway_limiter,
    eur_balances_limiter,
    ai_limiter,
    ai_daily_limiter,
)
from app.routers.messages._helpers import _invalidate_messaging_role_cache
from app.services.sales_invoice_service import _invalidate_compute_cache as _invalidate_sales_compute_cache
from app.services.deferral_service import invalidate_deferral_cache
from app.services.hold_service import invalidate_hold_cache
from app.services.period_lock_service import invalidate_lock_cache
from app.middleware.auth import invalidate_module_cache
from app.models.user import User
from app.models.module import Module
from app.models.role_module_permission import RoleModulePermission


# Test DB: ayrı bir veritabanı kullan (rollback ile izole, gerçek DB'ye dokunmaz)
SQLALCHEMY_TEST_URL = _db_url

engine = create_engine(SQLALCHEMY_TEST_URL, pool_pre_ping=True)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(engine, "connect")
def set_timezone(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("SET timezone = 'Europe/Istanbul'")
    cursor.close()


def extract_token(response) -> str:
    """Login/register yanıtından JWT token'ı çıkar.

    Önce HttpOnly cookie'den, yoksa body'den alır.
    """
    token = response.cookies.get("access_token")
    if not token:
        token = response.json().get("access_token", "")
    return token


# Testler için gerekli modül kodları
_REQUIRED_MODULE_CODES = [
    ("sales.acente_mahsup", "Acente Mahsup & Nakit Akım"),
]


def _ensure_admin_permissions():
    """
    Admin rolünün tüm modüller için tam yetkiye sahip olduğundan emin ol.
    Eksik modüller varsa oluştur.
    """
    db = TestSessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            return
        role_id = admin.role_id

        # Eksik modülleri oluştur
        for code, name in _REQUIRED_MODULE_CODES:
            mod = db.query(Module).filter(Module.code == code).first()
            if not mod:
                mod = Module(name=name, code=code, is_active=True, sort_order=0)
                db.add(mod)
                db.flush()

        # Tüm modüller için admin rolüne izin ver
        modules = db.query(Module).all()
        for module in modules:
            existing = (
                db.query(RoleModulePermission)
                .filter(
                    RoleModulePermission.role_id == role_id,
                    RoleModulePermission.module_id == module.id,
                )
                .first()
            )
            if not existing:
                perm = RoleModulePermission(
                    role_id=role_id,
                    module_id=module.id,
                    can_view=True,
                    can_use=True,
                )
                db.add(perm)
            else:
                if not existing.can_view or not existing.can_use:
                    existing.can_view = True
                    existing.can_use = True

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# Test oturumu başlarken admin yetkilerini ayarla
_ensure_admin_permissions()


# ── Transaction Rollback Fixture ────────────────────────────────────────
# Her test bir SAVEPOINT içinde çalışır → test bitince rollback → DB temiz kalır.

@pytest.fixture(autouse=True)
def _auto_rollback_and_reset():
    """Her test için:
    1. Bir connection + transaction aç
    2. get_db'yi bu transaction'a bağla (SAVEPOINT)
    3. Test bitince rollback → production DB'ye kalıcı veri yazılmaz
    4. Rate limiter'ları sıfırla
    """
    connection = engine.connect()
    transaction = connection.begin()

    # Bu connection üzerinden session oluştur
    session = Session(bind=connection)

    # Endpoint'lerdeki db.commit() çağrılarını SAVEPOINT'e dönüştür
    # (nested=True → her commit bir SAVEPOINT RELEASE olur, ana transaction korunur)
    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(session, trans):
        nonlocal nested
        if trans.nested and not trans._parent.nested:
            nested = connection.begin_nested()

    def override_get_db():
        try:
            yield session
        finally:
            pass  # session'ı kapatma — test sonunda rollback yapılacak

    app.dependency_overrides[get_db] = override_get_db

    # Rate limiter'ları sıfırla
    login_limiter._requests.clear()
    register_limiter._requests.clear()
    message_limiter._requests.clear()
    upload_limiter._requests.clear()
    search_limiter._requests.clear()
    heavy_limiter._requests.clear()
    runway_limiter._requests.clear()
    eur_balances_limiter._requests.clear()
    ai_limiter._requests.clear()
    ai_daily_limiter._requests.clear()
    _invalidate_messaging_role_cache()
    invalidate_module_cache()
    _invalidate_sales_compute_cache()  # test izolasyonu: FIFO cache testler arası sızmasın
    invalidate_deferral_cache()  # test izolasyonu: öteleme cache'i (DB rollback ile) sızmasın
    invalidate_hold_cache()  # test izolasyonu: bekletme cache'i (DB rollback ile) sızmasın
    invalidate_lock_cache()  # test izolasyonu: dönem kilidi cache'i (DB rollback ile) sızmasın

    yield session

    # Test bitti — herşeyi geri al
    session.close()
    transaction.rollback()
    connection.close()

    # get_db override'ını kaldır — module-scoped fixture'lar arada çalışırsa
    # kapalı session'a bağlanmasın
    app.dependency_overrides.pop(get_db, None)

    # Rate limiter'ları sıfırla
    login_limiter._requests.clear()
    register_limiter._requests.clear()
    message_limiter._requests.clear()
    upload_limiter._requests.clear()
    search_limiter._requests.clear()
    heavy_limiter._requests.clear()
    runway_limiter._requests.clear()
    eur_balances_limiter._requests.clear()
    ai_limiter._requests.clear()
    ai_daily_limiter._requests.clear()
    _invalidate_messaging_role_cache()
    invalidate_module_cache()
    _invalidate_sales_compute_cache()  # test izolasyonu: FIFO cache testler arası sızmasın
    invalidate_deferral_cache()  # test izolasyonu: öteleme cache'i (DB rollback ile) sızmasın
    invalidate_hold_cache()  # test izolasyonu: bekletme cache'i (DB rollback ile) sızmasın
    invalidate_lock_cache()  # test izolasyonu: dönem kilidi cache'i (DB rollback ile) sızmasın


@pytest.fixture(autouse=True)
def _disable_admin_approval_workflows(_auto_rollback_and_reset):
    """Admin rolünün requestor olduğu aktif onay workflow'larını test süresince devre dışı bırak.

    Why: Test DB'ye seed/migration ile bir workflow gelirse CRUD testleri (201 bekleyen)
    sessizce 202'ye düşer ve fail eder. Bu fixture, var olan workflow'ları test başında
    SAVEPOINT içinde `is_active=False` yapar — test bitince rollback ile geri döner.

    How to apply: Onay akışını test eden testler (test_onay.py) kendi workflow'larını
    yarattıkları için bu fixture onları etkilemez (sadece test başında zaten DB'de olan
    aktif workflow'lar deaktive edilir).
    """
    from app.models.approval import ApprovalWorkflow, ApprovalWorkflowRequestorRole

    session = _auto_rollback_and_reset
    # Bazı test modülleri (test_messages_extended) module-scoped transaction kullanır
    # ve _auto_rollback_and_reset'i None yapar — orada workflow temizliği yapılamaz.
    if session is None:
        yield
        return

    admin = session.query(User).filter(User.username == "admin").first()
    if admin and admin.role_id:
        workflow_id_rows = (
            session.query(ApprovalWorkflowRequestorRole.workflow_id)
            .filter(ApprovalWorkflowRequestorRole.role_id == admin.role_id)
            .all()
        )
        workflow_ids = [row[0] for row in workflow_id_rows]
        if workflow_ids:
            session.query(ApprovalWorkflow).filter(
                ApprovalWorkflow.id.in_(workflow_ids),
                ApprovalWorkflow.is_active == True,  # noqa: E712 — SQLAlchemy comparison
            ).update({"is_active": False}, synchronize_session=False)
            session.flush()
    yield


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    """Admin kullanıcı ile giriş yap ve Authorization header döndür.

    Token HttpOnly cookie ile geldiği için cookie'den çıkarılır.
    Test ortamında CORS_ORIGINS=http://... olduğu için secure=False → cookie geri döner.
    """
    response = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "admin123",
    })
    assert response.status_code == 200
    token = extract_token(response)
    assert token, "Token alınamadı (ne cookie ne body'de var)"
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def db(_auto_rollback_and_reset):
    """Test veritabanı oturumu — aynı rollback transaction'ını kullanır."""
    return _auto_rollback_and_reset


# ── Non-admin Test Kullanıcı Fixture'ları ───────────────────────────────
# can_view / can_use izin matrisi davranışını test etmek için kullanılır.
# Her fixture her test çağrısında yeni bir Role + User oluşturur
# (SAVEPOINT içinde — test bitince otomatik rollback olur).

def _create_user_and_login(db, client, *, view_all: bool = False, use_all: bool = False,
                           custom_perms: dict = None) -> dict:
    """Test kullanıcısı + rol + izin matrisi oluşturup login ederek auth header döner.

    Parametreler:
        view_all/use_all: Tüm modüllere can_view/can_use ata
        custom_perms: {"finance.cariler": {"view": True, "use": False}} — modül-spesifik
    """
    from uuid import uuid4
    from app.models.role import Role
    from app.utils.security import hash_password

    uid = uuid4().hex[:8]
    role = Role(name=f"test_role_{uid}", description="Test rolü")
    db.add(role)
    db.flush()

    modules = db.query(Module).all()
    for module in modules:
        if custom_perms is not None:
            spec = custom_perms.get(module.code, {})
            view = spec.get("view", False)
            use = spec.get("use", False)
        else:
            view = view_all
            use = use_all
        perm = RoleModulePermission(
            role_id=role.id,
            module_id=module.id,
            can_view=view,
            can_use=use,
        )
        db.add(perm)

    user = User(
        username=f"testuser_{uid}",
        email=f"testuser_{uid}@test.local",
        first_name="Test",
        last_name=f"User{uid}",
        hashed_password=hash_password("Test1234!"),
        role_id=role.id,
        is_active=True,
    )
    db.add(user)
    db.commit()

    response = client.post("/api/auth/login", json={
        "username": user.username,
        "password": "Test1234!",
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    token = extract_token(response)
    assert token, "Token alınamadı"
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def viewer_user_headers(client, db):
    """Tüm modüllerde yalnızca `can_view=True` (can_use=False) yetkili test kullanıcısı.

    Kullanım: 200 dönmesi gereken GET endpoint'leri için (read-only access),
    403 dönmesi gereken POST/PATCH/DELETE endpoint'leri için.
    """
    return _create_user_and_login(db, client, view_all=True, use_all=False)


@pytest.fixture
def use_user_headers(client, db):
    """Tüm modüllerde `can_view=True, can_use=True` (admin değil) test kullanıcısı.

    Kullanım: Admin-only kontrolü olan endpoint'lerin 403 döndüğünü doğrulamak için
    (rol bazlı değil yalnızca izin matrisi kullanan modüllerde 200 döner).
    """
    return _create_user_and_login(db, client, view_all=True, use_all=True)


@pytest.fixture
def no_perm_user_headers(client, db):
    """Hiçbir modülde izni olmayan test kullanıcısı.

    Kullanım: Tüm korumalı endpoint'lerin 403 döndüğünü doğrulamak için.
    """
    return _create_user_and_login(db, client, view_all=False, use_all=False)


@pytest.fixture
def make_user_with_perms(client, db):
    """Factory fixture: modül-spesifik izinlerle test kullanıcısı üret.

    Kullanım:
        def test_x(make_user_with_perms):
            headers = make_user_with_perms({
                "finance.cariler": {"view": True, "use": False},
                "finance.banks": {"view": True, "use": True},
            })
            # ... test ...
    """
    def _make(perms: dict) -> dict:
        return _create_user_and_login(db, client, custom_perms=perms)
    return _make
