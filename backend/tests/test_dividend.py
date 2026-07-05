"""Kâr payı dağıtımı (temettü) modülü testleri.

Endpoint'ler: /api/accounting/dividend/
Üretim doğruluğu (Excel paritesi), taksit/ödeme türetimi, net+stopaj finance_events
roll-up'ı, silme invalidate + CASCADE, ve RBAC 403.
"""

from app.models.dividend import (
    DividendDistribution,
    DividendInstallment,
    DividendPayment,
    DividendShareholder,
)
from app.models.finance_event import (
    FinanceEvent,
    SOURCE_DIVIDEND,
    SOURCE_DIVIDEND_STOPAJ,
)

PREFIX = "/api/accounting/dividend"

# MURAT-A / Side Prenses — 19.06.2025 Genel Kurul kâr payı dağıtımı (Excel)
EXCEL_SHAREHOLDERS = [
    ("RECEP ÖZDEN", 519750), ("İSMAİL ÖZDEN", 453750), ("NECİP ÖZDEN", 453750),
    ("AYFER DUYUN", 453750), ("MEVLÜT ÖZDEN", 354750), ("ŞEVKET CARUS", 118250),
    ("UĞUR CARUS", 118250), ("MİRAY ÇETİN", 118250), ("EROL YILDIZ", 177600),
    ("ERDOĞAN YILDIZ", 177150), ("MURAT ÖZDEN", 177150), ("FATMA ÖZDEN", 177600),
]


def _payload(**overrides):
    p = {
        "name": "2025 Kâr Payı Dağıtımı",
        "decision_date": "2025-06-19",
        "total_gross": 20000000,
        "capital": 3300000,
        "withholding_rate": 0.15,
        "installment_count": 6,
        "year": 2025,
        "first_installment_date": "2025-06-30",
        "shareholders": [{"name": n, "share_value": v} for n, v in EXCEL_SHAREHOLDERS],
    }
    p.update(overrides)
    return p


def _create(client, headers, **overrides):
    return client.post(f"{PREFIX}/", json=_payload(**overrides), headers=headers)


# ─── Üretim ─────────────────────────────────────────────────

class TestCreateGeneration:

    def test_create_generates_shareholders_installments_payments(self, client, auth_headers):
        resp = _create(client, auth_headers)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["status"] == "active"
        assert len(data["shareholders"]) == 12
        assert len(data["installments"]) == 6
        assert len(data["payments"]) == 72  # 12 ortak × 6 taksit
        assert data["shareholder_count"] == 12
        assert data["net_total_count"] == 72

    def test_amounts_match_excel(self, client, auth_headers):
        data = _create(client, auth_headers).json()
        recep = next(s for s in data["shareholders"] if s["name"] == "RECEP ÖZDEN")
        assert recep["share_ratio"] == 0.1575
        assert recep["gross_dividend"] == 3150000.0
        assert recep["stopaj_amount"] == 472500.0
        assert recep["net_dividend"] == 2677500.0

    def test_installment_dates_are_month_ends(self, client, auth_headers):
        data = _create(client, auth_headers).json()
        labels = [i["label"] for i in data["installments"]]
        assert labels == ["30.06.2025", "31.07.2025", "31.08.2025",
                          "30.09.2025", "31.10.2025", "30.11.2025"]

    def test_rounding_remainder_in_last_installment(self, client, auth_headers, db):
        data = _create(client, auth_headers).json()
        dist_id = data["id"]
        insts = sorted(data["installments"], key=lambda i: i["installment_no"])
        payments = db.query(DividendPayment).filter(
            DividendPayment.distribution_id == dist_id,
        ).all()
        # Her taksit için: Σ ödeme brüt == taksit brüt (ödemelerden türetilir)
        for inst in insts:
            s = sum(float(p.gross_amount) for p in payments if p.installment_id == inst["id"])
            assert abs(s - inst["gross_amount"]) < 0.001
        # İSMAİL'in son taksiti artığı absorbe eder (Excel: 458333.35)
        ism = next(s for s in data["shareholders"] if s["name"] == "İSMAİL ÖZDEN")
        last_inst = insts[-1]
        ism_last = next(
            p for p in payments
            if p.shareholder_id == ism["id"] and p.installment_id == last_inst["id"]
        )
        assert float(ism_last.gross_amount) == 458333.35

    def test_totals_mirror_excel(self, client, auth_headers):
        data = _create(client, auth_headers).json()
        # Excel TOPLAM: brüt 20.000.000,01 · net 17.000.000,01 (Excel de reconcile etmez)
        assert round(data["total_net"], 2) == 17000000.01
        assert round(data["total_stopaj"], 2) == 3000000.0


