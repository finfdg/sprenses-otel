"""Mesajlaşma modülü kapsamlı testleri.

İki test kullanıcısı (test_msg_user1 ve test_msg_user2) oluşturulur;
private konuşma, grup konuşma, mesaj CRUD, okundu, arama ve
yetkilendirme senaryoları test edilir.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session as SASession

from tests.conftest import engine, app, extract_token
from app.database import get_db
from app.routers.messages._helpers import _invalidate_messaging_role_cache
from app.models.user import User
from app.models.role import Role
from app.models.module import Module
from app.models.role_module_permission import RoleModulePermission
from app.models.conversation import Conversation, ConversationMember
from app.models.message import Message
from app.utils.security import hash_password
from app.middleware.rate_limit import message_limiter


# ─── Fixture'lar ──────────────────────────────────────────────────────


def _get_or_create_test_role(db, role_name="Test Mesaj Rolü"):
    """Messaging izni olan test rolü oluştur veya getir."""
    role = db.query(Role).filter(Role.name == role_name).first()
    if role:
        return role

    role = Role(name=role_name, description="Mesajlaşma testi için rol")
    db.add(role)
    db.flush()

    # Messaging modülüne izin ver
    messaging_mod = db.query(Module).filter(Module.code == "messaging").first()
    if messaging_mod:
        perm = RoleModulePermission(
            role_id=role.id,
            module_id=messaging_mod.id,
            can_view=True,
            can_use=True,
        )
        db.add(perm)
        db.flush()

    return role


def _get_or_create_user(db, username, email, first_name, last_name, role_id):
    """Test kullanıcısı oluştur veya getir."""
    user = db.query(User).filter(User.username == username).first()
    if user:
        return user

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password("test1234"),
        first_name=first_name,
        last_name=last_name,
        role_id=role_id,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _get_or_create_noperm_role(db):
    """Messaging izni OLMAYAN rol oluştur."""
    role_name = "Test İzinsiz Rolü"
    role = db.query(Role).filter(Role.name == role_name).first()
    if role:
        return role

    role = Role(name=role_name, description="İzin testi için rol")
    db.add(role)
    db.flush()
    return role


@pytest.fixture(autouse=True)
def _auto_rollback_and_reset():
    """Sıralı mesaj testleri — per-test rollback devre dışı."""
    yield None


@pytest.fixture(scope="module", autouse=True)
def _module_transaction():
    """Tüm modül tek bir transaction'da çalışır, sonunda rollback yapılır."""
    from app.middleware.rate_limit import (
        login_limiter, register_limiter, message_limiter,
        upload_limiter, search_limiter,
    )

    conn = engine.connect()
    txn = conn.begin()
    sess = SASession(bind=conn)

    nested = conn.begin_nested()

    @sa_event.listens_for(sess, "after_transaction_end")
    def restart(s, t):
        nonlocal nested
        if t.nested and not t._parent.nested:
            nested = conn.begin_nested()

    def override():
        try:
            yield sess
        finally:
            pass

    app.dependency_overrides[get_db] = override
    login_limiter._requests.clear()
    register_limiter._requests.clear()
    message_limiter._requests.clear()
    upload_limiter._requests.clear()
    search_limiter._requests.clear()
    _invalidate_messaging_role_cache()

    yield sess

    sess.close()
    txn.rollback()
    conn.close()
    app.dependency_overrides.pop(get_db, None)
    _invalidate_messaging_role_cache()


@pytest.fixture(scope="module")
def setup_test_users(_module_transaction):
    """Modül seviyesinde test kullanıcıları ve rolü oluştur."""
    db = _module_transaction
    role = _get_or_create_test_role(db)
    user1 = _get_or_create_user(
        db, "test_msg_user1", "msg1@test.com",
        "Mesaj", "Bir", role.id,
    )
    user2 = _get_or_create_user(
        db, "test_msg_user2", "msg2@test.com",
        "Mesaj", "İki", role.id,
    )
    user3 = _get_or_create_user(
        db, "test_msg_user3", "msg3@test.com",
        "Mesaj", "Üç", role.id,
    )

    # İzinsiz kullanıcı
    noperm_role = _get_or_create_noperm_role(db)
    noperm_user = _get_or_create_user(
        db, "test_msg_noperm", "msgnoperm@test.com",
        "İzinsiz", "Kullanıcı", noperm_role.id,
    )

    db.flush()

    return {
        "user1_id": user1.id,
        "user2_id": user2.id,
        "user3_id": user3.id,
        "noperm_user_id": noperm_user.id,
    }


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def user1_headers(client):
    resp = client.post("/api/auth/login", json={
        "username": "test_msg_user1",
        "password": "test1234",
    })
    assert resp.status_code == 200, f"user1 login başarısız: {resp.text}"
    return {"Authorization": f"Bearer {extract_token(resp)}"}


@pytest.fixture(scope="module")
def user2_headers(client):
    resp = client.post("/api/auth/login", json={
        "username": "test_msg_user2",
        "password": "test1234",
    })
    assert resp.status_code == 200, f"user2 login başarısız: {resp.text}"
    return {"Authorization": f"Bearer {extract_token(resp)}"}


