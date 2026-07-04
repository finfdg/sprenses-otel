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

    def test_events_created_on_create(self, client, auth_headers, db):
        data = _create(client, auth_headers).json()
        inst_ids = [i["id"] for i in data["installments"]]
        net = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == SOURCE_DIVIDEND,
            FinanceEvent.source_id.in_(inst_ids),
        ).all()
        stopaj = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == SOURCE_DIVIDEND_STOPAJ,
            FinanceEvent.source_id.in_(inst_ids),
        ).all()
        assert len(net) == 6
        assert len(stopaj) == 6
        assert all(e.event_status == "pending" and e.direction == -1 for e in net)
        assert all(e.event_status == "pending" for e in stopaj)

    def test_net_event_date_is_due_date(self, client, auth_headers, db):
        data = _create(client, auth_headers).json()
        inst1 = next(i for i in data["installments"] if i["installment_no"] == 1)
        net = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == SOURCE_DIVIDEND,
            FinanceEvent.source_id == inst1["id"],
        ).one()
        assert net.event_date.isoformat() == "2025-06-30"

    def test_stopaj_event_date_is_next_month_26th(self, client, auth_headers, db):
        data = _create(client, auth_headers).json()
        inst1 = next(i for i in data["installments"] if i["installment_no"] == 1)
        stopaj = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == SOURCE_DIVIDEND_STOPAJ,
            FinanceEvent.source_id == inst1["id"],
        ).one()
        assert stopaj.event_date.isoformat() == "2025-07-26"

    def test_net_toggle_rolls_up_installment_event(self, client, auth_headers, db):
        data = _create(client, auth_headers).json()
        inst1 = next(i for i in data["installments"] if i["installment_no"] == 1)
        pays1 = [p for p in data["payments"] if p["installment_id"] == inst1["id"]]
        assert len(pays1) == 12

        # 11 ödeme → hâlâ pending (kısmi)
        for p in pays1[:11]:
            r = client.patch(f"{PREFIX}/payments/{p['id']}", json={"is_paid": True}, headers=auth_headers)
            assert r.status_code == 200, r.text
        db.expire_all()
        fe = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == SOURCE_DIVIDEND, FinanceEvent.source_id == inst1["id"],
        ).one()
        assert fe.event_status == "pending" and fe.is_realized is False

        # 12. ödeme → tamamı ödendi → paid/realized
        client.patch(f"{PREFIX}/payments/{pays1[11]['id']}", json={"is_paid": True}, headers=auth_headers)
        db.expire_all()
        fe = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == SOURCE_DIVIDEND, FinanceEvent.source_id == inst1["id"],
        ).one()
        assert fe.event_status == "paid" and fe.is_realized is True

    def test_stopaj_toggle_rolls_up_stopaj_event(self, client, auth_headers, db):
        data = _create(client, auth_headers).json()
        inst1 = next(i for i in data["installments"] if i["installment_no"] == 1)
        pays1 = [p for p in data["payments"] if p["installment_id"] == inst1["id"]]
        for p in pays1:
            client.patch(f"{PREFIX}/payments/{p['id']}", json={"stopaj_paid": True}, headers=auth_headers)
        db.expire_all()
        fe = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == SOURCE_DIVIDEND_STOPAJ, FinanceEvent.source_id == inst1["id"],
        ).one()
        assert fe.event_status == "paid" and fe.is_realized is True

    def test_dividend_event_deferral_resync(self, client, auth_headers, db):
        """Öteleme: temettü FE'si bespoke (installment.id anahtarlı) → resync ScheduledEntry'ye
        DEĞİL dividend branch'ine gitmeli; ertelenmiş tarih FE.event_date'e yansımalı."""
        from datetime import date, timedelta
        from app.services import deferral_service

        data = _create(client, auth_headers).json()
        inst1 = next(i for i in data["installments"] if i["installment_no"] == 1)
        new_date = date.today() + timedelta(days=400)
        try:
            deferral_service.apply_deferral(db, SOURCE_DIVIDEND, inst1["id"], new_date, user_id=None)
            deferral_service.resync_deferred_event(db, SOURCE_DIVIDEND, inst1["id"])
            db.flush()
            db.expire_all()
            fe = db.query(FinanceEvent).filter(
                FinanceEvent.source_type == SOURCE_DIVIDEND, FinanceEvent.source_id == inst1["id"],
            ).one()
            assert fe.event_date == new_date
        finally:
            deferral_service.clear_deferral(db, SOURCE_DIVIDEND, inst1["id"])
            deferral_service.invalidate_deferral_cache()

    def test_delete_invalidates_events_and_cascades(self, client, auth_headers, db):
        data = _create(client, auth_headers).json()
        dist_id = data["id"]
        inst_ids = [i["id"] for i in data["installments"]]

        r = client.delete(f"{PREFIX}/{dist_id}", headers=auth_headers)
        assert r.status_code == 200, r.text
        db.expire_all()

        fe = db.query(FinanceEvent).filter(
            FinanceEvent.source_type.in_([SOURCE_DIVIDEND, SOURCE_DIVIDEND_STOPAJ]),
            FinanceEvent.source_id.in_(inst_ids),
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
        inst_ids = [i["id"] for i in data["installments"]]
        r = client.patch(f"{PREFIX}/{dist_id}", json={"status": "cancelled"}, headers=auth_headers)
        assert r.status_code == 200, r.text
        db.expire_all()
        fe = db.query(FinanceEvent).filter(
            FinanceEvent.source_type.in_([SOURCE_DIVIDEND, SOURCE_DIVIDEND_STOPAJ]),
            FinanceEvent.source_id.in_(inst_ids),
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
