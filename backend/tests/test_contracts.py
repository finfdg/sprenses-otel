"""Kontratlar modülü (sales.kontratlar) testleri.

Kapsam: kontrat CRUD + alt varlık (kind) CRUD + özet, RBAC (view/use),
uçtan-uca onay regresyonları (kontrat create + alt varlık taksit create —
payload tarih string→date coercion dahil).
"""
from datetime import date, timedelta
from uuid import uuid4

from app.models.agency_group import AgencyGroup
from app.models.contract import AgencyContract, ContractInstallment

from tests.test_approval_system import API, STATUS_APPROVED, _make_actor, _make_workflow

PREFIX = "/api/sales/kontratlar"


def _mk_group(db, name=None) -> AgencyGroup:
    g = AgencyGroup(name=name or f"KTEST{uuid4().hex[:6].upper()}",
                    members=["KTEST ACENTE"], term_days=21)
    db.add(g)
    db.commit()
    return g


def _contract_payload(group_id, code=None):
    return {
        "agency_group_id": group_id,
        "code": code or f"KT-{uuid4().hex[:6].upper()}",
        "title": "Test Kontratı S26",
        "season_code": "S26",
        "valid_from": "2026-03-01",
        "valid_to": "2026-10-31",
        "currency": "EUR",
        "pricing_model": "pp",
        "invoice_due_basis": "checkout",
        "invoice_due_days": 21,
        "markets": ["Almanya", "Avusturya"],
        "data_confidence": "scanned_approx",
    }


class TestContractCRUD:
    def test_create_detail_list_summary(self, client, auth_headers, db):
        """Kontrat oluştur → detay + liste + summary uçları tutarlı döner."""
        g = _mk_group(db)
        r = client.post(f"{PREFIX}/", json=_contract_payload(g.id), headers=auth_headers)
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        assert r.json()["agency_group_name"] == g.name
        assert r.json()["data_confidence"] == "scanned_approx"

        d = client.get(f"{PREFIX}/{cid}", headers=auth_headers)
        assert d.status_code == 200
        assert d.json()["valid_from"] == "2026-03-01"
        assert d.json()["markets"] == ["Almanya", "Avusturya"]

        lst = client.get(f"{PREFIX}/?group_id={g.id}", headers=auth_headers)
        assert lst.status_code == 200
        assert lst.json()["total"] == 1
        assert lst.json()["items"][0]["code"] == r.json()["code"]

        s = client.get(f"{PREFIX}/summary", headers=auth_headers)
        assert s.status_code == 200
        assert "pending_installment_total" in s.json()

    def test_duplicate_code_rejected(self, client, auth_headers, db):
        g = _mk_group(db)
        payload = _contract_payload(g.id)
        assert client.post(f"{PREFIX}/", json=payload, headers=auth_headers).status_code == 201
        r2 = client.post(f"{PREFIX}/", json=payload, headers=auth_headers)
        assert r2.status_code == 400
        assert "zaten kayıtlı" in r2.json()["detail"]

    def test_child_crud_flow(self, client, auth_headers, db):
        """Dönem + ödeme planı + taksit ekle → taksidi ödendi yap → dönem sil."""
        g = _mk_group(db)
        c = client.post(f"{PREFIX}/", json=_contract_payload(g.id), headers=auth_headers).json()
        cid = c["id"]

        p = client.post(f"{PREFIX}/{cid}/children/periods", headers=auth_headers, json={
            "code": "A", "date_start": "2026-03-01", "date_end": "2026-04-20",
            "release_days": 3, "min_stay": 3})
        assert p.status_code == 201, p.text

        plan = client.post(f"{PREFIX}/{cid}/children/plans", headers=auth_headers, json={
            "plan_type": "advance", "description": "Test avans planı",
            "total_amount": 500000, "currency": "EUR", "offset_rule": "offset_100"})
        assert plan.status_code == 201, plan.text

        inst = client.post(f"{PREFIX}/{cid}/children/installments", headers=auth_headers, json={
            "plan_id": plan.json()["id"], "due_date": "2026-04-10",
            "amount": 250000, "currency": "EUR"})
        assert inst.status_code == 201, inst.text
        assert inst.json()["status"] == "pending"

        upd = client.patch(f"{PREFIX}/children/installments/{inst.json()['id']}",
                           headers=auth_headers,
                           json={"status": "paid", "paid_date": "2026-04-11"})
        assert upd.status_code == 200, upd.text
        assert upd.json()["status"] == "paid"
        assert upd.json()["paid_date"] == "2026-04-11"

        dele = client.delete(f"{PREFIX}/children/periods/{p.json()['id']}",
                             headers=auth_headers)
        assert dele.status_code == 204

        detail = client.get(f"{PREFIX}/{cid}", headers=auth_headers).json()
        assert detail["periods"] == []
        assert detail["payment_plans"][0]["installments"][0]["status"] == "paid"

    def test_unknown_kind_404(self, client, auth_headers, db):
        g = _mk_group(db)
        c = client.post(f"{PREFIX}/", json=_contract_payload(g.id), headers=auth_headers).json()
        r = client.post(f"{PREFIX}/{c['id']}/children/bilinmeyen",
                        headers=auth_headers, json={})
        assert r.status_code == 404

    def test_installment_wrong_parent_rejected(self, client, auth_headers, db):
        """Başka kontratın planına taksit eklenemez (via_parent doğrulaması)."""
        g = _mk_group(db)
        c1 = client.post(f"{PREFIX}/", json=_contract_payload(g.id), headers=auth_headers).json()
        c2 = client.post(f"{PREFIX}/", json=_contract_payload(g.id), headers=auth_headers).json()
        plan1 = client.post(f"{PREFIX}/{c1['id']}/children/plans", headers=auth_headers,
                            json={"plan_type": "advance"}).json()
        r = client.post(f"{PREFIX}/{c2['id']}/children/installments", headers=auth_headers,
                        json={"plan_id": plan1["id"], "due_date": "2026-05-01", "amount": 100})
        assert r.status_code == 400
        assert "ait değil" in r.json()["detail"]