@pytest.fixture(scope="module")
def user3_headers(client):
    resp = client.post("/api/auth/login", json={
        "username": "test_msg_user3",
        "password": "test1234",
    })
    assert resp.status_code == 200, f"user3 login başarısız: {resp.text}"
    return {"Authorization": f"Bearer {extract_token(resp)}"}


@pytest.fixture(scope="module")
def noperm_headers(client):
    resp = client.post("/api/auth/login", json={
        "username": "test_msg_noperm",
        "password": "test1234",
    })
    assert resp.status_code == 200, f"noperm login başarısız: {resp.text}"
    return {"Authorization": f"Bearer {extract_token(resp)}"}


@pytest.fixture(autouse=True)
def reset_msg_limiter():
    """Her testten önce mesaj rate limiter'ı sıfırla."""
    message_limiter._requests.clear()
    yield
    message_limiter._requests.clear()


# ─── Kullanıcı Listesi Testleri ──────────────────────────────────────


class TestChatUsers:
    def test_list_chat_users(self, client, user1_headers, setup_test_users):
        """Mesajlaşılabilir kullanıcı listesini getirir."""
        resp = client.get("/api/messages/users", headers=user1_headers)
        assert resp.status_code == 200
        users = resp.json()
        # En az user2 ve user3 listede olmalı
        user_ids = [u["id"] for u in users]
        assert setup_test_users["user2_id"] in user_ids
        assert setup_test_users["user3_id"] in user_ids
        # Kendisi listede olmamalı
        assert setup_test_users["user1_id"] not in user_ids

    def test_list_chat_users_search(self, client, user1_headers, setup_test_users):
        """İsme göre arama çalışır."""
        resp = client.get(
            "/api/messages/users?search=İki",
            headers=user1_headers,
        )
        assert resp.status_code == 200
        users = resp.json()
        assert any(u["id"] == setup_test_users["user2_id"] for u in users)

    def test_list_chat_users_no_permission(self, client, noperm_headers, setup_test_users):
        """Messaging izni olmayan kullanıcı listeyi göremez."""
        resp = client.get("/api/messages/users", headers=noperm_headers)
        assert resp.status_code == 403


# ─── Private Konuşma Testleri ────────────────────────────────────────


class TestPrivateConversation:
    """Private (birebir) konuşma oluşturma ve yönetimi."""

    def test_create_conversation(self, client, user1_headers, setup_test_users):
        """Yeni private konuşma başlatır."""
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_test_users["user2_id"], "message": "Merhaba!"},
            headers=user1_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["type"] == "private"
        assert data["other_user"]["id"] == setup_test_users["user2_id"]
        assert len(data["messages"]) == 1
        assert data["messages"][0]["content"] == "Merhaba!"

    def test_create_conversation_without_message(self, client, user1_headers, setup_test_users):
        """Mesajsız konuşma başlatır (user3 ile)."""
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_test_users["user3_id"]},
            headers=user1_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["type"] == "private"
        assert data["messages"] == []

    def test_create_conversation_returns_existing(self, client, user1_headers, setup_test_users):
        """Zaten var olan konuşmayı tekrar oluşturmak mevcut olanı döndürür."""
        # İlk oluştur
        resp1 = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_test_users["user2_id"]},
            headers=user1_headers,
        )
        assert resp1.status_code == 201
        conv_id1 = resp1.json()["id"]

        # Tekrar oluşturmayı dene
        resp2 = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_test_users["user2_id"]},
            headers=user1_headers,
        )
        assert resp2.status_code == 201
        conv_id2 = resp2.json()["id"]
        assert conv_id1 == conv_id2

    def test_create_conversation_with_self(self, client, user1_headers, setup_test_users):
        """Kendinizle konuşma başlatamazsınız."""
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_test_users["user1_id"]},
            headers=user1_headers,
        )
        assert resp.status_code == 400
        assert "Kendinizle" in resp.json()["detail"]

    def test_create_conversation_nonexistent_user(self, client, user1_headers, setup_test_users):
        """Var olmayan kullanıcıyla konuşma başlatılamaz."""
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": 999999},
            headers=user1_headers,
        )
        assert resp.status_code == 404

    def test_create_conversation_no_permission(self, client, noperm_headers, setup_test_users):
        """Messaging izni olmayan kullanıcı konuşma başlatamaz."""
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_test_users["user1_id"]},
            headers=noperm_headers,
        )
        assert resp.status_code == 403


# ─── Konuşma Listesi Testleri ────────────────────────────────────────


