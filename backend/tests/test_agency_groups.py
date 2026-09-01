"""Acente grupları modülü testleri (sales.agency_groups).

Endpoint'ler:
- GET /api/sales/agency-groups/ — Liste
- POST /api/sales/agency-groups/ — Yeni grup
- PATCH /api/sales/agency-groups/{id} — Güncelle
- DELETE /api/sales/agency-groups/{id} — Sil
- POST /api/sales/agency-groups/assign — Acente ata/çıkar (atomik)

İzin: sales.acente_mahsup view/use (2026-07-09 birleştirme)
"""
import pytest

from app.models.agency_group import AgencyGroup


PREFIX = "/api/sales/agency-groups"


@pytest.fixture(autouse=True)
def _wipe_groups(db):
    """Her test başında agency_groups tablosunu temizle.

    Migration seed (7 grup) testler için belirsiz başlangıç yaratır.
    """
    db.query(AgencyGroup).delete()
    db.flush()
    yield


def _seed_group(db, **overrides):
    defaults = dict(name="TEST", members=[])
    defaults.update(overrides)
    grp = AgencyGroup(**defaults)
    db.add(grp)
    db.flush()
    return grp


# ─── Yetki ──────────────────────────────────────────────


def test_list_requires_auth(client):
    res = client.get(f"{PREFIX}/")
    assert res.status_code in (401, 403)


def test_create_requires_auth(client):
    res = client.post(f"{PREFIX}/", json={"name": "X"})
    assert res.status_code in (401, 403)


def test_update_requires_auth(client):
    res = client.patch(f"{PREFIX}/1", json={"name": "Y"})
    assert res.status_code in (401, 403)


def test_delete_requires_auth(client):
    res = client.delete(f"{PREFIX}/1")
    assert res.status_code in (401, 403)


def test_assign_requires_auth(client):
    res = client.post(f"{PREFIX}/assign", json={"agency_name": "AG"})
    assert res.status_code in (401, 403)


# ─── Liste ──────────────────────────────────────────────


