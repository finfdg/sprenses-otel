"""Modül yönetimi (system.modules) detaylı testleri."""

import pytest
from app.models.module import Module
from app.models.role_module_permission import RoleModulePermission


@pytest.fixture
def temp_module(db):
    """CRUD testleri için geçici modül oluştur."""
    mod = Module(name="GeçiciModül", code="temp_test_mod", is_active=True, sort_order=99)
    db.add(mod)
    db.commit()
    db.refresh(mod)
    yield mod
    existing = db.query(Module).filter(Module.id == mod.id).first()
    if existing:
        db.delete(existing)
        db.commit()


@pytest.fixture
def parent_child_modules(db):
    """Üst-alt modül ilişkisi oluştur."""
    parent = Module(name="ÜstModül", code="test_parent", is_active=True, sort_order=90)
    db.add(parent)
    db.flush()
    child = Module(name="AltModül", code="test_child", parent_id=parent.id, is_active=True, sort_order=91)
    db.add(child)
    db.commit()
    db.refresh(parent)
    db.refresh(child)
    yield parent, child
    # Temizlik — child önce
    for m in [child, parent]:
        existing = db.query(Module).filter(Module.id == m.id).first()
        if existing:
            db.delete(existing)
    db.commit()


# ==================== LİSTE TESTLERİ ====================


