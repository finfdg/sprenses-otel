"""Kredi ürünleri ve ödeme planı CRUD testleri.

Endpoint'ler: /api/finance/krediler/
"""

import pytest


# ─── Yardımcı ──────────────────────────────────────────────

def _create_product(client, auth_headers, **overrides):
    payload = {
        "type": "spot_kredi",
        "name": "Test Kredi",
        "bank_name": "Test Bank",
        "currency": "TRY",
        "total_amount": 100000,
        "remaining_amount": 80000,
        "interest_rate": 2.5,
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
    }
    payload.update(overrides)
    return client.post("/api/finance/krediler/", json=payload, headers=auth_headers)


def _add_payments(client, auth_headers, product_id, payments=None):
    if payments is None:
        payments = [
            {"installment_no": 1, "due_date": "2026-02-28", "amount": 10000, "principal": 8000, "interest": 2000},
            {"installment_no": 2, "due_date": "2026-03-31", "amount": 10000, "principal": 8000, "interest": 2000},
            {"installment_no": 3, "due_date": "2026-04-30", "amount": 10000, "principal": 8000, "interest": 2000},
        ]
    return client.post(
        f"/api/finance/krediler/{product_id}/payments",
        json={"payments": payments},
        headers=auth_headers,
    )


PREFIX = "/api/finance/krediler"


# ─── CREATE ─────────────────────────────────────────────────


class TestCreateProduct:

    def test_create_spot_kredi(self, client, auth_headers):
        resp = _create_product(client, auth_headers, type="spot_kredi")
        assert resp.status_code == 201
        data = resp.json()
        assert data["type"] == "spot_kredi"
        assert data["name"] == "Test Kredi"
        assert data["status"] == "active"

    def test_create_kredi_karti(self, client, auth_headers):
        resp = _create_product(client, auth_headers, type="kredi_karti", name="Kurumsal Kart")
        assert resp.status_code == 201
        assert resp.json()["type"] == "kredi_karti"

    def test_create_all_types(self, client, auth_headers):
        """Tüm kredi tipleri oluşturulabilmeli."""
        for t in ("kredi_karti", "kmh", "bch", "spot_kredi", "taksitli_kredi", "leasing"):
            resp = _create_product(client, auth_headers, type=t, name=f"Test {t}")
            assert resp.status_code == 201, f"Type {t} failed: {resp.text}"

    def test_create_invalid_type(self, client, auth_headers):
        resp = _create_product(client, auth_headers, type="invalid_type")
        assert resp.status_code == 400

    def test_create_with_details(self, client, auth_headers):
        resp = _create_product(client, auth_headers, details={"card_number": "****1234"})
        assert resp.status_code == 201

    def test_create_without_auth(self, client):
        resp = client.post(f"{PREFIX}/", json={
            "type": "spot_kredi", "name": "X", "total_amount": 100,
        })
        assert resp.status_code in (401, 403)


# ─── LIST ────────────────────────────────────────────────────