def test_list_empty(client, auth_headers):
    """Boş tablo []  döner."""
    res = client.get(f"{PREFIX}/", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


def test_list_returns_groups(client, auth_headers, db):
    """Var olan gruplar listelenir, isimle sıralı."""
    _seed_group(db, name="ZULU", members=["A"])
    _seed_group(db, name="ALPHA", members=["B", "C"])
    _seed_group(db, name="MIKE", members=[])

    res = client.get(f"{PREFIX}/", headers=auth_headers)
    assert res.status_code == 200
    groups = res.json()
    assert len(groups) == 3
    names = [g["name"] for g in groups]
    assert names == ["ALPHA", "MIKE", "ZULU"]


# ─── Oluştur ────────────────────────────────────────────


def test_create_group(client, auth_headers, db):
    """Yeni grup oluşturulur, 201 döner. İsim büyük harfe çevrilir."""
    res = client.post(
        f"{PREFIX}/",
        json={"name": "yenigrup", "members": ["AC1", "AC2"]},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["name"] == "YENIGRUP"
    assert data["members"] == ["AC1", "AC2"]

    db.expire_all()
    grp = db.query(AgencyGroup).filter(AgencyGroup.name == "YENIGRUP").first()
    assert grp is not None


def test_create_duplicate_name_returns_409(client, auth_headers, db):
    """Aynı isimde ikinci grup 409 döner."""
    _seed_group(db, name="MEVCUT")

    res = client.post(
        f"{PREFIX}/",
        json={"name": "MEVCUT", "members": []},
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert "zaten mevcut" in res.json()["detail"].lower()


def test_create_validation_empty_name(client, auth_headers):
    """Boş isim 422 döner (min_length=1)."""
    res = client.post(
        f"{PREFIX}/",
        json={"name": "", "members": []},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_create_default_empty_members(client, auth_headers, db):
    """members verilmezse [] varsayılan kullanılır."""
    res = client.post(
        f"{PREFIX}/",
        json={"name": "BOSURETIM"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["members"] == []


# ─── Güncelle ───────────────────────────────────────────


def test_update_group_rename(client, auth_headers, db):
    """Grup adı güncellenir (yeni isim büyük harfe çevrilir)."""
    grp = _seed_group(db, name="ESKI", members=["X"])

    res = client.patch(
        f"{PREFIX}/{grp.id}",
        json={"name": "yeni"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["name"] == "YENI"
    # Members değişmemeli
    assert res.json()["members"] == ["X"]


def test_update_group_members_dedupes(client, auth_headers, db):
    """members güncelleme tekrarları ve boşları temizler."""
    grp = _seed_group(db, name="MEMBERS")

    res = client.patch(
        f"{PREFIX}/{grp.id}",
        json={"members": ["A", "B", "A", "  ", "C", "B"]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    # Sıra korunur, tekrar ve boş atılır
    assert res.json()["members"] == ["A", "B", "C"]


def test_update_name_conflict_returns_409(client, auth_headers, db):
    """Mevcut başka grubun adıyla çakışırsa 409."""
    _seed_group(db, name="VAR")
    grp2 = _seed_group(db, name="DEGISECEK")

    res = client.patch(
        f"{PREFIX}/{grp2.id}",
        json={"name": "var"},
        headers=auth_headers,
    )
    assert res.status_code == 409


def test_update_nonexistent_returns_404(client, auth_headers):
    """Var olmayan ID için 404."""
    res = client.patch(
        f"{PREFIX}/9999999",
        json={"name": "X"},
        headers=auth_headers,
    )
    assert res.status_code == 404


# ─── Sil ────────────────────────────────────────────────


def test_delete_group(client, auth_headers, db):
    """Grup silinir, 204 döner."""
    grp = _seed_group(db, name="SILIN")
    gid = grp.id

    res = client.delete(f"{PREFIX}/{gid}", headers=auth_headers)
    assert res.status_code == 204

    db.expire_all()
    assert db.query(AgencyGroup).filter(AgencyGroup.id == gid).first() is None


def test_delete_nonexistent_returns_404(client, auth_headers):
    """Var olmayan grup için 404."""
    res = client.delete(f"{PREFIX}/9999999", headers=auth_headers)
    assert res.status_code == 404


# ─── /assign — Drag-Drop Atomik Atama ────────────────────


def test_assign_agency_to_target_group(client, auth_headers, db):
    """Bir acenteyi hedef gruba ekler."""
    grp = _seed_group(db, name="HEDEF", members=[])

    res = client.post(
        f"{PREFIX}/assign",
        json={"agency_name": "ANEX EU", "target_group_id": grp.id},
        headers=auth_headers,
    )
    assert res.status_code == 200
    groups = res.json()
    hedef = next(g for g in groups if g["id"] == grp.id)
    assert "ANEX EU" in hedef["members"]


def test_assign_moves_from_old_group(client, auth_headers, db):
    """Acente eski grubundan çıkarılır, yeniye eklenir (atomik)."""
    eski = _seed_group(db, name="ESKI", members=["CORAL RU", "BAGCI"])
    yeni = _seed_group(db, name="YENI", members=[])

    res = client.post(
        f"{PREFIX}/assign",
        json={"agency_name": "CORAL RU", "target_group_id": yeni.id},
        headers=auth_headers,
    )
    assert res.status_code == 200
    groups = {g["name"]: g for g in res.json()}
    assert "CORAL RU" not in groups["ESKI"]["members"]
    assert "BAGCI" in groups["ESKI"]["members"]  # Diğer üye etkilenmedi
    assert "CORAL RU" in groups["YENI"]["members"]


def test_assign_remove_only(client, auth_headers, db):
    """target_group_id=None ile acente tüm gruplardan çıkarılır."""
    grp = _seed_group(db, name="UYE", members=["ABC", "DEF"])

    res = client.post(
        f"{PREFIX}/assign",
        json={"agency_name": "ABC", "target_group_id": None},
        headers=auth_headers,
    )
    assert res.status_code == 200
    groups = {g["name"]: g for g in res.json()}
    assert "ABC" not in groups["UYE"]["members"]
    assert "DEF" in groups["UYE"]["members"]


def test_assign_noop_if_already_in_target(client, auth_headers, db):
    """Acente zaten hedef gruptaysa sessizce başarılı döner."""
    grp = _seed_group(db, name="ZATEN", members=["XYZ"])

    res = client.post(
        f"{PREFIX}/assign",
        json={"agency_name": "XYZ", "target_group_id": grp.id},
        headers=auth_headers,
    )
    assert res.status_code == 200
    # Member'lar değişmemeli
    groups = {g["name"]: g for g in res.json()}
    assert groups["ZATEN"]["members"] == ["XYZ"]


def test_assign_empty_agency_name_fails(client, auth_headers, db):
    """Boş acente adı 400 veya 422 döner."""
    grp = _seed_group(db, name="X")
    res = client.post(
        f"{PREFIX}/assign",
        json={"agency_name": "   ", "target_group_id": grp.id},
        headers=auth_headers,
    )
    # Backend trim sonrası "boş olamaz" 400 döner
    assert res.status_code in (400, 422)


def test_assign_to_nonexistent_target_returns_404(client, auth_headers):
    """Hedef grup yoksa 404."""
    res = client.post(
        f"{PREFIX}/assign",
        json={"agency_name": "ACENTE", "target_group_id": 9999999},
        headers=auth_headers,
    )
    assert res.status_code == 404


# ─── Ödeme günü hizalaması — payment_alignment (2026-09-01) ─────
# Denetim Y2: alan daha önce yalnız SQL ile set edilebiliyordu; API'den okunup yazılır,
# geçersiz değer şemada (pydantic pattern) 422 ile reddedilir.


def test_create_defaults_payment_alignment_friday(client, auth_headers):
    res = client.post(f"{PREFIX}/", json={"name": "HIZASIZ"}, headers=auth_headers)
    assert res.status_code == 201, res.text
    assert res.json()["payment_alignment"] == "friday"


def test_create_with_payment_alignment_day_of_month(client, auth_headers, db):
    res = client.post(
        f"{PREFIX}/",
        json={"name": "NORDIC TEST", "payment_alignment": "day_27"},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["payment_alignment"] == "day_27"
    db.expire_all()
    grp = db.query(AgencyGroup).filter(AgencyGroup.name == "NORDIC TEST").first()
    assert grp.payment_alignment == "day_27"


@pytest.mark.parametrize("bad", ["monday", "day_0", "day_32", "day_07", "DAY_5", "checkin ", ""])
def test_payment_alignment_invalid_values_422(client, auth_headers, db, bad):
    """Kabul edilen tek yazım: friday | month_end | checkin | day_1..day_31 (öncü sıfır yok)."""
    res = client.post(
        f"{PREFIX}/", json={"name": "KOTU", "payment_alignment": bad}, headers=auth_headers,
    )
    assert res.status_code == 422, res.text
    grp = _seed_group(db, name="GUNCEL")
    res = client.patch(f"{PREFIX}/{grp.id}", json={"payment_alignment": bad}, headers=auth_headers)
    assert res.status_code == 422, res.text


def test_update_payment_alignment_all_modes(client, auth_headers, db):
    grp = _seed_group(db, name="HIZA")
    for value in ("month_end", "checkin", "day_1", "day_31", "friday"):
        res = client.patch(
            f"{PREFIX}/{grp.id}", json={"payment_alignment": value}, headers=auth_headers,
        )
        assert res.status_code == 200, res.text
        assert res.json()["payment_alignment"] == value
    db.expire_all()
    assert db.get(AgencyGroup, grp.id).payment_alignment == "friday"


def test_update_without_alignment_keeps_existing(client, auth_headers, db):
    """Yalnız vade gönderilirse mevcut hizalama korunur (exclude_unset)."""
    grp = _seed_group(db, name="KORU", payment_alignment="checkin")
    res = client.patch(f"{PREFIX}/{grp.id}", json={"term_days": 15}, headers=auth_headers)
    assert res.status_code == 200, res.text
    assert res.json()["payment_alignment"] == "checkin"
    assert res.json()["term_days"] == 15


def test_list_exposes_payment_alignment(client, auth_headers, db):
    _seed_group(db, name="LISTE", payment_alignment="month_end")
    res = client.get(f"{PREFIX}/", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()[0]["payment_alignment"] == "month_end"


def test_service_rejects_invalid_alignment_outside_schema(db):
    """Executor yolu pydantic'ten geçmez → service kendi doğrulamasını yapmalı."""
    from app.services import agency_group_service

    grp = _seed_group(db, name="SERVIS")
    with pytest.raises(ValueError):
        agency_group_service.apply_group_update(db, grp, {"payment_alignment": "day_40"})
    with pytest.raises(ValueError):
        agency_group_service.create_group(db, {"name": "X", "payment_alignment": "tuesday"})
