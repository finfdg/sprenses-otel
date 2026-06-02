"""Kimlik doğrulama testleri."""

import pytest
from app.models.user import User
from app.models.role import Role
from app.utils.security import hash_password
from tests.conftest import extract_token


@pytest.fixture
def test_user(db):
    """Test için geçici kullanıcı oluştur, test sonrası sil."""
    role = db.query(Role).filter(Role.name == "Personel").first()
    if not role:
        role = Role(name="Personel", description="Test personel rolü", is_active=True)
        db.add(role)
        db.flush()

    user = User(
        username="testuser_auth",
        email="testauth@sprenses.com",
        hashed_password=hash_password("test1234"),
        first_name="Test",
        last_name="Kullanıcı",
        role_id=role.id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    yield user
    # Temizlik
    db.query(User).filter(User.id == user.id).delete()
    db.commit()


@pytest.fixture
def inactive_user(db):
    """Devre dışı test kullanıcısı oluştur."""
    role = db.query(Role).filter(Role.name == "Personel").first()
    user = User(
        username="testuser_inactive",
        email="testinactive@sprenses.com",
        hashed_password=hash_password("test1234"),
        first_name="Pasif",
        last_name="Kullanıcı",
        role_id=role.id,
        is_active=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    yield user
    db.query(User).filter(User.id == user.id).delete()
    db.commit()


# ==================== LOGIN TESTLERİ ====================


class TestLogin:
    """Giriş endpoint'i testleri."""

    def test_login_success(self, client):
        """Doğru bilgilerle giriş başarılı olmalı."""
        response = client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin123",
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["user"]["username"] == "admin"
        assert data["token_type"] == "bearer"
        assert "permissions" in data["user"]

    def test_login_returns_cookie(self, client):
        """Giriş, HttpOnly cookie dönmeli."""
        response = client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin123",
        })
        assert response.status_code == 200
        assert "access_token" in response.cookies

    def test_login_wrong_password(self, client):
        """Yanlış şifre ile giriş 401 dönmeli."""
        response = client.post("/api/auth/login", json={
            "username": "admin",
            "password": "wrongpassword",
        })
        assert response.status_code == 401
        assert "hatalı" in response.json()["detail"].lower()

    def test_login_nonexistent_user(self, client):
        """Var olmayan kullanıcı ile giriş 401 dönmeli."""
        response = client.post("/api/auth/login", json={
            "username": "nonexistent_user_xyz",
            "password": "anypass",
        })
        assert response.status_code == 401

    def test_login_inactive_user(self, client, inactive_user):
        """Devre dışı kullanıcı giriş yapamamalı."""
        response = client.post("/api/auth/login", json={
            "username": "testuser_inactive",
            "password": "test1234",
        })
        assert response.status_code == 403
        assert "devre dışı" in response.json()["detail"].lower()

    def test_login_empty_username(self, client):
        """Boş kullanıcı adı ile giriş başarısız olmalı."""
        response = client.post("/api/auth/login", json={
            "username": "",
            "password": "admin123",
        })
        assert response.status_code in (401, 422)

    def test_login_empty_password(self, client):
        """Boş şifre ile giriş başarısız olmalı."""
        response = client.post("/api/auth/login", json={
            "username": "admin",
            "password": "",
        })
        assert response.status_code == 401

    def test_login_missing_fields(self, client):
        """Eksik alan ile giriş 422 dönmeli."""
        response = client.post("/api/auth/login", json={
            "username": "admin",
        })
        assert response.status_code == 422

    def test_login_rate_limiting(self, client):
        """5 başarısız denemeden sonra rate limit devreye girmeli."""
        for i in range(5):
            client.post("/api/auth/login", json={
                "username": "admin",
                "password": "wrong",
            })

        response = client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin123",
        })
        assert response.status_code == 429
        assert "fazla istek" in response.json()["detail"].lower()

    def test_login_user_response_structure(self, client):
        """Giriş yanıtındaki kullanıcı verisi doğru yapıda olmalı."""
        response = client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin123",
        })
        user = response.json()["user"]
        required_fields = ["id", "username", "email", "first_name", "last_name",
                           "role_id", "role", "is_active", "created_at", "permissions"]
        for field in required_fields:
            assert field in user, f"'{field}' alanı eksik"

    def test_login_with_test_user(self, client, test_user):
        """Test kullanıcısı ile giriş başarılı olmalı."""
        response = client.post("/api/auth/login", json={
            "username": "testuser_auth",
            "password": "test1234",
        })
        assert response.status_code == 200
        assert response.json()["user"]["username"] == "testuser_auth"


# ==================== REGISTER TESTLERİ ====================


