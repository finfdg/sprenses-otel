"""Kullanıcı yönetimi (system.users) detaylı testleri."""

import pytest
from app.models.user import User
from app.models.role import Role
from tests.conftest import extract_token
from app.utils.security import hash_password


@pytest.fixture
def test_role(db):
    """Test için Personel rolünü döndür."""
    role = db.query(Role).filter(Role.name == "Personel").first()
    if not role:
        role = Role(name="Personel", description="Test personel rolü", is_active=True)
        db.add(role)
        db.commit()
        db.refresh(role)
    return role


@pytest.fixture
def admin_role(db):
    """Admin rolünü döndür."""
    role = db.query(Role).filter(Role.name == "Admin").first()
    return role


@pytest.fixture
def test_managed_user(db, test_role):
    """CRUD testleri için yönetilebilir kullanıcı oluştur."""
    user = User(
        username="managed_user_test",
        email="managed@sprenses.com",
        hashed_password=hash_password("managed123"),
        first_name="Yönetilen",
        last_name="Kullanıcı",
        role_id=test_role.id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    yield user
    # Temizlik
    existing = db.query(User).filter(User.id == user.id).first()
    if existing:
        db.delete(existing)
        db.commit()


# ==================== LİSTE TESTLERİ ====================


class TestListUsers:
    """Kullanıcı listeleme testleri."""

    def test_list_users_success(self, client, auth_headers):
        """Yetkili kullanıcı listesini görebilmeli."""
        response = client.get("/api/system/users/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "pages" in data
        assert data["total"] > 0

    def test_list_users_pagination(self, client, auth_headers):
        """Sayfalama doğru çalışmalı."""
        response = client.get("/api/system/users/?page=1&page_size=1", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) <= 1
        assert data["page"] == 1
        assert data["page_size"] == 1
        if data["total"] > 1:
            assert data["pages"] > 1

    def test_list_users_search(self, client, auth_headers):
        """Arama doğru çalışmalı."""
        response = client.get("/api/system/users/?search=admin", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        # Sonuçlarda admin olmalı
        usernames = [u["username"] for u in data["items"]]
        assert "admin" in usernames

    def test_list_users_search_no_results(self, client, auth_headers):
        """Olmayan arama boş sonuç dönmeli."""
        response = client.get("/api/system/users/?search=zzzznonexistent", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_list_users_unauthorized(self, client):
        """Token olmadan erişim 401 dönmeli."""
        response = client.get("/api/system/users/")
        assert response.status_code == 401

    def test_list_users_response_structure(self, client, auth_headers):
        """Her kullanıcı doğru yapıda olmalı."""
        response = client.get("/api/system/users/", headers=auth_headers)
        data = response.json()
        user = data["items"][0]
        required_fields = ["id", "username", "email", "first_name", "last_name",
                           "role_id", "role", "is_active", "created_at", "permissions"]
        for field in required_fields:
            assert field in user, f"'{field}' alanı eksik"

    def test_list_users_invalid_page(self, client, auth_headers):
        """Geçersiz sayfa numarası 422 dönmeli."""
        response = client.get("/api/system/users/?page=0", headers=auth_headers)
        assert response.status_code == 422

    def test_list_users_invalid_page_size(self, client, auth_headers):
        """Geçersiz sayfa boyutu 422 dönmeli."""
        response = client.get("/api/system/users/?page_size=0", headers=auth_headers)
        assert response.status_code == 422


# ==================== DETAY TESTLERİ ====================


class TestGetUser:
    """Kullanıcı detay testleri."""

    def test_get_user_success(self, client, auth_headers, test_managed_user):
        """Kullanıcı detayı görüntülenebilmeli."""
        response = client.get(f"/api/system/users/{test_managed_user.id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "managed_user_test"
        assert data["first_name"] == "Yönetilen"

    def test_get_user_not_found(self, client, auth_headers):
        """Olmayan kullanıcı 404 dönmeli."""
        response = client.get("/api/system/users/999999", headers=auth_headers)
        assert response.status_code == 404

    def test_get_user_unauthorized(self, client, test_managed_user):
        """Token olmadan erişim 401 dönmeli."""
        response = client.get(f"/api/system/users/{test_managed_user.id}")
        assert response.status_code == 401


# ==================== OLUŞTURMA TESTLERİ ====================


class TestCreateUser:
    """Kullanıcı oluşturma testleri."""

    def _cleanup(self, db, username):
        user = db.query(User).filter(User.username == username).first()
        if user:
            db.delete(user)
            db.commit()

    def test_create_user_success(self, client, auth_headers, db, test_role):
        """Geçerli bilgilerle kullanıcı oluşturulabilmeli."""
        response = client.post("/api/system/users/", headers=auth_headers, json={
            "username": "newuser_sys",
            "email": "newsys@sprenses.com",
            "password": "secure123",
            "first_name": "Yeni",
            "last_name": "Kullanıcı",
            "role_id": test_role.id,
        })
        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "newuser_sys"
        assert data["email"] == "newsys@sprenses.com"
        assert data["is_active"] is True
        assert data["role"]["name"] == "Personel"
        self._cleanup(db, "newuser_sys")

    def test_create_user_missing_required_fields(self, client, auth_headers, test_role):
        """Zorunlu alanlar olmadan oluşturma 422 dönmeli."""
        response = client.post("/api/system/users/", headers=auth_headers, json={
            "username": "incomplete_user",
            "password": "secure123",
            "role_id": test_role.id,
        })
        assert response.status_code == 422

    def test_create_user_duplicate_username(self, client, auth_headers, test_managed_user, test_role):
        """Aynı kullanıcı adı 409 dönmeli."""
        response = client.post("/api/system/users/", headers=auth_headers, json={
            "username": "managed_user_test",
            "email": "different@sprenses.com",
            "password": "secure123",
            "first_name": "Çakışan",
            "last_name": "Ad",
            "role_id": test_role.id,
        })
        assert response.status_code == 409

    def test_create_user_duplicate_email(self, client, auth_headers, test_managed_user, test_role):
        """Aynı e-posta 409 dönmeli."""
        response = client.post("/api/system/users/", headers=auth_headers, json={
            "username": "unique_user_xyz",
            "email": "managed@sprenses.com",
            "password": "secure123",
            "first_name": "Çakışan",
            "last_name": "Email",
            "role_id": test_role.id,
        })
        assert response.status_code == 409

    def test_create_user_invalid_role(self, client, auth_headers):
        """Olmayan rol ID'si 404 dönmeli."""
        response = client.post("/api/system/users/", headers=auth_headers, json={
            "username": "badrole_user",
            "email": "badrole@sprenses.com",
            "password": "secure123",
            "first_name": "Kötü",
            "last_name": "Rol",
            "role_id": 999999,
        })
        assert response.status_code == 404

    def test_create_user_short_password(self, client, auth_headers, test_role):
        """Kısa şifre ile oluşturma 422 dönmeli."""
        response = client.post("/api/system/users/", headers=auth_headers, json={
            "username": "shortpw_user",
            "email": "shortpw@sprenses.com",
            "password": "abc",
            "first_name": "Kısa",
            "last_name": "Şifre",
            "role_id": test_role.id,
        })
        assert response.status_code == 422

    def test_create_user_inactive(self, client, auth_headers, db, test_role):
        """Devre dışı kullanıcı oluşturulabilmeli."""
        response = client.post("/api/system/users/", headers=auth_headers, json={
            "username": "inactive_sys",
            "email": "inactive_sys@sprenses.com",
            "password": "secure123",
            "first_name": "Pasif",
            "last_name": "Kullanıcı",
            "role_id": test_role.id,
            "is_active": False,
        })
        assert response.status_code == 201
        assert response.json()["is_active"] is False
        self._cleanup(db, "inactive_sys")

    def test_create_user_unauthorized(self, client, test_role):
        """Token olmadan oluşturma 401 dönmeli."""
        response = client.post("/api/system/users/", json={
            "username": "noauth_user",
            "password": "secure123",
            "first_name": "Yetkisiz",
            "last_name": "Test",
            "role_id": test_role.id,
        })
        assert response.status_code == 401


# ==================== GÜNCELLEME TESTLERİ ====================


class TestUpdateUser:
    """Kullanıcı güncelleme testleri."""

    def test_update_user_name(self, client, auth_headers, test_managed_user):
        """Kullanıcı adı güncellenebilmeli."""
        response = client.patch(
            f"/api/system/users/{test_managed_user.id}",
            headers=auth_headers,
            json={"first_name": "Güncel"},
        )
        assert response.status_code == 200
        assert response.json()["first_name"] == "Güncel"

    def test_update_user_role(self, client, auth_headers, test_managed_user, admin_role):
        """Kullanıcı rolü değiştirilebilmeli."""
        if not admin_role:
            pytest.skip("Admin rolü bulunamadı")
        response = client.patch(
            f"/api/system/users/{test_managed_user.id}",
            headers=auth_headers,
            json={"role_id": admin_role.id},
        )
        assert response.status_code == 200
        assert response.json()["role_id"] == admin_role.id

    def test_update_user_deactivate(self, client, auth_headers, test_managed_user):
        """Kullanıcı devre dışı bırakılabilmeli."""
        response = client.patch(
            f"/api/system/users/{test_managed_user.id}",
            headers=auth_headers,
            json={"is_active": False},
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is False

    def test_update_user_duplicate_username(self, client, auth_headers, test_managed_user):
        """Mevcut kullanıcı adına güncelleme 409 dönmeli."""
        response = client.patch(
            f"/api/system/users/{test_managed_user.id}",
            headers=auth_headers,
            json={"username": "admin"},
        )
        assert response.status_code == 409

    def test_update_user_duplicate_email(self, client, auth_headers, test_managed_user):
        """Mevcut e-postaya güncelleme 409 dönmeli."""
        # Admin'in e-postasını bul
        admin_resp = client.get("/api/auth/me", headers=auth_headers)
        admin_email = admin_resp.json()["email"]
        if not admin_email:
            pytest.skip("Admin'in e-postası yok")

        response = client.patch(
            f"/api/system/users/{test_managed_user.id}",
            headers=auth_headers,
            json={"email": admin_email},
        )
        assert response.status_code == 409

    def test_update_user_not_found(self, client, auth_headers):
        """Olmayan kullanıcı 404 dönmeli."""
        response = client.patch(
            "/api/system/users/999999",
            headers=auth_headers,
            json={"first_name": "Test"},
        )
        assert response.status_code == 404

    def test_update_user_password(self, client, auth_headers, test_managed_user):
        """Kullanıcı şifresi güncellenebilmeli."""
        response = client.patch(
            f"/api/system/users/{test_managed_user.id}",
            headers=auth_headers,
            json={"password": "newsecure123"},
        )
        assert response.status_code == 200

        # Yeni şifre ile giriş yapılabilmeli
        login_resp = client.post("/api/auth/login", json={
            "username": "managed_user_test",
            "password": "newsecure123",
        })
        assert login_resp.status_code == 200

    def test_update_user_unauthorized(self, client, test_managed_user):
        """Token olmadan güncelleme 401 dönmeli."""
        response = client.patch(
            f"/api/system/users/{test_managed_user.id}",
            json={"first_name": "Yetkisiz"},
        )
        assert response.status_code == 401


# ==================== SİLME TESTLERİ ====================


class TestDeleteUser:
    """Kullanıcı silme testleri."""

    def test_delete_user_success(self, client, auth_headers, db, test_role):
        """Kullanıcı silinebilmeli."""
        # Önce oluştur
        user = User(
            username="deletable_user",
            email="deletable@sprenses.com",
            hashed_password=hash_password("delete123"),
            first_name="Silinecek",
            last_name="Kullanıcı",
            role_id=test_role.id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

        response = client.delete(f"/api/system/users/{user_id}", headers=auth_headers)
        assert response.status_code == 204

        # Silinen kullanıcı artık bulunamaz
        get_resp = client.get(f"/api/system/users/{user_id}", headers=auth_headers)
        assert get_resp.status_code == 404

    def test_delete_self(self, client, auth_headers):
        """Kendini silmeye çalışma 400 dönmeli."""
        # Admin kullanıcısının ID'sini öğren
        me_resp = client.get("/api/auth/me", headers=auth_headers)
        my_id = me_resp.json()["id"]

        response = client.delete(f"/api/system/users/{my_id}", headers=auth_headers)
        assert response.status_code == 400
        assert "kendinizi" in response.json()["detail"].lower()

    def test_delete_user_not_found(self, client, auth_headers):
        """Olmayan kullanıcı silme 404 dönmeli."""
        response = client.delete("/api/system/users/999999", headers=auth_headers)
        assert response.status_code == 404

    def test_delete_user_unauthorized(self, client, test_managed_user):
        """Token olmadan silme 401 dönmeli."""
        response = client.delete(f"/api/system/users/{test_managed_user.id}")
        assert response.status_code == 401


# ==================== ŞİFRE SIFIRLAMA TESTLERİ ====================


class TestResetPassword:
    """Admin şifre sıfırlama testleri."""

    def test_reset_password_success(self, client, auth_headers, test_managed_user):
        """Admin, kullanıcı şifresini sıfırlayabilmeli."""
        response = client.post(
            f"/api/system/users/{test_managed_user.id}/reset-password",
            headers=auth_headers,
            json={"new_password": "resetpass123"},
        )
        assert response.status_code == 200
        assert "başarıyla" in response.json()["detail"].lower()

        # Yeni şifre ile giriş yapılabilmeli
        login_resp = client.post("/api/auth/login", json={
            "username": "managed_user_test",
            "password": "resetpass123",
        })
        assert login_resp.status_code == 200

    def test_reset_password_short(self, client, auth_headers, test_managed_user):
        """Kısa şifre ile sıfırlama başarısız olmalı."""
        response = client.post(
            f"/api/system/users/{test_managed_user.id}/reset-password",
            headers=auth_headers,
            json={"new_password": "abc"},
        )
        assert response.status_code == 422

    def test_reset_password_not_found(self, client, auth_headers):
        """Olmayan kullanıcı şifre sıfırlama 404 dönmeli."""
        response = client.post(
            "/api/system/users/999999/reset-password",
            headers=auth_headers,
            json={"new_password": "secure123"},
        )
        assert response.status_code == 404

    def test_reset_password_invalidates_session(self, client, auth_headers, test_managed_user):
        """Şifre sıfırlama sonrası eski oturum sonlanmalı."""
        # Kullanıcı giriş yapsın
        login_resp = client.post("/api/auth/login", json={
            "username": "managed_user_test",
            "password": "managed123",
        })
        old_token = extract_token(login_resp)

        # Admin şifreyi sıfırlasın
        client.post(
            f"/api/system/users/{test_managed_user.id}/reset-password",
            headers=auth_headers,
            json={"new_password": "newreset123"},
        )

        # Eski token artık çalışmamalı
        me_resp = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {old_token}",
        })
        assert me_resp.status_code == 401

    def test_reset_password_unauthorized(self, client, test_managed_user):
        """Token olmadan şifre sıfırlama 401 dönmeli."""
        response = client.post(
            f"/api/system/users/{test_managed_user.id}/reset-password",
            json={"new_password": "secure123"},
        )
        assert response.status_code == 401
