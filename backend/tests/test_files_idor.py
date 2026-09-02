"""SECA-001 regresyon: files.py serve_file IDOR koruması.

serve_file yalnız kimlik değil, dosyanın ait olduğu modülün `view` iznini ve
(mesaj ekleri için) konuşma üyeliğini de arar. Yetkisiz kullanıcı başka modülün
dosyasını 403 alır; tanınmayan dizin öneki deny-by-default reddedilir.

Düzeltme geri alınırsa (yalnız auth kontrolü) bu testler kırmızıya döner.
"""

import uuid

import pytest

from app.models.conversation import Conversation, ConversationMember
from app.models.message import Message
from app.models.module import Module
from app.models.role import Role
from app.models.role_module_permission import RoleModulePermission
from app.models.user import User
from app.routers.core.files import _uploads_dir
from app.utils.security import hash_password


def _token(resp) -> str:
    token = resp.cookies.get("access_token")
    if not token:
        token = resp.json().get("access_token", "")
    return token


def _make_user(db, client, perms: dict):
    """Belirtilen modül izinleriyle kullanıcı oluştur, login et; (headers, user) döner."""
    uid = uuid.uuid4().hex[:8]
    role = Role(name=f"idor_role_{uid}", description="IDOR test rolü")
    db.add(role)
    db.flush()
    for module in db.query(Module).all():
        spec = perms.get(module.code, {})
        db.add(RoleModulePermission(
            role_id=role.id,
            module_id=module.id,
            can_view=spec.get("view", False),
            can_use=spec.get("use", False),
        ))
    user = User(
        username=f"idor_{uid}",
        email=f"idor_{uid}@test.local",
        first_name="Idor",
        last_name=uid,
        hashed_password=hash_password("Test1234!"),
        role_id=role.id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    resp = client.post("/api/auth/login", json={"username": user.username, "password": "Test1234!"})
    assert resp.status_code == 200, f"Login başarısız: {resp.text}"
    return {"Authorization": f"Bearer {_token(resp)}"}, user


@pytest.fixture
def cc_file():
    """cc_statements (finance.krediler) dizininde gerçek bir dosya oluştur, test sonunda temizle."""
    d = _uploads_dir / "cc_statements"
    d.mkdir(parents=True, exist_ok=True)
    name = f"test_{uuid.uuid4().hex}.pdf"
    path = d / name
    path.write_bytes(b"%PDF-1.4 test ekstre")
    yield f"cc_statements/{name}"
    if path.exists():
        path.unlink()


def test_unauthenticated_denied(client, cc_file):
    """Token yoksa 401."""
    r = client.get(f"/uploads/{cc_file}")
    assert r.status_code == 401


def test_unauthorized_module_forbidden(client, db, cc_file):
    """messaging izni olan ama finance.krediler izni OLMAYAN kullanıcı ekstre dosyasını 403 alır."""
    headers, _ = _make_user(db, client, {"messaging": {"view": True, "use": True}})
    r = client.get(f"/uploads/{cc_file}", headers=headers)
    assert r.status_code == 403


def test_authorized_module_allowed(client, db, cc_file):
    """finance.krediler view izni olan kullanıcı ekstre dosyasına erişir (200)."""
    headers, _ = _make_user(db, client, {"finance.krediler": {"view": True}})
    r = client.get(f"/uploads/{cc_file}", headers=headers)
    assert r.status_code == 200
    assert r.content == b"%PDF-1.4 test ekstre"


def test_unknown_prefix_denied(client, db, cc_file):
    """Tanınmayan dizin öneki deny-by-default — tüm modül izinleri olsa bile 403."""
    headers, _ = _make_user(db, client, {
        "finance.krediler": {"view": True, "use": True},
        "messaging": {"view": True, "use": True},
    })
    r = client.get("/uploads/gizli_dizin/secret.pdf", headers=headers)
    assert r.status_code == 403


def test_message_attachment_requires_membership(client, db):
    """Mesaj eki: konuşma üyesi 200, messaging izni olan ama üye OLMAYAN 403 alır."""
    owner_headers, owner = _make_user(db, client, {"messaging": {"view": True, "use": True}})
    outsider_headers, _ = _make_user(db, client, {"messaging": {"view": True, "use": True}})

    conv = Conversation(type="private", created_by=owner.id)
    db.add(conv)
    db.flush()
    db.add(ConversationMember(conversation_id=conv.id, user_id=owner.id))

    d = _uploads_dir / "2026" / "02"
    d.mkdir(parents=True, exist_ok=True)
    name = f"msg_{uuid.uuid4().hex}.png"
    path = d / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    file_url = f"/uploads/2026/02/{name}"
    db.add(Message(
        conversation_id=conv.id,
        sender_id=owner.id,
        content="ek",
        message_type="image",
        file_url=file_url,
    ))
    db.commit()

    try:
        # Konuşma üyesi → 200
        r_owner = client.get(file_url, headers=owner_headers)
        assert r_owner.status_code == 200
        # Üye olmayan (messaging izni olsa da) → 403 (kaynak sahipliği)
        r_out = client.get(file_url, headers=outsider_headers)
        assert r_out.status_code == 403
    finally:
        if path.exists():
            path.unlink()