class TestConversationList:
    def test_list_conversations(self, client, user1_headers, setup_test_users):
        """Kullanıcının konuşma listesini getirir."""
        resp = client.get("/api/messages/conversations", headers=user1_headers)
        assert resp.status_code == 200
        convs = resp.json()
        assert isinstance(convs, list)
        assert len(convs) >= 1
        # Her konuşmada updated_at olmalı
        for conv in convs:
            assert "updated_at" in conv
            assert "type" in conv

    def test_list_conversations_user2_sees_private(self, client, user2_headers, setup_test_users):
        """User2 de user1 ile olan konuşmayı görür."""
        resp = client.get("/api/messages/conversations", headers=user2_headers)
        assert resp.status_code == 200
        convs = resp.json()
        private_convs = [c for c in convs if c["type"] == "private"]
        assert len(private_convs) >= 1

    def test_list_conversations_no_permission(self, client, noperm_headers, setup_test_users):
        """İzinsiz kullanıcı konuşma listesini göremez."""
        resp = client.get("/api/messages/conversations", headers=noperm_headers)
        assert resp.status_code == 403


# ─── Mesaj Gönderme Testleri ─────────────────────────────────────────


class TestSendMessage:
    def _get_conv_id(self, client, user1_headers, user2_id):
        """user1-user2 arası private konuşma ID'sini al."""
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": user2_id},
            headers=user1_headers,
        )
        return resp.json()["id"]

    def test_send_message(self, client, user1_headers, setup_test_users):
        """Konuşmaya mesaj gönderir."""
        conv_id = self._get_conv_id(
            client, user1_headers, setup_test_users["user2_id"],
        )
        resp = client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": "Test mesajı gönderiliyor"},
            headers=user1_headers,
        )
        assert resp.status_code == 201
        msg = resp.json()
        assert msg["content"] == "Test mesajı gönderiliyor"
        assert msg["sender_id"] == setup_test_users["user1_id"]
        assert msg["is_edited"] is False
        assert msg["is_deleted"] is False
        assert msg["message_type"] == "text"

    def test_send_empty_message(self, client, user1_headers, setup_test_users):
        """Boş mesaj gönderilemez."""
        conv_id = self._get_conv_id(
            client, user1_headers, setup_test_users["user2_id"],
        )
        resp = client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": "   "},
            headers=user1_headers,
        )
        assert resp.status_code == 400

    def test_send_message_not_member(self, client, user3_headers, user1_headers, setup_test_users):
        """Üye olmayan konuşmaya mesaj gönderilemez."""
        # user1-user2 arası konuşmayı al
        conv_id = self._get_conv_id(
            client, user1_headers, setup_test_users["user2_id"],
        )
        # user3 bu konuşmaya mesaj göndermeye çalışsın
        resp = client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": "İzinsiz mesaj"},
            headers=user3_headers,
        )
        assert resp.status_code == 404

    def test_send_message_no_permission(self, client, noperm_headers, setup_test_users):
        """İzinsiz kullanıcı mesaj gönderemez."""
        resp = client.post(
            "/api/messages/conversations/1",
            json={"content": "test"},
            headers=noperm_headers,
        )
        assert resp.status_code == 403

    def test_send_multiple_messages(self, client, user1_headers, user2_headers, setup_test_users):
        """Birden fazla mesaj gönderilir ve sıralama doğrulanır."""
        conv_id = self._get_conv_id(
            client, user1_headers, setup_test_users["user2_id"],
        )
        for i in range(3):
            resp = client.post(
                f"/api/messages/conversations/{conv_id}",
                json={"content": f"Sıralı mesaj {i}"},
                headers=user1_headers,
            )
            assert resp.status_code == 201

        # user2 de mesaj göndersin
        resp = client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": "User2 yanıtı"},
            headers=user2_headers,
        )
        assert resp.status_code == 201

        # Konuşma detayını al ve sırala
        detail = client.get(
            f"/api/messages/conversations/{conv_id}",
            headers=user1_headers,
        )
        assert detail.status_code == 200
        messages = detail.json()["messages"]
        # Mesajlar kronolojik sırada olmalı (eski→yeni)
        for i in range(len(messages) - 1):
            assert messages[i]["id"] < messages[i + 1]["id"]


# ─── Konuşma Detayı Testleri ─────────────────────────────────────────


