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
from app.models.scheduled import ScheduledDefinition
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


# ── Faz 2 genişletme — ödeme yasağı + avans ekle + düzenli ödeme ekle ──────────

def test_execute_cari_odeme_yasagi(db):
    """cari_durum (update) → cari 'ödeme yasaklısı' olur."""
    admin = _admin(db)
    v = _vendor(db, status="normal")
    res = ai_service.execute_action(db, admin, "cari_durum", v.id, {"status": "odeme_yasaklisi"})
    assert res["durum"] == "uygulandi", res
    db.refresh(v)
    assert v.status == "odeme_yasaklisi"


def test_execute_avans_ekle_create(db):
    """avans_ekle (create) → yeni Advance kaydı oluşur (tarih string→date coercion)."""
    from app.models.advance import Advance
    admin = _admin(db)
    res = ai_service.execute_action(db, admin, "avans_ekle", 0, {
        "agency_name": "TEST ACENTE AI", "amount": 1500.0, "currency": "EUR",
        "advance_date": "2026-07-15", "notes": "test",
    })
    assert res["durum"] == "uygulandi", res
    adv = db.query(Advance).filter(Advance.agency_name == "TEST ACENTE AI").first()
    assert adv is not None
    assert float(adv.amount) == 1500.0 and adv.currency == "EUR"


def test_execute_duzenli_odeme_create(db):
    """duzenli_odeme_ekle (create) → yeni ScheduledDefinition (source_type=recurring) oluşur."""
    admin = _admin(db)
    res = ai_service.execute_action(db, admin, "duzenli_odeme_ekle", 0, {
        "name": "TEST DUZENLI AI", "amount": 500.0, "currency": "TRY",
        "frequency": "monthly", "payment_day": 10, "start_month": 1,
    })
    assert res["durum"] == "uygulandi", res
    d = (
        db.query(ScheduledDefinition)
        .filter(ScheduledDefinition.name == "TEST DUZENLI AI")
        .first()
    )
    assert d is not None
    assert d.source_type == "recurring" and float(d.amount) == 500.0


def test_execute_avans_gecersiz_tutar_reddedilir(db):
    admin = _admin(db)
    res = ai_service.execute_action(db, admin, "avans_ekle", 0, {
        "agency_name": "X", "amount": -5, "advance_date": "2026-07-15",
    })
    assert res["durum"] == "hata"


# ── Konuşma sürekliliği (hafıza) + yeni okuma araçları ────────────────────────

def test_seed_messages_ilk_mesaj_user():
    """Geçmiş baştaki assistant turlarını at, yeni soruyu sona ekle, ilk mesaj user olsun."""
    gecmis = [
        {"rol": "assistant", "metin": "önceki yanıt (atılmalı)"},
        {"rol": "user", "metin": "önceki soru"},
        {"rol": "assistant", "metin": "önceki cevap"},
    ]
    msgs = ai_service._seed_messages("yeni soru", gecmis)
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "önceki soru"        # baştaki assistant atıldı
    assert msgs[-1] == {"role": "user", "content": "yeni soru"}


def test_seed_messages_gecmissiz():
    msgs = ai_service._seed_messages("tek soru", None)
    assert msgs == [{"role": "user", "content": "tek soru"}]


def test_cari_detay(db):
    """cari_detay carinin vadesini/bakiyesini/durumunu okur."""
    admin = _admin(db)
    v = _vendor(db, payment_days=75, status="normal")
    res = ai_service._tool_cari_detay(db, admin, {"hesap_kodu": v.hesap_kodu})
    assert res["odeme_vadesi_gun"] == 75
    assert res["durum"] == "Normal"
    assert res["hesap_kodu"] == v.hesap_kodu


def test_kredi_durumu_yapisi(db):
    admin = _admin(db)
    res = ai_service._tool_kredi_durumu(db, admin, {})
    assert "para_bazli" in res and "krediler" in res


def test_yaklasan_odemeler_yapisi(db):
    admin = _admin(db)
    res = ai_service._tool_yaklasan_odemeler(db, admin, {"gun_sayisi": 7})
    assert res["gun_sayisi"] == 7 and "para_bazli" in res and "odemeler" in res


def test_execute_cari_not_onaydan_muaf(db):
    """cari_not (approval_exempt create) → VendorNote doğrudan oluşur (onay yok)."""
    from app.models.vendor_note import VendorNote
    admin = _admin(db)
    v = _vendor(db)
    res = ai_service.execute_action(
        db, admin, "cari_not", 0, {"vendor_id": v.id, "text": "Test not — AI"}
    )
    assert res["durum"] == "uygulandi", res
    note = db.query(VendorNote).filter(VendorNote.vendor_id == v.id).first()
    assert note is not None and note.text == "Test not — AI"


def test_gunluk_nakit_akim_yapisi(db):
    admin = _admin(db)
    res = ai_service._tool_gunluk_nakit_akim(db, admin, {"para_birimi": "TRY"})
    assert "gunluk" in res and res["para_birimi"] == "TRY"
    assert isinstance(res["gunluk"], list)


def test_compute_cost():
    # 1M girdi + 1M çıktı = 5 + 25 = 30 USD
    c = ai_service.compute_cost({"input": 1_000_000, "output": 1_000_000, "cache_read": 0, "cache_write": 0})
    assert abs(c - 30.0) < 1e-6


def test_record_usage_satir_ekler(db):
    from app.models.ai_usage import AiUsage
    admin = _admin(db)
    before = db.query(AiUsage).count()
    ai_service.record_usage(db, admin.id, {"input": 1000, "output": 500, "cache_read": 0, "cache_write": 0}, 2)
    db.flush()
    assert db.query(AiUsage).count() == before + 1
    row = db.query(AiUsage).order_by(AiUsage.id.desc()).first()
    assert row.input_tokens == 1000 and row.output_tokens == 500 and row.tool_count == 2
    assert float(row.cost_usd) > 0


def test_read_izin_yoksa_reddedilir(db):
    """finance.krediler görme izni olmayan kullanıcı kredi durumunu okuyamaz."""
    import uuid
    role = Role(name=f"nokredi_{uuid.uuid4().hex[:6]}", description="izinsiz")
    db.add(role)
    db.flush()
    user = User(
        username=f"nokredi_{uuid.uuid4().hex[:6]}",
        email=f"nokredi_{uuid.uuid4().hex[:6]}@test.local",
        first_name="No", last_name="Kredi",
        hashed_password=hash_password("Test1234!"),
        role_id=role.id, is_active=True,
    )
    db.add(user)
    res = ai_service._tool_kredi_durumu(db, user, {})
    assert res.get("_error") is True


def test_execute_izin_yoksa_avans_eklenemez(db):
    """finance.avanslar can_use olmayan kullanıcı avans ekleyemez."""
    import uuid
    from app.models.advance import Advance
    role = Role(name=f"noperm_av_{uuid.uuid4().hex[:6]}", description="izinsiz")
    db.add(role)
    db.flush()
    user = User(
        username=f"noperm_av_{uuid.uuid4().hex[:6]}",
        email=f"noperm_av_{uuid.uuid4().hex[:6]}@test.local",
        first_name="No", last_name="Perm",
        hashed_password=hash_password("Test1234!"),
        role_id=role.id, is_active=True,
    )
    db.add(user)
    before = db.query(Advance).count()
    res = ai_service.execute_action(db, user, "avans_ekle", 0, {
        "agency_name": "YETKI YOK", "amount": 100.0, "advance_date": "2026-07-15",
    })
    assert res["durum"] == "hata"
    assert db.query(Advance).count() == before  # kayıt oluşmadı
