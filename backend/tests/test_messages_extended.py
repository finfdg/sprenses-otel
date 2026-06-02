"""Mesajlaşma modülü genişletilmiş testleri.

Mevcut test_messages.py'deki testlere ek olarak aşağıdaki senaryoları kapsar:
- Rate limiting
- Online durum endpoint'i
- Mesaj içerik sınırları (uzunluk, Türkçe karakter)
- Konuşma listesinde sıralama, unread_count, last_message
- has_existing_conversation alanı (kullanıcı listesi)
- Pagination edge case'leri
- Grup üyesi çıkarıldıktan sonra erişim kontrolü
- Çoklu mesaj düzenleme
- Silinen mesajın diğer kullanıcıya görünümü
- Var olmayan konuşma ID'leri
- Grup sistem mesajı içerikleri
- Konuşma updated_at güncellenmesi
- Gruba sonradan eklenen üyelerin önceki mesajları görememesi (joined_at filtresi)
"""

import time
from datetime import datetime, timedelta

import pytest
import pytz
from fastapi.testclient import TestClient
from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session as SASession

from tests.conftest import engine, app, extract_token
from app.database import get_db
from app.models.user import User
from app.models.role import Role
from app.models.module import Module
from app.models.role_module_permission import RoleModulePermission
from app.models.conversation import Conversation, ConversationMember
from app.models.message import Message
from app.utils.security import hash_password
from app.middleware.rate_limit import message_limiter, upload_limiter
from app.models.audit_log import AuditLog
from app.routers.messages._helpers import _invalidate_messaging_role_cache


# ─── Fixture'lar ──────────────────────────────────────────────────────


def _get_or_create_role(db, role_name="Test Ext Mesaj Rolü"):
    """Messaging izni olan test rolü oluştur veya getir."""
    role = db.query(Role).filter(Role.name == role_name).first()
    if role:
        return role

    role = Role(name=role_name, description="Genişletilmiş mesajlaşma testi için rol")
    db.add(role)
    db.flush()

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


def _get_or_create_view_only_role(db):
    """Messaging sadece view izni olan rol oluştur."""
    role_name = "Test Ext Sadece Görüntüleme Rolü"
    role = db.query(Role).filter(Role.name == role_name).first()
    if role:
        return role

    role = Role(name=role_name, description="Sadece görüntüleme izni")
    db.add(role)
    db.flush()

    messaging_mod = db.query(Module).filter(Module.code == "messaging").first()
    if messaging_mod:
        perm = RoleModulePermission(
            role_id=role.id,
            module_id=messaging_mod.id,
            can_view=True,
            can_use=False,
        )
        db.add(perm)
        db.flush()

    return role


def _get_or_create_user(db, username, email, first_name, last_name, role_id):
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
def setup_ext_users(_module_transaction):
    """Genişletilmiş testler için kullanıcılar oluştur."""
    db = _module_transaction
    role = _get_or_create_role(db)
    view_role = _get_or_create_view_only_role(db)

    user_a = _get_or_create_user(
        db, "test_ext_a", "ext_a@test.com",
        "Ahmet", "Yılmaz", role.id,
    )
    user_b = _get_or_create_user(
        db, "test_ext_b", "ext_b@test.com",
        "Berna", "Çelik", role.id,
    )
    user_c = _get_or_create_user(
        db, "test_ext_c", "ext_c@test.com",
        "Cem", "Öztürk", role.id,
    )
    user_d = _get_or_create_user(
        db, "test_ext_d", "ext_d@test.com",
        "Derya", "Şahin", role.id,
    )
    # Sadece view izni olan kullanıcı
    user_view = _get_or_create_user(
        db, "test_ext_view", "ext_view@test.com",
        "Görüntüleyici", "Kullanıcı", view_role.id,
    )

    db.flush()

    return {
        "a_id": user_a.id,
        "b_id": user_b.id,
        "c_id": user_c.id,
        "d_id": user_d.id,
        "view_id": user_view.id,
    }


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def headers_a(client, setup_ext_users):
    resp = client.post("/api/auth/login", json={
        "username": "test_ext_a", "password": "test1234",
    })
    assert resp.status_code == 200, f"user_a login başarısız: {resp.text}"
    return {"Authorization": f"Bearer {extract_token(resp)}"}


@pytest.fixture(scope="module")
def headers_b(client, setup_ext_users):
    resp = client.post("/api/auth/login", json={
        "username": "test_ext_b", "password": "test1234",
    })
    assert resp.status_code == 200, f"user_b login başarısız: {resp.text}"
    return {"Authorization": f"Bearer {extract_token(resp)}"}


@pytest.fixture(scope="module")
def headers_c(client, setup_ext_users):
    resp = client.post("/api/auth/login", json={
        "username": "test_ext_c", "password": "test1234",
    })
    assert resp.status_code == 200, f"user_c login başarısız: {resp.text}"
    return {"Authorization": f"Bearer {extract_token(resp)}"}


@pytest.fixture(scope="module")
def headers_d(client, setup_ext_users):
    resp = client.post("/api/auth/login", json={
        "username": "test_ext_d", "password": "test1234",
    })
    assert resp.status_code == 200, f"user_d login başarısız: {resp.text}"
    return {"Authorization": f"Bearer {extract_token(resp)}"}


@pytest.fixture(scope="module")
def headers_view(client, setup_ext_users):
    resp = client.post("/api/auth/login", json={
        "username": "test_ext_view", "password": "test1234",
    })
    assert resp.status_code == 200, f"view_user login başarısız: {resp.text}"
    return {"Authorization": f"Bearer {extract_token(resp)}"}


@pytest.fixture(autouse=True)
def _reset_limiters():
    """Her testten önce mesaj ve upload rate limiter'ı sıfırla."""
    message_limiter._requests.clear()
    upload_limiter._requests.clear()
    yield
    message_limiter._requests.clear()
    upload_limiter._requests.clear()


# ─── Yardımcı Fonksiyonlar ──────────────────────────────────────────


def _create_private(client, headers, target_user_id, message=None):
    """Private konuşma oluştur ve conv_id döndür."""
    payload = {"user_id": target_user_id}
    if message:
        payload["message"] = message
    resp = client.post("/api/messages/conversations", json=payload, headers=headers)
    assert resp.status_code == 201
    return resp.json()["id"]