class TestConversationDetail:
    def _get_conv_id(self, client, user1_headers, user2_id):
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": user2_id},
            headers=user1_headers,
        )
        return resp.json()["id"]

    def test_get_conversation_detail(self, client, user1_headers, setup_test_users):
        """Konuşma detayını getirir."""
        conv_id = self._get_conv_id(
            client, user1_headers, setup_test_users["user2_id"],
        )
        resp = client.get(
            f"/api/messages/conversations/{conv_id}",
            headers=user1_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "private"
        assert data["other_user"]["id"] == setup_test_users["user2_id"]
        assert isinstance(data["messages"], list)

    def test_get_conversation_not_member(self, client, user3_headers, user1_headers, setup_test_users):
        """Üye olmayan konuşma detayına erişilemez."""
        conv_id = self._get_conv_id(
            client, user1_headers, setup_test_users["user2_id"],
        )
        resp = client.get(
            f"/api/messages/conversations/{conv_id}",
            headers=user3_headers,
        )
        assert resp.status_code == 404

    def test_conversation_pagination(self, client, user1_headers, setup_test_users):
        """Cursor-based pagination çalışır."""
        conv_id = self._get_conv_id(
            client, user1_headers, setup_test_users["user2_id"],
        )

        # Detayı limit ile al
        resp = client.get(
            f"/api/messages/conversations/{conv_id}?limit=2",
            headers=user1_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        messages = data["messages"]
        # Limit 2 ise en fazla 2 mesaj döner
        assert len(messages) <= 2

        if data["has_more"] and len(messages) > 0:
            # before_id ile eski mesajları al
            first_id = messages[0]["id"]
            resp2 = client.get(
                f"/api/messages/conversations/{conv_id}?before_id={first_id}&limit=2",
                headers=user1_headers,
            )
            assert resp2.status_code == 200
            older = resp2.json()["messages"]
            # Tüm mesajlar before_id'den küçük olmalı
            for m in older:
                assert m["id"] < first_id


# ─── Mesaj Düzenleme Testleri ────────────────────────────────────────


class TestEditMessage:
    def _setup_message(self, client, user1_headers, user2_id):
        """Konuşma oluştur ve mesaj gönder, (conv_id, msg_id) döndür."""
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": user2_id},
            headers=user1_headers,
        )
        conv_id = resp.json()["id"]

        msg_resp = client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": "Düzenlenecek mesaj"},
            headers=user1_headers,
        )
        msg_id = msg_resp.json()["id"]
        return conv_id, msg_id

    def test_edit_own_message(self, client, user1_headers, setup_test_users):
        """Kendi mesajını düzenler."""
        conv_id, msg_id = self._setup_message(
            client, user1_headers, setup_test_users["user2_id"],
        )
        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/messages/{msg_id}",
            json={"content": "Düzenlenmiş mesaj"},
            headers=user1_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "Düzenlenmiş mesaj"
        assert data["is_edited"] is True
        assert data["edited_at"] is not None

    def test_edit_other_user_message(self, client, user1_headers, user2_headers, setup_test_users):
        """Başkasının mesajını düzenleyemez."""
        conv_id, msg_id = self._setup_message(
            client, user1_headers, setup_test_users["user2_id"],
        )
        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/messages/{msg_id}",
            json={"content": "Hacked!"},
            headers=user2_headers,
        )
        assert resp.status_code == 403

    def test_edit_empty_content(self, client, user1_headers, setup_test_users):
        """Boş içerikle düzenleme yapılamaz."""
        conv_id, msg_id = self._setup_message(
            client, user1_headers, setup_test_users["user2_id"],
        )
        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/messages/{msg_id}",
            json={"content": "   "},
            headers=user1_headers,
        )
        assert resp.status_code == 400

    def test_edit_nonexistent_message(self, client, user1_headers, setup_test_users):
        """Var olmayan mesajı düzenleyemez."""
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_test_users["user2_id"]},
            headers=user1_headers,
        )
        conv_id = resp.json()["id"]

        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/messages/999999",
            json={"content": "test"},
            headers=user1_headers,
        )
        assert resp.status_code == 404

    def test_edit_not_member(self, client, user3_headers, user1_headers, setup_test_users):
        """Üye olmayan konuşmadaki mesajı düzenleyemez."""
        conv_id, msg_id = self._setup_message(
            client, user1_headers, setup_test_users["user2_id"],
        )
        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/messages/{msg_id}",
            json={"content": "test"},
            headers=user3_headers,
        )
        assert resp.status_code == 404


# ─── Mesaj Silme Testleri ────────────────────────────────────────────


class TestDeleteMessage:
    def _setup_message(self, client, user1_headers, user2_id):
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": user2_id},
            headers=user1_headers,
        )
        conv_id = resp.json()["id"]
        msg_resp = client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": "Silinecek mesaj"},
            headers=user1_headers,
        )
        msg_id = msg_resp.json()["id"]
        return conv_id, msg_id

    def test_delete_own_message(self, client, user1_headers, setup_test_users):
        """Kendi mesajını siler (soft delete)."""
        conv_id, msg_id = self._setup_message(
            client, user1_headers, setup_test_users["user2_id"],
        )
        resp = client.delete(
            f"/api/messages/conversations/{conv_id}/messages/{msg_id}",
            headers=user1_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_deleted"] is True
        assert data["content"] == "Bu mesaj silindi"

    def test_delete_other_user_message(self, client, user1_headers, user2_headers, setup_test_users):
        """Başkasının mesajını silemez."""
        conv_id, msg_id = self._setup_message(
            client, user1_headers, setup_test_users["user2_id"],
        )
        resp = client.delete(
            f"/api/messages/conversations/{conv_id}/messages/{msg_id}",
            headers=user2_headers,
        )
        assert resp.status_code == 403

    def test_delete_already_deleted(self, client, user1_headers, setup_test_users):
        """Zaten silinmiş mesajı tekrar silemez."""
        conv_id, msg_id = self._setup_message(
            client, user1_headers, setup_test_users["user2_id"],
        )
        # İlk silme
        client.delete(
            f"/api/messages/conversations/{conv_id}/messages/{msg_id}",
            headers=user1_headers,
        )
        # Tekrar silme denemesi
        resp = client.delete(
            f"/api/messages/conversations/{conv_id}/messages/{msg_id}",
            headers=user1_headers,
        )
        assert resp.status_code == 400

    def test_edit_deleted_message(self, client, user1_headers, setup_test_users):
        """Silinmiş mesajı düzenleyemez."""
        conv_id, msg_id = self._setup_message(
            client, user1_headers, setup_test_users["user2_id"],
        )
        client.delete(
            f"/api/messages/conversations/{conv_id}/messages/{msg_id}",
            headers=user1_headers,
        )
        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/messages/{msg_id}",
            json={"content": "Düzenleme denemesi"},
            headers=user1_headers,
        )
        assert resp.status_code == 400

    def test_delete_not_member(self, client, user3_headers, user1_headers, setup_test_users):
        """Üye olmayan konuşmadaki mesajı silemez."""
        conv_id, msg_id = self._setup_message(
            client, user1_headers, setup_test_users["user2_id"],
        )
        resp = client.delete(
            f"/api/messages/conversations/{conv_id}/messages/{msg_id}",
            headers=user3_headers,
        )
        assert resp.status_code == 404