class TestRegister:
    """Kayıt endpoint'i testleri."""

    def _cleanup_user(self, db, username):
        """Test kullanıcısını temizle."""
        user = db.query(User).filter(User.username == username).first()
        if user:
            db.delete(user)
            db.commit()

    def test_register_success(self, client, db):
        """Geçerli bilgilerle kayıt başarılı olmalı."""
        response = client.post("/api/auth/register", json={
            "username": "newuser_reg",
            "email": "newuser_reg@sprenses.com",
            "password": "securepass123",
            "first_name": "Yeni",
            "last_name": "Kullanıcı",
        })
        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert data["user"]["username"] == "newuser_reg"
        assert data["user"]["email"] == "newuser_reg@sprenses.com"
        # Temizlik
        self._cleanup_user(db, "newuser_reg")

    def test_register_returns_cookie(self, client, db):
        """Kayıt, HttpOnly cookie dönmeli."""
        response = client.post("/api/auth/register", json={
            "username": "newuser_cookie",
            "email": "cookie@sprenses.com",
            "password": "securepass123",
            "first_name": "Cookie",
            "last_name": "Test",
        })
        assert response.status_code == 201
        assert "access_token" in response.cookies
        self._cleanup_user(db, "newuser_cookie")

    def test_register_duplicate_username(self, client, test_user):
        """Aynı kullanıcı adı ile kayıt 409 dönmeli."""
        response = client.post("/api/auth/register", json={
            "username": "testuser_auth",
            "email": "different@sprenses.com",
            "password": "securepass123",
            "first_name": "Duplicate",
            "last_name": "User",
        })
        assert response.status_code == 409
        assert "zaten kayıtlı" in response.json()["detail"].lower()

    def test_register_duplicate_email(self, client, test_user):
        """Aynı e-posta ile kayıt 409 dönmeli."""
        response = client.post("/api/auth/register", json={
            "username": "uniqueuser_xyz",
            "email": "testauth@sprenses.com",
            "password": "securepass123",
            "first_name": "Duplicate",
            "last_name": "Email",
        })
        assert response.status_code == 409
        assert "e-posta zaten kayıtlı" in response.json()["detail"].lower()

    def test_register_short_password(self, client):
        """Kısa şifre ile kayıt 422 dönmeli."""
        response = client.post("/api/auth/register", json={
            "username": "shortpass_user",
            "email": "shortpass@sprenses.com",
            "password": "abc",
            "first_name": "Short",
            "last_name": "Pass",
        })
        assert response.status_code == 422

    def test_register_short_username(self, client):
        """Kısa kullanıcı adı ile kayıt 422 dönmeli."""
        response = client.post("/api/auth/register", json={
            "username": "ab",
            "email": "short@sprenses.com",
            "password": "securepass123",
            "first_name": "Short",
            "last_name": "User",
        })
        assert response.status_code == 422

    def test_register_invalid_email(self, client):
        """Geçersiz e-posta ile kayıt 422 dönmeli."""
        response = client.post("/api/auth/register", json={
            "username": "invalidemail_user",
            "email": "not-an-email",
            "password": "securepass123",
            "first_name": "Invalid",
            "last_name": "Email",
        })
        assert response.status_code == 422

    def test_register_missing_fields(self, client):
        """Eksik alanlarla kayıt 422 dönmeli."""
        response = client.post("/api/auth/register", json={
            "username": "incomplete",
            "password": "securepass123",
        })
        assert response.status_code == 422

    def test_register_rate_limiting(self, client, db):
        """3 kayıt denemesinden sonra rate limit devreye girmeli."""
        for i in range(3):
            resp = client.post("/api/auth/register", json={
                "username": f"ratelimit_user_{i}",
                "email": f"ratelimit{i}@sprenses.com",
                "password": "securepass123",
                "first_name": "Rate",
                "last_name": "Limit",
            })

        response = client.post("/api/auth/register", json={
            "username": "ratelimit_user_extra",
            "email": "ratelimitextra@sprenses.com",
            "password": "securepass123",
            "first_name": "Rate",
            "last_name": "Limit",
        })
        assert response.status_code == 429

        # Temizlik
        for i in range(3):
            self._cleanup_user(db, f"ratelimit_user_{i}")
        self._cleanup_user(db, "ratelimit_user_extra")

    def test_register_default_role(self, client, db):
        """Kayıt olan kullanıcıya Personel rolü atanmalı."""
        response = client.post("/api/auth/register", json={
            "username": "rolecheck_user",
            "email": "rolecheck@sprenses.com",
            "password": "securepass123",
            "first_name": "Role",
            "last_name": "Check",
        })
        assert response.status_code == 201
        user_data = response.json()["user"]
        assert user_data["role"]["name"] == "Personel"
        self._cleanup_user(db, "rolecheck_user")


