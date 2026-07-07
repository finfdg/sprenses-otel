"""Yapay Zeka Asistanı — Faz 2 yazma aksiyonu regresyon testleri.

execute_action() güvenlik katmanlarını doğrular: (1) bilinmeyen aksiyon reddi,
(2) hedef modül can_use izni, (3) payload whitelist + değer doğrulama, (4) doğrudan
uygulama (onay kapalıyken vendor.payment_days değişir), (5) proposer'ın mutasyon
YAPMAMASI. Onay akışı autouse `_disable_admin_approval_workflows` ile kapalı olduğundan
admin için execute_action doğrudan-uygula yoluna girer.
"""

import uuid

import pytest

from app.models.role import Role
from app.models.user import User
from app.models.vendor import Vendor
from app.services import ai_service
from app.utils.security import hash_password


def _admin(db) -> User:
    return (
        db.query(User)
        .join(Role, User.role_id == Role.id)
        .filter(Role.name == "Admin")
        .first()
    )


def _vendor(db, payment_days: int = 90, status: str = "normal") -> Vendor:
    v = Vendor(
        hesap_kodu=f"320.AI.{uuid.uuid4().hex[:8]}",
        hesap_adi="Test AI Cari",
        payment_days=payment_days,
        status=status,
    )
    db.add(v)
    db.commit()
    return v


def test_execute_cari_vade_dogrudan_uygula(db):
    """Onay kapalı → execute_action carinin vadesini gerçekten günceller."""
    admin = _admin(db)
    v = _vendor(db, payment_days=90)

    res = ai_service.execute_action(db, admin, "cari_vade", v.id, {"payment_days": 45})

    assert res["durum"] == "uygulandi", res
    db.refresh(v)
    assert v.payment_days == 45


def test_execute_bilinmeyen_aksiyon_reddedilir(db):
    admin = _admin(db)
    res = ai_service.execute_action(db, admin, "sql_calistir", 1, {})
    assert res["durum"] == "hata"


def test_execute_izin_yoksa_reddedilir(db):
    """finance.cariler can_use izni olmayan kullanıcı carinin vadesini değiştiremez."""
    role = Role(name=f"noperm_ai_{uuid.uuid4().hex[:6]}", description="izinsiz")
    db.add(role)
    db.flush()
    user = User(
        username=f"noperm_ai_{uuid.uuid4().hex[:6]}",
        email=f"noperm_{uuid.uuid4().hex[:6]}@test.local",
        first_name="No",
        last_name="Perm",
        hashed_password=hash_password("Test1234!"),
        role_id=role.id,
        is_active=True,
    )
    db.add(user)
    v = _vendor(db, payment_days=90)

    res = ai_service.execute_action(db, user, "cari_vade", v.id, {"payment_days": 45})

    assert res["durum"] == "hata"
    db.refresh(v)
    assert v.payment_days == 90  # değişmedi


def test_execute_payload_whitelist_ve_dogrulama(db):
    """Whitelist dışı anahtar (status) düşürülür; negatif vade doğrulamada takılır."""
    admin = _admin(db)
    v = _vendor(db, payment_days=90, status="normal")

    res = ai_service.execute_action(
        db, admin, "cari_vade", v.id,
        {"payment_days": -5, "status": "odeme_yasaklisi"},  # negatif + yetkisiz anahtar
    )

    assert res["durum"] == "hata"
    db.refresh(v)
    assert v.payment_days == 90       # mutasyon yok
    assert v.status == "normal"       # whitelist: status hiç uygulanmadı


def test_propose_mutasyon_yapmaz(db):
    """Chat döngüsündeki proposer yalnız öneri döndürür, veriyi değiştirmez."""
    admin = _admin(db)
    v = _vendor(db, payment_days=90)

    res = ai_service._propose_cari_vade(
        db, admin, {"hesap_kodu": v.hesap_kodu, "yeni_vade_gun": 30}
    )

    assert res.get("_propose") is True
    assert res["entity_id"] == v.id
    assert res["payload"] == {"payment_days": 30}
    db.refresh(v)
    assert v.payment_days == 90  # öneri mutasyon yapmadı


def test_propose_gecersiz_durum_hata(db):
    admin = _admin(db)
    res = ai_service._propose_cek_durum(db, admin, {"cek_no": "X", "yeni_durum": "belirsiz"})
    assert res.get("_error") is True