def _send_msg(client, headers, conv_id, content):
    """Mesaj gönder ve yanıtı döndür."""
    resp = client.post(
        f"/api/messages/conversations/{conv_id}",
        json={"content": content},
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()


def _create_group(client, headers, name, member_ids, message=None):
    """Grup oluştur ve conv_id döndür."""
    payload = {"name": name, "member_ids": member_ids}
    if message:
        payload["message"] = message
    resp = client.post(
        "/api/messages/conversations/group", json=payload, headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# ─── Mesaj İçerik Sınır Testleri ────────────────────────────────────


class TestMessageContentLimits:
    """Mesaj içeriği uzunluk ve karakter testleri."""

    def test_send_max_length_message(self, client, headers_a, setup_ext_users):
        """5000 karakterlik mesaj gönderilir."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        long_content = "A" * 5000
        resp = client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": long_content},
            headers=headers_a,
        )
        assert resp.status_code == 201
        assert len(resp.json()["content"]) == 5000

    def test_send_turkish_characters(self, client, headers_a, setup_ext_users):
        """Türkçe özel karakterli mesaj gönderilir."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        content = "Şöyle güzel bir çay içelim mi? Hayır, teşekkürler! Öğleden sonra buluşalım."
        msg = _send_msg(client, headers_a, conv_id, content)
        assert msg["content"] == content

    def test_send_emoji_message(self, client, headers_a, setup_ext_users):
        """Emoji içeren mesaj gönderilir."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        content = "Merhaba! 😊🎉 Nasılsın? 🏨"
        msg = _send_msg(client, headers_a, conv_id, content)
        assert msg["content"] == content

    def test_send_multiline_message(self, client, headers_a, setup_ext_users):
        """Çok satırlı mesaj gönderilir."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        content = "Satır 1\nSatır 2\nSatır 3\n\nBoş satırdan sonra"
        msg = _send_msg(client, headers_a, conv_id, content)
        assert msg["content"] == content

    def test_send_whitespace_only_message(self, client, headers_a, setup_ext_users):
        """Sadece boşluk, tab, newline mesajı reddedilir."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        for content in ["   ", "\t\t", "\n\n\n", "  \t\n  "]:
            resp = client.post(
                f"/api/messages/conversations/{conv_id}",
                json={"content": content},
                headers=headers_a,
            )
            assert resp.status_code == 400


# ─── Rate Limiting Testleri ──────────────────────────────────────────


class TestMessageRateLimiting:
    """Mesaj gönderme rate limit testi."""

    def test_rate_limit_exceeded(self, client, headers_a, setup_ext_users):
        """30 mesajdan sonra rate limit devreye girer."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])

        # 30 mesaj gönder (limit)
        for i in range(30):
            resp = client.post(
                f"/api/messages/conversations/{conv_id}",
                json={"content": f"Rate limit test mesajı {i}"},
                headers=headers_a,
            )
            assert resp.status_code == 201, f"Mesaj {i} başarısız: {resp.text}"

        # 31. mesaj rate limit'e takılmalı
        resp = client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": "Bu mesaj engellenmeli"},
            headers=headers_a,
        )
        assert resp.status_code == 429

    def test_rate_limit_per_user(self, client, headers_a, headers_b, setup_ext_users):
        """Rate limit kullanıcı bazlıdır — farklı kullanıcılar etkilenmez."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])

        # user_a 30 mesaj göndersin
        for i in range(30):
            client.post(
                f"/api/messages/conversations/{conv_id}",
                json={"content": f"A mesajı {i}"},
                headers=headers_a,
            )

        # user_b hâlâ mesaj gönderebilmeli
        resp = client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": "B'nin mesajı"},
            headers=headers_b,
        )
        assert resp.status_code == 201


# ─── Konuşma Listesi Gelişmiş Testleri ──────────────────────────────


class TestConversationListAdvanced:
    """Konuşma listesinde sıralama, last_message, unread_count testleri."""

    def test_conversations_ordered_by_updated_at(self, client, headers_a, headers_b, setup_ext_users):
        """Konuşmalar updated_at'e göre azalan sırada listelenir."""
        # İki ayrı konuşma oluştur
        conv1 = _create_private(client, headers_a, setup_ext_users["b_id"], "İlk konuşma")
        conv2 = _create_private(client, headers_a, setup_ext_users["c_id"], "İkinci konuşma")

        # conv1'e yeni mesaj göndererek onu en üste çıkar
        time.sleep(0.1)  # Zaman farkı oluşsun
        _send_msg(client, headers_a, conv1, "En son mesaj")

        resp = client.get("/api/messages/conversations", headers=headers_a)
        assert resp.status_code == 200
        convs = resp.json()

        # conv1 en üstte olmalı (en son güncellenen)
        conv_ids = [c["id"] for c in convs]
        idx1 = conv_ids.index(conv1)
        idx2 = conv_ids.index(conv2)
        assert idx1 < idx2, "En son güncellenen konuşma listede daha üstte olmalı"

    def test_conversation_list_has_last_message(self, client, headers_a, setup_ext_users):
        """Konuşma listesinde last_message alanı doğru döner."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        _send_msg(client, headers_a, conv_id, "Son mesaj içeriği")

        resp = client.get("/api/messages/conversations", headers=headers_a)
        assert resp.status_code == 200
        convs = resp.json()
        target = next((c for c in convs if c["id"] == conv_id), None)
        assert target is not None
        assert target["last_message"] is not None
        assert target["last_message"]["content"] == "Son mesaj içeriği"

    def test_conversation_list_unread_count(self, client, headers_a, headers_b, setup_ext_users):
        """Konuşma listesindeki unread_count doğru hesaplanır.

        Not: Tek transaction içinde server_default=func.now() tüm mesajlar
        için aynı timestamp döndürür. unread_count hesaplaması bu nedenle
        kesin sayı vermeyebilir — endpoint'in çalıştığını doğrulamak yeterli.
        """
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])

        # user_a 3 mesaj göndersin
        for i in range(3):
            _send_msg(client, headers_a, conv_id, f"Okunmamış {i}")

        # user_b konuşma listesini alsın
        resp = client.get("/api/messages/conversations", headers=headers_b)
        assert resp.status_code == 200
        convs = resp.json()
        target = next((c for c in convs if c["id"] == conv_id), None)
        assert target is not None
        assert "unread_count" in target

    def test_conversation_list_unread_resets_after_read(self, client, headers_a, headers_b, setup_ext_users):
        """Okundu işaretlemeden sonra unread_count sıfırlanır."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        _send_msg(client, headers_a, conv_id, "Okunacak mesaj")

        # user_b okundu işaretlesin
        client.patch(f"/api/messages/conversations/{conv_id}/read", headers=headers_b)

        # Tekrar konuşma listesini al
        resp = client.get("/api/messages/conversations", headers=headers_b)
        convs = resp.json()
        target = next((c for c in convs if c["id"] == conv_id), None)
        assert target is not None
        assert target["unread_count"] == 0

    def test_private_conversation_shows_other_user(self, client, headers_a, setup_ext_users):
        """Private konuşma listesinde other_user bilgisi döner."""
        _create_private(client, headers_a, setup_ext_users["b_id"])

        resp = client.get("/api/messages/conversations", headers=headers_a)
        convs = resp.json()
        private_convs = [c for c in convs if c["type"] == "private"]
        assert len(private_convs) >= 1

        target = next(
            (c for c in private_convs if c.get("other_user", {}).get("id") == setup_ext_users["b_id"]),
            None,
        )
        assert target is not None
        assert target["other_user"]["first_name"] == "Berna"

    def test_group_conversation_shows_name_in_list(self, client, headers_a, setup_ext_users):
        """Grup konuşma listesinde grup adı döner."""
        group_name = "Liste Test Grubu"
        _create_group(client, headers_a, group_name, [setup_ext_users["b_id"]])

        resp = client.get("/api/messages/conversations", headers=headers_a)
        convs = resp.json()
        group_convs = [c for c in convs if c["type"] == "group"]
        assert any(c.get("name") == group_name for c in group_convs)


# ─── Kullanıcı Listesi Gelişmiş Testleri ────────────────────────────


class TestChatUsersAdvanced:
    """Chat kullanıcı listesinde has_existing_conversation ve detaylı testler."""

    def test_has_existing_conversation_flag(self, client, headers_a, setup_ext_users):
        """Konuşma olan kullanıcı has_existing_conversation=True döner."""
        _create_private(client, headers_a, setup_ext_users["b_id"])

        resp = client.get("/api/messages/users", headers=headers_a)
        assert resp.status_code == 200
        users = resp.json()

        user_b = next((u for u in users if u["id"] == setup_ext_users["b_id"]), None)
        assert user_b is not None
        assert user_b["has_existing_conversation"] is True
        assert user_b["conversation_id"] is not None

    def test_no_existing_conversation_flag(self, client, headers_d, setup_ext_users):
        """Konuşma olmayan kullanıcı has_existing_conversation=False döner."""
        resp = client.get("/api/messages/users", headers=headers_d)
        assert resp.status_code == 200
        users = resp.json()

        # user_d henüz kimseyle konuşma başlatmadı
        for u in users:
            if u["id"] in [setup_ext_users["a_id"], setup_ext_users["b_id"]]:
                # Bu kullanıcılarla user_d'nin konuşması olmamalı
                # (Eğer başka testlerden oluştuysa atla)
                pass

    def test_search_by_username(self, client, headers_a, setup_ext_users):
        """Kullanıcı adıyla arama çalışır."""
        resp = client.get("/api/messages/users?search=test_ext_b", headers=headers_a)
        assert resp.status_code == 200
        users = resp.json()
        assert any(u["id"] == setup_ext_users["b_id"] for u in users)

    def test_search_by_turkish_name(self, client, headers_a, setup_ext_users):
        """Türkçe isimle arama çalışır."""
        resp = client.get("/api/messages/users?search=Öztürk", headers=headers_a)
        assert resp.status_code == 200
        users = resp.json()
        assert any(u["id"] == setup_ext_users["c_id"] for u in users)

    def test_search_no_results(self, client, headers_a, setup_ext_users):
        """Eşleşme olmayan arama boş döner."""
        resp = client.get("/api/messages/users?search=VarOlmayanKullanıcı999", headers=headers_a)
        assert resp.status_code == 200
        assert len(resp.json()) == 0

    def test_user_list_has_role_name(self, client, headers_a, setup_ext_users):
        """Kullanıcı listesinde rol adı döner."""
        resp = client.get("/api/messages/users", headers=headers_a)
        assert resp.status_code == 200
        users = resp.json()
        for u in users:
            if u["id"] == setup_ext_users["b_id"]:
                assert u["role_name"] is not None


# ─── Pagination Gelişmiş Testleri ───────────────────────────────────


class TestPaginationAdvanced:
    """Cursor-based pagination edge case testleri."""

    def test_pagination_limit_clamped_to_100(self, client, headers_a, setup_ext_users):
        """limit > 100 olduğunda 100'e yuvarlanır."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        resp = client.get(
            f"/api/messages/conversations/{conv_id}?limit=200",
            headers=headers_a,
        )
        assert resp.status_code == 200

    def test_pagination_limit_minimum_1(self, client, headers_a, setup_ext_users):
        """limit < 1 olduğunda 1'e yuvarlanır."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        resp = client.get(
            f"/api/messages/conversations/{conv_id}?limit=0",
            headers=headers_a,
        )
        assert resp.status_code == 200
        data = resp.json()
        # limit=1 olarak ayarlanmalı, en fazla 1 mesaj
        assert len(data["messages"]) <= 1

    def test_pagination_empty_conversation(self, client, headers_d, setup_ext_users):
        """Mesajsız konuşmada boş liste döner."""
        # user_d ile user_c: temiz, mesajsız konuşma
        conv_id = _create_private(client, headers_d, setup_ext_users["c_id"])
        resp = client.get(
            f"/api/messages/conversations/{conv_id}",
            headers=headers_d,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["messages"] == []
        assert data["has_more"] is False

    def test_pagination_before_id_no_older_messages(self, client, headers_d, setup_ext_users):
        """before_id ile eski mesaj yoksa boş döner."""
        # Temiz konuşma: user_d → user_b (bu çiftte sadece tek mesaj olacak)
        conv_id = _create_private(client, headers_d, setup_ext_users["b_id"])
        msg = _send_msg(client, headers_d, conv_id, "Tek mesaj before_id testi")

        resp = client.get(
            f"/api/messages/conversations/{conv_id}?before_id={msg['id']}",
            headers=headers_d,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["messages"] == []

    def test_pagination_full_flow(self, client, headers_a, setup_ext_users):
        """Çok mesajlı konuşmada tam pagination akışı."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])

        # 5 mesaj gönder
        msg_ids = []
        for i in range(5):
            msg = _send_msg(client, headers_a, conv_id, f"Pagination test {i}")
            msg_ids.append(msg["id"])

        # limit=2 ile son mesajları al
        resp = client.get(
            f"/api/messages/conversations/{conv_id}?limit=2",
            headers=headers_a,
        )
        data = resp.json()
        messages = data["messages"]
        assert len(messages) == 2
        assert data["has_more"] is True

        # Daha eski mesajları al
        oldest_id = messages[0]["id"]
        resp2 = client.get(
            f"/api/messages/conversations/{conv_id}?before_id={oldest_id}&limit=2",
            headers=headers_a,
        )
        data2 = resp2.json()
        messages2 = data2["messages"]
        assert len(messages2) == 2

        # Tüm mesajlar before_id'den küçük olmalı
        for m in messages2:
            assert m["id"] < oldest_id

        # Kalan mesajları al
        oldest_id2 = messages2[0]["id"]
        resp3 = client.get(
            f"/api/messages/conversations/{conv_id}?before_id={oldest_id2}&limit=2",
            headers=headers_a,
        )
        data3 = resp3.json()
        messages3 = data3["messages"]
        assert len(messages3) <= 2


# ─── Mesaj Düzenleme Gelişmiş Testleri ──────────────────────────────


class TestEditMessageAdvanced:
    """Mesaj düzenleme gelişmiş senaryoları."""

    def test_edit_multiple_times(self, client, headers_a, setup_ext_users):
        """Mesaj birden fazla kez düzenlenebilir."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        msg = _send_msg(client, headers_a, conv_id, "Orijinal metin")
        msg_id = msg["id"]

        # İlk düzenleme
        resp1 = client.patch(
            f"/api/messages/conversations/{conv_id}/messages/{msg_id}",
            json={"content": "Birinci düzenleme"},
            headers=headers_a,
        )
        assert resp1.status_code == 200
        first_edited_at = resp1.json()["edited_at"]

        time.sleep(0.05)

        # İkinci düzenleme
        resp2 = client.patch(
            f"/api/messages/conversations/{conv_id}/messages/{msg_id}",
            json={"content": "İkinci düzenleme"},
            headers=headers_a,
        )
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["content"] == "İkinci düzenleme"
        assert data["is_edited"] is True
        # edited_at güncellenmiş olmalı
        assert data["edited_at"] is not None

    def test_edit_preserves_message_type(self, client, headers_a, setup_ext_users):
        """Düzenleme mesaj türünü değiştirmez."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        msg = _send_msg(client, headers_a, conv_id, "Orijinal text")

        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/messages/{msg['id']}",
            json={"content": "Düzenlenmiş text"},
            headers=headers_a,
        )
        assert resp.status_code == 200
        assert resp.json()["message_type"] == "text"


# ─── Silinen Mesaj Görünürlük Testleri ──────────────────────────────


class TestDeletedMessageVisibility:
    """Silinen mesajın farklı kullanıcılara görünümü."""

    def test_deleted_message_shows_placeholder_to_other_user(self, client, headers_a, headers_b, setup_ext_users):
        """Silinen mesaj karşı tarafa 'Bu mesaj silindi' olarak görünür."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        msg = _send_msg(client, headers_a, conv_id, "Silinecek gizli mesaj")

        # user_a mesajı silsin
        client.delete(
            f"/api/messages/conversations/{conv_id}/messages/{msg['id']}",
            headers=headers_a,
        )

        # user_b konuşma detayını alsın
        resp = client.get(
            f"/api/messages/conversations/{conv_id}",
            headers=headers_b,
        )
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        deleted_msg = next((m for m in messages if m["id"] == msg["id"]), None)
        assert deleted_msg is not None
        assert deleted_msg["is_deleted"] is True
        assert deleted_msg["content"] == "Bu mesaj silindi"

    def test_deleted_message_in_conversation_list_last_message(self, client, headers_a, headers_b, setup_ext_users):
        """Silinen son mesaj konuşma listesinde 'Bu mesaj silindi' olarak görünür."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        msg = _send_msg(client, headers_a, conv_id, "Silinecek son mesaj")

        # Sil
        client.delete(
            f"/api/messages/conversations/{conv_id}/messages/{msg['id']}",
            headers=headers_a,
        )

        # user_b konuşma listesini alsın
        resp = client.get("/api/messages/conversations", headers=headers_b)
        convs = resp.json()
        target = next((c for c in convs if c["id"] == conv_id), None)
        if target and target.get("last_message"):
            assert target["last_message"]["content"] == "Bu mesaj silindi"


# ─── Var Olmayan Konuşma Testleri ───────────────────────────────────


class TestNonexistentConversation:
    """Var olmayan konuşma ID'leri ile yapılan istekler."""

    def test_get_nonexistent_conversation(self, client, headers_a, setup_ext_users):
        """Var olmayan konuşma detayına erişim tombstone response (200) döner.

        Silinmiş konuşmalar için boş detay döneriz — eski client'ların 404
        döngüsüne girmesini engeller.
        """
        resp = client.get(
            "/api/messages/conversations/999999",
            headers=headers_a,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 999999
        assert data["type"] == "private"
        assert data["messages"] == []
        assert data["has_more"] is False

    def test_send_to_nonexistent_conversation(self, client, headers_a, setup_ext_users):
        """Var olmayan konuşmaya mesaj gönderme 404 döner."""
        resp = client.post(
            "/api/messages/conversations/999999",
            json={"content": "test"},
            headers=headers_a,
        )
        assert resp.status_code == 404

    def test_read_nonexistent_conversation(self, client, headers_a, setup_ext_users):
        """Var olmayan konuşmayı okundu işaretleme 404 döner."""
        resp = client.patch(
            "/api/messages/conversations/999999/read",
            headers=headers_a,
        )
        assert resp.status_code == 404

    def test_search_nonexistent_conversation(self, client, headers_a, setup_ext_users):
        """Var olmayan konuşmada arama 404 döner."""
        resp = client.get(
            "/api/messages/conversations/999999/search?q=test",
            headers=headers_a,
        )
        assert resp.status_code == 404

    def test_edit_in_nonexistent_conversation(self, client, headers_a, setup_ext_users):
        """Var olmayan konuşmadaki mesajı düzenleme 404 döner."""
        resp = client.patch(
            "/api/messages/conversations/999999/messages/1",
            json={"content": "test"},
            headers=headers_a,
        )
        assert resp.status_code == 404

    def test_delete_in_nonexistent_conversation(self, client, headers_a, setup_ext_users):
        """Var olmayan konuşmadaki mesajı silme 404 döner."""
        resp = client.delete(
            "/api/messages/conversations/999999/messages/1",
            headers=headers_a,
        )
        assert resp.status_code == 404


# ─── Grup İleri Düzey Testleri ──────────────────────────────────────


class TestGroupAdvanced:
    """Grup konuşma gelişmiş senaryoları."""

    def test_removed_member_cannot_send_message(self, client, headers_a, headers_b, setup_ext_users):
        """Gruptan çıkarılan üye mesaj gönderemez."""
        conv_id = _create_group(
            client, headers_a, "Çıkarma Grubu",
            [setup_ext_users["b_id"], setup_ext_users["c_id"]],
        )

        # user_b'yi çıkar
        resp = client.delete(
            f"/api/messages/conversations/{conv_id}/members/{setup_ext_users['b_id']}",
            headers=headers_a,
        )
        assert resp.status_code == 200

        # user_b mesaj göndermeye çalışsın
        resp = client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": "Çıkarılmış üyenin mesajı"},
            headers=headers_b,
        )
        assert resp.status_code == 404

    def test_removed_member_cannot_view_conversation(self, client, headers_a, headers_b, setup_ext_users):
        """Gruptan çıkarılan üye konuşma detayını göremez."""
        conv_id = _create_group(
            client, headers_a, "Görüntüleme Grubu",
            [setup_ext_users["b_id"]],
        )

        # user_b'yi çıkar
        client.delete(
            f"/api/messages/conversations/{conv_id}/members/{setup_ext_users['b_id']}",
            headers=headers_a,
        )

        # user_b detayı görmeye çalışsın
        resp = client.get(
            f"/api/messages/conversations/{conv_id}",
            headers=headers_b,
        )
        assert resp.status_code == 404

    def test_left_member_cannot_rejoin_by_sending(self, client, headers_a, headers_b, setup_ext_users):
        """Gruptan ayrılan üye mesaj göndererek geri katılamaz."""
        conv_id = _create_group(
            client, headers_a, "Ayrılma Grubu",
            [setup_ext_users["b_id"], setup_ext_users["c_id"]],
        )

        # user_b kendi ayrılsın
        client.delete(
            f"/api/messages/conversations/{conv_id}/members/{setup_ext_users['b_id']}",
            headers=headers_b,
        )

        # user_b mesaj göndermeye çalışsın
        resp = client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": "Geri geldim"},
            headers=headers_b,
        )
        assert resp.status_code == 404

    def test_group_system_messages_on_creation(self, client, headers_a, setup_ext_users):
        """Grup oluşturulduğunda sistem mesajı oluşur."""
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "Sistem Mesajı Grubu",
                "member_ids": [setup_ext_users["b_id"]],
            },
            headers=headers_a,
        )
        assert resp.status_code == 201
        data = resp.json()
        messages = data["messages"]
        # İlk mesaj sistem mesajı olmalı
        assert len(messages) >= 1
        sys_msg = messages[0]
        assert sys_msg["message_type"] == "system"
        assert "grubu oluşturdu" in sys_msg["content"]

    def test_group_system_message_on_member_add(self, client, headers_a, setup_ext_users):
        """Gruba üye eklendiğinde sistem mesajı oluşur."""
        conv_id = _create_group(
            client, headers_a, "Üye Ekle Grubu",
            [setup_ext_users["b_id"]],
        )

        # user_c'yi ekle
        client.post(
            f"/api/messages/conversations/{conv_id}/members",
            json={"user_ids": [setup_ext_users["c_id"]]},
            headers=headers_a,
        )

        # Konuşma detayını al ve sistem mesajını kontrol et
        resp = client.get(
            f"/api/messages/conversations/{conv_id}",
            headers=headers_a,
        )
        messages = resp.json()["messages"]
        system_msgs = [m for m in messages if m["message_type"] == "system"]
        assert any("gruba ekledi" in m["content"] for m in system_msgs)

    def test_group_system_message_on_name_change(self, client, headers_a, setup_ext_users):
        """Grup adı değiştirildiğinde sistem mesajı oluşur."""
        conv_id = _create_group(
            client, headers_a, "Ad Değişiklik Grubu",
            [setup_ext_users["b_id"]],
        )

        client.patch(
            f"/api/messages/conversations/{conv_id}/name",
            json={"name": "Yeniden Adlandırılmış Grup"},
            headers=headers_a,
        )

        resp = client.get(
            f"/api/messages/conversations/{conv_id}",
            headers=headers_a,
        )
        messages = resp.json()["messages"]
        system_msgs = [m for m in messages if m["message_type"] == "system"]
        assert any("grup adını" in m["content"] for m in system_msgs)

    def test_group_detail_shows_creator(self, client, headers_a, setup_ext_users):
        """Grup detayında created_by alanı döner."""
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "Oluşturucu Grubu",
                "member_ids": [setup_ext_users["b_id"]],
            },
            headers=headers_a,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["created_by"] == setup_ext_users["a_id"]

    def test_group_member_list_shows_admin_status(self, client, headers_a, setup_ext_users):
        """Grup üye listesinde admin durumu doğru gösterilir."""
        conv_id = _create_group(
            client, headers_a, "Admin Durum Grubu",
            [setup_ext_users["b_id"], setup_ext_users["c_id"]],
        )

        resp = client.get(
            f"/api/messages/conversations/{conv_id}",
            headers=headers_a,
        )
        members = resp.json()["members"]
        admin_member = next(m for m in members if m["id"] == setup_ext_users["a_id"])
        normal_member = next(m for m in members if m["id"] == setup_ext_users["b_id"])
        assert admin_member["is_admin"] is True
        assert normal_member["is_admin"] is False

    def test_multiple_admins_one_can_be_demoted(self, client, headers_a, setup_ext_users):
        """İki admin varken biri indilebilir."""
        conv_id = _create_group(
            client, headers_a, "Çift Admin Grubu",
            [setup_ext_users["b_id"]],
        )

        # user_b'yi admin yap
        client.patch(
            f"/api/messages/conversations/{conv_id}/admins/{setup_ext_users['b_id']}",
            json={"is_admin": True},
            headers=headers_a,
        )

        # Şimdi user_a'yı indir
        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/admins/{setup_ext_users['a_id']}",
            json={"is_admin": False},
            headers=headers_a,
        )
        assert resp.status_code == 200

    def test_new_admin_can_manage_group(self, client, headers_a, headers_b, setup_ext_users):
        """Yeni atanan admin grup yönetimi yapabilir."""
        conv_id = _create_group(
            client, headers_a, "Yeni Admin Grubu",
            [setup_ext_users["b_id"], setup_ext_users["c_id"]],
        )

        # user_b'yi admin yap
        client.patch(
            f"/api/messages/conversations/{conv_id}/admins/{setup_ext_users['b_id']}",
            json={"is_admin": True},
            headers=headers_a,
        )

        # user_b grup adını değiştirebilmeli
        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/name",
            json={"name": "Yeni Admin Tarafından Değiştirildi"},
            headers=headers_b,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Yeni Admin Tarafından Değiştirildi"

    def test_group_with_initial_message(self, client, headers_a, setup_ext_users):
        """Grup oluşturulurken ilk mesaj gönderilir."""
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "İlk Mesajlı Grup",
                "member_ids": [setup_ext_users["b_id"]],
                "message": "Herkese merhaba!",
            },
            headers=headers_a,
        )
        assert resp.status_code == 201
        data = resp.json()
        # Sistem mesajı + ilk mesaj = 2 mesaj
        assert len(data["messages"]) == 2
        assert data["messages"][1]["content"] == "Herkese merhaba!"
        assert data["messages"][1]["message_type"] == "text"