# ==================== ME TESTLERİ ====================


class TestMe:
    """Mevcut kullanıcı bilgisi endpoint'i testleri."""

    def test_me_authenticated(self, client, auth_headers):
        """Yetkili kullanıcı kendi bilgilerini görebilmeli."""
        response = client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "admin"
        assert "permissions" in data
        assert "role" in data

    def test_me_unauthenticated(self, client):
        """Token olmadan erişim 401 dönmeli."""
        response = client.get("/api/auth/me")
        assert response.status_code == 401

    def test_me_invalid_token(self, client):
        """Geçersiz token ile erişim 401 dönmeli."""
        response = client.get("/api/auth/me", headers={
            "Authorization": "Bearer invalid.token.here",
        })
        assert response.status_code == 401

    def test_me_response_structure(self, client, auth_headers):
        """Me yanıtı doğru yapıda olmalı."""
        response = client.get("/api/auth/me", headers=auth_headers)
        data = response.json()
        assert isinstance(data["id"], int)
        assert isinstance(data["username"], str)
        assert isinstance(data["email"], str)
        assert isinstance(data["is_active"], bool)
        assert isinstance(data["permissions"], list)

    def test_me_with_cookie_auth(self, client):
        """Cookie tabanlı kimlik doğrulama çalışmalı."""
        # Önce giriş yap (cookie set edilir)
        login_resp = client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin123",
        })
        assert login_resp.status_code == 200
        token = login_resp.cookies.get("access_token")
        assert token is not None

        # Cookie'yi manuel olarak gönder
        response = client.get("/api/auth/me", cookies={"access_token": token})
        assert response.status_code == 200
        assert response.json()["username"] == "admin"


# ==================== CHANGE PASSWORD TESTLERİ ====================


class TestChangePassword:
    """Şifre değiştirme endpoint'i testleri."""

    def test_change_password_success(self, client, db, test_user):
        """Doğru mevcut şifre ile değiştirme başarılı olmalı."""
        # Giriş yap
        login_resp = client.post("/api/auth/login", json={
            "username": "testuser_auth",
            "password": "test1234",
        })
        token = extract_token(login_resp)
        headers = {"Authorization": f"Bearer {token}"}

        # Şifre değiştir
        response = client.post("/api/auth/change-password", json={
            "current_password": "test1234",
            "new_password": "newpass1234",
        }, headers=headers)
        assert response.status_code == 200
        assert "başarıyla" in response.json()["detail"].lower()

        # Yeni şifre ile giriş yap
        login_resp2 = client.post("/api/auth/login", json={
            "username": "testuser_auth",
            "password": "newpass1234",
        })
        assert login_resp2.status_code == 200

        # Eski şifre ile giriş yapılamamalı
        login_resp3 = client.post("/api/auth/login", json={
            "username": "testuser_auth",
            "password": "test1234",
        })
        assert login_resp3.status_code == 401

        # Şifreyi geri al (diğer testler için)
        new_token = extract_token(login_resp2)
        client.post("/api/auth/change-password", json={
            "current_password": "newpass1234",
            "new_password": "test1234",
        }, headers={"Authorization": f"Bearer {new_token}"})

    def test_change_password_wrong_current(self, client, test_user):
        """Yanlış mevcut şifre ile değiştirme başarısız olmalı."""
        login_resp = client.post("/api/auth/login", json={
            "username": "testuser_auth",
            "password": "test1234",
        })
        token = extract_token(login_resp)

        response = client.post("/api/auth/change-password", json={
            "current_password": "wrongcurrent",
            "new_password": "newpass1234",
        }, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 400
        assert "hatalı" in response.json()["detail"].lower()

    def test_change_password_short_new(self, client, test_user):
        """Kısa yeni şifre ile değiştirme başarısız olmalı."""
        login_resp = client.post("/api/auth/login", json={
            "username": "testuser_auth",
            "password": "test1234",
        })
        token = extract_token(login_resp)

        response = client.post("/api/auth/change-password", json={
            "current_password": "test1234",
            "new_password": "abc",
        }, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code in (400, 422)

    def test_change_password_unauthenticated(self, client):
        """Token olmadan şifre değiştirme 401 dönmeli."""
        response = client.post("/api/auth/change-password", json={
            "current_password": "test1234",
            "new_password": "newpass1234",
        })
        assert response.status_code == 401

    def test_change_password_invalidates_old_token(self, client, test_user):
        """Şifre değiştirdikten sonra eski token geçersiz olmalı."""
        login_resp = client.post("/api/auth/login", json={
            "username": "testuser_auth",
            "password": "test1234",
        })
        old_token = extract_token(login_resp)
        old_headers = {"Authorization": f"Bearer {old_token}"}

        # Şifre değiştir
        change_resp = client.post("/api/auth/change-password", json={
            "current_password": "test1234",
            "new_password": "newpass1234",
        }, headers=old_headers)
        assert change_resp.status_code == 200
        new_token = extract_token(change_resp)

        # Eski token ile me endpoint'ine erişim başarısız olmalı
        me_resp = client.get("/api/auth/me", headers=old_headers)
        assert me_resp.status_code == 401

        # Yeni token çalışmalı
        me_resp2 = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {new_token}",
        })
        assert me_resp2.status_code == 200

        # Şifreyi geri al
        client.post("/api/auth/change-password", json={
            "current_password": "newpass1234",
            "new_password": "test1234",
        }, headers={"Authorization": f"Bearer {new_token}"})


