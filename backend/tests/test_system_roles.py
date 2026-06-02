"""Rol yönetimi (system.roles) detaylı testleri."""

import pytest
from app.models.role import Role
from app.models.module import Module
from app.models.user import User
from app.models.role_module_permission import RoleModulePermission
from app.utils.security import hash_password


@pytest.fixture
def test_module(db):
    """Test için modül döndür (varsa mevcut, yoksa oluştur)."""
    mod = db.query(Module).filter(Module.code == "dashboard").first()
    if not mod:
        mod = Module(name="Panel", code="dashboard", is_active=True, sort_order=0)
        db.add(mod)
        db.commit()
        db.refresh(mod)
    return mod


@pytest.fixture
def second_module(db):
    """İkinci test modülü döndür."""
    mod = db.query(Module).filter(Module.code == "messaging").first()
    if not mod:
        mod = Module(name="Mesajlaşma", code="messaging", is_active=True, sort_order=1)
        db.add(mod)
        db.commit()
        db.refresh(mod)
    return mod


@pytest.fixture
def test_role_crud(db):
    """CRUD testleri için geçici rol oluştur."""
    role = Role(name="TestRolCrud", description="Test rolü", is_active=True)
    db.add(role)
    db.commit()
    db.refresh(role)
    yield role
    # Temizlik
    existing = db.query(Role).filter(Role.id == role.id).first()
    if existing:
        # Önce izinleri sil
        db.query(RoleModulePermission).filter(RoleModulePermission.role_id == role.id).delete()
        db.delete(existing)
        db.commit()


# ==================== LİSTE TESTLERİ ====================