# ─── Okundu İşaretleme Testleri ─────────────────────────────────────


class TestReadStatus:
    def _get_conv_id(self, client, user1_headers, user2_id):
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": user2_id},
            headers=user1_headers,
        )
        return resp.json()["id"]

    def test_mark_as_read(self, client, user2_headers, user1_headers, setup_test_users):
        """Konuşmayı okundu olarak işaretler."""
        conv_id = self._get_conv_id(
            client, user1_headers, setup_test_users["user2_id"],
        )
        # user1 mesaj göndersin
        client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": "Okunmamış mesaj"},
            headers=user1_headers,
        )

        # user2 okundu işaretlesin
        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/read",
            headers=user2_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_mark_as_read_not_member(self, client, user3_headers, user1_headers, setup_test_users):
        """Üye olmayan konuşmayı okundu işaretleyemez."""
        conv_id = self._get_conv_id(
            client, user1_headers, setup_test_users["user2_id"],
        )
        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/read",
            headers=user3_headers,
        )
        assert resp.status_code == 404


# ─── Okunmamış Sayısı Testleri ──────────────────────────────────────


class TestUnreadCount:
    def test_get_unread_count(self, client, user3_headers, user1_headers, setup_test_users):
        """Okunmamış mesaj sayısını döndürür."""
        # user1-user3 arası yeni konuşma oluştur (önceki testlerde mark_as_read
        # yapılmamış olmalı) ve user1'den mesaj gönder
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_test_users["user3_id"]},
            headers=user1_headers,
        )
        conv_id = resp.json()["id"]

        client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": "Yeni okunmamış"},
            headers=user1_headers,
        )

        # user3 okunmamış sayısını alsın
        resp = client.get("/api/messages/unread-count", headers=user3_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_unread" in data
        assert data["total_unread"] >= 1

    def test_unread_count_decreases_after_read(self, client, user3_headers, user1_headers, setup_test_users):
        """Okundu işaretinden sonra okunmamış sayısı azalır."""
        # user1-user3 arası konuşma kullan (mark_as_read yapılmamış)
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_test_users["user3_id"]},
            headers=user1_headers,
        )
        conv_id = resp.json()["id"]

        # Mesaj gönder
        client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": "Sayaç testi"},
            headers=user1_headers,
        )

        # Okunmamış sayısını al
        before = client.get("/api/messages/unread-count", headers=user3_headers).json()["total_unread"]

        # Okundu işaretle
        client.patch(f"/api/messages/conversations/{conv_id}/read", headers=user3_headers)

        # Tekrar al
        after = client.get("/api/messages/unread-count", headers=user3_headers).json()["total_unread"]
        assert after <= before


# ─── Mesaj Arama Testleri ────────────────────────────────────────────