# ==================== LOGOUT TESTLERİ ====================


class TestLogout:
    """Çıkış endpoint'i testleri."""

    def test_logout_success(self, client, test_user):
        """Başarılı çıkış yapılabilmeli."""
        login_resp = client.post("/api/auth/login", json={
            "username": "testuser_auth",
            "password": "test1234",
        })
        token = extract_token(login_resp)

        response = client.post("/api/auth/logout", headers={
            "Authorization": f"Bearer {token}",
        })
        assert response.status_code == 200
        assert "başarıyla" in response.json()["detail"].lower()

    def test_logout_clears_cookie(self, client, test_user):
        """Çıkış, cookie'yi temizlemeli."""
        login_resp = client.post("/api/auth/login", json={
            "username": "testuser_auth",
            "password": "test1234",
        })
        token = extract_token(login_resp)

        response = client.post("/api/auth/logout", headers={
            "Authorization": f"Bearer {token}",
        })
        assert response.status_code == 200
        # Cookie max_age=0 ile silinmeli
        cookie = response.cookies.get("access_token")
        # TestClient'ta cookie silme, boş değer döner
        assert cookie is None or cookie == ""

    def test_logout_invalidates_session(self, client, test_user):
        """Çıkış sonrası eski token geçersiz olmalı."""
        login_resp = client.post("/api/auth/login", json={
            "username": "testuser_auth",
            "password": "test1234",
        })
        token = extract_token(login_resp)
        headers = {"Authorization": f"Bearer {token}"}

        # Çıkış yap
        client.post("/api/auth/logout", headers=headers)

        # Eski token ile me erişim başarısız olmalı
        me_resp = client.get("/api/auth/me", headers=headers)
        assert me_resp.status_code == 401

    def test_logout_unauthenticated(self, client):
        """Token olmadan çıkış 401 dönmeli."""
        response = client.post("/api/auth/logout")
        assert response.status_code == 401


# ==================== OTURUM YÖNETİMİ TESTLERİ ====================


class TestSessionManagement:
    """Tek oturum kontrolü testleri."""

    def test_second_login_invalidates_first(self, client, test_user):
        """İkinci giriş, ilk oturumu sonlandırmalı."""
        # İlk giriş
        login1 = client.post("/api/auth/login", json={
            "username": "testuser_auth",
            "password": "test1234",
        })
        token1 = extract_token(login1)

        # İkinci giriş
        login2 = client.post("/api/auth/login", json={
            "username": "testuser_auth",
            "password": "test1234",
        })
        token2 = extract_token(login2)

        # İlk token artık geçersiz olmalı
        me_resp1 = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {token1}",
        })
        assert me_resp1.status_code == 401

        # İkinci token çalışmalı
        me_resp2 = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {token2}",
        })
        assert me_resp2.status_code == 200


# ==================== GÜVENLİK TESTLERİ ====================


class TestSecurity:
    """Güvenlik ile ilgili testler."""

    def test_password_not_in_response(self, client):
        """Şifre hash'i yanıtta yer almamalı."""
        response = client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin123",
        })
        data_str = str(response.json())
        assert "hashed_password" not in data_str
        assert "password" not in data_str.lower() or "change_password" in data_str.lower() or "new_password" not in data_str.lower()

    def test_token_format(self, client):
        """Token JWT formatında olmalı (3 parçalı dot-separated)."""
        response = client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin123",
        })
        token = extract_token(response)
        parts = token.split(".")
        assert len(parts) == 3, "JWT token 3 parçalı olmalı"

    def test_different_users_get_different_tokens(self, client, test_user):
        """Farklı kullanıcılar farklı token almalı."""
        login1 = client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin123",
        })
        login2 = client.post("/api/auth/login", json={
            "username": "testuser_auth",
            "password": "test1234",
        })
        assert extract_token(login1) != extract_token(login2)