class TestListModules:
    """Modül listeleme testleri."""

    def test_list_modules_success(self, client, auth_headers):
        """Yetkili kullanıcı modül listesini görebilmeli."""
        response = client.get("/api/system/modules/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_list_modules_response_structure(self, client, auth_headers):
        """Her modül doğru yapıda olmalı."""
        response = client.get("/api/system/modules/", headers=auth_headers)
        mod = response.json()[0]
        for field in ["id", "name", "code", "sort_order", "is_active", "created_at"]:
            assert field in mod, f"'{field}' alanı eksik"

    def test_list_modules_sorted_by_sort_order(self, client, auth_headers):
        """Modüller sort_order'a göre sıralı olmalı."""
        response = client.get("/api/system/modules/", headers=auth_headers)
        orders = [m["sort_order"] for m in response.json()]
        assert orders == sorted(orders)

    def test_list_modules_unauthorized(self, client):
        """Token olmadan erişim 401 dönmeli."""
        response = client.get("/api/system/modules/")
        assert response.status_code == 401


# ==================== AĞAÇ TESTLERİ ====================


class TestModuleTree:
    """Modül ağacı testleri."""

    def test_tree_returns_hierarchical(self, client, auth_headers):
        """Ağaç yapısı hiyerarşik olmalı."""
        response = client.get("/api/system/modules/tree", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        # Kök modüller parent_id=None olmalı
        for root in data:
            assert root["parent_id"] is None

    def test_tree_children_nested(self, client, auth_headers, parent_child_modules):
        """Alt modüller children dizisinde olmalı."""
        response = client.get("/api/system/modules/tree", headers=auth_headers)
        data = response.json()
        parent_code = "test_parent"
        parent_node = next((m for m in data if m["code"] == parent_code), None)
        assert parent_node is not None
        assert len(parent_node["children"]) > 0
        child_codes = [c["code"] for c in parent_node["children"]]
        assert "test_child" in child_codes

    def test_tree_only_active_modules(self, client, auth_headers, db):
        """Ağaçta sadece aktif modüller gösterilmeli."""
        inactive = Module(name="PasifModül", code="test_inactive", is_active=False, sort_order=999)
        db.add(inactive)
        db.commit()
        db.refresh(inactive)

        response = client.get("/api/system/modules/tree", headers=auth_headers)
        codes = []
        for m in response.json():
            codes.append(m["code"])
            codes.extend(c["code"] for c in m.get("children", []))
        assert "test_inactive" not in codes

        db.delete(inactive)
        db.commit()

    def test_tree_unauthorized(self, client):
        """Token olmadan ağaç erişimi 401 dönmeli."""
        response = client.get("/api/system/modules/tree")
        assert response.status_code == 401


# ==================== DETAY TESTLERİ ====================


class TestGetModule:
    """Modül detay testleri."""

    def test_get_module_success(self, client, auth_headers, temp_module):
        """Modül detayı görüntülenebilmeli."""
        response = client.get(f"/api/system/modules/{temp_module.id}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["code"] == "temp_test_mod"

    def test_get_module_not_found(self, client, auth_headers):
        """Olmayan modül 404 dönmeli."""
        response = client.get("/api/system/modules/999999", headers=auth_headers)
        assert response.status_code == 404

    def test_get_module_unauthorized(self, client):
        """Token olmadan erişim 401 dönmeli."""
        response = client.get("/api/system/modules/1")
        assert response.status_code == 401


# ==================== OLUŞTURMA TESTLERİ ====================


class TestCreateModule:
    """Modül oluşturma testleri."""

    def _cleanup(self, db, code):
        mod = db.query(Module).filter(Module.code == code).first()
        if mod:
            db.delete(mod)
            db.commit()

    def test_create_module_success(self, client, auth_headers, db):
        """Geçerli bilgilerle modül oluşturulabilmeli."""
        response = client.post("/api/system/modules/", headers=auth_headers, json={
            "name": "Test Yeni Modül",
            "code": "test_new_module",
            "description": "Test açıklaması",
            "icon": "TestIcon",
            "sort_order": 100,
        })
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Yeni Modül"
        assert data["code"] == "test_new_module"
        assert data["is_active"] is True
        self._cleanup(db, "test_new_module")

    def test_create_module_with_parent(self, client, auth_headers, db, temp_module):
        """Üst modül ile oluşturulabilmeli."""
        response = client.post("/api/system/modules/", headers=auth_headers, json={
            "name": "Alt Test Modül",
            "code": "test_sub_module",
            "parent_id": temp_module.id,
            "sort_order": 101,
        })
        assert response.status_code == 201
        assert response.json()["parent_id"] == temp_module.id
        self._cleanup(db, "test_sub_module")

    def test_create_module_invalid_parent(self, client, auth_headers):
        """Geçersiz üst modül ile oluşturma 404 dönmeli."""
        response = client.post("/api/system/modules/", headers=auth_headers, json={
            "name": "Yetim Modül",
            "code": "test_orphan",
            "parent_id": 999999,
            "sort_order": 102,
        })
        assert response.status_code == 404

    def test_create_module_duplicate_code(self, client, auth_headers, temp_module):
        """Aynı kodla modül oluşturma 409 dönmeli."""
        response = client.post("/api/system/modules/", headers=auth_headers, json={
            "name": "Duplicate",
            "code": "temp_test_mod",
            "sort_order": 0,
        })
        assert response.status_code == 409
        assert "zaten mevcut" in response.json()["detail"].lower()

    def test_create_module_unauthorized(self, client):
        """Token olmadan oluşturma 401 dönmeli."""
        response = client.post("/api/system/modules/", json={
            "name": "NoAuth",
            "code": "noauth",
        })
        assert response.status_code == 401


# ==================== GÜNCELLEME TESTLERİ ====================


class TestUpdateModule:
    """Modül güncelleme testleri."""

    def test_update_module_name(self, client, auth_headers, temp_module):
        """Modül adı güncellenebilmeli."""
        response = client.patch(
            f"/api/system/modules/{temp_module.id}",
            headers=auth_headers,
            json={"name": "Güncellenmiş Modül"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Güncellenmiş Modül"

    def test_update_module_code(self, client, auth_headers, temp_module, db):
        """Modül kodu benzersiz kalarak güncellenebilmeli."""
        response = client.patch(
            f"/api/system/modules/{temp_module.id}",
            headers=auth_headers,
            json={"code": "temp_test_mod_v2"},
        )
        assert response.status_code == 200
        assert response.json()["code"] == "temp_test_mod_v2"
        # Geri al
        client.patch(
            f"/api/system/modules/{temp_module.id}",
            headers=auth_headers,
            json={"code": "temp_test_mod"},
        )

    def test_update_module_duplicate_code(self, client, auth_headers, temp_module):
        """Var olan kodla güncelleme 409 dönmeli."""
        response = client.patch(
            f"/api/system/modules/{temp_module.id}",
            headers=auth_headers,
            json={"code": "dashboard"},  # Mevcut modül kodu
        )
        assert response.status_code == 409

    def test_update_module_deactivate(self, client, auth_headers, temp_module):
        """Modül devre dışı bırakılabilmeli."""
        response = client.patch(
            f"/api/system/modules/{temp_module.id}",
            headers=auth_headers,
            json={"is_active": False},
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is False

    def test_update_module_self_parent(self, client, auth_headers, temp_module):
        """Modül kendisinin üst modülü olamaz."""
        response = client.patch(
            f"/api/system/modules/{temp_module.id}",
            headers=auth_headers,
            json={"parent_id": temp_module.id},
        )
        assert response.status_code == 400
        assert "kendisinin" in response.json()["detail"].lower()

    def test_update_module_circular_reference(self, client, auth_headers, parent_child_modules):
        """Döngüsel referans engellenmelidir."""
        parent, child = parent_child_modules
        # Üst modülü alt modülün altına taşımaya çalış
        response = client.patch(
            f"/api/system/modules/{parent.id}",
            headers=auth_headers,
            json={"parent_id": child.id},
        )
        assert response.status_code == 400
        assert "döngüsel" in response.json()["detail"].lower()

    def test_update_module_invalid_parent(self, client, auth_headers, temp_module):
        """Geçersiz üst modül 404 dönmeli."""
        response = client.patch(
            f"/api/system/modules/{temp_module.id}",
            headers=auth_headers,
            json={"parent_id": 999999},
        )
        assert response.status_code == 404

    def test_update_module_not_found(self, client, auth_headers):
        """Olmayan modül güncelleme 404 dönmeli."""
        response = client.patch(
            "/api/system/modules/999999",
            headers=auth_headers,
            json={"name": "Test"},
        )
        assert response.status_code == 404

    def test_update_module_unauthorized(self, client, temp_module):
        """Token olmadan güncelleme 401 dönmeli."""
        response = client.patch(
            f"/api/system/modules/{temp_module.id}",
            json={"name": "Test"},
        )
        assert response.status_code == 401


# ==================== SİLME TESTLERİ ====================


class TestDeleteModule:
    """Modül silme testleri."""

    def test_delete_module_success(self, client, auth_headers, db):
        """Alt modülsüz modül silinebilmeli."""
        mod = Module(name="SilinecekMod", code="test_del_mod", is_active=True, sort_order=99)
        db.add(mod)
        db.commit()
        db.refresh(mod)

        response = client.delete(f"/api/system/modules/{mod.id}", headers=auth_headers)
        assert response.status_code == 204

        get_resp = client.get(f"/api/system/modules/{mod.id}", headers=auth_headers)
        assert get_resp.status_code == 404

    def test_delete_module_with_children(self, client, auth_headers, parent_child_modules):
        """Alt modülü olan modül silinemez."""
        parent, child = parent_child_modules
        response = client.delete(f"/api/system/modules/{parent.id}", headers=auth_headers)
        assert response.status_code == 400
        assert "alt modül" in response.json()["detail"].lower()

    def test_delete_module_not_found(self, client, auth_headers):
        """Olmayan modül silme 404 dönmeli."""
        response = client.delete("/api/system/modules/999999", headers=auth_headers)
        assert response.status_code == 404

    def test_delete_module_unauthorized(self, client):
        """Token olmadan silme 401 dönmeli."""
        response = client.delete("/api/system/modules/1")
        assert response.status_code == 401

    def test_delete_child_then_parent(self, client, auth_headers, db):
        """Önce alt, sonra üst modül silinebilmeli."""
        parent = Module(name="SilÜst", code="test_del_parent", is_active=True, sort_order=90)
        db.add(parent)
        db.flush()
        child = Module(name="SilAlt", code="test_del_child", parent_id=parent.id, is_active=True, sort_order=91)
        db.add(child)
        db.commit()
        db.refresh(parent)
        db.refresh(child)

        # Önce child sil
        resp1 = client.delete(f"/api/system/modules/{child.id}", headers=auth_headers)
        assert resp1.status_code == 204
        # Sonra parent sil
        resp2 = client.delete(f"/api/system/modules/{parent.id}", headers=auth_headers)
        assert resp2.status_code == 204