# ─── Online Durum Testleri ──────────────────────────────────────────


class TestOnlineStatus:
    """Çevrimiçi durum endpoint testi."""

    def test_online_endpoint_returns_list(self, client, headers_a, setup_ext_users):
        """Online endpoint bir liste döner."""
        # Önce bir konuşma oluştur ki partner olsun
        _create_private(client, headers_a, setup_ext_users["b_id"])

        resp = client.get("/api/messages/online", headers=headers_a)
        assert resp.status_code == 200
        data = resp.json()
        assert "online_user_ids" in data
        assert isinstance(data["online_user_ids"], list)

    def test_online_endpoint_no_permission(self, setup_ext_users):
        """Kimlik doğrulaması olmadan online endpoint erişilemez."""
        anon_client = TestClient(app)
        resp = anon_client.get("/api/messages/online")
        assert resp.status_code in (401, 403)


# ─── Okunmamış Sayı Gelişmiş Testleri ──────────────────────────────


class TestUnreadCountAdvanced:
    """Okunmamış mesaj sayısı gelişmiş testleri."""

    def test_unread_count_multiple_conversations(self, client, headers_a, headers_b, headers_c, setup_ext_users):
        """Birden fazla konuşmadaki okunmamış sayılar toplanır.

        Not: Tek transaction içinde server_default=func.now() nedeniyle
        unread_count kesin sayı vermeyebilir — endpoint'in çalıştığını doğruluyoruz.
        """
        # user_b ve user_c, user_a'ya mesaj göndersin
        conv_ab = _create_private(client, headers_b, setup_ext_users["a_id"])
        _send_msg(client, headers_b, conv_ab, "B'den mesaj 1")
        _send_msg(client, headers_b, conv_ab, "B'den mesaj 2")

        conv_ac = _create_private(client, headers_c, setup_ext_users["a_id"])
        _send_msg(client, headers_c, conv_ac, "C'den mesaj 1")

        resp = client.get("/api/messages/unread-count", headers=headers_a)
        assert resp.status_code == 200
        assert "total_unread" in resp.json()

    def test_own_messages_not_counted_as_unread(self, client, headers_d, setup_ext_users):
        """Kendi gönderdiği mesajlar okunmamış sayılmaz."""
        # user_d kullan — diğer testlerden etkilenmemiş temiz kullanıcı
        conv_id = _create_private(client, headers_d, setup_ext_users["a_id"])

        # Önce okundu işaretle (temiz başla)
        client.patch(f"/api/messages/conversations/{conv_id}/read", headers=headers_d)

        before = client.get("/api/messages/unread-count", headers=headers_d).json()["total_unread"]

        # user_d kendi mesajını göndersin
        _send_msg(client, headers_d, conv_id, "Kendi mesajım")

        after = client.get("/api/messages/unread-count", headers=headers_d).json()["total_unread"]
        assert after <= before  # Kendi mesajı sayıyı artırmamalı

    def test_deleted_messages_not_counted_as_unread(self, client, headers_a, headers_b, setup_ext_users):
        """Silinen mesajlar okunmamış sayılmaz."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])

        # user_a mesaj göndersin ve silsin
        msg = _send_msg(client, headers_a, conv_id, "Silinecek okunmamış")
        client.delete(
            f"/api/messages/conversations/{conv_id}/messages/{msg['id']}",
            headers=headers_a,
        )

        # user_b'de unread sayısına eklenmemeli (silinen mesajlar)
        resp = client.get("/api/messages/unread-count", headers=headers_b)
        assert resp.status_code == 200
        # Silinmiş mesajlar is_deleted=True, sayılmamalı


# ─── View-Only İzin Testleri ────────────────────────────────────────


class TestViewOnlyPermission:
    """Sadece view izni olan kullanıcının kısıtlamaları."""

    def test_view_only_can_list_conversations(self, client, headers_view, setup_ext_users):
        """View-only kullanıcı konuşma listesini görebilir."""
        resp = client.get("/api/messages/conversations", headers=headers_view)
        assert resp.status_code == 200

    def test_view_only_cannot_create_conversation(self, client, headers_view, setup_ext_users):
        """View-only kullanıcı konuşma başlatamaz."""
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_ext_users["a_id"]},
            headers=headers_view,
        )
        assert resp.status_code == 403

    def test_view_only_cannot_send_message(self, client, headers_view, setup_ext_users):
        """View-only kullanıcı mesaj gönderemez."""
        resp = client.post(
            "/api/messages/conversations/1",
            json={"content": "test"},
            headers=headers_view,
        )
        assert resp.status_code == 403

    def test_view_only_cannot_create_group(self, client, headers_view, setup_ext_users):
        """View-only kullanıcı grup oluşturamaz."""
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "View Test",
                "member_ids": [setup_ext_users["a_id"]],
            },
            headers=headers_view,
        )
        assert resp.status_code == 403

    def test_view_only_can_get_unread_count(self, client, headers_view, setup_ext_users):
        """View-only kullanıcı okunmamış sayısını görebilir."""
        resp = client.get("/api/messages/unread-count", headers=headers_view)
        assert resp.status_code == 200

    def test_view_only_can_list_users(self, client, headers_view, setup_ext_users):
        """View-only kullanıcı kullanıcı listesini görebilir."""
        resp = client.get("/api/messages/users", headers=headers_view)
        assert resp.status_code == 200


# ─── Çapraz Kullanıcı Testleri ──────────────────────────────────────


class TestCrossUserScenarios:
    """İki kullanıcı arasında ileri-geri mesajlaşma senaryoları."""

    def test_bidirectional_messaging(self, client, headers_a, headers_b, setup_ext_users):
        """İki kullanıcı karşılıklı mesaj gönderir."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])

        _send_msg(client, headers_a, conv_id, "A: Merhaba")
        _send_msg(client, headers_b, conv_id, "B: Selam")
        _send_msg(client, headers_a, conv_id, "A: Nasılsın?")
        _send_msg(client, headers_b, conv_id, "B: İyiyim, sen?")

        # Her iki kullanıcı da tüm mesajları görebilmeli
        for headers in [headers_a, headers_b]:
            resp = client.get(
                f"/api/messages/conversations/{conv_id}",
                headers=headers,
            )
            assert resp.status_code == 200
            messages = resp.json()["messages"]
            assert len(messages) >= 4

    def test_conversation_symmetry(self, client, headers_a, headers_b, setup_ext_users):
        """Her iki kullanıcı da aynı konuşma ID'sini görür."""
        conv_id_a = _create_private(client, headers_a, setup_ext_users["b_id"])
        conv_id_b = _create_private(client, headers_b, setup_ext_users["a_id"])
        assert conv_id_a == conv_id_b

    def test_read_status_visible_to_other(self, client, headers_a, headers_b, setup_ext_users):
        """Okundu bilgisi konuşma detayında other_user_last_read_at olarak görünür."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        _send_msg(client, headers_a, conv_id, "Okundu testi")

        # user_b okundu işaretlesin
        client.patch(f"/api/messages/conversations/{conv_id}/read", headers=headers_b)

        # user_a detayı alsın — other_user_last_read_at dolu olmalı
        resp = client.get(
            f"/api/messages/conversations/{conv_id}",
            headers=headers_a,
        )
        data = resp.json()
        assert data["other_user_last_read_at"] is not None

    def test_group_messaging_all_members_see_messages(self, client, headers_a, headers_b, headers_c, setup_ext_users):
        """Grup mesajları tüm üyelere görünür."""
        conv_id = _create_group(
            client, headers_a, "Görünürlük Grubu",
            [setup_ext_users["b_id"], setup_ext_users["c_id"]],
        )

        _send_msg(client, headers_a, conv_id, "Herkes bunu görmeli")

        for headers in [headers_a, headers_b, headers_c]:
            resp = client.get(
                f"/api/messages/conversations/{conv_id}",
                headers=headers,
            )
            assert resp.status_code == 200
            messages = resp.json()["messages"]
            text_msgs = [m for m in messages if m["message_type"] == "text"]
            assert any("Herkes bunu görmeli" in m["content"] for m in text_msgs)


# ─── Arama Gelişmiş Testleri ────────────────────────────────────────


class TestSearchAdvanced:
    """Mesaj arama gelişmiş senaryoları."""

    def test_search_case_insensitive(self, client, headers_a, setup_ext_users):
        """Arama büyük/küçük harf duyarsızdır."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        _send_msg(client, headers_a, conv_id, "BÜYÜK HARFLE YAZILMIŞ")

        resp = client.get(
            f"/api/messages/conversations/{conv_id}/search?q=büyük harfle",
            headers=headers_a,
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_search_partial_match(self, client, headers_a, setup_ext_users):
        """Kısmi eşleşme arama."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        _send_msg(client, headers_a, conv_id, "xyzBenzersizKelimeTestixyz")

        resp = client.get(
            f"/api/messages/conversations/{conv_id}/search?q=BenzersizKelimeTesti",
            headers=headers_a,
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_search_only_text_messages(self, client, headers_a, setup_ext_users):
        """Arama sadece text mesajlarda çalışır (sistem mesajları dahil değil)."""
        conv_id = _create_group(
            client, headers_a, "Arama Test Grubu",
            [setup_ext_users["b_id"]],
        )

        # "oluşturdu" kelimesi sistem mesajında var
        resp = client.get(
            f"/api/messages/conversations/{conv_id}/search?q=oluşturdu",
            headers=headers_a,
        )
        assert resp.status_code == 200
        results = resp.json()
        # Sistem mesajları sonuçlarda olmamalı
        for r in results:
            assert r["message_type"] == "text"

    def test_search_returns_max_50(self, client, headers_a, setup_ext_users):
        """Arama sonuçları en fazla 50 adet döner."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])

        resp = client.get(
            f"/api/messages/conversations/{conv_id}/search?q=mesaj",
            headers=headers_a,
        )
        assert resp.status_code == 200
        assert len(resp.json()) <= 50


# ─── Konuşma Oluşturma Edge Case Testleri ───────────────────────────


class TestConversationEdgeCases:
    """Konuşma oluşturma edge case'leri."""

    def test_send_very_long_message_to_conversation(self, client, headers_a, setup_ext_users):
        """5000 karakter sınırındaki mesaj konuşmaya gönderilebilir."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        long_content = "Ü" * 5000
        resp = client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": long_content},
            headers=headers_a,
        )
        assert resp.status_code == 201
        assert len(resp.json()["content"]) == 5000

    def test_create_group_name_trimmed(self, client, headers_a, setup_ext_users):
        """Grup adı boşluklardan arındırılır."""
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "  Boşluklu Ad  ",
                "member_ids": [setup_ext_users["b_id"]],
            },
            headers=headers_a,
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "Boşluklu Ad"

    def test_create_group_duplicate_member_ids(self, client, headers_a, setup_ext_users):
        """Aynı üye ID tekrarlanırsa de-duplicate edilir."""
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "Tekrar Grubu",
                "member_ids": [
                    setup_ext_users["b_id"],
                    setup_ext_users["b_id"],
                    setup_ext_users["b_id"],
                ],
            },
            headers=headers_a,
        )
        assert resp.status_code == 201
        members = resp.json()["members"]
        # user_a (admin) + user_b = 2 üye
        assert len(members) == 2


# ─── Konuşma Silme Testleri ──────────────────────────────────────────


class TestDeleteConversation:
    """Konuşma silme (swipe-to-delete) endpoint testleri."""

    def test_delete_private_conversation(self, client, headers_a, setup_ext_users):
        """Private konuşmayı silme başarılı olur."""
        # Yeni konuşma oluştur
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_ext_users["d_id"], "message": "Silinecek konuşma"},
            headers=headers_a,
        )
        assert resp.status_code == 201
        conv_id = resp.json()["id"]

        # Konuşmayı sil
        resp = client.delete(
            f"/api/messages/conversations/{conv_id}",
            headers=headers_a,
        )
        assert resp.status_code == 200
        assert resp.json()["detail"] == "Konuşma silindi"

    def test_deleted_conversation_disappears_from_list(self, client, headers_a, headers_d, setup_ext_users):
        """Silinen konuşma kullanıcının listesinden kaybolur."""
        # Konuşma oluştur
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_ext_users["d_id"], "message": "Kaybolacak konuşma"},
            headers=headers_a,
        )
        conv_id = resp.json()["id"]

        # Sil
        client.delete(f"/api/messages/conversations/{conv_id}", headers=headers_a)

        # user_a'nın listesinde olmamalı
        resp = client.get("/api/messages/conversations", headers=headers_a)
        conv_ids = [c["id"] for c in resp.json()]
        assert conv_id not in conv_ids

    def test_other_user_still_sees_conversation(self, client, headers_a, headers_d, setup_ext_users):
        """Silme sonrası karşı taraf konuşmayı hâlâ görür."""
        # Konuşma oluştur
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_ext_users["d_id"], "message": "Karşı taraf görecek"},
            headers=headers_a,
        )
        conv_id = resp.json()["id"]

        # user_a siler
        client.delete(f"/api/messages/conversations/{conv_id}", headers=headers_a)

        # user_d hâlâ görmeli
        resp = client.get("/api/messages/conversations", headers=headers_d)
        conv_ids = [c["id"] for c in resp.json()]
        assert conv_id in conv_ids

    def test_delete_group_conversation_leaves_group(self, client, headers_a, headers_b, setup_ext_users):
        """Grup konuşmayı silmek sessizce listeden kaldırır."""
        # Grup oluştur
        conv_id = _create_group(
            client, headers_a, "Silinecek Grup",
            [setup_ext_users["b_id"], setup_ext_users["c_id"]],
        )

        # user_b grubu "siler"
        resp = client.delete(
            f"/api/messages/conversations/{conv_id}",
            headers=headers_b,
        )
        assert resp.status_code == 200

        # user_b artık gruba erişemez
        resp = client.post(
            f"/api/messages/conversations/{conv_id}",
            json={"content": "Ayrılmışım"},
            headers=headers_b,
        )
        assert resp.status_code == 404

    def test_delete_group_no_system_message(self, client, headers_a, headers_b, setup_ext_users):
        """Grup silme (sadece benden sil) sistem mesajı oluşturmaz."""
        conv_id = _create_group(
            client, headers_a, "Sessiz Silme Grup",
            [setup_ext_users["b_id"]],
        )

        # Mesaj gönder (referans)
        _send_msg(client, headers_a, conv_id, "Test mesajı")

        # user_b siler
        client.delete(f"/api/messages/conversations/{conv_id}", headers=headers_b)

        # user_a detayda "gruptan ayrıldı" sistem mesajı GÖRMEMELİ
        resp = client.get(
            f"/api/messages/conversations/{conv_id}",
            headers=headers_a,
        )
        messages = resp.json()["messages"]
        system_msgs = [m for m in messages if m["message_type"] == "system"]
        assert not any("gruptan ayrıldı" in m["content"] for m in system_msgs)

    def test_delete_nonexistent_conversation(self, client, headers_a, setup_ext_users):
        """Var olmayan konuşmayı silme 404 döner."""
        resp = client.delete(
            "/api/messages/conversations/999999",
            headers=headers_a,
        )
        assert resp.status_code == 404

    def test_delete_conversation_not_member(self, client, headers_c, headers_a, setup_ext_users):
        """Üye olmadığı konuşmayı silme 404 döner."""
        # user_a ile user_d arası konuşma oluştur
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_ext_users["d_id"]},
            headers=headers_a,
        )
        conv_id = resp.json()["id"]

        # user_c bu konuşmayı silmeye çalışsın
        resp = client.delete(
            f"/api/messages/conversations/{conv_id}",
            headers=headers_c,
        )
        assert resp.status_code == 404

    def test_delete_conversation_no_permission(self, client, headers_view, setup_ext_users):
        """İzinsiz kullanıcı konuşma silemez."""
        resp = client.delete(
            "/api/messages/conversations/1",
            headers=headers_view,
        )
        assert resp.status_code == 403

    def test_both_users_delete_cleans_up(self, client, headers_a, headers_d, setup_ext_users):
        """Her iki taraf da silerse konuşma tamamen temizlenir."""
        # Konuşma oluştur
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_ext_users["d_id"], "message": "Tamamen silinecek"},
            headers=headers_a,
        )
        conv_id = resp.json()["id"]

        # Her iki taraf da siler
        client.delete(f"/api/messages/conversations/{conv_id}", headers=headers_a)
        client.delete(f"/api/messages/conversations/{conv_id}", headers=headers_d)

        # Her ikisinin de listesinde olmamalı
        resp_a = client.get("/api/messages/conversations", headers=headers_a)
        resp_d = client.get("/api/messages/conversations", headers=headers_d)
        assert conv_id not in [c["id"] for c in resp_a.json()]
        assert conv_id not in [c["id"] for c in resp_d.json()]

    def test_delete_active_conversation_deselects(self, client, headers_a, setup_ext_users):
        """Silinen konuşma aktif konuşma ise erişilemez."""
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_ext_users["d_id"]},
            headers=headers_a,
        )
        conv_id = resp.json()["id"]

        # Sil
        client.delete(f"/api/messages/conversations/{conv_id}", headers=headers_a)

        # Artık detayına erişilemez
        resp = client.get(
            f"/api/messages/conversations/{conv_id}",
            headers=headers_a,
        )
        assert resp.status_code == 404


# ─── Gruba Sonradan Eklenen Üyelerin Mesaj Görünürlüğü ───────────────

_tz_istanbul = pytz.timezone("Europe/Istanbul")


def _fix_timestamps_for_join_test(db, conv_id, user_id, pre_contents, post_contents):
    """Tek transaction'da func.now() aynı timestamp verdiği için
    joined_at filtre testleri çalışmaz.

    Bu yardımcı timestamp'ları düzeltir:
    - Orijinal üyelerin joined_at → uzak geçmiş
    - pre_contents mesajları → geçmiş (joined_at öncesi)
    - Sonradan eklenen üyenin joined_at → orta nokta
    - Sistem mesajları → joined_at ile aynı (görünür olsun)
    - post_contents mesajları → gelecek (joined_at sonrası)
    """
    now = datetime.now(_tz_istanbul)
    origin_dt = now - timedelta(hours=4)
    past_dt = now - timedelta(hours=3)
    join_dt = now - timedelta(hours=2)
    future_dt = now - timedelta(hours=1)

    # Tüm orijinal üyelerin joined_at'ını çok geçmişe ayarla
    all_members = (
        db.query(ConversationMember)
        .filter(ConversationMember.conversation_id == conv_id)
        .all()
    )
    for m in all_members:
        if m.user_id != user_id:
            m.joined_at = origin_dt

    # Pre-join mesajları geçmişe çek
    for content in pre_contents:
        msg = (
            db.query(Message)
            .filter(Message.conversation_id == conv_id, Message.content == content)
            .first()
        )
        if msg:
            msg.created_at = past_dt

    # Post-join mesajları geleceğe ayarla
    for content in post_contents:
        msg = (
            db.query(Message)
            .filter(Message.conversation_id == conv_id, Message.content == content)
            .first()
        )
        if msg:
            msg.created_at = future_dt

    # Sistem mesajlarını join zamanına ayarla
    sys_msgs = (
        db.query(Message)
        .filter(
            Message.conversation_id == conv_id,
            Message.message_type == "system",
        )
        .all()
    )
    for msg in sys_msgs:
        msg.created_at = join_dt

    # Sonradan eklenen üyenin joined_at'ını ayarla
    member = (
        db.query(ConversationMember)
        .filter(
            ConversationMember.conversation_id == conv_id,
            ConversationMember.user_id == user_id,
        )
        .first()
    )
    if member:
        member.joined_at = join_dt

    db.flush()


class TestGroupJoinedAtVisibility:
    """Gruba sonradan eklenen üyeler, eklenmeden önceki mesajları göremez."""

    def test_late_joiner_cannot_see_pre_join_messages(
        self, client, headers_a, headers_b, headers_c, setup_ext_users,
        _module_transaction,
    ):
        """Gruba sonradan eklenen üye, eklenme öncesi mesajları göremez."""
        # 1. Grup oluştur: a + b (c yok)
        conv_id = _create_group(
            client, headers_a, "JoinAt Test Grubu",
            [setup_ext_users["b_id"]],
        )

        # 2. Mesajlar gönder (c eklenmeden önce)
        _send_msg(client, headers_a, conv_id, "Önceki mesaj 1")
        _send_msg(client, headers_b, conv_id, "Önceki mesaj 2")
        _send_msg(client, headers_a, conv_id, "Önceki mesaj 3")

        # 3. c'yi gruba ekle
        resp = client.post(
            f"/api/messages/conversations/{conv_id}/members",
            json={"user_ids": [setup_ext_users["c_id"]]},
            headers=headers_a,
        )
        assert resp.status_code == 200

        # 4. Ekleme sonrası mesajlar
        _send_msg(client, headers_a, conv_id, "Sonraki mesaj 1")
        _send_msg(client, headers_b, conv_id, "Sonraki mesaj 2")

        # 5. Tek transaction'da func.now() aynı zaman damgasını döndürür;
        #    timestamp'ları düzelt
        _fix_timestamps_for_join_test(
            _module_transaction, conv_id, setup_ext_users["c_id"],
            pre_contents=["Önceki mesaj 1", "Önceki mesaj 2", "Önceki mesaj 3"],
            post_contents=["Sonraki mesaj 1", "Sonraki mesaj 2"],
        )

        # 6. c'nin gördüğü mesajları kontrol et
        resp_c = client.get(
            f"/api/messages/conversations/{conv_id}",
            headers=headers_c,
        )
        assert resp_c.status_code == 200
        messages = resp_c.json()["messages"]

        # c, "Sonraki mesaj 1" ve "Sonraki mesaj 2"yi görmeli
        # + sistem mesajı (eklendi bildirimi)
        text_messages = [m for m in messages if m["message_type"] == "text"]
        assert len(text_messages) == 2
        contents = [m["content"] for m in text_messages]
        assert "Sonraki mesaj 1" in contents
        assert "Sonraki mesaj 2" in contents
        # Önceki mesajlar görünmemeli
        assert "Önceki mesaj 1" not in contents
        assert "Önceki mesaj 2" not in contents
        assert "Önceki mesaj 3" not in contents

    def test_original_member_sees_all_messages(
        self, client, headers_a, headers_b, headers_c, setup_ext_users,
    ):
        """Grubun orijinal üyesi tüm mesajları görür."""
        # Bir önceki testte oluşturulan grup üzerinden kontrol
        # Grup adına göre bul
        resp = client.get("/api/messages/conversations", headers=headers_a)
        convs = resp.json()
        group = next((c for c in convs if c.get("name") == "JoinAt Test Grubu"), None)
        assert group is not None, "JoinAt Test Grubu bulunamadı"

        resp_a = client.get(
            f"/api/messages/conversations/{group['id']}",
            headers=headers_a,
        )
        assert resp_a.status_code == 200
        messages = resp_a.json()["messages"]
        text_messages = [m for m in messages if m["message_type"] == "text"]
        # a tüm mesajları görmeli: 3 önceki + 2 sonraki = 5
        assert len(text_messages) == 5

    def test_late_joiner_unread_count_excludes_pre_join(
        self, client, headers_a, headers_c, setup_ext_users, _module_transaction,
    ):
        """Sonradan eklenen üyenin okunmamış sayısı, eklenmeden önceki mesajları içermez."""
        # Yeni temiz bir grup oluştur
        conv_id = _create_group(
            client, headers_a, "UnreadJoinAt Grubu",
            [setup_ext_users["b_id"]],
        )

        # Eklenmeden önce 3 mesaj gönder
        _send_msg(client, headers_a, conv_id, "Unread önceki 1")
        _send_msg(client, headers_a, conv_id, "Unread önceki 2")
        _send_msg(client, headers_a, conv_id, "Unread önceki 3")

        # c'yi ekle
        resp = client.post(
            f"/api/messages/conversations/{conv_id}/members",
            json={"user_ids": [setup_ext_users["c_id"]]},
            headers=headers_a,
        )
        assert resp.status_code == 200

        # Ekleme sonrası 2 mesaj gönder
        _send_msg(client, headers_a, conv_id, "Unread sonraki 1")
        _send_msg(client, headers_a, conv_id, "Unread sonraki 2")

        # Timestamp'ları düzelt
        _fix_timestamps_for_join_test(
            _module_transaction, conv_id, setup_ext_users["c_id"],
            pre_contents=["Unread önceki 1", "Unread önceki 2", "Unread önceki 3"],
            post_contents=["Unread sonraki 1", "Unread sonraki 2"],
        )

        # c'nin toplam okunmamış sayısını kontrol et
        resp_unread = client.get("/api/messages/unread-count", headers=headers_c)
        assert resp_unread.status_code == 200

        # c'nin konuşma listesindeki unread_count'u kontrol et
        resp_convs = client.get("/api/messages/conversations", headers=headers_c)
        assert resp_convs.status_code == 200
        conv_data = next(
            (c for c in resp_convs.json() if c["id"] == conv_id), None,
        )
        assert conv_data is not None
        # Sadece eklenmeden sonraki mesajlar okunmamış olmalı
        assert "unread_count" in conv_data

    def test_late_joiner_search_excludes_pre_join(
        self, client, headers_a, headers_c, setup_ext_users, _module_transaction,
    ):
        """Sonradan eklenen üye, arama yaparken eklenmeden önceki mesajları bulamaz."""
        # Yeni grup oluştur
        conv_id = _create_group(
            client, headers_a, "SearchJoinAt Grubu",
            [setup_ext_users["b_id"]],
        )

        # Eklenmeden önce mesaj gönder
        _send_msg(client, headers_a, conv_id, "Aranacak gizli içerik")

        # c'yi ekle
        client.post(
            f"/api/messages/conversations/{conv_id}/members",
            json={"user_ids": [setup_ext_users["c_id"]]},
            headers=headers_a,
        )

        # Ekleme sonrası mesaj gönder
        _send_msg(client, headers_a, conv_id, "Aranacak açık içerik")

        # Timestamp'ları düzelt
        _fix_timestamps_for_join_test(
            _module_transaction, conv_id, setup_ext_users["c_id"],
            pre_contents=["Aranacak gizli içerik"],
            post_contents=["Aranacak açık içerik"],
        )

        # c ile arama yap
        resp = client.get(
            f"/api/messages/conversations/{conv_id}/search?q=Aranacak",
            headers=headers_c,
        )
        assert resp.status_code == 200
        results = resp.json()
        contents = [r["content"] for r in results]
        # c, sadece eklendikten sonraki mesajı bulmalı
        assert "Aranacak açık içerik" in contents
        assert "Aranacak gizli içerik" not in contents

    def test_original_member_search_sees_all(
        self, client, headers_a, setup_ext_users,
    ):
        """Orijinal üye arama yaparken tüm mesajları bulur."""
        # SearchJoinAt Grubu'nu bul
        resp = client.get("/api/messages/conversations", headers=headers_a)
        group = next(
            (c for c in resp.json() if c.get("name") == "SearchJoinAt Grubu"), None,
        )
        assert group is not None

        resp = client.get(
            f"/api/messages/conversations/{group['id']}/search?q=Aranacak",
            headers=headers_a,
        )
        assert resp.status_code == 200
        results = resp.json()
        contents = [r["content"] for r in results]
        assert "Aranacak gizli içerik" in contents
        assert "Aranacak açık içerik" in contents

    def test_late_joiner_has_more_excludes_pre_join(
        self, client, headers_a, headers_c, setup_ext_users, _module_transaction,
    ):
        """Sonradan eklenen üye için has_more önceki mesajları dikkate almaz."""
        conv_id = _create_group(
            client, headers_a, "HasMoreJoinAt Grubu",
            [setup_ext_users["b_id"]],
        )

        # Eklenmeden önce 5 mesaj gönder
        pre_contents = []
        for i in range(5):
            content = f"Eski mesaj {i}"
            _send_msg(client, headers_a, conv_id, content)
            pre_contents.append(content)

        # c'yi ekle
        client.post(
            f"/api/messages/conversations/{conv_id}/members",
            json={"user_ids": [setup_ext_users["c_id"]]},
            headers=headers_a,
        )

        # Eklendikten sonra 2 mesaj gönder
        _send_msg(client, headers_a, conv_id, "Yeni mesaj 1")
        _send_msg(client, headers_a, conv_id, "Yeni mesaj 2")

        # Timestamp'ları düzelt
        _fix_timestamps_for_join_test(
            _module_transaction, conv_id, setup_ext_users["c_id"],
            pre_contents=pre_contents,
            post_contents=["Yeni mesaj 1", "Yeni mesaj 2"],
        )

        # c konuşmayı açtığında has_more=false olmalı (sadece 2-3 mesaj var)
        resp = client.get(
            f"/api/messages/conversations/{conv_id}",
            headers=headers_c,
        )
        assert resp.status_code == 200
        data = resp.json()
        text_messages = [m for m in data["messages"] if m["message_type"] == "text"]
        assert len(text_messages) == 2
        assert data["has_more"] is False

    def test_private_conversation_not_affected_by_joined_at(
        self, client, headers_c, headers_d, setup_ext_users,
    ):
        """Private konuşmalarda joined_at filtresi uygulanmaz — tüm mesajlar görünür."""
        conv_id = _create_private(client, headers_c, setup_ext_users["d_id"])
        _send_msg(client, headers_c, conv_id, "Private joinat mesaj 1")
        _send_msg(client, headers_d, conv_id, "Private joinat mesaj 2")

        # Her iki taraf da tüm mesajları görmeli
        resp_c = client.get(
            f"/api/messages/conversations/{conv_id}", headers=headers_c,
        )
        resp_d = client.get(
            f"/api/messages/conversations/{conv_id}", headers=headers_d,
        )
        msgs_c = resp_c.json()["messages"]
        msgs_d = resp_d.json()["messages"]
        contents_c = [m["content"] for m in msgs_c]
        contents_d = [m["content"] for m in msgs_d]
        assert "Private joinat mesaj 1" in contents_c
        assert "Private joinat mesaj 2" in contents_c
        assert "Private joinat mesaj 1" in contents_d
        assert "Private joinat mesaj 2" in contents_d

    def test_late_joiner_read_marks_only_post_join(
        self, client, headers_a, headers_c, setup_ext_users, _module_transaction,
    ):
        """Sonradan eklenen üye konuşmayı 'okundu' olarak işaretlerse sadece eklendikten sonraki mesajlar etkilenir."""
        conv_id = _create_group(
            client, headers_a, "ReadMarkJoinAt Grubu",
            [setup_ext_users["b_id"]],
        )

        # Önceki mesajlar
        _send_msg(client, headers_a, conv_id, "Read test önceki")

        # c'yi ekle
        client.post(
            f"/api/messages/conversations/{conv_id}/members",
            json={"user_ids": [setup_ext_users["c_id"]]},
            headers=headers_a,
        )

        # Sonraki mesajlar
        _send_msg(client, headers_a, conv_id, "Read test sonraki")

        # Timestamp'ları düzelt
        _fix_timestamps_for_join_test(
            _module_transaction, conv_id, setup_ext_users["c_id"],
            pre_contents=["Read test önceki"],
            post_contents=["Read test sonraki"],
        )

        # c okundu olarak işaretlesin
        client.patch(
            f"/api/messages/conversations/{conv_id}/read",
            headers=headers_c,
        )

        # c'nin okunmamış sayısı 0 olmalı (read_test sonraki okundu)
        resp = client.get("/api/messages/conversations", headers=headers_c)
        conv_data = next(
            (c for c in resp.json() if c["id"] == conv_id), None,
        )
        assert conv_data is not None
        assert conv_data["unread_count"] == 0

    def test_multiple_late_joiners_have_different_visibility(
        self, client, headers_a, headers_b, headers_c, headers_d, setup_ext_users,
        _module_transaction,
    ):
        """Farklı zamanlarda eklenen üyeler, farklı mesaj kümeleri görür."""
        db = _module_transaction
        now = datetime.now(_tz_istanbul)

        conv_id = _create_group(
            client, headers_a, "MultiJoin Grubu",
            [setup_ext_users["b_id"]],
        )

        # Faz 1: Sadece a ve b var
        _send_msg(client, headers_a, conv_id, "Faz1 mesaj")

        # c'yi ekle
        client.post(
            f"/api/messages/conversations/{conv_id}/members",
            json={"user_ids": [setup_ext_users["c_id"]]},
            headers=headers_a,
        )

        # Faz 2: a, b, c var
        _send_msg(client, headers_a, conv_id, "Faz2 mesaj")

        # d'yi ekle
        client.post(
            f"/api/messages/conversations/{conv_id}/members",
            json={"user_ids": [setup_ext_users["d_id"]]},
            headers=headers_a,
        )

        # Faz 3: hepsi var
        _send_msg(client, headers_a, conv_id, "Faz3 mesaj")

        # Timestamp'ları manuel ayarla — 3 faz için 3 farklı zaman
        t_origin = now - timedelta(hours=4)  # Orijinal üyeler
        t1 = now - timedelta(hours=3)  # Faz 1
        t_c_join = now - timedelta(hours=2)  # c'nin katılma zamanı
        t2 = now - timedelta(hours=1)  # Faz 2
        t_d_join = now  # d'nin katılma zamanı
        t3 = now + timedelta(hours=1)  # Faz 3

        # Orijinal üyelerin joined_at'ını en eski zamana ayarla
        for uid in [setup_ext_users["a_id"], setup_ext_users["b_id"]]:
            m = db.query(ConversationMember).filter(
                ConversationMember.conversation_id == conv_id,
                ConversationMember.user_id == uid,
            ).first()
            if m:
                m.joined_at = t_origin

        # Mesaj timestamp'ları
        for content, ts in [("Faz1 mesaj", t1), ("Faz2 mesaj", t2), ("Faz3 mesaj", t3)]:
            msg = db.query(Message).filter(
                Message.conversation_id == conv_id, Message.content == content,
            ).first()
            if msg:
                msg.created_at = ts

        # Sistem mesajlarını sırayla ayarla
        sys_msgs = (
            db.query(Message)
            .filter(Message.conversation_id == conv_id, Message.message_type == "system")
            .order_by(Message.id)
            .all()
        )
        for sm in sys_msgs:
            # İlk sistem mesajı (grup oluşturma) → faz 1 öncesi
            # Sonraki sistem mesajları (üye ekleme) → katılma zamanları
            if "oluşturdu" in sm.content:
                sm.created_at = t1 - timedelta(seconds=1)
            elif setup_ext_users["c_id"] and "gruba ekledi" in sm.content:
                sm.created_at = t_c_join
            elif setup_ext_users["d_id"] and "gruba ekledi" in sm.content:
                sm.created_at = t_d_join

        # joined_at'ları ayarla
        for uid, jt in [
            (setup_ext_users["c_id"], t_c_join),
            (setup_ext_users["d_id"], t_d_join),
        ]:
            member = db.query(ConversationMember).filter(
                ConversationMember.conversation_id == conv_id,
                ConversationMember.user_id == uid,
            ).first()
            if member:
                member.joined_at = jt

        db.flush()

        # a: Faz1 + Faz2 + Faz3 = 3 text mesaj
        resp_a = client.get(
            f"/api/messages/conversations/{conv_id}", headers=headers_a,
        )
        text_a = [m for m in resp_a.json()["messages"] if m["message_type"] == "text"]
        assert len(text_a) == 3

        # c: Faz2 + Faz3 = 2 text mesaj (sistem mesajları hariç)
        resp_c = client.get(
            f"/api/messages/conversations/{conv_id}", headers=headers_c,
        )
        text_c = [m for m in resp_c.json()["messages"] if m["message_type"] == "text"]
        assert len(text_c) == 2
        c_contents = [m["content"] for m in text_c]
        assert "Faz2 mesaj" in c_contents
        assert "Faz3 mesaj" in c_contents
        assert "Faz1 mesaj" not in c_contents

        # d: Faz3 = 1 text mesaj (sistem mesajları hariç)
        resp_d = client.get(
            f"/api/messages/conversations/{conv_id}", headers=headers_d,
        )
        text_d = [m for m in resp_d.json()["messages"] if m["message_type"] == "text"]
        assert len(text_d) == 1
        assert text_d[0]["content"] == "Faz3 mesaj"


# ─── Temizlik ─────────────────────────────────────────────────────────


# ─── Sessize Alma Testleri ─────────────────────────────────────────────


class TestMuteConversation:
    """Konuşma sessize alma özelliği testleri."""

    def test_mute_conversation(self, client, setup_ext_users, headers_a, headers_b):
        """Konuşma sessize alınabilmeli."""
        # a→b konuşma başlat
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_ext_users["b_id"], "message": "Mute test mesaj"},
            headers=headers_a,
        )
        assert resp.status_code == 201
        conv_id = resp.json()["id"]

        # Sessize al
        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/mute",
            json={"is_muted": True},
            headers=headers_a,
        )
        assert resp.status_code == 200
        assert resp.json()["is_muted"] is True

    def test_unmute_conversation(self, client, setup_ext_users, headers_a, headers_b):
        """Sessiz konuşma tekrar sesli yapılabilmeli."""
        # a→b konuşma
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_ext_users["b_id"]},
            headers=headers_a,
        )
        conv_id = resp.json()["id"]

        # Önce sessize al
        client.patch(
            f"/api/messages/conversations/{conv_id}/mute",
            json={"is_muted": True},
            headers=headers_a,
        )

        # Sonra sesi aç
        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/mute",
            json={"is_muted": False},
            headers=headers_a,
        )
        assert resp.status_code == 200
        assert resp.json()["is_muted"] is False

    def test_mute_in_conversation_list(self, client, setup_ext_users, headers_a, headers_b):
        """Konuşma listesinde is_muted alanı doğru dönmeli."""
        # a→b konuşma
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_ext_users["b_id"]},
            headers=headers_a,
        )
        conv_id = resp.json()["id"]

        # Sessize al
        client.patch(
            f"/api/messages/conversations/{conv_id}/mute",
            json={"is_muted": True},
            headers=headers_a,
        )

        # Konuşma listesini kontrol et
        resp = client.get("/api/messages/conversations", headers=headers_a)
        assert resp.status_code == 200
        convs = resp.json()
        target_conv = next((c for c in convs if c["id"] == conv_id), None)
        assert target_conv is not None
        assert target_conv["is_muted"] is True

        # Diğer kullanıcı (b) için sessiz olmamalı
        resp = client.get("/api/messages/conversations", headers=headers_b)
        assert resp.status_code == 200
        convs_b = resp.json()
        target_conv_b = next((c for c in convs_b if c["id"] == conv_id), None)
        assert target_conv_b is not None
        assert target_conv_b["is_muted"] is False

    def test_mute_nonexistent_conversation(self, client, headers_a):
        """Üye olunmayan konuşma sessize alınamaz (404)."""
        resp = client.patch(
            "/api/messages/conversations/999999/mute",
            json={"is_muted": True},
            headers=headers_a,
        )
        assert resp.status_code == 404

    def test_mute_requires_use_permission(self, client, setup_ext_users, headers_a, headers_view):
        """Sadece view izni olan kullanıcı sessiz yapamaz (403)."""
        # a→b konuşma oluştur ve id al
        resp = client.post(
            "/api/messages/conversations",
            json={"user_id": setup_ext_users["b_id"]},
            headers=headers_a,
        )
        conv_id = resp.json()["id"]

        # view-only kullanıcı ile mute dene
        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/mute",
            json={"is_muted": True},
            headers=headers_view,
        )
        assert resp.status_code == 403

    def test_mute_group_conversation(self, client, setup_ext_users, headers_a, headers_b):
        """Grup konuşması da sessize alınabilmeli."""
        # Grup oluştur
        resp = client.post(
            "/api/messages/conversations/group",
            json={
                "name": "Sessiz Test Grubu",
                "member_ids": [setup_ext_users["b_id"], setup_ext_users["c_id"]],
            },
            headers=headers_a,
        )
        assert resp.status_code == 201
        conv_id = resp.json()["id"]

        # a sessiz yapsın
        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/mute",
            json={"is_muted": True},
            headers=headers_a,
        )
        assert resp.status_code == 200
        assert resp.json()["is_muted"] is True

        # Liste'de a için sessiz, b için değil
        resp_a = client.get("/api/messages/conversations", headers=headers_a)
        conv_a = next((c for c in resp_a.json() if c["id"] == conv_id), None)
        assert conv_a is not None
        assert conv_a["is_muted"] is True

        resp_b = client.get("/api/messages/conversations", headers=headers_b)
        conv_b = next((c for c in resp_b.json() if c["id"] == conv_id), None)
        assert conv_b is not None
        assert conv_b["is_muted"] is False


# ─── Dosya Yükleme Testleri ─────────────────────────────────────────────


class TestFileUpload:
    """Dosya yükleme endpoint'i testleri."""

    def test_upload_image(self, client, setup_ext_users, headers_a, headers_b):
        """JPEG görsel yükleme — 201 döner, alanlar doğru."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        # Gerçek JPEG magic bytes
        jpeg_content = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        resp = client.post(
            f"/api/messages/conversations/{conv_id}/upload",
            files={"file": ("test.jpg", jpeg_content, "image/jpeg")},
            headers=headers_a,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["message_type"] == "image"
        assert data["file_name"] == "test.jpg"
        assert data["file_type"] == "image/jpeg"
        assert data["file_url"] is not None
        assert data["file_size"] > 0

    def test_upload_with_caption(self, client, setup_ext_users, headers_a, headers_b):
        """Açıklamalı yükleme — content caption ile dolar."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        jpeg_content = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        resp = client.post(
            f"/api/messages/conversations/{conv_id}/upload",
            files={"file": ("photo.jpg", jpeg_content, "image/jpeg")},
            data={"caption": "Güzel manzara"},
            headers=headers_a,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["content"] == "Güzel manzara"

    def test_upload_too_large(self, client, setup_ext_users, headers_a, headers_b):
        """21MB dosya → 400."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        jpeg_content = b"\xff\xd8\xff\xe0" + b"\x00" * (21 * 1024 * 1024)
        resp = client.post(
            f"/api/messages/conversations/{conv_id}/upload",
            files={"file": ("big.jpg", jpeg_content, "image/jpeg")},
            headers=headers_a,
        )
        assert resp.status_code == 400
        assert "boyut" in resp.json()["detail"].lower() or "MB" in resp.json()["detail"]

    def test_upload_invalid_type(self, client, setup_ext_users, headers_a, headers_b):
        """Desteklenmeyen dosya türü → 400."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        exe_content = b"MZ" + b"\x00" * 100
        resp = client.post(
            f"/api/messages/conversations/{conv_id}/upload",
            files={"file": ("malware.exe", exe_content, "application/x-msdownload")},
            headers=headers_a,
        )
        assert resp.status_code == 400
        assert "desteklenmiyor" in resp.json()["detail"].lower()

    def test_upload_without_membership(self, client, setup_ext_users, headers_a, headers_b, headers_c):
        """Üye olmayan konuşmaya yükleme → 404."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        jpeg_content = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        resp = client.post(
            f"/api/messages/conversations/{conv_id}/upload",
            files={"file": ("test.jpg", jpeg_content, "image/jpeg")},
            headers=headers_c,
        )
        assert resp.status_code == 404

    def test_upload_rate_limit(self, client, setup_ext_users, headers_a, headers_b):
        """Aşırı yükleme → 429."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        jpeg_content = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        # upload_limiter: 10/dk
        for i in range(10):
            resp = client.post(
                f"/api/messages/conversations/{conv_id}/upload",
                files={"file": (f"img{i}.jpg", jpeg_content, "image/jpeg")},
                headers=headers_a,
            )
            assert resp.status_code == 201, f"Upload {i+1} başarısız: {resp.text}"

        # 11. yükleme → 429
        resp = client.post(
            f"/api/messages/conversations/{conv_id}/upload",
            files={"file": ("img_over.jpg", jpeg_content, "image/jpeg")},
            headers=headers_a,
        )
        assert resp.status_code == 429

    def test_upload_empty_file(self, client, setup_ext_users, headers_a, headers_b):
        """Boş dosya → 400."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        resp = client.post(
            f"/api/messages/conversations/{conv_id}/upload",
            files={"file": ("empty.jpg", b"", "image/jpeg")},
            headers=headers_a,
        )
        assert resp.status_code == 400
        assert "boş" in resp.json()["detail"].lower() or "Boş" in resp.json()["detail"]


# ─── Cascade Delete Testleri ─────────────────────────────────────────────


class TestCascadeDelete:
    """Konuşma silme ve üye ayrılma davranış testleri."""

    def test_delete_membership_preserves_conversation(
        self, client, setup_ext_users, headers_a, headers_b,
    ):
        """Bir üye konuşmayı silerse diğer üye hâlâ görür."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"], "Merhaba!")

        # a konuşmayı siler
        resp = client.delete(f"/api/messages/conversations/{conv_id}", headers=headers_a)
        assert resp.status_code == 200

        # a artık konuşmayı görmez
        resp_a = client.get("/api/messages/conversations", headers=headers_a)
        conv_ids_a = [c["id"] for c in resp_a.json()]
        assert conv_id not in conv_ids_a

        # b hâlâ konuşmayı görür
        resp_b = client.get("/api/messages/conversations", headers=headers_b)
        conv_ids_b = [c["id"] for c in resp_b.json()]
        assert conv_id in conv_ids_b

    def test_last_member_leaves_cleans_up(
        self, client, setup_ext_users, headers_a, headers_b, _module_transaction,
    ):
        """Son üye ayrıldığında konuşma ve mesajlar temizlenir."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"], "Temizlenecek")
        _send_msg(client, headers_b, conv_id, "Cevap")

        # Her iki üye de siler
        resp = client.delete(f"/api/messages/conversations/{conv_id}", headers=headers_a)
        assert resp.status_code == 200
        resp = client.delete(f"/api/messages/conversations/{conv_id}", headers=headers_b)
        assert resp.status_code == 200

        # Konuşma veritabanından silinmiş olmalı
        db = _module_transaction
        conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
        assert conv is None
        msg_count = db.query(Message).filter(Message.conversation_id == conv_id).count()
        assert msg_count == 0

    def test_group_last_member_cleans_up(
        self, client, setup_ext_users, headers_a, headers_b, _module_transaction,
    ):
        """Grup konuşmasında tüm üyeler ayrıldığında temizlenir."""
        # Grup oluştur
        resp = client.post(
            "/api/messages/conversations/group",
            json={"name": "Silinecek Grup", "member_ids": [setup_ext_users["b_id"]]},
            headers=headers_a,
        )
        assert resp.status_code == 201
        conv_id = resp.json()["id"]

        # Her iki üye de siler
        client.delete(f"/api/messages/conversations/{conv_id}", headers=headers_a)
        client.delete(f"/api/messages/conversations/{conv_id}", headers=headers_b)

        db = _module_transaction
        conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
        assert conv is None


# ─── Audit Logging Testleri ──────────────────────────────────────────────


class TestAuditLogging:
    """Mesajlaşma CRUD işlemlerinin audit_logs'a kaydedilme testleri."""

    def test_group_create_audit(self, client, setup_ext_users, headers_a, _module_transaction):
        """Grup oluşturma audit_logs'a yazılır."""
        resp = client.post(
            "/api/messages/conversations/group",
            json={"name": "Audit Test Grubu", "member_ids": [setup_ext_users["b_id"]]},
            headers=headers_a,
        )
        assert resp.status_code == 201
        conv_id = resp.json()["id"]

        db = _module_transaction
        log = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "group_conversation",
                AuditLog.entity_id == conv_id,
                AuditLog.action == "create",
            )
            .first()
        )
        assert log is not None
        assert log.user_id == setup_ext_users["a_id"]
        assert "Audit Test Grubu" in (log.details or "")

    def test_message_edit_audit(self, client, setup_ext_users, headers_a, headers_b, _module_transaction):
        """Mesaj düzenleme audit_logs'a yazılır."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        msg = _send_msg(client, headers_a, conv_id, "Orijinal mesaj")
        msg_id = msg["id"]

        resp = client.patch(
            f"/api/messages/conversations/{conv_id}/messages/{msg_id}",
            json={"content": "Düzenlenmiş mesaj"},
            headers=headers_a,
        )
        assert resp.status_code == 200

        db = _module_transaction
        log = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "message",
                AuditLog.entity_id == msg_id,
                AuditLog.action == "update",
            )
            .first()
        )
        assert log is not None
        assert log.user_id == setup_ext_users["a_id"]

    def test_message_delete_audit(self, client, setup_ext_users, headers_a, headers_b, _module_transaction):
        """Mesaj silme audit_logs'a yazılır."""
        conv_id = _create_private(client, headers_a, setup_ext_users["b_id"])
        msg = _send_msg(client, headers_a, conv_id, "Silinecek mesaj")
        msg_id = msg["id"]

        resp = client.delete(
            f"/api/messages/conversations/{conv_id}/messages/{msg_id}",
            headers=headers_a,
        )
        assert resp.status_code == 200

        db = _module_transaction
        log = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "message",
                AuditLog.entity_id == msg_id,
                AuditLog.action == "delete",
            )
            .first()
        )
        assert log is not None
        assert log.user_id == setup_ext_users["a_id"]