class TestSearchMessages:
    def test_search_in_conversation(self, client, user1_headers, setup_test_users):
        """Konuşma içinde mesaj arar."""
        # Konuşma oluştur ve benzersiz mesaj gönder
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_test_users["user2_id"]},
            headers=user1_headers,
        )
        conv_id = resp.json()["id"]

        client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": "xyzAramaBenzersizKelimexyz"},
            headers=user1_headers,
        )

        # Ara
        resp = client.get(
            f"/api/messages/conversations/{conv_id}/search?q=AramaBenzersiz",
            headers=user1_headers,
        )
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1
        assert any("AramaBenzersiz" in r["content"] for r in results)

    def test_search_empty_query(self, client, user1_headers, setup_test_users):
        """Boş sorgu boş sonuç döndürür."""
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_test_users["user2_id"]},
            headers=user1_headers,
        )
        conv_id = resp.json()["id"]

        resp = client.get(
            f"/api/messages/conversations/{conv_id}/search?q=",
            headers=user1_headers,
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_search_no_results(self, client, user1_headers, setup_test_users):
        """Eşleşme olmayan sorgu boş sonuç döndürür."""
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_test_users["user2_id"]},
            headers=user1_headers,
        )
        conv_id = resp.json()["id"]

        resp = client.get(
            f"/api/messages/conversations/{conv_id}/search?q=OlmayanKelimeXYZ123456",
            headers=user1_headers,
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_search_not_member(self, client, user3_headers, user1_headers, setup_test_users):
        """Üye olmayan konuşmada arama yapamaz."""
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_test_users["user2_id"]},
            headers=user1_headers,
        )
        conv_id = resp.json()["id"]

        resp = client.get(
            f"/api/messages/conversations/{conv_id}/search?q=test",
            headers=user3_headers,
        )
        assert resp.status_code == 404

    def test_search_deleted_messages_excluded(self, client, user1_headers, setup_test_users):
        """Silinmiş mesajlar aramada görünmez."""
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_test_users["user2_id"]},
            headers=user1_headers,
        )
        conv_id = resp.json()["id"]

        # Benzersiz mesaj gönder ve sil
        msg_resp = client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": "SilinmişAramaTesti987"},
            headers=user1_headers,
        )
        msg_id = msg_resp.json()["id"]
        client.delete(
            f"/api/messages/conversations/{conv_id}/messages/{msg_id}",
            headers=user1_headers,
        )

        # Ara
        resp = client.get(
            f"/api/messages/conversations/{conv_id}/search?q=SilinmişAramaTesti987",
            headers=user1_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 0


# ─── Grup Konuşma Testleri ───────────────────────────────────────────


class TestGroupConversation:
    def test_create_group(self, client, user1_headers, setup_test_users):
        """Yeni grup oluşturur."""
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "Test Grubu",
                "member_ids": [
                    setup_test_users["user2_id"],
                    setup_test_users["user3_id"],
                ],
                "message": "Gruba hoş geldiniz!",
            },
            headers=user1_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["type"] == "group"
        assert data["name"] == "Test Grubu"
        assert data["created_by"] == setup_test_users["user1_id"]
        # Üyeler listesi (user1 admin)
        assert data["members"] is not None
        member_ids = [m["id"] for m in data["members"]]
        assert setup_test_users["user1_id"] in member_ids
        assert setup_test_users["user2_id"] in member_ids
        assert setup_test_users["user3_id"] in member_ids
        # Sistem mesajı + ilk mesaj
        assert len(data["messages"]) == 2

    def test_create_group_no_name(self, client, user1_headers, setup_test_users):
        """İsimsiz grup oluşturulamaz."""
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "   ",
                "member_ids": [setup_test_users["user2_id"]],
            },
            headers=user1_headers,
        )
        assert resp.status_code == 400

    def test_create_group_no_members(self, client, user1_headers, setup_test_users):
        """Üyesiz grup oluşturulamaz."""
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "Boş Grup",
                "member_ids": [],
            },
            headers=user1_headers,
        )
        assert resp.status_code == 400

    def test_create_group_only_self(self, client, user1_headers, setup_test_users):
        """Sadece kendini içeren grup oluşturulamaz."""
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "Tekil Grup",
                "member_ids": [setup_test_users["user1_id"]],
            },
            headers=user1_headers,
        )
        assert resp.status_code == 400

    def test_create_group_invalid_members(self, client, user1_headers, setup_test_users):
        """Var olmayan üyelerle grup oluşturulamaz."""
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "Geçersiz Grup",
                "member_ids": [999998, 999999],
            },
            headers=user1_headers,
        )
        assert resp.status_code == 400

    def test_group_send_message(self, client, user1_headers, user2_headers, setup_test_users):
        """Grup üyeleri mesaj gönderebilir."""
        # Grup oluştur
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "Mesaj Grubu",
                "member_ids": [
                    setup_test_users["user2_id"],
                    setup_test_users["user3_id"],
                ],
            },
            headers=user1_headers,
        )
        conv_id = resp.json()["id"]

        # user2 mesaj göndersin
        msg_resp = client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": "Grup mesajı user2'den"},
            headers=user2_headers,
        )
        assert msg_resp.status_code == 201
        assert msg_resp.json()["sender_id"] == setup_test_users["user2_id"]

    def test_group_detail_has_members(self, client, user1_headers, setup_test_users):
        """Grup detayında üye listesi döner."""
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "Detay Grubu",
                "member_ids": [setup_test_users["user2_id"]],
            },
            headers=user1_headers,
        )
        conv_id = resp.json()["id"]

        detail = client.get(
            f"/api/messages/conversations/{conv_id}",
            headers=user1_headers,
        )
        assert detail.status_code == 200
        data = detail.json()
        assert data["type"] == "group"
        assert data["members"] is not None
        assert len(data["members"]) >= 2

    def test_update_group_name(self, client, user1_headers, setup_test_users):
        """Admin grup adını değiştirebilir."""
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "Eski Ad",
                "member_ids": [setup_test_users["user2_id"]],
            },
            headers=user1_headers,
        )
        conv_id = resp.json()["id"]

        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/name",
            json={"name": "Yeni Ad"},
            headers=user1_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Yeni Ad"

    def test_update_group_name_not_admin(self, client, user1_headers, user2_headers, setup_test_users):
        """Admin olmayan kullanıcı grup adını değiştiremez."""
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "Admin Test Grubu",
                "member_ids": [setup_test_users["user2_id"]],
            },
            headers=user1_headers,
        )
        conv_id = resp.json()["id"]

        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/name",
            json={"name": "Hack"},
            headers=user2_headers,
        )
        assert resp.status_code == 403

    def test_update_group_name_empty(self, client, user1_headers, setup_test_users):
        """Boş grup adı kabul edilmez."""
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "Boş Test Grubu",
                "member_ids": [setup_test_users["user2_id"]],
            },
            headers=user1_headers,
        )
        conv_id = resp.json()["id"]

        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/name",
            json={"name": "   "},
            headers=user1_headers,
        )
        assert resp.status_code == 400