# ─── finance_events ─────────────────────────────────────────

class TestFinanceEvents:
    """finance_events ÖDEME (pay sahibi × taksit) bazlıdır — kişi-kişi görünürlük + kısmi ödeme ayrımı."""

    def test_events_created_per_payment(self, client, auth_headers, db):
        data = _create(client, auth_headers).json()
        pay_ids = [p["id"] for p in data["payments"]]
        assert len(pay_ids) == 72  # 12 ortak × 6 taksit
        net = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == SOURCE_DIVIDEND, FinanceEvent.source_id.in_(pay_ids),
        ).all()
        stopaj = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == SOURCE_DIVIDEND_STOPAJ, FinanceEvent.source_id.in_(pay_ids),
        ).all()
        assert len(net) == 72
        assert len(stopaj) == 72
        assert all(e.event_status == "pending" and e.direction == -1 for e in net)
        # açıklama pay sahibi adını taşır (kişi-kişi görünürlük)
        assert any("RECEP ÖZDEN" in (e.description or "") for e in net)

    def _pay1(self, data, name="MEVLÜT ÖZDEN"):
        inst1 = next(i for i in data["installments"] if i["installment_no"] == 1)
        return next(p for p in data["payments"]
                    if p["installment_id"] == inst1["id"] and p["shareholder_name"] == name)

    def test_unpaid_net_date_is_due_and_stopaj_next_month_26(self, client, auth_headers, db):
        data = _create(client, auth_headers).json()
        p = self._pay1(data)
        net = db.query(FinanceEvent).filter_by(source_type=SOURCE_DIVIDEND, source_id=p["id"]).one()
        stopaj = db.query(FinanceEvent).filter_by(source_type=SOURCE_DIVIDEND_STOPAJ, source_id=p["id"]).one()
        assert net.event_date.isoformat() == "2025-06-30"   # taksit vadesi
        assert stopaj.event_date.isoformat() == "2025-07-26"  # ertesi ay 26

    def test_paid_late_moves_net_and_shifts_stopaj_month(self, client, auth_headers, db):
        """Gerçek ödeme 3 gün geç (03.07) → net o tarihe kayar, stopaj bir SONRAKİ aya (Ağustos 26) sarkar."""
        data = _create(client, auth_headers).json()
        p = self._pay1(data)
        r = client.patch(f"{PREFIX}/payments/{p['id']}",
                         json={"is_paid": True, "paid_date": "2025-07-03"}, headers=auth_headers)
        assert r.status_code == 200, r.text
        db.expire_all()
        net = db.query(FinanceEvent).filter_by(source_type=SOURCE_DIVIDEND, source_id=p["id"]).one()
        stopaj = db.query(FinanceEvent).filter_by(source_type=SOURCE_DIVIDEND_STOPAJ, source_id=p["id"]).one()
        assert net.event_date.isoformat() == "2025-07-03"
        assert net.event_status == "paid" and net.is_realized is True
        assert stopaj.event_date.isoformat() == "2025-08-26"  # Haziran değil, Temmuz ödemesi → Ağustos muhtasar

    def test_partial_payment_is_independent(self, client, auth_headers, db):
        """Bir ödemeyi işaretlemek diğerlerini ETKİLEMEZ (kısmi ödeme ayrımı)."""
        data = _create(client, auth_headers).json()
        p_paid = self._pay1(data, "MEVLÜT ÖZDEN")
        p_other = self._pay1(data, "RECEP ÖZDEN")
        client.patch(f"{PREFIX}/payments/{p_paid['id']}", json={"is_paid": True}, headers=auth_headers)
        db.expire_all()
        fe_paid = db.query(FinanceEvent).filter_by(source_type=SOURCE_DIVIDEND, source_id=p_paid["id"]).one()
        fe_other = db.query(FinanceEvent).filter_by(source_type=SOURCE_DIVIDEND, source_id=p_other["id"]).one()
        assert fe_paid.event_status == "paid"
        assert fe_other.event_status == "pending"  # diğeri etkilenmedi

    def test_dividend_event_deferral_resync(self, client, auth_headers, db):
        """Öteleme: temettü FE'si ödeme (payment.id) anahtarlı → resync dividend branch'ine gider."""
        from datetime import date, timedelta
        from app.services import deferral_service

        data = _create(client, auth_headers).json()
        p = self._pay1(data)
        new_date = date.today() + timedelta(days=400)
        try:
            deferral_service.apply_deferral(db, SOURCE_DIVIDEND, p["id"], new_date, user_id=None)
            deferral_service.resync_deferred_event(db, SOURCE_DIVIDEND, p["id"])
            db.flush()
            db.expire_all()
            fe = db.query(FinanceEvent).filter_by(source_type=SOURCE_DIVIDEND, source_id=p["id"]).one()
            assert fe.event_date == new_date
        finally:
            deferral_service.clear_deferral(db, SOURCE_DIVIDEND, p["id"])
            deferral_service.invalidate_deferral_cache()

    def test_delete_invalidates_events_and_cascades(self, client, auth_headers, db):
        data = _create(client, auth_headers).json()
        dist_id = data["id"]
        pay_ids = [p["id"] for p in data["payments"]]

        r = client.delete(f"{PREFIX}/{dist_id}", headers=auth_headers)
        assert r.status_code == 200, r.text
        db.expire_all()

        fe = db.query(FinanceEvent).filter(
            FinanceEvent.source_type.in_([SOURCE_DIVIDEND, SOURCE_DIVIDEND_STOPAJ]),
            FinanceEvent.source_id.in_(pay_ids),
        ).count()
        assert fe == 0
        assert db.query(DividendDistribution).filter_by(id=dist_id).first() is None
        assert db.query(DividendShareholder).filter_by(distribution_id=dist_id).count() == 0
        assert db.query(DividendInstallment).filter_by(distribution_id=dist_id).count() == 0
        assert db.query(DividendPayment).filter_by(distribution_id=dist_id).count() == 0


