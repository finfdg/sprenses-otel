"""Alınan Avanslar modülü testleri."""
import pytest
from datetime import date
from unittest.mock import patch

REC = "app.routers.finance.advances"


def test_sedna_reconciliation_matches(client, auth_headers, db):
    """Manuel avans ↔ Sedna 340 eşleşir (isim) + Sedna-only avanslar raporlanır."""
    from app.models.advance import Advance
    db.add(Advance(agency_name="Alltours", amount=4748000, currency="EUR",
                   status="received", received_amount=4748000, advance_date=date(2026, 1, 1)))
    db.flush()
    fake = [
        {"code": "340.02.01.0017", "name": "ALLTOURS FLUGREİSEN", "currency": "EUR",
         "received": 4748000, "consumed": 592630},
        {"code": "340.01.01.0099", "name": "LAVİNYA OTELCİLİK TURİZM", "currency": "TL",
         "received": 3432964, "consumed": 0},
    ]
    with patch(f"{REC}.sedna_configured", return_value=True), \
         patch(f"{REC}.fetch_advance_accounts", return_value=fake):
        r = client.get("/api/finance/avanslar/sedna-reconciliation", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        m = next(x for x in d["matched"] if x["agency_name"] == "Alltours")
        assert m["matched"] and m["sedna_code"] == "340.02.01.0017"
        assert m["sedna_received"] == 4748000.0 and m["variance"] == 0.0
        assert m["sedna_remaining"] == 4155370.0   # 4748000 - 592630
        assert any(x["sedna_code"] == "340.01.01.0099" for x in d["sedna_only"])  # manuelde yok


def test_reconciliation_not_configured_503(client, auth_headers):
    with patch(f"{REC}.sedna_configured", return_value=False):
        assert client.get("/api/finance/avanslar/sedna-reconciliation", headers=auth_headers).status_code == 503


def test_list_advances_empty(client, auth_headers):
    """Boş avans listesi testi."""
    r = client.get("/api/finance/avanslar/", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 0


def test_create_advance(client, auth_headers):
    """Yeni avans oluşturma testi."""
    payload = {
        "agency_name": "Test Acente",
        "amount": 10000.00,
        "currency": "EUR",
        "advance_date": "2026-04-15",
        "notes": "Test avansı",
    }
    r = client.post("/api/finance/avanslar/", json=payload, headers=auth_headers)
    assert r.status_code == 201
    data = r.json()
    assert data["agency_name"] == "Test Acente"
    assert data["amount"] == 10000.00
    assert data["currency"] == "EUR"
    assert data["status"] == "pending"
    return data["id"]


def test_summary(client, auth_headers):
    """Özet testi."""
    r = client.get("/api/finance/avanslar/summary", headers=auth_headers)
    assert r.status_code == 200


def test_update_advance(client, auth_headers):
    """Avans güncelleme testi."""
    # Create first
    payload = {
        "agency_name": "Güncelleme Testi",
        "amount": 5000.00,
        "currency": "USD",
        "advance_date": "2026-05-01",
    }
    r = client.post("/api/finance/avanslar/", json=payload, headers=auth_headers)
    assert r.status_code == 201
    adv_id = r.json()["id"]

    # Update
    r = client.patch(f"/api/finance/avanslar/{adv_id}", json={"notes": "Güncellenmiş"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["notes"] == "Güncellenmiş"


def test_match_advance(client, auth_headers):
    """Avans eşleştirme testi."""
    # Create
    payload = {
        "agency_name": "Eşleştirme Testi",
        "amount": 8000.00,
        "currency": "EUR",
        "advance_date": "2026-04-20",
    }
    r = client.post("/api/finance/avanslar/", json=payload, headers=auth_headers)
    assert r.status_code == 201
    adv_id = r.json()["id"]

    # Match
    r = client.post(f"/api/finance/avanslar/{adv_id}/match", json={
        "received_date": "2026-04-21",
        "received_amount": 7950.00,
    }, headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "received"
    assert data["received_amount"] == 7950.00


def test_delete_advance(client, auth_headers):
    """Avans silme testi."""
    # Create
    payload = {
        "agency_name": "Silinecek",
        "amount": 3000.00,
        "currency": "TRY",
        "advance_date": "2026-06-01",
    }
    r = client.post("/api/finance/avanslar/", json=payload, headers=auth_headers)
    assert r.status_code == 201
    adv_id = r.json()["id"]

    # Delete
    r = client.delete(f"/api/finance/avanslar/{adv_id}", headers=auth_headers)
    assert r.status_code == 200


def test_delete_received_advance_fails(client, auth_headers):
    """Alınmış avans silinemez."""
    # Create & match
    payload = {
        "agency_name": "Silinemez",
        "amount": 2000.00,
        "currency": "EUR",
        "advance_date": "2026-04-25",
    }
    r = client.post("/api/finance/avanslar/", json=payload, headers=auth_headers)
    assert r.status_code == 201
    adv_id = r.json()["id"]

    r = client.post(f"/api/finance/avanslar/{adv_id}/match", json={
        "received_date": "2026-04-26",
        "received_amount": 2000.00,
    }, headers=auth_headers)
    assert r.status_code == 200

    # Try to delete
    r = client.delete(f"/api/finance/avanslar/{adv_id}", headers=auth_headers)
    assert r.status_code == 400


# ─── Otomatik Eşleştirme (ekstre yükleme sonrası) ─────────


def _mk_advance(db, agency, amount, currency, adv_date):
    """FE'li bekleyen avans oluştur (servis üzerinden — router ile aynı yol)."""
    from app.services import advance_service

    adv = advance_service.create_advance(db, {
        "agency_name": agency,
        "amount": amount,
        "currency": currency,
        "advance_date": adv_date,
    }, actor_id=None)
    db.flush()
    return adv


def _mk_bank_income(db, iban, currency, amount, tx_date, description, tx_hash):
    """Hesap + gelir işlemi oluştur, banka FE'sini üret."""
    from app.models.bank_account import BankAccount
    from app.models.bank_transaction import BankTransaction
    from app.utils.finance_event_service import finance_event_svc

    acc = BankAccount(bank_name="Avans Match Bank", iban=iban, currency=currency, is_active=True)
    db.add(acc)
    db.flush()
    btx = BankTransaction(
        account_id=acc.id, date=tx_date, amount=amount, type="income",
        description=description, tx_hash=tx_hash,
    )
    db.add(btx)
    db.flush()
    finance_event_svc.upsert_bank_tx(db, btx, acc)
    return btx


def test_auto_match_advance_by_agency_name(db):
    """Acente adı açıklamada geçiyorsa geniş tarih penceresinde eşleşir;
    avans 'received' olur, FE is_matched=True + event_status='received',
    banka FE görünür kalır (is_realized=True) → nakit akımda çift sayım kapanır."""
    from app.models.finance_event import FinanceEvent
    from app.utils.matching_service import _match_advances_to_bank

    adv = _mk_advance(db, "Alltours Flugreisen GmbH", 250000, "EUR", date(2026, 6, 20))
    btx = _mk_bank_income(
        db, "TR990000000000000000000201", "EUR", 250000, date(2026, 7, 10),
        "Swift şubeden para yatırma Ref: ALLTOURS FLUGREISEN", "adv-automatch-1",
    )

    res = _match_advances_to_bank(db)
    db.flush()
    assert res["matched"] == 1

    db.refresh(adv)
    assert adv.status == "received"
    assert adv.bank_transaction_id == btx.id
    assert float(adv.received_amount) == 250000
    assert adv.received_date == date(2026, 7, 10)

    adv_fe = db.query(FinanceEvent).filter(
        FinanceEvent.source_type == "advance", FinanceEvent.source_id == adv.id
    ).first()
    assert adv_fe.is_matched is True
    assert adv_fe.event_status == "received"

    bank_fe = db.query(FinanceEvent).filter(
        FinanceEvent.source_type == "bank", FinanceEvent.source_id == btx.id
    ).first()
    assert bank_fe.is_matched is False  # banka bacağı listede kalır
    assert bank_fe.is_realized is True


def test_auto_match_advance_blind_close_date(db):
    """İsim geçmese de tutar+para birimi+yakın tarih (kör yol) eşleşir."""
    from app.utils.matching_service import _match_advances_to_bank

    adv = _mk_advance(db, "Körtest Acentesi", 120000, "EUR", date(2026, 7, 8))
    _mk_bank_income(
        db, "TR990000000000000000000202", "EUR", 120000, date(2026, 7, 10),
        "Swift şubeden para yatırma Ref: 03PR99", "adv-automatch-2",
    )

    res = _match_advances_to_bank(db)
    assert res["matched"] == 1
    db.refresh(adv)
    assert adv.status == "received"


def test_auto_match_advance_blind_far_date_skipped(db):
    """İsim yok + tarih uzak (>10 gün) → eşleşmez (yanlış-pozitif koruması)."""
    from app.utils.matching_service import _match_advances_to_bank

    adv = _mk_advance(db, "Uzaktarih Acentesi", 90000, "EUR", date(2026, 5, 1))
    _mk_bank_income(
        db, "TR990000000000000000000203", "EUR", 90000, date(2026, 7, 10),
        "Swift şubeden para yatırma Ref: 03PR77", "adv-automatch-3",
    )

    res = _match_advances_to_bank(db)
    assert res["matched"] == 0
    db.refresh(adv)
    assert adv.status == "pending"


def test_auto_match_advance_currency_mismatch_skipped(db):
    """Para birimi farklıysa (TRY hesaba EUR avans) eşleşmez."""
    from app.utils.matching_service import _match_advances_to_bank

    adv = _mk_advance(db, "Dövizfark Acentesi", 50000, "EUR", date(2026, 7, 9))
    _mk_bank_income(
        db, "TR990000000000000000000204", "TRY", 50000, date(2026, 7, 10),
        "Havale DÖVIZFARK ACENTESI", "adv-automatch-4",
    )

    res = _match_advances_to_bank(db)
    assert res["matched"] == 0
    db.refresh(adv)
    assert adv.status == "pending"


def test_auto_match_advance_virman_skipped(db):
    """Virman (hesaplar arası aktarım) açıklaması aday olamaz."""
    from app.utils.matching_service import _match_advances_to_bank

    adv = _mk_advance(db, "Virmantest Acentesi", 75000, "EUR", date(2026, 7, 9))
    _mk_bank_income(
        db, "TR990000000000000000000205", "EUR", 75000, date(2026, 7, 10),
        "Virman Döviz Satış VIRMANTEST", "adv-automatch-5",
    )

    res = _match_advances_to_bank(db)
    assert res["matched"] == 0
    db.refresh(adv)
    assert adv.status == "pending"


def test_auto_match_advance_early_payment_skipped(db):
    """İsim geçse bile beklenen tarihten >10 gün ÖNCE gelen para eşleşmez —
    erken gelen para önceki taksitin tahsilatıdır (canlı vaka: 10.06 Swift'i
    20.07 taksitine bağlanıyordu)."""
    from app.utils.matching_service import _match_advances_to_bank

    adv = _mk_advance(db, "Erkentest Acentesi", 250000, "EUR", date(2026, 7, 20))
    _mk_bank_income(
        db, "TR990000000000000000000206", "EUR", 250000, date(2026, 6, 10),
        "Swift para yatırma Amir: ERKENTEST ACENTESI GmbH", "adv-automatch-6",
    )

    res = _match_advances_to_bank(db)
    assert res["matched"] == 0
    db.refresh(adv)
    assert adv.status == "pending"


def test_auto_match_advance_manual_receipt_tx_skipped(db):
    """Elle 'alındı' işaretlenmiş (banka bağlantısız) avansın karşılığı olan banka
    hareketi başka bir taksite aday olamaz (para birimi+tutar+tarih imzası)."""
    from app.services import advance_service
    from app.utils.matching_service import _match_advances_to_bank

    # Haziran taksiti elle alındı işaretlendi (btx bağlantısı YOK)
    received = advance_service.create_advance(db, {
        "agency_name": "Ellealdi Acentesi", "amount": 250000, "currency": "EUR",
        "advance_date": date(2026, 6, 10),
    }, actor_id=None)
    received.status = "received"
    received.received_date = date(2026, 6, 12)
    received.received_amount = 250000
    db.flush()

    # Temmuz taksiti hâlâ bekliyor
    pending = _mk_advance(db, "Ellealdi Acentesi", 250000, "EUR", date(2026, 6, 15))

    # Haziran taksitinin gerçek banka hareketi (elle işaretlemeyle aynı tarih+tutar)
    _mk_bank_income(
        db, "TR990000000000000000000207", "EUR", 250000, date(2026, 6, 12),
        "Swift para yatırma Amir: ELLEALDI ACENTESI GmbH", "adv-automatch-7",
    )

    res = _match_advances_to_bank(db)
    assert res["matched"] == 0
    db.refresh(pending)
    assert pending.status == "pending"