class TestListProducts:

    def test_list_structure(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data

    def test_list_with_product(self, client, auth_headers):
        _create_product(client, auth_headers, name="Liste Testi")
        resp = client.get(f"{PREFIX}/", headers=auth_headers)
        assert resp.json()["total"] >= 1

    def test_list_filter_by_type(self, client, auth_headers):
        _create_product(client, auth_headers, type="leasing", name="Leasing Testi")
        resp = client.get(f"{PREFIX}/?type_filter=leasing", headers=auth_headers)
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["type"] == "leasing"

    def test_list_filter_by_status(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/?status_filter=active", headers=auth_headers)
        assert resp.status_code == 200

    def test_list_search(self, client, auth_headers):
        _create_product(client, auth_headers, name="Benzersiz Arama Kredi")
        resp = client.get(f"{PREFIX}/?search=Benzersiz", headers=auth_headers)
        assert resp.status_code == 200
        names = [i["name"] for i in resp.json()["items"]]
        assert any("Benzersiz" in n for n in names)

    def test_list_pagination(self, client, auth_headers):
        _create_product(client, auth_headers, name="Sayfa A")
        _create_product(client, auth_headers, name="Sayfa B")
        resp = client.get(f"{PREFIX}/?page=1&page_size=1", headers=auth_headers)
        assert len(resp.json()["items"]) <= 1


# ─── GET DETAIL ──────────────────────────────────────────────


class TestGetProduct:

    def test_get_detail(self, client, auth_headers):
        create_resp = _create_product(client, auth_headers)
        pid = create_resp.json()["id"]
        resp = client.get(f"{PREFIX}/{pid}", headers=auth_headers)
        assert resp.status_code == 200
        assert "payments" in resp.json()

    def test_get_not_found(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/999999", headers=auth_headers)
        assert resp.status_code == 404


# ─── UPDATE ──────────────────────────────────────────────────


class TestUpdateProduct:

    def test_update_name(self, client, auth_headers):
        pid = _create_product(client, auth_headers).json()["id"]
        resp = client.patch(f"{PREFIX}/{pid}", json={"name": "Güncellendi"}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Güncellendi"

    def test_update_status(self, client, auth_headers):
        pid = _create_product(client, auth_headers).json()["id"]
        resp = client.patch(f"{PREFIX}/{pid}", json={"status": "inactive"}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "inactive"

    def test_update_not_found(self, client, auth_headers):
        resp = client.patch(f"{PREFIX}/999999", json={"name": "X"}, headers=auth_headers)
        assert resp.status_code == 404


# ─── DELETE ──────────────────────────────────────────────────


class TestDeleteProduct:

    def test_delete(self, client, auth_headers):
        pid = _create_product(client, auth_headers).json()["id"]
        resp = client.delete(f"{PREFIX}/{pid}", headers=auth_headers)
        assert resp.status_code == 204

        # Silindikten sonra 404
        assert client.get(f"{PREFIX}/{pid}", headers=auth_headers).status_code == 404

    def test_delete_not_found(self, client, auth_headers):
        resp = client.delete(f"{PREFIX}/999999", headers=auth_headers)
        assert resp.status_code in (404, 204)


# ─── PAYMENTS ────────────────────────────────────────────────


class TestPayments:

    def test_add_payments(self, client, auth_headers):
        pid = _create_product(client, auth_headers).json()["id"]
        resp = _add_payments(client, auth_headers, pid)
        assert resp.status_code in (200, 201)

    def test_add_payments_product_not_found(self, client, auth_headers):
        resp = _add_payments(client, auth_headers, 999999)
        assert resp.status_code == 404

    def test_update_payment_mark_paid(self, client, auth_headers):
        pid = _create_product(client, auth_headers).json()["id"]
        _add_payments(client, auth_headers, pid)

        # Ödeme listesini al
        detail = client.get(f"{PREFIX}/{pid}", headers=auth_headers).json()
        payment_id = detail["payments"][0]["id"]

        resp = client.patch(
            f"{PREFIX}/payments/{payment_id}",
            json={"is_paid": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["is_paid"] is True

    def test_update_payment_amount(self, client, auth_headers):
        pid = _create_product(client, auth_headers).json()["id"]
        _add_payments(client, auth_headers, pid)
        detail = client.get(f"{PREFIX}/{pid}", headers=auth_headers).json()
        payment_id = detail["payments"][0]["id"]

        resp = client.patch(
            f"{PREFIX}/payments/{payment_id}",
            json={"amount": 15000},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["amount"] == 15000.0

    def test_update_payment_not_found(self, client, auth_headers):
        resp = client.patch(
            f"{PREFIX}/payments/999999",
            json={"is_paid": True},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_delete_payment(self, client, auth_headers):
        pid = _create_product(client, auth_headers).json()["id"]
        _add_payments(client, auth_headers, pid)
        detail = client.get(f"{PREFIX}/{pid}", headers=auth_headers).json()
        payment_id = detail["payments"][0]["id"]

        resp = client.delete(f"{PREFIX}/payments/{payment_id}", headers=auth_headers)
        assert resp.status_code == 204

    def test_delete_payment_not_found(self, client, auth_headers):
        resp = client.delete(f"{PREFIX}/payments/999999", headers=auth_headers)
        assert resp.status_code in (404, 204)

    def test_paid_reduces_remaining(self, client, auth_headers):
        """Ödeme yapınca remaining_amount azalmalı."""
        create_resp = _create_product(client, auth_headers, remaining_amount=80000)
        pid = create_resp.json()["id"]
        _add_payments(client, auth_headers, pid)

        detail = client.get(f"{PREFIX}/{pid}", headers=auth_headers).json()
        payment_id = detail["payments"][0]["id"]

        # Öde (principal=8000)
        client.patch(
            f"{PREFIX}/payments/{payment_id}",
            json={"is_paid": True},
            headers=auth_headers,
        )

        # remaining_amount = 80000 - 8000 = 72000
        updated = client.get(f"{PREFIX}/{pid}", headers=auth_headers).json()
        assert updated["remaining_amount"] == 72000.0


# ─── SUMMARY ─────────────────────────────────────────────────


class TestSummary:

    def test_summary_structure(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/summary/by-type", headers=auth_headers)
        assert resp.status_code == 200
        # Yanıt bir liste olmalı
        assert isinstance(resp.json(), list)

    def test_summary_with_product(self, client, auth_headers):
        _create_product(client, auth_headers, type="spot_kredi")
        resp = client.get(f"{PREFIX}/summary/by-type", headers=auth_headers)
        types = [item["type"] for item in resp.json()]
        assert "spot_kredi" in types


# ─── UPCOMING PAYMENTS ───────────────────────────────────────


class TestUpcomingPayments:

    def test_upcoming_structure(self, client, auth_headers):
        resp = client.get(f"{PREFIX}/upcoming-payments?days=365", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_upcoming_without_auth(self, client):
        resp = client.get(f"{PREFIX}/upcoming-payments")
        assert resp.status_code in (401, 403)


# ─── CLOSE / REOPEN ──────────────────────────────────────────


class TestCloseReopen:
    """Kredi kapatma/yeniden açma + ileri vadeli ödeme nakit akım entegrasyonu."""

    def _setup_with_unpaid(self, client, auth_headers, db):
        """Kredi + 1 ödenmiş + 1 ödenmemiş taksit oluştur, FE'leri üret."""
        from app.models.credit_product import CreditPayment
        from app.models.finance_event import FinanceEvent

        pid = _create_product(client, auth_headers).json()["id"]
        _add_payments(client, auth_headers, pid, payments=[
            {"installment_no": 1, "due_date": "2026-02-28", "amount": 10000, "principal": 8000, "interest": 2000},
            {"installment_no": 2, "due_date": "2026-12-31", "amount": 50000, "principal": 48000, "interest": 2000},
        ])
        pays = db.query(CreditPayment).filter(CreditPayment.credit_product_id == pid).order_by(CreditPayment.due_date).all()
        # İlk taksiti ödendi işaretle
        client.patch(f"{PREFIX}/payments/{pays[0].id}", json={"is_paid": True}, headers=auth_headers)
        return pid, pays

    def test_close_sets_status_and_date(self, client, auth_headers):
        pid = _create_product(client, auth_headers).json()["id"]
        resp = client.post(f"{PREFIX}/{pid}/close", json={"closed_date": "2026-05-25"}, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "closed"
        assert data["closed_date"] == "2026-05-25"

    def test_close_default_date_today(self, client, auth_headers):
        pid = _create_product(client, auth_headers).json()["id"]
        resp = client.post(f"{PREFIX}/{pid}/close", json={}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["closed_date"] is not None

    def test_close_removes_unpaid_finance_events(self, client, auth_headers, db):
        from app.models.credit_product import CreditPayment
        from app.models.finance_event import FinanceEvent

        pid, pays = self._setup_with_unpaid(client, auth_headers, db)
        unpaid = db.query(CreditPayment).filter(
            CreditPayment.credit_product_id == pid, CreditPayment.is_paid.is_(False)
        ).first()
        # Kapatmadan önce ödenmemiş taksitin FE'si var
        fe_before = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == "credit", FinanceEvent.source_id == unpaid.id
        ).count()
        assert fe_before == 1

        client.post(f"{PREFIX}/{pid}/close", json={"closed_date": "2026-05-25"}, headers=auth_headers)
        db.expire_all()
        # Kapatmadan sonra ödenmemiş taksitin FE'si silinmiş
        fe_after = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == "credit", FinanceEvent.source_id == unpaid.id
        ).count()
        assert fe_after == 0

    def test_close_keeps_payment_records(self, client, auth_headers, db):
        from app.models.credit_product import CreditPayment

        pid, _ = self._setup_with_unpaid(client, auth_headers, db)
        client.post(f"{PREFIX}/{pid}/close", json={"closed_date": "2026-05-25"}, headers=auth_headers)
        db.expire_all()
        # Taksit kayıtları korunur (iz)
        count = db.query(CreditPayment).filter(CreditPayment.credit_product_id == pid).count()
        assert count == 2

    def test_close_already_closed_fails(self, client, auth_headers):
        pid = _create_product(client, auth_headers).json()["id"]
        client.post(f"{PREFIX}/{pid}/close", json={}, headers=auth_headers)
        resp = client.post(f"{PREFIX}/{pid}/close", json={}, headers=auth_headers)
        assert resp.status_code == 400

    def test_close_not_found(self, client, auth_headers):
        resp = client.post(f"{PREFIX}/999999/close", json={}, headers=auth_headers)
        assert resp.status_code == 404

    def test_reopen_restores_status(self, client, auth_headers):
        pid = _create_product(client, auth_headers).json()["id"]
        client.post(f"{PREFIX}/{pid}/close", json={"closed_date": "2026-05-25"}, headers=auth_headers)
        resp = client.post(f"{PREFIX}/{pid}/reopen", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["closed_date"] is None

    def test_reopen_restores_finance_events(self, client, auth_headers, db):
        from app.models.credit_product import CreditPayment
        from app.models.finance_event import FinanceEvent

        pid, _ = self._setup_with_unpaid(client, auth_headers, db)
        unpaid = db.query(CreditPayment).filter(
            CreditPayment.credit_product_id == pid, CreditPayment.is_paid.is_(False)
        ).first()
        client.post(f"{PREFIX}/{pid}/close", json={"closed_date": "2026-05-25"}, headers=auth_headers)
        client.post(f"{PREFIX}/{pid}/reopen", headers=auth_headers)
        db.expire_all()
        # Yeniden açınca ödenmemiş taksitin FE'si geri gelir
        fe = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == "credit", FinanceEvent.source_id == unpaid.id
        ).count()
        assert fe == 1

    def test_reopen_not_closed_fails(self, client, auth_headers):
        pid = _create_product(client, auth_headers).json()["id"]
        resp = client.post(f"{PREFIX}/{pid}/reopen", headers=auth_headers)
        assert resp.status_code == 400

    def test_close_without_auth(self, client):
        resp = client.post(f"{PREFIX}/1/close", json={})
        assert resp.status_code in (401, 403)

    def test_closed_credit_excluded_from_summary(self, client, auth_headers):
        """Kapalı kredi summary/by-type tip kartında sayılmaz."""
        pid = _create_product(client, auth_headers, type="spot_kredi", remaining_amount=99999).json()["id"]
        # Kapatmadan önce spot count
        before = client.get(f"{PREFIX}/summary/by-type", headers=auth_headers).json()
        spot_before = next((i["count"] for i in before if i["type"] == "spot_kredi"), 0)

        client.post(f"{PREFIX}/{pid}/close", json={}, headers=auth_headers)
        after = client.get(f"{PREFIX}/summary/by-type", headers=auth_headers).json()
        spot_after = next((i["count"] for i in after if i["type"] == "spot_kredi"), 0)
        assert spot_after == spot_before - 1

    def test_closed_credit_excluded_from_upcoming(self, client, auth_headers, db):
        """Kapalı kredinin ödenmemiş ileri vadeli taksiti yaklaşan ödemelerde görünmez."""
        from datetime import date, timedelta
        from app.models.credit_product import CreditPayment

        future = (date.today() + timedelta(days=30)).isoformat()
        pid = _create_product(client, auth_headers).json()["id"]
        _add_payments(client, auth_headers, pid, payments=[
            {"installment_no": 1, "due_date": future, "amount": 25000},
        ])
        # Kapatmadan önce yaklaşan ödemelerde var
        up_before = client.get(f"{PREFIX}/upcoming-payments?days=365", headers=auth_headers).json()
        assert any(p["product_id"] == pid for p in up_before)

        client.post(f"{PREFIX}/{pid}/close", json={}, headers=auth_headers)
        up_after = client.get(f"{PREFIX}/upcoming-payments?days=365", headers=auth_headers).json()
        assert not any(p["product_id"] == pid for p in up_after)

    def test_closed_credit_excluded_from_active_list(self, client, auth_headers):
        """Kapalı kredi status=active listede görünmez, status=closed listede görünür."""
        pid = _create_product(client, auth_headers).json()["id"]
        client.post(f"{PREFIX}/{pid}/close", json={}, headers=auth_headers)

        active = client.get(f"{PREFIX}/?status=active&page_size=200", headers=auth_headers).json()
        assert not any(i["id"] == pid for i in active["items"])

        closed = client.get(f"{PREFIX}/?status=closed&page_size=200", headers=auth_headers).json()
        assert any(i["id"] == pid for i in closed["items"])


# ─── BCH FINANCE_EVENTS (nakit akım yansıması) ───────────────


class TestBchFinanceEvents:
    """BCH kredisi oluşturulunca/güncellenince ödeme planı nakit akıma (finance_events) yazılmalı.

    Regresyon: _regenerate_bch_payments eskiden FE üretmiyordu → BCH krediler
    nakit akımda görünmüyordu (2026-06-01 düzeltildi).
    """

    def _make_bch(self, client, auth_headers):
        return _create_product(
            client, auth_headers,
            type="bch", name="Test BCH", currency="EUR",
            total_amount=200000, remaining_amount=200000,
            interest_rate=9.5, commission_rate=1.1,
            start_date="2026-05-25", end_date="2027-05-25",
        ).json()

    def test_bch_create_generates_finance_events(self, client, auth_headers, db):
        from app.models.credit_product import CreditPayment
        from app.models.finance_event import FinanceEvent

        prod = self._make_bch(client, auth_headers)
        assert prod["payment_count"] > 0

        pay_ids = [
            r[0] for r in db.query(CreditPayment.id)
            .filter(CreditPayment.credit_product_id == prod["id"]).all()
        ]
        fe_count = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == "credit",
            FinanceEvent.source_id.in_(pay_ids),
        ).count()
        # Her ödenmemiş taksit için bir FE olmalı
        assert fe_count == len(pay_ids), f"FE {fe_count} != taksit {len(pay_ids)}"

    def test_bch_recalc_refreshes_finance_events(self, client, auth_headers, db):
        from app.models.credit_product import CreditPayment
        from app.models.finance_event import FinanceEvent

        prod = self._make_bch(client, auth_headers)
        old_pay_ids = [
            r[0] for r in db.query(CreditPayment.id)
            .filter(CreditPayment.credit_product_id == prod["id"]).all()
        ]

        # Faiz oranını değiştir → recalc → eski taksitler silinir, yenileri oluşur
        client.patch(f"{PREFIX}/{prod['id']}", json={"interest_rate": 10.5}, headers=auth_headers)
        db.expire_all()

        # Eski taksitlerin FE'si temizlenmiş olmalı
        orphan = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == "credit",
            FinanceEvent.source_id.in_(old_pay_ids),
        ).count()
        assert orphan == 0, "Eski taksitlerin FE'si invalidate edilmedi"

        # Yeni taksitlerin FE'si oluşmuş olmalı
        new_pay_ids = [
            r[0] for r in db.query(CreditPayment.id)
            .filter(CreditPayment.credit_product_id == prod["id"]).all()
        ]
        new_fe = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == "credit",
            FinanceEvent.source_id.in_(new_pay_ids),
        ).count()
        assert new_fe == len(new_pay_ids)