# ─── Grup Üye Yönetimi Testleri ─────────────────────────────────────


class TestGroupMemberManagement:
    def _create_group(self, client, user1_headers, member_ids):
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "Üye Yönetim Grubu",
                "member_ids": member_ids,
            },
            headers=user1_headers,
        )
        assert resp.status_code == 201
        return resp.json()["id"]

    def test_add_member(self, client, user1_headers, setup_test_users):
        """Admin gruba üye ekler."""
        conv_id = self._create_group(
            client, user1_headers,
            [setup_test_users["user2_id"]],
        )

        resp = client.post(
            f"/api/messages/conversations/{conv_id}/members",
            json={"user_ids": [setup_test_users["user3_id"]]},
            headers=user1_headers,
        )
        assert resp.status_code == 200
        members = resp.json()["members"]
        member_ids = [m["id"] for m in members]
        assert setup_test_users["user3_id"] in member_ids

    def test_add_existing_member(self, client, user1_headers, setup_test_users):
        """Zaten grupta olan üyeyi eklemeye çalışınca hata döner."""
        conv_id = self._create_group(
            client, user1_headers,
            [setup_test_users["user2_id"]],
        )

        resp = client.post(
            f"/api/messages/conversations/{conv_id}/members",
            json={"user_ids": [setup_test_users["user2_id"]]},
            headers=user1_headers,
        )
        assert resp.status_code == 400

    def test_add_member_not_admin(self, client, user1_headers, user2_headers, setup_test_users):
        """Admin olmayan kullanıcı üye ekleyemez."""
        conv_id = self._create_group(
            client, user1_headers,
            [setup_test_users["user2_id"]],
        )

        resp = client.post(
            f"/api/messages/conversations/{conv_id}/members",
            json={"user_ids": [setup_test_users["user3_id"]]},
            headers=user2_headers,
        )
        assert resp.status_code == 403

    def test_remove_member(self, client, user1_headers, setup_test_users):
        """Admin gruptan üye çıkarır."""
        conv_id = self._create_group(
            client, user1_headers,
            [setup_test_users["user2_id"], setup_test_users["user3_id"]],
        )

        resp = client.delete(
            f"/api/messages/conversations/{conv_id}/members/{setup_test_users['user3_id']}",
            headers=user1_headers,
        )
        assert resp.status_code == 200

    def test_remove_member_not_admin(self, client, user1_headers, user2_headers, setup_test_users):
        """Admin olmayan kullanıcı başkasını çıkaramaz."""
        conv_id = self._create_group(
            client, user1_headers,
            [setup_test_users["user2_id"], setup_test_users["user3_id"]],
        )

        resp = client.delete(
            f"/api/messages/conversations/{conv_id}/members/{setup_test_users['user3_id']}",
            headers=user2_headers,
        )
        assert resp.status_code == 403

    def test_leave_group(self, client, user1_headers, user2_headers, setup_test_users):
        """Üye gruptan kendisi ayrılabilir."""
        conv_id = self._create_group(
            client, user1_headers,
            [setup_test_users["user2_id"]],
        )

        resp = client.delete(
            f"/api/messages/conversations/{conv_id}/members/{setup_test_users['user2_id']}",
            headers=user2_headers,
        )
        assert resp.status_code == 200

    def test_remove_nonexistent_member(self, client, user1_headers, setup_test_users):
        """Grupta olmayan üyeyi çıkarmak 404 döner."""
        conv_id = self._create_group(
            client, user1_headers,
            [setup_test_users["user2_id"]],
        )

        resp = client.delete(
            f"/api/messages/conversations/{conv_id}/members/999999",
            headers=user1_headers,
        )
        assert resp.status_code == 404


# ─── Grup Admin Yönetimi Testleri ────────────────────────────────────