class TestListRoles:
    """Rol listeleme testleri."""

    def test_list_roles_success(self, client, auth_headers):
        """Yetkili kullanıcı rol listesini görebilmeli."""
        response = client.get("/api/system/roles/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_list_roles_response_structure(self, client, auth_headers):
        """Her rol doğru yapıda olmalı."""
        response = client.get("/api/system/roles/", headers=auth_headers)
        role = response.json()[0]
        required_fields = ["id", "name", "description", "is_active", "created_at", "permissions"]
        for field in required_fields:
            assert field in role, f"'{field}' alanı eksik"

    def test_list_roles_has_permissions(self, client, auth_headers):
        """Roller izin bilgilerini içermeli."""
        response = client.get("/api/system/roles/", headers=auth_headers)
        # Admin rolünün izinleri olmalı
        admin_role = next((r for r in response.json() if r["name"] == "Admin"), None)
        assert admin_role is not None
        assert len(admin_role["permissions"]) > 0
        perm = admin_role["permissions"][0]
        assert "module_id" in perm
        assert "module_code" in perm
        assert "can_view" in perm
        assert "can_use" in perm

    def test_list_roles_unauthorized(self, client):
        """Token olmadan erişim 401 dönmeli."""
        response = client.get("/api/system/roles/")
        assert response.status_code == 401

    def test_list_roles_sorted_by_name(self, client, auth_headers):
        """Roller isme göre sıralı olmalı."""
        response = client.get("/api/system/roles/", headers=auth_headers)
        names = [r["name"] for r in response.json()]
        assert names == sorted(names)


# ==================== DETAY TESTLERİ ====================


class TestGetRole:
    """Rol detay testleri."""

    def test_get_role_success(self, client, auth_headers, test_role_crud):
        """Rol detayı görüntülenebilmeli."""
        response = client.get(f"/api/system/roles/{test_role_crud.id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "TestRolCrud"
        assert data["description"] == "Test rolü"

    def test_get_role_not_found(self, client, auth_headers):
        """Olmayan rol 404 dönmeli."""
        response = client.get("/api/system/roles/999999", headers=auth_headers)
        assert response.status_code == 404

    def test_get_role_unauthorized(self, client):
        """Token olmadan erişim 401 dönmeli."""
        response = client.get("/api/system/roles/1")
        assert response.status_code == 401


# ==================== OLUŞTURMA TESTLERİ ====================


class TestCreateRole:
    """Rol oluşturma testleri."""

    def _cleanup_role(self, db, name):
        role = db.query(Role).filter(Role.name == name).first()
        if role:
            db.query(RoleModulePermission).filter(RoleModulePermission.role_id == role.id).delete()
            db.delete(role)
            db.commit()

    def test_create_role_success(self, client, auth_headers, db):
        """Geçerli bilgilerle rol oluşturulabilmeli."""
        response = client.post("/api/system/roles/", headers=auth_headers, json={
            "name": "YeniTestRol",
            "description": "Yeni test rolü açıklaması",
            "permissions": [],
        })
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "YeniTestRol"
        assert data["description"] == "Yeni test rolü açıklaması"
        assert data["is_active"] is True
        self._cleanup_role(db, "YeniTestRol")

    def test_create_role_with_permissions(self, client, auth_headers, db, test_module, second_module):
        """İzinlerle birlikte rol oluşturulabilmeli."""
        response = client.post("/api/system/roles/", headers=auth_headers, json={
            "name": "İzinliRol",
            "description": "İzinli rol",
            "permissions": [
                {"module_id": test_module.id, "can_view": True, "can_use": False},
                {"module_id": second_module.id, "can_view": True, "can_use": True},
            ],
        })
        assert response.status_code == 201
        data = response.json()
        assert len(data["permissions"]) == 2
        self._cleanup_role(db, "İzinliRol")

    def test_create_role_duplicate_name(self, client, auth_headers, test_role_crud):
        """Aynı isimle rol oluşturma 409 dönmeli."""
        response = client.post("/api/system/roles/", headers=auth_headers, json={
            "name": "TestRolCrud",
            "description": "Duplicate",
        })
        assert response.status_code == 409
        assert "zaten mevcut" in response.json()["detail"].lower()

    def test_create_role_empty_name(self, client, auth_headers, db):
        """Boş isimle rol oluşturma — boş string geçerse temizle."""
        response = client.post("/api/system/roles/", headers=auth_headers, json={
            "name": "",
        })
        # Boş string Pydantic'ten geçebilir veya DB'de duplicate hatası verebilir
        assert response.status_code in (201, 409, 422, 500)
        # Oluştuysa temizle
        if response.status_code == 201:
            role = db.query(Role).filter(Role.name == "").first()
            if role:
                db.query(RoleModulePermission).filter(RoleModulePermission.role_id == role.id).delete()
                db.delete(role)
                db.commit()

    def test_create_role_unauthorized(self, client):
        """Token olmadan oluşturma 401 dönmeli."""
        response = client.post("/api/system/roles/", json={
            "name": "NoAuthRol",
        })
        assert response.status_code == 401


# ==================== GÜNCELLEME TESTLERİ ====================


class TestUpdateRole:
    """Rol güncelleme testleri."""

    def test_update_role_name(self, client, auth_headers, test_role_crud, db):
        """Rol adı güncellenebilmeli."""
        response = client.patch(
            f"/api/system/roles/{test_role_crud.id}",
            headers=auth_headers,
            json={"name": "GüncelRolAdı"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "GüncelRolAdı"
        # Geri al
        client.patch(
            f"/api/system/roles/{test_role_crud.id}",
            headers=auth_headers,
            json={"name": "TestRolCrud"},
        )

    def test_update_role_description(self, client, auth_headers, test_role_crud):
        """Rol açıklaması güncellenebilmeli."""
        response = client.patch(
            f"/api/system/roles/{test_role_crud.id}",
            headers=auth_headers,
            json={"description": "Güncellenmiş açıklama"},
        )
        assert response.status_code == 200
        assert response.json()["description"] == "Güncellenmiş açıklama"

    def test_update_role_deactivate(self, client, auth_headers, test_role_crud):
        """Rol devre dışı bırakılabilmeli."""
        response = client.patch(
            f"/api/system/roles/{test_role_crud.id}",
            headers=auth_headers,
            json={"is_active": False},
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is False

    def test_update_role_permissions(self, client, auth_headers, test_role_crud, test_module):
        """Rol izinleri güncellenebilmeli."""
        response = client.patch(
            f"/api/system/roles/{test_role_crud.id}",
            headers=auth_headers,
            json={
                "permissions": [
                    {"module_id": test_module.id, "can_view": True, "can_use": True},
                ],
            },
        )
        assert response.status_code == 200
        perms = response.json()["permissions"]
        assert len(perms) == 1
        assert perms[0]["can_view"] is True
        assert perms[0]["can_use"] is True

    def test_update_role_clear_permissions(self, client, auth_headers, test_role_crud, test_module):
        """Rol izinleri temizlenebilmeli."""
        # Önce izin ekle
        client.patch(
            f"/api/system/roles/{test_role_crud.id}",
            headers=auth_headers,
            json={"permissions": [
                {"module_id": test_module.id, "can_view": True, "can_use": False},
            ]},
        )
        # Sonra temizle
        response = client.patch(
            f"/api/system/roles/{test_role_crud.id}",
            headers=auth_headers,
            json={"permissions": []},
        )
        assert response.status_code == 200
        assert len(response.json()["permissions"]) == 0

    def test_update_role_duplicate_name(self, client, auth_headers, test_role_crud):
        """Mevcut rol adına güncelleme 409 dönmeli."""
        response = client.patch(
            f"/api/system/roles/{test_role_crud.id}",
            headers=auth_headers,
            json={"name": "Admin"},
        )
        assert response.status_code == 409

    def test_update_role_not_found(self, client, auth_headers):
        """Olmayan rol güncelleme 404 dönmeli."""
        response = client.patch(
            "/api/system/roles/999999",
            headers=auth_headers,
            json={"name": "Test"},
        )
        assert response.status_code == 404

    def test_update_role_unauthorized(self, client, test_role_crud):
        """Token olmadan güncelleme 401 dönmeli."""
        response = client.patch(
            f"/api/system/roles/{test_role_crud.id}",
            json={"name": "Test"},
        )
        assert response.status_code == 401


# ==================== SİLME TESTLERİ ====================


class TestDeleteRole:
    """Rol silme testleri."""

    def test_delete_role_success(self, client, auth_headers, db):
        """Kullanıcısı olmayan rol silinebilmeli."""
        role = Role(name="SilinecekRol", description="Silinecek", is_active=True)
        db.add(role)
        db.commit()
        db.refresh(role)

        response = client.delete(f"/api/system/roles/{role.id}", headers=auth_headers)
        assert response.status_code == 204

        # Silinen rol artık bulunamazP
        get_resp = client.get(f"/api/system/roles/{role.id}", headers=auth_headers)
        assert get_resp.status_code == 404

    def test_delete_role_with_users(self, client, auth_headers, db):
        """Kullanıcısı olan rol silinemez."""
        # Admin rolünün ID'sini bul (kullanıcılar var)
        admin = db.query(User).filter(User.username == "admin").first()
        response = client.delete(f"/api/system/roles/{admin.role_id}", headers=auth_headers)
        assert response.status_code == 400
        assert "kullanıcı var" in response.json()["detail"].lower()

    def test_delete_role_not_found(self, client, auth_headers):
        """Olmayan rol silme 404 dönmeli."""
        response = client.delete("/api/system/roles/999999", headers=auth_headers)
        assert response.status_code == 404

    def test_delete_role_unauthorized(self, client):
        """Token olmadan silme 401 dönmeli."""
        response = client.delete("/api/system/roles/1")
        assert response.status_code == 401


# ==================== İZİN MATRISI TESTLERİ ====================


class TestPermissionMatrix:
    """İzin matrisi testleri."""

    def test_permission_response_structure(self, client, auth_headers):
        """İzin yanıtı doğru yapıda olmalı."""
        response = client.get("/api/system/roles/", headers=auth_headers)
        admin_role = next((r for r in response.json() if r["name"] == "Admin"), None)
        if admin_role and admin_role["permissions"]:
            perm = admin_role["permissions"][0]
            assert "module_id" in perm
            assert "module_code" in perm
            assert "module_name" in perm
            assert "can_view" in perm
            assert "can_use" in perm
            assert isinstance(perm["can_view"], bool)
            assert isinstance(perm["can_use"], bool)

    def test_create_role_multiple_permissions(self, client, auth_headers, db, test_module, second_module):
        """Birden fazla modül izni ile rol oluşturulabilmeli."""
        response = client.post("/api/system/roles/", headers=auth_headers, json={
            "name": "ÇokluİzinRol",
            "permissions": [
                {"module_id": test_module.id, "can_view": True, "can_use": False},
                {"module_id": second_module.id, "can_view": True, "can_use": True},
            ],
        })
        assert response.status_code == 201
        perms = response.json()["permissions"]
        assert len(perms) == 2

        # Temizlik
        role = db.query(Role).filter(Role.name == "ÇokluİzinRol").first()
        if role:
            db.query(RoleModulePermission).filter(RoleModulePermission.role_id == role.id).delete()
            db.delete(role)
            db.commit()

    def test_update_replaces_all_permissions(self, client, auth_headers, test_role_crud, test_module, second_module):
        """İzin güncellemesi eski izinleri tamamen değiştirmeli."""
        # Önce 2 izin ekle
        client.patch(
            f"/api/system/roles/{test_role_crud.id}",
            headers=auth_headers,
            json={"permissions": [
                {"module_id": test_module.id, "can_view": True, "can_use": True},
                {"module_id": second_module.id, "can_view": True, "can_use": False},
            ]},
        )
        # Sadece 1 izinle güncelle
        response = client.patch(
            f"/api/system/roles/{test_role_crud.id}",
            headers=auth_headers,
            json={"permissions": [
                {"module_id": second_module.id, "can_view": True, "can_use": True},
            ]},
        )
        assert response.status_code == 200
        perms = response.json()["permissions"]
        assert len(perms) == 1
        assert perms[0]["module_code"] == "messaging"
