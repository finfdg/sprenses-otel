"""Cari banka/IBAN yönetimi + ödeme talimatı IBAN seçimi testleri.

İlk IBAN otomatik varsayılan, IBAN normalize, mükerrer 409, varsayılan değiştirme,
varsayılan silinince devir. PI'ye otomatik varsayılan IBAN + manuel değiştirme + export.
"""
import uuid

import pytest

from app.models.vendor import Vendor

C = "/api/finance/cariler"
PI = "/api/finance/payment-instructions"


@pytest.fixture
def vendor(db):
    v = Vendor(hesap_kodu="320.TEST." + uuid.uuid4().hex[:6], hesap_adi="Test Cari A")
    db.add(v)
    db.flush()
    return v.id


def test_first_iban_default_normalize_dup(client, auth_headers, vendor):
    r = client.post(f"{C}/vendors/{vendor}/bank-accounts",
                    json={"bank_name": "Yapı Kredi", "iban": "TR12 0006 7010 0000 0012 3456 78"},
                    headers=auth_headers)
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["is_default"] is True
    assert j["iban"] == "TR120006701000000012345678"   # normalize (büyük harf, boşluksuz)
    # ikinci → varsayılan değil
    r2 = client.post(f"{C}/vendors/{vendor}/bank-accounts",
                     json={"bank_name": "Garanti", "iban": "tr330006200000000098765432"}, headers=auth_headers)
    assert r2.status_code == 201 and r2.json()["is_default"] is False
    # mükerrer IBAN → 409
    assert client.post(f"{C}/vendors/{vendor}/bank-accounts",
                       json={"iban": "TR120006701000000012345678"}, headers=auth_headers).status_code == 409


def test_set_default_and_delete_transfers(client, auth_headers, vendor):
    a = client.post(f"{C}/vendors/{vendor}/bank-accounts", json={"iban": "TR000000000000000000000001"}, headers=auth_headers).json()
    b = client.post(f"{C}/vendors/{vendor}/bank-accounts", json={"iban": "TR000000000000000000000002"}, headers=auth_headers).json()
    client.patch(f"{C}/vendors/{vendor}/bank-accounts/{b['id']}", json={"is_default": True}, headers=auth_headers)
    lst = {x["id"]: x["is_default"] for x in client.get(f"{C}/vendors/{vendor}/bank-accounts", headers=auth_headers).json()}
    assert lst[b["id"]] is True and lst[a["id"]] is False
    # varsayılan (b) silinince kalan (a) varsayılan olur
    client.delete(f"{C}/vendors/{vendor}/bank-accounts/{b['id']}", headers=auth_headers)
    lst2 = client.get(f"{C}/vendors/{vendor}/bank-accounts", headers=auth_headers).json()
    assert len(lst2) == 1 and lst2[0]["id"] == a["id"] and lst2[0]["is_default"] is True


def test_bank_account_requires_use(client, viewer_user_headers, vendor):
    assert client.post(f"{C}/vendors/{vendor}/bank-accounts",
                       json={"iban": "TR1"}, headers=viewer_user_headers).status_code == 403


def test_pi_autofills_default_iban_select_export(client, auth_headers, vendor):
    client.post(f"{C}/vendors/{vendor}/bank-accounts",
                json={"bank_name": "Yapı Kredi", "iban": "TR120006701000000012345678"}, headers=auth_headers)
    pl = client.post(f"{PI}/", json={"name": "Test Talimat", "items": []}, headers=auth_headers).json()
    add = client.post(f"{PI}/{pl['id']}/items",
                      json={"items": [{"vendor_id": vendor, "hesap_adi": "Test Cari A", "amount": 100}]},
                      headers=auth_headers).json()
    it = add["items"][0]
    # varsayılan banka/IBAN otomatik geldi
    assert it["bank_name"] == "Yapı Kredi" and it["iban"] == "TR120006701000000012345678"
    # manuel değiştir (normalize)
    upd = client.patch(f"{PI}/{pl['id']}/items/{it['id']}",
                       json={"bank_name": "Garanti", "iban": "tr33 0006 2000 0000 0098 7654 32"},
                       headers=auth_headers).json()
    assert upd["iban"] == "TR330006200000000098765432" and upd["bank_name"] == "Garanti"
    # export (PDF + Excel) IBAN sütunlu — 200
    assert client.get(f"{PI}/{pl['id']}/export/pdf", headers=auth_headers).status_code == 200
    assert client.get(f"{PI}/{pl['id']}/export/excel", headers=auth_headers).status_code == 200