class TestGroupAdminManagement:
    def _create_group(self, client, user1_headers, member_ids):
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "Admin Yönetim Grubu",
                "member_ids": member_ids,
            },
            headers=user1_headers,
        )
        assert resp.status_code == 201
        return resp.json()["id"]

    def test_make_admin(self, client, user1_headers, setup_test_users):
        """Admin başka bir üyeyi admin yapar."""
        conv_id = self._create_group(
            client, user1_headers,
            [setup_test_users["user2_id"]],
        )

        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/admins/{setup_test_users['user2_id']}",
            json={"is_admin": True},
            headers=user1_headers,
        )
        assert resp.status_code == 200
        members = resp.json()["members"]
        user2_member = next(m for m in members if m["id"] == setup_test_users["user2_id"])
        assert user2_member["is_admin"] is True

    def test_remove_admin(self, client, user1_headers, setup_test_users):
        """Admin yetkilendirmesini kaldırır."""
        conv_id = self._create_group(
            client, user1_headers,
            [setup_test_users["user2_id"]],
        )
        # Önce admin yap
        client.patch(
            f"/api/messages/conversations/{conv_id}/admins/{setup_test_users['user2_id']}",
            json={"is_admin": True},
            headers=user1_headers,
        )
        # Sonra kaldır
        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/admins/{setup_test_users['user2_id']}",
            json={"is_admin": False},
            headers=user1_headers,
        )
        assert resp.status_code == 200

    def test_cannot_remove_last_admin(self, client, user1_headers, setup_test_users):
        """Son yönetici yöneticiliğini kaldıramaz."""
        conv_id = self._create_group(
            client, user1_headers,
            [setup_test_users["user2_id"]],
        )

        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/admins/{setup_test_users['user1_id']}",
            json={"is_admin": False},
            headers=user1_headers,
        )
        assert resp.status_code == 400
        assert "en az bir yönetici" in resp.json()["detail"]

    def test_non_admin_cannot_change_admin(self, client, user1_headers, user2_headers, setup_test_users):
        """Admin olmayan kullanıcı yönetici atayamaz."""
        conv_id = self._create_group(
            client, user1_headers,
            [setup_test_users["user2_id"], setup_test_users["user3_id"]],
        )

        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/admins/{setup_test_users['user3_id']}",
            json={"is_admin": True},
            headers=user2_headers,
        )
        assert resp.status_code == 403

    def test_admin_change_nonexistent_member(self, client, user1_headers, setup_test_users):
        """Grupta olmayan üyeyi admin yapamaz."""
        conv_id = self._create_group(
            client, user1_headers,
            [setup_test_users["user2_id"]],
        )

        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/admins/999999",
            json={"is_admin": True},
            headers=user1_headers,
        )
        assert resp.status_code == 404


# ─── Private Konuşma için Grup İşlemleri Testleri ────────────────────


class TestPrivateGroupMismatch:
    """Private konuşmada grup işlemleri yapılamaz."""

    def _get_private_conv_id(self, client, user1_headers, user2_id):
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": user2_id},
            headers=user1_headers,
        )
        return resp.json()["id"]

    def test_cannot_add_member_to_private(self, client, user1_headers, setup_test_users):
        """Private konuşmaya üye eklenemez."""
        conv_id = self._get_private_conv_id(
            client, user1_headers, setup_test_users["user2_id"],
        )
        resp = client.post(
            f"/api/messages/conversations/{conv_id}/members",
            json={"user_ids": [setup_test_users["user3_id"]]},
            headers=user1_headers,
        )
        assert resp.status_code == 400

    def test_cannot_update_name_on_private(self, client, user1_headers, setup_test_users):
        """Private konuşmada ad değiştirilemez."""
        conv_id = self._get_private_conv_id(
            client, user1_headers, setup_test_users["user2_id"],
        )
        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/name",
            json={"name": "Private Ad"},
            headers=user1_headers,
        )
        assert resp.status_code == 400

    def test_cannot_change_admin_on_private(self, client, user1_headers, setup_test_users):
        """Private konuşmada admin değiştirilemez."""
        conv_id = self._get_private_conv_id(
            client, user1_headers, setup_test_users["user2_id"],
        )
        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/admins/{setup_test_users['user2_id']}",
            json={"is_admin": True},
            headers=user1_headers,
        )
        assert resp.status_code == 400


# ─── Kimlik Doğrulama Testleri ───────────────────────────────────────


class TestAuthentication:
    """Kimlik doğrulama olmadan erişim denemeleri."""

    def _anon_client(self):
        """Cookie'siz yeni TestClient — unauthenticated istekler için."""
        return TestClient(app)

    def test_conversations_unauthenticated(self, setup_test_users):
        resp = self._anon_client().get("/api/messages/conversations")
        assert resp.status_code in (401, 403)

    def test_send_message_unauthenticated(self, setup_test_users):
        resp = self._anon_client().post(
            "/api/messages/conversations/1",
            json={"content": "test"},
        )
        assert resp.status_code in (401, 403)

    def test_unread_count_unauthenticated(self, setup_test_users):
        resp = self._anon_client().get("/api/messages/unread-count")
        assert resp.status_code in (401, 403)

    def test_chat_users_unauthenticated(self, setup_test_users):
        resp = self._anon_client().get("/api/messages/users")
        assert resp.status_code in (401, 403)


# ─── Temizlik ─────────────────────────────────────────────────────────


@pytest.fixture(scope="module", autouse=True)
def cleanup_test_data(setup_test_users):
    """_module_transaction rollback ile temizlik otomatik yapılır."""
    yield