class TestContractRBAC:
    def test_view_required(self, client, no_perm_user_headers):
        assert client.get(f"{PREFIX}/", headers=no_perm_user_headers).status_code == 403

    def test_use_required_for_mutations(self, client, viewer_user_headers, db):
        g = _mk_group(db)
        r = client.post(f"{PREFIX}/", json=_contract_payload(g.id),
                        headers=viewer_user_headers)
        assert r.status_code == 403

    def test_viewer_can_read(self, client, viewer_user_headers):
        assert client.get(f"{PREFIX}/", headers=viewer_user_headers).status_code == 200


class TestContractApproval:
    def test_create_contract_via_approval_regression(self, db):
        """Uçtan-uca onay: kontrat oluşturma isteği 202 → onaylanınca kontrat gerçekten
        oluşur (handler + payload uyumu; tarih alanları JSON string → date coercion)."""
        _, req_role, req_client = _make_actor(db, {
            "sales.kontratlar": {"view": True, "use": True},
            "system.approval": {"view": True, "use": False},
        })
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "sales.kontratlar", req_role, app_role)

        g = _mk_group(db)
        payload = _contract_payload(g.id)
        resp = req_client.post(f"{PREFIX}/", json=payload)
        assert resp.status_code == 202, f"onaya düşmeli: {resp.text}"
        req_id = resp.json()["request_id"]

        db.expire_all()
        assert db.query(AgencyContract).filter(
            AgencyContract.code == payload["code"]).first() is None

        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"handler eksik/uyumsuzsa 500: {ap.text}"
        assert ap.json()["status"] == STATUS_APPROVED

        db.expire_all()
        c = db.query(AgencyContract).filter(AgencyContract.code == payload["code"]).first()
        assert c is not None, "Onay sonrası kontrat oluşmalıydı"
        assert c.valid_from == date(2026, 3, 1)  # string→date coercion kanıtı
        assert c.invoice_due_days == 21

    def test_create_installment_via_approval_regression(self, db, client, auth_headers):
        """Alt varlık onayı: _kind + _contract_id taşınır, taksit due_date string→date
        coerce edilerek doğru plana bağlanır."""
        _, req_role, req_client = _make_actor(db, {
            "sales.kontratlar": {"view": True, "use": True},
            "system.approval": {"view": True, "use": False},
        })
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "sales.kontratlar", req_role, app_role)

        # Kontrat + plan admin ile (onaysız yol) kurulur — yalnız taksit onaya düşer
        g = _mk_group(db)
        c = client.post(f"{PREFIX}/", json=_contract_payload(g.id), headers=auth_headers).json()
        plan = client.post(f"{PREFIX}/{c['id']}/children/plans", headers=auth_headers,
                           json={"plan_type": "advance", "total_amount": 100000}).json()

        due = (date.today() + timedelta(days=30)).isoformat()
        resp = req_client.post(f"{PREFIX}/{c['id']}/children/installments", json={
            "plan_id": plan["id"], "due_date": due, "amount": 100000, "currency": "EUR"})
        assert resp.status_code == 202, f"onaya düşmeli: {resp.text}"
        req_id = resp.json()["request_id"]

        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"alt varlık handler'ı bozuksa 500: {ap.text}"

        db.expire_all()
        inst = db.query(ContractInstallment).filter(
            ContractInstallment.plan_id == plan["id"]).first()
        assert inst is not None, "Onay sonrası taksit oluşmalıydı"
        assert inst.due_date == date.fromisoformat(due)
        assert float(inst.amount) == 100000