# ─── Metadata + liste ───────────────────────────────────────

class TestMetadataAndList:

    def test_update_metadata(self, client, auth_headers):
        dist_id = _create(client, auth_headers).json()["id"]
        r = client.patch(f"{PREFIX}/{dist_id}", json={"notes": "güncellendi"}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["notes"] == "güncellendi"

    def test_cancel_removes_events(self, client, auth_headers, db):
        data = _create(client, auth_headers).json()
        dist_id = data["id"]
        pay_ids = [p["id"] for p in data["payments"]]
        r = client.patch(f"{PREFIX}/{dist_id}", json={"status": "cancelled"}, headers=auth_headers)
        assert r.status_code == 200, r.text
        db.expire_all()
        fe = db.query(FinanceEvent).filter(
            FinanceEvent.source_type.in_([SOURCE_DIVIDEND, SOURCE_DIVIDEND_STOPAJ]),
            FinanceEvent.source_id.in_(pay_ids),
        ).count()
        assert fe == 0

    def test_list_returns_distribution(self, client, auth_headers):
        _create(client, auth_headers)
        r = client.get(f"{PREFIX}/?year=2025", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] >= 1
        assert any(it["year"] == 2025 for it in body["items"])

    def test_create_rejects_zero_total(self, client, auth_headers):
        r = _create(client, auth_headers, total_gross=0)
        assert r.status_code == 422  # pydantic gt=0


# ─── RBAC ───────────────────────────────────────────────────

class TestRBAC:

    def test_list_requires_view(self, client, no_perm_user_headers):
        assert client.get(f"{PREFIX}/", headers=no_perm_user_headers).status_code == 403

    def test_create_requires_use(self, client, viewer_user_headers):
        r = _create(client, viewer_user_headers)
        assert r.status_code == 403

    def test_payment_patch_requires_use(self, client, auth_headers, viewer_user_headers):
        data = _create(client, auth_headers).json()
        pid = data["payments"][0]["id"]
        r = client.patch(f"{PREFIX}/payments/{pid}", json={"is_paid": True}, headers=viewer_user_headers)
        assert r.status_code == 403
