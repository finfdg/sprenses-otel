"""Sistem onay akışı motoru testleri.

Audit'te "KRİTİK boşluk" olarak işaretlenen, neredeyse testsiz (~%9-24 kapsam)
çekirdek altyapıyı kapsar:
- routers/approval/workflows.py    — workflow tanım CRUD
- routers/approval/requests.py     — talep yaşam döngüsü + yetkilendirme
- utils/approval_service.py        — workflow eşleştirme + durum makinesi + koşullar
- utils/approval_check.py          — modül CRUD entegrasyonu (202 onay / 409 çakışma)
- utils/approval_executor.py       — onaylanan payload'ın gerçekten uygulanması (uçtan uca)

NOT: test_onay.py AYRI bir özelliği (finance.onay departman onayı) test eder — bu motoru DEĞİL.
"""

import json
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.middleware.rate_limit import login_limiter
from app.models.advance import Advance
from app.models.approval import (
    STATUS_APPROVED,
    STATUS_CANCELLED,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_RETURNED,
    ApprovalRequest,
    ApprovalWorkflow,
    ApprovalWorkflowApproverRole,
    ApprovalWorkflowRequestorRole,
)
from app.models.department import Department
from app.models.module import Module
from app.models.role import Role
from app.models.role_module_permission import RoleModulePermission
from app.models.scheduled import ScheduledDefinition
from app.models.user import User
from app.routers.approval.requests import _redact_payload
from app.utils.approval_service import (
    _evaluate_conditions,
    check_and_trigger_approval,
    find_matching_workflow,
    get_pending_approver_ids,
    is_user_approver,
)
from app.utils.security import hash_password

API = "/api/system/approval"


# ─────────────────────────── Yardımcılar ───────────────────────────

def _login_client(username: str, password: str = "Test1234!") -> TestClient:
    """Verilen kullanıcı ile login olmuş ayrı bir TestClient döndür (cookie auth)."""
    login_limiter._requests.clear()  # çoklu aktörde rate-limit flakiness'ini önle
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"login başarısız: {r.text}"
    return c


def _make_actor(db, perms: dict):
    """Rol + kullanıcı + modül izinleri oluştur, login olmuş client döndür.

    perms: {"finance.avanslar": {"view": True, "use": True}, ...}
    Returns: (user_id, role_id, client)
    """
    uid = uuid4().hex[:8]
    role = Role(name=f"approle_{uid}", description="onay test rolü", is_active=True)
    db.add(role)
    db.flush()

    mods = {m.code: m for m in db.query(Module).all()}
    for code, spec in perms.items():
        m = mods.get(code)
        if m is None:
            continue
        db.add(RoleModulePermission(
            role_id=role.id, module_id=m.id,
            can_view=spec.get("view", False), can_use=spec.get("use", False),
        ))

    username = f"appru_{uid}"
    user = User(
        username=username, email=f"{username}@test.local",
        first_name="Onay", last_name=uid[:6],
        hashed_password=hash_password("Test1234!"), role_id=role.id, is_active=True,
    )
    db.add(user)
    db.commit()
    return user.id, role.id, _login_client(username)


def _mk_role(db) -> int:
    """Aktif bir test rolü oluştur, id döndür."""
    r = Role(name=f"role_{uuid4().hex[:8]}", description="test", is_active=True)
    db.add(r)
    db.flush()
    return r.id


def _module_id(db, code: str) -> int:
    m = db.query(Module).filter(Module.code == code).first()
    assert m is not None, f"modül bulunamadı: {code}"
    return m.id


def _make_workflow(db, module_code, requestor_role_id, approver_role_id, *,
                   name=None, conditions_json=None, is_active=True) -> ApprovalWorkflow:
    """Doğrudan DB'de modül-rol tabanlı bir workflow oluştur."""
    wf = ApprovalWorkflow(
        name=name or f"wf_{uuid4().hex[:8]}",
        module_id=_module_id(db, module_code),
        entity_type=module_code,
        is_active=is_active,
        conditions_json=conditions_json,
    )
    db.add(wf)
    db.flush()
    db.add(ApprovalWorkflowRequestorRole(workflow_id=wf.id, role_id=requestor_role_id))
    db.add(ApprovalWorkflowApproverRole(workflow_id=wf.id, role_id=approver_role_id))
    db.commit()
    return wf


def _setup_avans_flow(db):
    """Avans onay akışı için requestor + approver + workflow kurar.

    Requestor: hedef modülde (finance.avanslar) use + onay modülünde view
    (kendi taleplerini görmek/iptal/yeniden göndermek için). Approver: onay
    modülünde use (onayla/reddet/iade için).
    """
    _, req_role, req_client = _make_actor(db, {
        "finance.avanslar": {"view": True, "use": True},
        "system.approval": {"view": True, "use": False},
    })
    app_uid, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
    wf = _make_workflow(db, "finance.avanslar", req_role, app_role)
    return req_client, app_client, app_uid, wf


def _create_advance_request(req_client, agency=None, amount=5000) -> tuple:
    """requestor avans oluşturma talebi gönderir → (agency_name, request_id)."""
    agency = agency or f"Acente {uuid4().hex[:6]}"
    resp = req_client.post("/api/finance/avanslar/", json={
        "agency_name": agency, "amount": amount, "currency": "EUR",
        "advance_date": "2026-08-01",
    })
    assert resp.status_code == 202, f"202 bekleniyordu: {resp.status_code} {resp.text}"
    body = resp.json()
    assert body.get("requires_approval") is True
    return agency, body["request_id"]


# ─────────────────────── Workflow CRUD ───────────────────────

class TestWorkflowCRUD:
    def test_create_workflow(self, client, auth_headers, db):
        mod_id = _module_id(db, "finance.avanslar")
        r1, r2 = _mk_role(db), _mk_role(db)
        db.commit()
        resp = client.post(f"{API}/workflows", headers=auth_headers, json={
            "name": f"WF {uuid4().hex[:6]}",
            "module_id": mod_id,
            "requestor_role_ids": [r1],
            "approver_role_ids": [r2],
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["module_id"] == mod_id
        assert len(body["requestor_roles"]) == 1
        assert len(body["approver_roles"]) == 1

    def test_create_duplicate_name_rejected(self, client, auth_headers, db):
        mod_id = _module_id(db, "finance.avanslar")
        r1, r2 = _mk_role(db), _mk_role(db)
        db.commit()
        name = f"WF {uuid4().hex[:6]}"
        payload = {"name": name, "module_id": mod_id,
                   "requestor_role_ids": [r1], "approver_role_ids": [r2]}
        assert client.post(f"{API}/workflows", headers=auth_headers, json=payload).status_code == 201
        dup = client.post(f"{API}/workflows", headers=auth_headers, json=payload)
        assert dup.status_code == 400

    def test_create_invalid_module_rejected(self, client, auth_headers, db):
        r1, r2 = _mk_role(db), _mk_role(db)
        db.commit()
        resp = client.post(f"{API}/workflows", headers=auth_headers, json={
            "name": f"WF {uuid4().hex[:6]}", "module_id": 99999999,
            "requestor_role_ids": [r1], "approver_role_ids": [r2],
        })
        assert resp.status_code == 400

    def test_create_invalid_role_rejected(self, client, auth_headers, db):
        mod_id = _module_id(db, "finance.avanslar")
        r1 = _mk_role(db)
        db.commit()
        resp = client.post(f"{API}/workflows", headers=auth_headers, json={
            "name": f"WF {uuid4().hex[:6]}", "module_id": mod_id,
            "requestor_role_ids": [r1], "approver_role_ids": [88888888],
        })
        assert resp.status_code == 400

    def test_list_and_get_workflow(self, client, auth_headers, db):
        r1, r2 = _mk_role(db), _mk_role(db)
        wf = _make_workflow(db, "finance.avanslar", r1, r2)
        lst = client.get(f"{API}/workflows", headers=auth_headers)
        assert lst.status_code == 200
        assert any(it["id"] == wf.id for it in lst.json()["items"])
        detail = client.get(f"{API}/workflows/{wf.id}", headers=auth_headers)
        assert detail.status_code == 200
        assert detail.json()["id"] == wf.id

    def test_get_workflow_404(self, client, auth_headers):
        assert client.get(f"{API}/workflows/99999999", headers=auth_headers).status_code == 404

    def test_update_workflow(self, client, auth_headers, db):
        r1, r2, r3 = _mk_role(db), _mk_role(db), _mk_role(db)
        wf = _make_workflow(db, "finance.avanslar", r1, r2)
        new_name = f"Güncel {uuid4().hex[:6]}"
        resp = client.patch(f"{API}/workflows/{wf.id}", headers=auth_headers, json={
            "name": new_name, "approver_role_ids": [r2, r3],
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == new_name
        assert len(body["approver_roles"]) == 2

    def test_update_workflow_404(self, client, auth_headers):
        resp = client.patch(f"{API}/workflows/99999999", headers=auth_headers, json={"name": "x yeni"})
        assert resp.status_code == 404

    def test_delete_workflow_soft(self, client, auth_headers, db):
        r1, r2 = _mk_role(db), _mk_role(db)
        wf = _make_workflow(db, "finance.avanslar", r1, r2)
        assert client.delete(f"{API}/workflows/{wf.id}", headers=auth_headers).status_code == 200
        # Soft delete → is_active=False → listede görünmez
        lst = client.get(f"{API}/workflows", headers=auth_headers)
        assert not any(it["id"] == wf.id for it in lst.json()["items"])

    def test_delete_workflow_404(self, client, auth_headers):
        assert client.delete(f"{API}/workflows/99999999", headers=auth_headers).status_code == 404

    def test_create_requires_use_permission(self, client, viewer_user_headers, db):
        """can_view var, can_use yok → 403."""
        mod_id = _module_id(db, "finance.avanslar")
        r1, r2 = _mk_role(db), _mk_role(db)
        db.commit()
        resp = client.post(f"{API}/workflows", headers=viewer_user_headers, json={
            "name": f"WF {uuid4().hex[:6]}", "module_id": mod_id,
            "requestor_role_ids": [r1], "approver_role_ids": [r2],
        })
        assert resp.status_code == 403

    def test_list_requires_view_permission(self, client, no_perm_user_headers):
        assert client.get(f"{API}/workflows", headers=no_perm_user_headers).status_code == 403

    def test_unauthenticated_rejected(self, client):
        assert client.get(f"{API}/workflows").status_code == 401

    def test_modules_with_roles(self, client, auth_headers):
        resp = client.get(f"{API}/modules-with-roles", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ─────────────────── approval_service birim testleri ───────────────────

class TestApprovalServiceUnit:
    def test_find_matching_workflow_role_match(self, db):
        r_req, r_app = _mk_role(db), _mk_role(db)
        wf = _make_workflow(db, "finance.avanslar", r_req, r_app)
        found = find_matching_workflow(db, "finance.avanslar", r_req)
        assert found is not None and found.id == wf.id

    def test_find_matching_workflow_role_mismatch(self, db):
        r_req, r_app, r_other = _mk_role(db), _mk_role(db), _mk_role(db)
        _make_workflow(db, "finance.avanslar", r_req, r_app)
        assert find_matching_workflow(db, "finance.avanslar", r_other) is None

    def test_find_matching_workflow_unknown_module(self, db):
        r_req, r_app = _mk_role(db), _mk_role(db)
        _make_workflow(db, "finance.avanslar", r_req, r_app)
        assert find_matching_workflow(db, "modul.yok", r_req) is None

    def test_find_matching_workflow_inactive_skipped(self, db):
        r_req, r_app = _mk_role(db), _mk_role(db)
        _make_workflow(db, "finance.avanslar", r_req, r_app, is_active=False)
        assert find_matching_workflow(db, "finance.avanslar", r_req) is None

    def test_conditions_min_amount(self, db):
        r_req, r_app = _mk_role(db), _mk_role(db)
        _make_workflow(db, "finance.avanslar", r_req, r_app,
                       conditions_json=json.dumps({"min_amount": 1000}))
        assert find_matching_workflow(db, "finance.avanslar", r_req, {"amount": 2000}) is not None
        assert find_matching_workflow(db, "finance.avanslar", r_req, {"amount": 500}) is None
        # context_data yoksa koşullu workflow eşleşmez
        assert find_matching_workflow(db, "finance.avanslar", r_req, None) is None

    def test_evaluate_conditions_unit(self):
        assert _evaluate_conditions({"min_amount": 1000}, {"amount": 2000}) is True
        assert _evaluate_conditions({"min_amount": 1000}, {"amount": 500}) is False
        assert _evaluate_conditions({"max_amount": 1000}, {"amount": 500}) is True
        assert _evaluate_conditions({"max_amount": 1000}, {"amount": 5000}) is False
        assert _evaluate_conditions({"field_equals": {"currency": "EUR"}}, {"currency": "EUR"}) is True
        assert _evaluate_conditions({"field_equals": {"currency": "EUR"}}, {"currency": "USD"}) is False
        assert _evaluate_conditions({"min_amount": 1}, None) is False

    def test_check_and_trigger_creates_request(self, db):
        req_uid, r_req, _ = _make_actor(db, {"finance.avanslar": {"view": True, "use": True}})
        r_app = _mk_role(db)
        _make_workflow(db, "finance.avanslar", r_req, r_app)
        req = check_and_trigger_approval(db, "finance.avanslar", 0, req_uid, "create", "{}")
        assert req is not None
        assert req.status == STATUS_PENDING
        assert req.module_code == "finance.avanslar"

    def test_check_and_trigger_no_workflow_returns_none(self, db):
        req_uid, _, _ = _make_actor(db, {"finance.avanslar": {"view": True, "use": True}})
        assert check_and_trigger_approval(db, "finance.avanslar", 0, req_uid, "create", "{}") is None

    def test_pending_approver_resolution(self, db):
        req_uid, r_req, _ = _make_actor(db, {"finance.avanslar": {"view": True, "use": True}})
        app_uid, r_app, _ = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "finance.avanslar", r_req, r_app)
        req = check_and_trigger_approval(db, "finance.avanslar", 0, req_uid, "create", "{}")
        approver_ids = get_pending_approver_ids(db, req)
        assert app_uid in approver_ids
        assert req_uid not in approver_ids
        assert is_user_approver(db, app_uid, req) is True
        assert is_user_approver(db, req_uid, req) is False


# ─────────────────── Talep yaşam döngüsü (uçtan uca) ───────────────────

class TestApprovalLifecycle:
    def test_create_then_approve_applies_change(self, db):
        req_client, app_client, _, _ = _setup_avans_flow(db)
        agency, req_id = _create_advance_request(req_client)

        # Onaydan ÖNCE: avans henüz oluşturulmadı
        db.expire_all()
        assert db.query(Advance).filter(Advance.agency_name == agency).first() is None

        # Approver bekleyen listede görür
        pend = app_client.get(f"{API}/requests/pending")
        assert pend.status_code == 200
        assert any(it["id"] == req_id for it in pend.json()["items"])

        # Onayla → değişiklik uygulanır
        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, ap.text
        assert ap.json()["status"] == STATUS_APPROVED

        db.expire_all()
        adv = db.query(Advance).filter(Advance.agency_name == agency).first()
        assert adv is not None, "Onay sonrası avans oluşturulmalıydı"
        assert float(adv.amount) == 5000

    def test_reject_blocks_change(self, db):
        req_client, app_client, _, _ = _setup_avans_flow(db)
        agency, req_id = _create_advance_request(req_client)
        rej = app_client.post(f"{API}/requests/{req_id}/reject", json={"note": "Uygun değil"})
        assert rej.status_code == 200, rej.text
        assert rej.json()["status"] == STATUS_REJECTED
        db.expire_all()
        assert db.query(Advance).filter(Advance.agency_name == agency).first() is None

    def test_reject_requires_note(self, db):
        req_client, app_client, _, _ = _setup_avans_flow(db)
        _, req_id = _create_advance_request(req_client)
        # note olmadan reddetme → 422
        assert app_client.post(f"{API}/requests/{req_id}/reject", json={}).status_code == 422

    def test_return_then_resubmit(self, db):
        req_client, app_client, _, _ = _setup_avans_flow(db)
        _, req_id = _create_advance_request(req_client)
        ret = app_client.post(f"{API}/requests/{req_id}/return", json={"note": "Düzelt"})
        assert ret.status_code == 200
        assert ret.json()["status"] == STATUS_RETURNED
        # Sadece talep sahibi yeniden gönderebilir
        rs = req_client.post(f"{API}/requests/{req_id}/resubmit", json={})
        assert rs.status_code == 200, rs.text
        assert rs.json()["status"] == STATUS_PENDING

    def test_resubmit_only_owner(self, db):
        req_client, app_client, _, _ = _setup_avans_flow(db)
        _, req_id = _create_advance_request(req_client)
        app_client.post(f"{API}/requests/{req_id}/return", json={"note": "Düzelt"})
        # approver yeniden gönderemez (sahip değil)
        assert app_client.post(f"{API}/requests/{req_id}/resubmit", json={}).status_code == 403

    def test_resubmit_only_when_returned(self, db):
        req_client, app_client, _, _ = _setup_avans_flow(db)
        _, req_id = _create_advance_request(req_client)
        # pending durumda resubmit → 400
        assert req_client.post(f"{API}/requests/{req_id}/resubmit", json={}).status_code == 400

    def test_cancel_by_owner(self, db):
        req_client, app_client, _, _ = _setup_avans_flow(db)
        _, req_id = _create_advance_request(req_client)
        c = req_client.post(f"{API}/requests/{req_id}/cancel", json={"note": "Vazgeçtim"})
        assert c.status_code == 200
        assert c.json()["status"] == STATUS_CANCELLED

    def test_duplicate_pending_conflict(self, db):
        """Aynı kayıt için bekleyen onay varken ikinci işlem → 409."""
        req_client, app_client, _, _ = _setup_avans_flow(db)
        # Mevcut bir avans oluştur (id>0 update yolu için)
        adv = Advance(agency_name=f"X {uuid4().hex[:5]}", amount=100, currency="EUR",
                      advance_date="2026-08-01", status="pending")
        db.add(adv)
        db.commit()
        adv_id = adv.id
        # İlk update → 202
        r1 = req_client.patch(f"/api/finance/avanslar/{adv_id}", json={"amount": 200})
        assert r1.status_code == 202, r1.text
        # İkinci update (bekleyen var) → 409
        r2 = req_client.patch(f"/api/finance/avanslar/{adv_id}", json={"amount": 300})
        assert r2.status_code == 409


# ─────────────────── Yetkilendirme sınırları ───────────────────

class TestApprovalAuthorization:
    def test_non_approver_cannot_approve(self, db):
        """system.approval use'u OLAN ama bu workflow'un onaycısı OLMAYAN kullanıcı → 403."""
        req_client, app_client, _, _ = _setup_avans_flow(db)
        _, req_id = _create_advance_request(req_client)
        # Farklı rolde, system.approval yetkili ama approver_roles'ta olmayan kullanıcı
        _, _, other_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        resp = other_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert resp.status_code == 403

    def test_approve_requires_use_permission(self, db):
        """system.approval view var ama use yok → 403."""
        req_client, _, _, wf = _setup_avans_flow(db)
        _, req_id = _create_advance_request(req_client)
        # wf'in approver rolüne sahip ama sadece view yetkili kullanıcı yapamaz —
        # bu yüzden ayrı: sadece view'lı yeni approver
        _, view_role, view_client = _make_actor(db, {"system.approval": {"view": True, "use": False}})
        # bu kullanıcıyı workflow'un onaycısı yap
        db.add(ApprovalWorkflowApproverRole(workflow_id=wf.id, role_id=view_role))
        db.commit()
        resp = view_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert resp.status_code == 403

    def test_approve_nonexistent_404(self, db):
        _, app_client, _, _ = _setup_avans_flow(db)
        assert app_client.post(f"{API}/requests/99999999/approve", json={}).status_code == 404

    def test_approve_non_pending_400(self, db):
        req_client, app_client, _, _ = _setup_avans_flow(db)
        _, req_id = _create_advance_request(req_client)
        assert app_client.post(f"{API}/requests/{req_id}/approve", json={}).status_code == 200
        # ikinci kez onaylama (artık approved) → 400
        assert app_client.post(f"{API}/requests/{req_id}/approve", json={}).status_code == 400


# ─────────────────── Executor uçtan uca (executor %9 → kapsam) ───────────────────

class TestApprovalExecutor:
    def test_update_advance_via_approval(self, db):
        req_client, app_client, _, _ = _setup_avans_flow(db)
        adv = Advance(agency_name="Eski Ad", amount=100, currency="EUR",
                      advance_date="2026-08-01", status="pending")
        db.add(adv)
        db.commit()
        adv_id = adv.id
        r = req_client.patch(f"/api/finance/avanslar/{adv_id}", json={"amount": 777})
        assert r.status_code == 202, r.text
        req_id = r.json()["request_id"]
        app_client.post(f"{API}/requests/{req_id}/approve", json={})
        db.expire_all()
        assert float(db.get(Advance, adv_id).amount) == 777

    def test_delete_advance_via_approval(self, db):
        req_client, app_client, _, _ = _setup_avans_flow(db)
        adv = Advance(agency_name="Silinecek", amount=100, currency="EUR",
                      advance_date="2026-08-01", status="pending")
        db.add(adv)
        db.commit()
        adv_id = adv.id
        r = req_client.delete(f"/api/finance/avanslar/{adv_id}")
        assert r.status_code == 202, r.text
        req_id = r.json()["request_id"]
        app_client.post(f"{API}/requests/{req_id}/approve", json={})
        db.expire_all()
        assert db.get(Advance, adv_id) is None

    def test_create_department_via_approval_regression(self, db):
        """REGRESYON: departman create handler'ı eskiden zorunlu `code`'u set etmiyor +
        olmayan `description`'ı geçiyordu → onay yoluyla departman oluşturma 500 veriyordu.
        Düzeltme sonrası onaylanınca departman doğru kodla oluşmalı."""
        _, req_role, req_client = _make_actor(db, {"finance.butce": {"view": True, "use": True}})
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "finance.butce", req_role, app_role)

        name = f"Dept {uuid4().hex[:6]}"
        code = f"D{uuid4().hex[:5]}"
        resp = req_client.post("/api/finance/departmanlar/", json={"name": name, "code": code})
        assert resp.status_code == 202, resp.text
        req_id = resp.json()["request_id"]

        db.expire_all()
        assert db.query(Department).filter(Department.name == name).first() is None

        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"onay 500 vermemeli (handler hatası): {ap.text}"
        assert ap.json()["status"] == STATUS_APPROVED

        db.expire_all()
        dept = db.query(Department).filter(Department.name == name).first()
        assert dept is not None, "Onay sonrası departman oluşturulmalıydı"
        assert dept.code == code

    def test_create_room_type_via_approval_regression(self, db):
        """REGRESYON: oda tipi executor handler'ı EKSİKTİ → onaylar 500 veriyordu
        (modül-denetci subagent yakaladı, 2026-06-17). Handler eklendikten sonra onaylanınca
        oda tipi gerçekten oluşmalı. 2026-07-09: satış modülleri birleştirildi —
        oda tipi CRUD onayı artık sales.acente_mahsup modül kodundan geçer."""
        from app.models.room_type import RoomType

        _, req_role, req_client = _make_actor(db, {
            "sales.acente_mahsup": {"view": True, "use": True},
            "system.approval": {"view": True, "use": False},
        })
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "sales.acente_mahsup", req_role, app_role)

        code = f"RT{uuid4().hex[:5].upper()}"
        resp = req_client.post("/api/sales/room-types/", json={
            "code": code, "name": "Test Oda", "total_rooms": 10, "max_occupancy": 3,
        })
        assert resp.status_code == 202, f"onaya düşmeli: {resp.text}"
        req_id = resp.json()["request_id"]

        db.expire_all()
        assert db.query(RoomType).filter(RoomType.code == code).first() is None

        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"handler eksikse 500 verir: {ap.text}"
        assert ap.json()["status"] == STATUS_APPROVED

        db.expire_all()
        rt = db.query(RoomType).filter(RoomType.code == code).first()
        assert rt is not None, "Onay sonrası oda tipi oluşturulmalıydı"
        assert rt.total_rooms == 10
        assert rt.max_occupancy == 3

    def test_check_status_via_approval_regression(self, db):
        """REGRESYON: _handle_finance_checks payload {"new_status"} ile model alanı "status"'u
        uyuşturmuyordu → onaylı çek durumu SESSİZCE değişmiyordu (2026-06-17 tarama bulgusu)."""
        from datetime import date as _date

        from app.models.check import Check, CheckUpload

        _, req_role, req_client = _make_actor(db, {
            "finance.checks": {"view": True, "use": True},
            "system.approval": {"view": True, "use": False},
        })
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "finance.checks", req_role, app_role)

        up = CheckUpload(file_name="seed", file_url="x")
        db.add(up)
        db.flush()
        chk = Check(upload_id=up.id, check_no=f"CHK{uuid4().hex[:5]}", vendor_name="Test Cari",
                    due_date=_date(2026, 9, 1), amount_tl=1000, amount_currency=1000, status="pending")
        db.add(chk)
        db.commit()
        chk_id = chk.id

        r = req_client.patch(f"/api/finance/checks/{chk_id}/status?new_status=paid")
        assert r.status_code == 202, f"onaya düşmeli: {r.text}"
        req_id = r.json()["request_id"]

        db.expire_all()
        assert db.get(Check, chk_id).status == "pending"  # onaydan önce değişmedi

        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"handler bug: {ap.text}"
        db.expire_all()
        assert db.get(Check, chk_id).status == "paid"  # ARTIK uygulanıyor (eskiden sessiz no-op)

# ─────────────────── Liste / durum endpoint'leri ───────────────────

class TestApprovalListEndpoints:
    def test_my_submissions(self, db):
        req_client, app_client, _, _ = _setup_avans_flow(db)
        _, req_id = _create_advance_request(req_client)
        resp = req_client.get(f"{API}/requests/my-submissions")
        assert resp.status_code == 200
        assert any(it["id"] == req_id for it in resp.json()["items"])

    def test_pending_count(self, db):
        req_client, app_client, _, _ = _setup_avans_flow(db)
        _create_advance_request(req_client)
        resp = app_client.get(f"{API}/requests/pending/count")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1

    def test_history_after_approve(self, db):
        req_client, app_client, _, _ = _setup_avans_flow(db)
        _, req_id = _create_advance_request(req_client)
        app_client.post(f"{API}/requests/{req_id}/approve", json={})
        resp = app_client.get(f"{API}/requests/history")
        assert resp.status_code == 200
        assert any(it["id"] == req_id for it in resp.json()["items"])

    def test_entity_status(self, db):
        req_client, app_client, _, _ = _setup_avans_flow(db)
        _, req_id = _create_advance_request(req_client)
        resp = app_client.get(f"{API}/status/finance.avanslar/0")
        assert resp.status_code == 200
        assert resp.json()["has_approval"] is True

    def test_request_detail_and_404(self, db):
        req_client, app_client, _, _ = _setup_avans_flow(db)
        _, req_id = _create_advance_request(req_client)
        assert app_client.get(f"{API}/requests/{req_id}").status_code == 200
        assert app_client.get(f"{API}/requests/99999999").status_code == 404


# ─────── P0 güvenlik: onay-okuma yetkilendirmesi (IDOR / payload sızıntısı) ───────

class TestApprovalReadAuthorization:
    """system.approval:view TEK BAŞINA başkasının talebini/yükünü görmeye yetmemeli."""

    @staticmethod
    def _outsider(db):
        """system.approval:view'li ama hiçbir talebin sahibi/onaycısı OLMAYAN 3. kişi."""
        _, _, client = _make_actor(db, {"system.approval": {"view": True, "use": False}})
        return client

    def test_outsider_cannot_read_request_detail(self, db):
        """IDOR: yabancı başkasının talep detayını GÖREMEZ (403); sahip+onaycı görebilir."""
        req_client, app_client, _, _ = _setup_avans_flow(db)
        _, req_id = _create_advance_request(req_client)
        outsider = self._outsider(db)
        assert outsider.get(f"{API}/requests/{req_id}").status_code == 403
        # Regresyon: meşru taraflar hâlâ görebilmeli
        assert req_client.get(f"{API}/requests/{req_id}").status_code == 200
        assert app_client.get(f"{API}/requests/{req_id}").status_code == 200

    def test_outsider_history_excludes_others(self, db):
        """IDOR: yabancının geçmişi başkalarının taleplerini içermez."""
        req_client, app_client, _, _ = _setup_avans_flow(db)
        _, req_id = _create_advance_request(req_client)
        app_client.post(f"{API}/requests/{req_id}/approve", json={})
        outsider = self._outsider(db)
        resp = outsider.get(f"{API}/requests/history")
        assert resp.status_code == 200
        assert all(it["id"] != req_id for it in resp.json()["items"])
        # Regresyon: işlem yapan onaycı kendi geçmişinde görebilmeli
        own = app_client.get(f"{API}/requests/history")
        assert any(it["id"] == req_id for it in own.json()["items"])

    def test_outsider_entity_status_hides_payload(self, db):
        """Yabancı durumu görebilir ama yük (payload) gizli; onaycı tam yükü görür."""
        req_client, app_client, _, _ = _setup_avans_flow(db)
        _create_advance_request(req_client)
        outsider = self._outsider(db)
        body = outsider.get(f"{API}/status/finance.avanslar/0").json()
        assert body["has_approval"] is True
        assert body.get("request") is None
        app_body = app_client.get(f"{API}/status/finance.avanslar/0").json()
        assert app_body.get("request") is not None

    def test_user_create_password_redacted_e2e(self, db):
        """Uçtan uca: kullanıcı oluşturma onayının yükünde düz-metin şifre API'den DÖNMEZ."""
        _, req_role, req_client = _make_actor(db, {
            "system.users": {"view": True, "use": True},
            "system.approval": {"view": True, "use": False},
        })
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "system.users", req_role, app_role)
        target_role = _mk_role(db)
        db.commit()

        uid = uuid4().hex[:6]
        secret = "CokGizliSifre12345"
        resp = req_client.post("/api/system/users/", json={
            "username": f"yeni_{uid}", "email": f"yeni_{uid}@test.local",
            "password": secret, "first_name": "Yeni", "last_name": "Kullanici",
            "role_id": target_role,
        })
        assert resp.status_code == 202, f"onaya düşmeli: {resp.text}"
        req_id = resp.json()["request_id"]

        detail = app_client.get(f"{API}/requests/{req_id}").json()
        assert secret not in (detail["payload_json"] or ""), "düz-metin şifre sızdı!"
        payload = json.loads(detail["payload_json"])
        assert payload["password"] == "***"
        assert payload["username"] == f"yeni_{uid}"  # şifre dışı alanlar korunur

    def test_redact_payload_unit(self):
        """_redact_payload: özyinelemeli hassas-alan maskeleme + bozuk/boş giriş."""
        raw = json.dumps({
            "username": "ali", "password": "x", "role_id": 5,
            "nested": {"api_token": "t", "name": "y"},
            "items": [{"secret_key": "s"}],
        })
        out = json.loads(_redact_payload(raw))
        assert out["password"] == "***"
        assert out["username"] == "ali"
        assert out["role_id"] == 5
        assert out["nested"]["api_token"] == "***"
        assert out["nested"]["name"] == "y"
        assert out["items"][0]["secret_key"] == "***"
        assert _redact_payload(None) is None
        assert _redact_payload("not-json") is None  # parse edilemeyen yük dışarı verilmez


# ─────── Executor — ek modül handler'ları (scheduled + system.roles) ───────

class TestApprovalExecutorMoreModules:
    def test_scheduled_salary_create_via_approval(self, db):
        """Scheduled handler (8 modülün paylaştığı): onay yolunda pasif tanım oluşur,
        onaylanınca executor onu aktifleştirir + girişleri üretir."""
        _, req_role, req_client = _make_actor(db, {"hr.salary": {"view": True, "use": True}})
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "hr.salary", req_role, app_role)

        name = f"Maaş {uuid4().hex[:6]}"
        resp = req_client.post("/api/hr/salary/", json={
            "name": name, "amount": 5000.0, "currency": "TRY",
            "frequency": "monthly", "payment_day": 15, "start_month": 1, "year": 2026,
        })
        assert resp.status_code == 202, resp.text
        req_id = resp.json()["request_id"]

        # Onaydan önce: pasif tanım var ama aktif değil
        db.expire_all()
        defn = (
            db.query(ScheduledDefinition)
            .filter(ScheduledDefinition.source_type == "salary", ScheduledDefinition.name == name)
            .first()
        )
        assert defn is not None and defn.is_active is False

        # Onayla → executor aktifleştirir (200 = executor hatasız çalıştı)
        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, ap.text

        db.expire_all()
        defn2 = (
            db.query(ScheduledDefinition)
            .filter(ScheduledDefinition.source_type == "salary", ScheduledDefinition.name == name)
            .first()
        )
        assert defn2 is not None and defn2.is_active is True

    def test_role_create_via_approval(self, db):
        """system.roles handler: onaylanınca rol gerçekten oluşturulur."""
        _, req_role, req_client = _make_actor(db, {"system.roles": {"view": True, "use": True}})
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "system.roles", req_role, app_role)

        rname = f"Rol {uuid4().hex[:6]}"
        resp = req_client.post("/api/system/roles/",
                               json={"name": rname, "description": "onay testi", "permissions": []})
        assert resp.status_code == 202, resp.text
        req_id = resp.json()["request_id"]

        db.expire_all()
        assert db.query(Role).filter(Role.name == rname).first() is None

        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, ap.text

        db.expire_all()
        assert db.query(Role).filter(Role.name == rname).first() is not None

    def test_bank_account_create_via_approval(self, db):
        """REGRESYON: banks handler'ı `from app.models.bank_transaction import BankAccount`
        ile yanlış modülden import ediyordu → onaylanınca ImportError → 500."""
        from app.models.bank_account import BankAccount
        _, req_role, req_client = _make_actor(db, {"finance.banks": {"view": True, "use": True}})
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "finance.banks", req_role, app_role)

        bname = f"Banka {uuid4().hex[:6]}"
        resp = req_client.post("/api/finance/banks/accounts/", json={
            "bank_name": bname, "iban": f"TR{uuid4().hex[:20]}", "currency": "TRY",
        })
        assert resp.status_code == 202, resp.text
        req_id = resp.json()["request_id"]

        db.expire_all()
        assert db.query(BankAccount).filter(BankAccount.bank_name == bname).first() is None

        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"banks handler 500 vermemeli (import regresyonu): {ap.text}"

        db.expire_all()
        assert db.query(BankAccount).filter(BankAccount.bank_name == bname).first() is not None

    def test_credit_product_create_via_approval(self, db):
        """REGRESYON: krediler handler'ı `from app.models.credit import ...` ile yanlış
        modülden import ediyordu (doğrusu credit_product) → onaylanınca 500."""
        from app.models.credit_product import CreditProduct
        _, req_role, req_client = _make_actor(db, {"finance.krediler": {"view": True, "use": True}})
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "finance.krediler", req_role, app_role)

        cname = f"Kredi {uuid4().hex[:6]}"
        resp = req_client.post("/api/finance/krediler/", json={
            "type": "spot_kredi", "name": cname, "currency": "TRY", "total_amount": 100000,
        })
        assert resp.status_code == 202, resp.text
        req_id = resp.json()["request_id"]

        db.expire_all()
        assert db.query(CreditProduct).filter(CreditProduct.name == cname).first() is None

        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"krediler handler 500 vermemeli (import regresyonu): {ap.text}"

        db.expire_all()
        assert db.query(CreditProduct).filter(CreditProduct.name == cname).first() is not None

    def test_credit_bch_create_via_approval_generates_plan(self, db):
        """REGRESYON (D2-4): krediler create handler'ı BCH/KMH ödeme planını + finance_events'i
        ÜRETMİYORDU (router üretiyordu) → onaylı BCH kredisi sessizce plansız/nakit-akımsız oluşuyordu.
        Service ortaklaştırması (2026-06-22) sonrası onaylanan BCH kredisi taksit planını + FE üretmeli."""
        from app.models.credit_product import CreditPayment, CreditProduct
        from app.models.finance_event import FinanceEvent
        _, req_role, req_client = _make_actor(db, {"finance.krediler": {"view": True, "use": True}})
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "finance.krediler", req_role, app_role)

        cname = f"BCH {uuid4().hex[:6]}"
        resp = req_client.post("/api/finance/krediler/", json={
            "type": "bch", "name": cname, "currency": "TRY", "total_amount": 1000000,
            "interest_rate": 50, "start_date": "2026-01-01", "end_date": "2026-12-31",
        })
        assert resp.status_code == 202, resp.text
        req_id = resp.json()["request_id"]

        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"BCH onayı 500 vermemeli (plan/tarih regresyonu): {ap.text}"

        db.expire_all()
        prod = db.query(CreditProduct).filter(CreditProduct.name == cname).first()
        assert prod is not None
        payments = db.query(CreditPayment).filter(CreditPayment.credit_product_id == prod.id).all()
        assert len(payments) > 0, "Onaylı BCH kredisi ödeme planı üretmeliydi (D2-4)"
        fe = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == "credit",
            FinanceEvent.source_id.in_([p.id for p in payments]),
        ).count()
        assert fe > 0, "Taksitlerin finance_events kayıtları üretilmeliydi (D2-4)"

    def test_credit_payment_update_via_approval(self, db):
        """REGRESYON (D2-4): executor payment update `payment.product_id` (yanlış kolon —
        model `credit_product_id`) kullanıyordu → onaylı ödeme güncelleme AttributeError/500.
        Service sonrası onaylanınca ödeme güncellenmeli + kalan borç principal kadar azalmalı."""
        from datetime import date

        from app.models.credit_product import CreditPayment, CreditProduct
        _, req_role, req_client = _make_actor(db, {"finance.krediler": {"view": True, "use": True}})
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "finance.krediler", req_role, app_role)

        prod = CreditProduct(type="spot_kredi", name=f"K {uuid4().hex[:6]}", currency="TRY",
                             total_amount=100000, remaining_amount=100000)
        db.add(prod)
        db.flush()
        pay = CreditPayment(credit_product_id=prod.id, installment_no=1, due_date=date(2026, 6, 30),
                            amount=10000, principal=10000, is_paid=False)
        db.add(pay)
        db.commit()
        pid, prod_id = pay.id, prod.id

        r = req_client.patch(f"/api/finance/krediler/payments/{pid}", json={"is_paid": True})
        assert r.status_code == 202, r.text
        req_id = r.json()["request_id"]

        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"executor product_id bug'ı 500 verirdi (D2-4): {ap.text}"

        db.expire_all()
        assert db.get(CreditPayment, pid).is_paid is True
        assert float(db.get(CreditProduct, prod_id).remaining_amount) == 90000  # 100000 - 10000 principal

    def test_dividend_create_via_approval_generates_installments_payments_and_events(self, db):
        """Temettü bespoke handler (_handle_accounting_dividend): onaylanınca dağıtım +
        taksitler + 72 (burada 6) ödeme + net/stopaj finance_events üretilir (router ile birebir)."""
        from app.models.dividend import (
            DividendDistribution, DividendInstallment, DividendPayment,
        )
        from app.models.finance_event import (
            FinanceEvent, SOURCE_DIVIDEND, SOURCE_DIVIDEND_STOPAJ,
        )
        _, req_role, req_client = _make_actor(db, {"accounting.dividend": {"view": True, "use": True}})
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "accounting.dividend", req_role, app_role)

        dname = f"KP {uuid4().hex[:6]}"
        resp = req_client.post("/api/accounting/dividend/", json={
            "name": dname, "total_gross": 1200000, "withholding_rate": 0.15,
            "installment_count": 3, "year": 2026, "first_installment_date": "2026-06-30",
            "shareholders": [{"name": "A", "share_value": 600000},
                             {"name": "B", "share_value": 600000}],
        })
        assert resp.status_code == 202, resp.text
        req_id = resp.json()["request_id"]

        db.expire_all()
        assert db.query(DividendDistribution).filter(DividendDistribution.name == dname).first() is None

        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"temettü onayı 500 vermemeli: {ap.text}"

        db.expire_all()
        dist = db.query(DividendDistribution).filter(DividendDistribution.name == dname).first()
        assert dist is not None
        insts = db.query(DividendInstallment).filter_by(distribution_id=dist.id).all()
        assert len(insts) == 3
        pay_ids = [pid for (pid,) in db.query(DividendPayment.id).filter_by(distribution_id=dist.id).all()]
        assert len(pay_ids) == 6  # 2 ortak × 3 taksit
        # finance_events ÖDEME bazlı (kişi-kişi): 6 net + 6 stopaj
        net = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == SOURCE_DIVIDEND, FinanceEvent.source_id.in_(pay_ids)).count()
        stopaj = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == SOURCE_DIVIDEND_STOPAJ, FinanceEvent.source_id.in_(pay_ids)).count()
        assert net == 6 and stopaj == 6

    def test_dividend_payment_toggle_via_approval(self, db):
        """Temettü ödeme (net) toggle onay yolu → _target=payment dalı is_paid'i uygular."""
        from app.models.dividend import DividendPayment
        from app.services import dividend_service
        _, req_role, req_client = _make_actor(db, {"accounting.dividend": {"view": True, "use": True}})
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "accounting.dividend", req_role, app_role)

        dist = dividend_service.create_distribution(db, {
            "name": f"KP {uuid4().hex[:6]}", "total_gross": 600000, "withholding_rate": 0.15,
            "installment_count": 2, "year": 2026, "first_installment_date": "2026-06-30",
            "shareholders": [{"name": "A", "share_value": 600000}],
        }, actor_id=None)
        db.commit()
        pid = db.query(DividendPayment).filter_by(distribution_id=dist.id).first().id

        r = req_client.patch(f"/api/accounting/dividend/payments/{pid}", json={"is_paid": True})
        assert r.status_code == 202, r.text
        req_id = r.json()["request_id"]

        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"temettü ödeme onayı 500 vermemeli: {ap.text}"

        db.expire_all()
        assert db.get(DividendPayment, pid).is_paid is True

    def test_credit_product_delete_via_approval(self, db):
        """REGRESYON (D2-4): executor product delete `CreditPayment.product_id` (yanlış kolon)
        ile sorguluyordu → AttributeError/500. Service sonrası onaylı silme ürünü + ödemeleri
        kaldırmalı, finance_events invalidate edilmeli."""
        from datetime import date

        from app.models.credit_product import CreditPayment, CreditProduct
        from app.models.finance_event import FinanceEvent
        from app.utils.finance_event_service import finance_event_svc
        _, req_role, req_client = _make_actor(db, {"finance.krediler": {"view": True, "use": True}})
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "finance.krediler", req_role, app_role)

        prod = CreditProduct(type="spot_kredi", name=f"Sil {uuid4().hex[:6]}", currency="TRY",
                             total_amount=50000, remaining_amount=50000)
        db.add(prod)
        db.flush()
        pay = CreditPayment(credit_product_id=prod.id, installment_no=1, due_date=date(2026, 6, 30),
                            amount=5000, principal=5000, is_paid=False)
        db.add(pay)
        db.flush()
        finance_event_svc.upsert_credit_payment(db, pay, prod)
        db.commit()
        prod_id, pid = prod.id, pay.id
        assert db.query(FinanceEvent).filter(
            FinanceEvent.source_type == "credit", FinanceEvent.source_id == pid).count() == 1

        r = req_client.delete(f"/api/finance/krediler/{prod_id}")
        assert r.status_code == 202, r.text
        req_id = r.json()["request_id"]

        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"executor product_id bug'ı 500 verirdi (D2-4): {ap.text}"

        db.expire_all()
        assert db.get(CreditProduct, prod_id) is None
        assert db.get(CreditPayment, pid) is None
        assert db.query(FinanceEvent).filter(
            FinanceEvent.source_type == "credit", FinanceEvent.source_id == pid).count() == 0

    def test_vendor_payment_days_via_approval(self, db):
        """REGRESYON (D1-2, 2026-06-22): cari vade güncelleme onay yoluyla — executor router'la
        ORTAK service (vendor_service.apply_vendor_update) çağırmalı; vade değişince işlemlerin
        ödeme tarihi yeniden hesaplanmalı (eski elle-tekrar handler router'dan saparsa onaylı
        vade değişimi nakit akıma yansımazdı)."""
        from datetime import date

        from app.models.vendor import Vendor
        from app.models.vendor_transaction import VendorTransaction
        from app.models.vendor_upload import VendorUpload
        from app.utils.vendor_parser import calculate_payment_friday, compute_vendor_tx_hash

        _, req_role, req_client = _make_actor(db, {"finance.cariler": {"view": True, "use": True}})
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "finance.cariler", req_role, app_role)

        up = VendorUpload(file_name="t.xlsx", file_url="/tmp/t.xlsx", uploaded_by=1,
                          total_vendors=1, total_transactions=0, new_transactions=0, skipped_transactions=0)
        db.add(up)
        db.flush()
        code = f"320.{uuid4().hex[:6]}"
        vendor = Vendor(hesap_kodu=code, hesap_adi="Test Cari", payment_days=30)
        db.add(vendor)
        db.flush()
        d = date(2026, 3, 2)
        tx = VendorTransaction(vendor_id=vendor.id, upload_id=up.id, date=d, transaction_type="Fatura",
                               borc=0, alacak=1000, bakiye=0,
                               tx_hash=compute_vendor_tx_hash(code, d, "E1", 0, 1000))
        db.add(tx)
        db.commit()
        vid, tid = vendor.id, tx.id

        r = req_client.patch(f"/api/finance/cariler/vendors/{vid}/payment-days", json={"payment_days": 60})
        assert r.status_code == 202, r.text
        req_id = r.json()["request_id"]
        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"cari vade onayı 500 vermemeli: {ap.text}"

        db.expire_all()
        assert db.get(Vendor, vid).payment_days == 60
        assert db.get(VendorTransaction, tid).payment_due_date == calculate_payment_friday(d, 60)

    def test_vendor_status_via_approval_syncs_finance_events(self, db):
        """REGRESYON (D1-2): cari 'ödeme yasaklısı' yapma onay yoluyla → sync_vendor_finance_events
        çağrılıp yasaklı carinin nakit-akım (vendor_payment) kayıtları silinmeli (router davranışı)."""
        from datetime import date

        from app.models.finance_event import FinanceEvent
        from app.models.vendor import STATUS_PAYMENT_BANNED, Vendor
        from app.models.vendor_transaction import VendorTransaction
        from app.models.vendor_upload import VendorUpload
        from app.utils.sync_vendor_fifo import sync_vendor_finance_events
        from app.utils.vendor_parser import compute_vendor_tx_hash

        _, req_role, req_client = _make_actor(db, {"finance.cariler": {"view": True, "use": True}})
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "finance.cariler", req_role, app_role)

        up = VendorUpload(file_name="t.xlsx", file_url="/tmp/t.xlsx", uploaded_by=1,
                          total_vendors=1, total_transactions=0, new_transactions=0, skipped_transactions=0)
        db.add(up)
        db.flush()
        code = f"320.{uuid4().hex[:6]}"
        vendor = Vendor(hesap_kodu=code, hesap_adi="Yasak Cari", payment_days=30)
        db.add(vendor)
        db.flush()
        d = date(2026, 3, 2)
        tx = VendorTransaction(vendor_id=vendor.id, upload_id=up.id, date=d, transaction_type="Fatura",
                               borc=0, alacak=5000, bakiye=0, payment_due_date=d,
                               tx_hash=compute_vendor_tx_hash(code, d, "E1", 0, 5000))
        db.add(tx)
        db.flush()
        sync_vendor_finance_events(db)
        db.commit()
        vid, tid = vendor.id, tx.id
        assert db.query(FinanceEvent).filter(
            FinanceEvent.source_type == "vendor_payment", FinanceEvent.source_id == tid).count() == 1

        r = req_client.patch(f"/api/finance/cariler/vendors/{vid}/status", json={"status": STATUS_PAYMENT_BANNED})
        assert r.status_code == 202, r.text
        req_id = r.json()["request_id"]
        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"cari durum onayı 500 vermemeli: {ap.text}"

        db.expire_all()
        assert db.get(Vendor, vid).status == STATUS_PAYMENT_BANNED
        assert db.query(FinanceEvent).filter(
            FinanceEvent.source_type == "vendor_payment", FinanceEvent.source_id == tid).count() == 0

    def test_check_cancel_via_approval_unmatches_vendor(self, db):
        """REGRESYON (D1-2, 2026-06-22): eşleşmiş çekin onay yoluyla İPTAL edilmesi → cari eşleşmesi
        (match_number + payment_method) kaldırılmalı (router iptal kademesi). Eski executor handler bu
        çoklu-varlık kademeyi elle tekrarlıyordu; `check_service` ile router↔executor tek kaynak →
        kademe sapamaz (mevcut test yalnız temel pending→paid'i kapsıyordu, iptal kademesini değil)."""
        from datetime import date as _date

        from app.models.check import Check, CheckUpload
        from app.models.vendor import Vendor
        from app.models.vendor_transaction import VendorTransaction
        from app.models.vendor_upload import VendorUpload
        from app.utils.vendor_parser import compute_vendor_tx_hash

        _, req_role, req_client = _make_actor(db, {"finance.checks": {"view": True, "use": True}})
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "finance.checks", req_role, app_role)

        mno = int(uuid4().int % 9000000) + 1000000  # benzersiz match_number
        cu = CheckUpload(file_name="seed", file_url="x")
        db.add(cu)
        vu = VendorUpload(file_name="t.xlsx", file_url="/tmp/t.xlsx", uploaded_by=1,
                          total_vendors=1, total_transactions=0, new_transactions=0, skipped_transactions=0)
        db.add(vu)
        db.flush()
        code = f"320.{uuid4().hex[:6]}"
        vendor = Vendor(hesap_kodu=code, hesap_adi="Eşleşen Cari")
        db.add(vendor)
        db.flush()
        d = _date(2026, 3, 2)
        vtx = VendorTransaction(vendor_id=vendor.id, upload_id=vu.id, date=d, transaction_type="Fatura",
                                borc=1000, alacak=0, bakiye=0, match_number=mno, payment_method="cek",
                                tx_hash=compute_vendor_tx_hash(code, d, "E1", 1000, 0))
        db.add(vtx)
        chk = Check(upload_id=cu.id, check_no=f"CHK{uuid4().hex[:5]}", vendor_name="Eşleşen Cari",
                    due_date=_date(2026, 9, 1), amount_tl=1000, amount_currency=1000, status="pending",
                    match_number=mno, matched_vendor_id=vendor.id)
        db.add(chk)
        db.commit()
        chk_id, vtx_id = chk.id, vtx.id

        r = req_client.patch(f"/api/finance/checks/{chk_id}/status?new_status=cancelled")
        assert r.status_code == 202, r.text
        req_id = r.json()["request_id"]
        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"çek iptal onayı 500 vermemeli: {ap.text}"

        db.expire_all()
        chk2 = db.get(Check, chk_id)
        assert chk2.status == "cancelled"
        assert chk2.match_number is None and chk2.matched_vendor_id is None  # çek eşleşmesi kalktı
        vtx2 = db.get(VendorTransaction, vtx_id)
        assert vtx2.match_number is None and vtx2.payment_method is None  # cari eşleşmesi de kalktı (kademe)


    def test_budget_create_via_approval_upserts_not_duplicate(self, db):
        """REGRESYON: budget executor handler entity_id bazlı INSERT yapıyordu (create'te
        entity_id=0 → existing=None → her zaman INSERT). Router ise KOMPOZİT ANAHTAR upsert
        (dept+cat+yıl+ay) yapar → aynı dönem için onaylı iki budget create ÇİFT satır / 
        uq_budget_dept_cat_year_month ihlali oluşturuyordu. Düzeltme sonrası ikinci onay AYNI
        kaydı GÜNCELLEMELİ (tek satır kalmalı, tutar güncellenmeli)."""
        from app.models.budget import Budget, BudgetCategory

        _, req_role, req_client = _make_actor(db, {"finance.butce": {"view": True, "use": True}})
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "finance.butce", req_role, app_role)

        dept = Department(name=f"Dept {uuid4().hex[:6]}", code=f"D{uuid4().hex[:5]}", is_active=True)
        cat = BudgetCategory(name=f"Kat {uuid4().hex[:6]}", type="expense", is_active=True)
        db.add(dept)
        db.add(cat)
        db.commit()
        dept_id, cat_id = dept.id, cat.id

        def _period_count():
            return db.query(Budget).filter(
                Budget.department_id == dept_id,
                Budget.category_id == cat_id,
                Budget.year == 2099,
                Budget.month == 5,
            ).count()

        # 1. onaylı create
        r1 = req_client.post("/api/finance/butce/", json={
            "department_id": dept_id, "category_id": cat_id,
            "year": 2099, "month": 5, "planned_amount": 1000, "currency": "TRY",
        })
        assert r1.status_code == 202, r1.text
        ap1 = app_client.post(f"{API}/requests/{r1.json()['request_id']}/approve", json={})
        assert ap1.status_code == 200, ap1.text
        db.expire_all()
        assert _period_count() == 1, "İlk onaylı create tek bütçe oluşturmalı"

        # 2. AYNI dönem için ikinci onaylı create → çift değil, upsert (güncelle)
        r2 = req_client.post("/api/finance/butce/", json={
            "department_id": dept_id, "category_id": cat_id,
            "year": 2099, "month": 5, "planned_amount": 2500, "currency": "TRY",
        })
        assert r2.status_code == 202, r2.text
        ap2 = app_client.post(f"{API}/requests/{r2.json()['request_id']}/approve", json={})
        assert ap2.status_code == 200, f"ikinci onay 500/çakışma vermemeli: {ap2.text}"
        db.expire_all()
        assert _period_count() == 1, "İkinci onaylı create ÇİFT bütçe oluşturmamalı (kompozit upsert)"
        row = db.query(Budget).filter(
            Budget.department_id == dept_id, Budget.category_id == cat_id,
            Budget.year == 2099, Budget.month == 5,
        ).first()
        assert float(row.planned_amount) == 2500, "Upsert planned_amount'u güncellemeli"

    def test_budget_bulk_via_approval_upserts_not_duplicate(self, db):
        """REGRESYON: /butce/bulk eskiden check_approval çağırmıyordu (kritik denetim bulgusu,
        2026-07-01) VE elle Budget() insert/update ile budget_service'i bypass ediyordu.
        Düzeltme sonrası bulk onaya girer (202) ve executor `_target="bulk"` dalı her kalemi
        kompozit-anahtar upsert eder → onaylı bulk çift satır oluşturmaz, ikinci onay günceller."""
        from app.models.budget import Budget, BudgetCategory

        _, req_role, req_client = _make_actor(db, {"finance.butce": {"view": True, "use": True}})
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "finance.butce", req_role, app_role)

        dept = Department(name=f"Dept {uuid4().hex[:6]}", code=f"D{uuid4().hex[:5]}", is_active=True)
        cat = BudgetCategory(name=f"Kat {uuid4().hex[:6]}", type="expense", is_active=True)
        db.add(dept)
        db.add(cat)
        db.commit()
        dept_id, cat_id = dept.id, cat.id

        def _period_count():
            return db.query(Budget).filter(
                Budget.department_id == dept_id,
                Budget.category_id == cat_id,
                Budget.year == 2099,
                Budget.month == 7,
            ).count()

        payload = {"items": [{
            "department_id": dept_id, "category_id": cat_id,
            "year": 2099, "month": 7, "planned_amount": 1000, "currency": "TRY",
        }]}

        # 1. onaylı bulk → 202 → onay → tek satır
        r1 = req_client.post("/api/finance/butce/bulk", json=payload)
        assert r1.status_code == 202, r1.text
        ap1 = app_client.post(f"{API}/requests/{r1.json()['request_id']}/approve", json={})
        assert ap1.status_code == 200, ap1.text
        db.expire_all()
        assert _period_count() == 1, "Onaylı bulk tek bütçe oluşturmalı"

        # 2. AYNI dönem farklı tutar → çift değil, upsert (güncelle)
        payload["items"][0]["planned_amount"] = 3300
        r2 = req_client.post("/api/finance/butce/bulk", json=payload)
        assert r2.status_code == 202, r2.text
        ap2 = app_client.post(f"{API}/requests/{r2.json()['request_id']}/approve", json={})
        assert ap2.status_code == 200, f"ikinci onay çakışma vermemeli: {ap2.text}"
        db.expire_all()
        assert _period_count() == 1, "İkinci onaylı bulk ÇİFT bütçe oluşturmamalı (kompozit upsert)"
        row = db.query(Budget).filter(
            Budget.department_id == dept_id, Budget.category_id == cat_id,
            Budget.year == 2099, Budget.month == 7,
        ).first()
        assert float(row.planned_amount) == 3300, "Bulk upsert planned_amount'u güncellemeli"

    def test_hakedis_term_via_approval_regression(self, db):
        """finance.hakedis vade tanımı onay akışı uçtan-uca: PATCH 202 → onay →
        executor _handle_finance_hakedis ortak receivable_service.upsert_term'i çağırır →
        vade GERÇEKTEN uygulanır (customer_code doğal anahtarlı upsert, çift kayıt yok)."""
        from app.models.receivable_term import ReceivableTerm

        _, req_role, req_client = _make_actor(db, {"finance.hakedis": {"view": True, "use": True}})
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "finance.hakedis", req_role, app_role)

        code = f"120.97.01.{uuid4().hex[:4].upper()}"
        r = req_client.patch(f"/api/finance/hakedis/terms/{code}",
                             json={"term_days": 45, "notes": "onaylı anlaşma"})
        assert r.status_code == 202, r.text
        ap = app_client.post(f"{API}/requests/{r.json()['request_id']}/approve", json={})
        assert ap.status_code == 200, ap.text
        db.expire_all()
        rows = db.query(ReceivableTerm).filter(ReceivableTerm.customer_code == code).all()
        assert len(rows) == 1, "Onaylı upsert TEK kayıt oluşturmalı"
        assert rows[0].term_days == 45, "Onay sonrası vade gerçekten uygulanmalı"

    def test_credit_close_reopen_via_approval_actually_toggles(self, db):
        """REGRESYON (2026-07-01 denetim, KRİTİK): close/reopen onay payload'ı {"action":"close"|"reopen"}
        gönderir ama executor bunu OKUMUYORDU → apply_product_update `action`'ı anlamsız bir attribute'a
        yazıp status'ü DEĞİŞTİRMİYORDU → onaylı kapatma/açma SESSİZCE çalışmıyordu. Düzeltme sonrası
        executor ortak credit_service.close_product/reopen_product'ı çağırır → status GERÇEKTEN değişir."""
        from app.models.credit_product import CreditProduct

        _, req_role, req_client = _make_actor(db, {"finance.krediler": {"view": True, "use": True}})
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "finance.krediler", req_role, app_role)

        product = CreditProduct(
            type="spot", name=f"Kredi {uuid4().hex[:6]}", currency="TRY",
            total_amount=100000, remaining_amount=100000, status="active",
        )
        db.add(product)
        db.commit()
        pid = product.id

        # close → 202 → onay → status GERÇEKTEN 'closed'
        r = req_client.post(f"/api/finance/krediler/{pid}/close", json={})
        assert r.status_code == 202, r.text
        ap = app_client.post(f"{API}/requests/{r.json()['request_id']}/approve", json={})
        assert ap.status_code == 200, ap.text
        db.expire_all()
        closed = db.query(CreditProduct).filter(CreditProduct.id == pid).first()
        assert closed.status == "closed", "Onaylı kapatma status'ü 'closed' yapmalı (executor action bug regresyonu)"
        assert closed.closed_date is not None, "Onaylı kapatma closed_date set etmeli"

        # reopen → 202 → onay → status GERÇEKTEN 'active'
        r2 = req_client.post(f"/api/finance/krediler/{pid}/reopen", json={})
        assert r2.status_code == 202, r2.text
        ap2 = app_client.post(f"{API}/requests/{r2.json()['request_id']}/approve", json={})
        assert ap2.status_code == 200, ap2.text
        db.expire_all()
        reopened = db.query(CreditProduct).filter(CreditProduct.id == pid).first()
        assert reopened.status == "active", "Onaylı reopen status'ü 'active' yapmalı"
        assert reopened.closed_date is None, "Onaylı reopen closed_date'i temizlemeli"


class TestApprovalExecutorHR:
    """İK modüllerinin (hr.attendance, hr.shift_schedule) uçtan-uca onay→uygula regresyonu.

    Bu handler'lar yalnızca onay onaylanınca çalışır → router'dan sapması sessiz kalır.
    Modül-bazlı regresyon: 202 → approver onaylar → handler kaydı GERÇEKTEN üretir
    (alanlar doğru, yan etkiler doğru). Handler eksik/bozuk olsaydı onay 500 verirdi.
    """

    @staticmethod
    def _mk_personnel(db):
        import uuid as _uuid

        from app.models.personnel import Personnel
        p = Personnel(
            full_name="Onay Personel",
            employee_code=f"AP-{_uuid.uuid4().hex[:6]}",
            department="Mutfak",
            access_token=f"ENR-{_uuid.uuid4().hex}",
            is_active=True,
        )
        db.add(p)
        db.commit()
        return p

    def test_attendance_manual_create_via_approval(self, db):
        """REGRESYON: hr.attendance elle giriş onaya düşünce `_handle_attendance` create
        AttendanceLog'u GERÇEKTEN oluşturmalı (kaynak=manual, tip/personel/zaman doğru)."""
        from datetime import datetime as _dt
        from datetime import timedelta as _td

        import pytz as _pytz

        from app.models.personnel import TYPE_IN, AttendanceLog

        tz = _pytz.timezone("Europe/Istanbul")
        _, req_role, req_client = _make_actor(db, {
            "hr.attendance": {"view": True, "use": True},
            "system.approval": {"view": True, "use": False},
        })
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "hr.attendance", req_role, app_role)

        p = self._mk_personnel(db)
        when = (_dt.now(tz) - _td(hours=2)).isoformat()
        resp = req_client.post("/api/attendance/manual", json={
            "personnel_id": p.id, "type": TYPE_IN, "punched_at": when, "note": "Onaylı giriş",
        })
        assert resp.status_code == 202, f"onaya düşmeli: {resp.text}"
        req_id = resp.json()["request_id"]

        # Onaydan önce: kayıt oluşmamalı
        db.expire_all()
        assert db.query(AttendanceLog).filter(AttendanceLog.personnel_id == p.id).count() == 0

        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"_handle_attendance create hatası → 500: {ap.text}"

        db.expire_all()
        logs = db.query(AttendanceLog).filter(AttendanceLog.personnel_id == p.id).all()
        assert len(logs) == 1, "Onay sonrası elle giriş kaydı oluşmalıydı"
        assert logs[0].type == TYPE_IN
        assert logs[0].source == "manual"
        assert logs[0].note == "Onaylı giriş"

    def test_attendance_delete_via_approval_soft_delete(self, db):
        """REGRESYON: hr.attendance silme onaylanınca `_handle_attendance` soft delete
        uygulamalı (deleted_at set; kayıt DB'de kalır)."""
        from datetime import datetime as _dt
        from datetime import timedelta as _td

        import pytz as _pytz

        from app.models.personnel import TYPE_IN, AttendanceLog

        tz = _pytz.timezone("Europe/Istanbul")
        _, req_role, req_client = _make_actor(db, {
            "hr.attendance": {"view": True, "use": True},
            "system.approval": {"view": True, "use": False},
        })
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "hr.attendance", req_role, app_role)

        p = self._mk_personnel(db)
        lg = AttendanceLog(personnel_id=p.id, type=TYPE_IN, source="manual",
                           punched_at=_dt.now(tz) - _td(hours=1))
        db.add(lg)
        db.commit()
        lg_id = lg.id

        r = req_client.delete(f"/api/attendance/logs/{lg_id}")
        assert r.status_code == 202, f"onaya düşmeli: {r.text}"
        req_id = r.json()["request_id"]

        # Onaydan önce: silinmemiş
        db.expire_all()
        assert db.get(AttendanceLog, lg_id).deleted_at is None

        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"_handle_attendance delete hatası → 500: {ap.text}"

        db.expire_all()
        row = db.get(AttendanceLog, lg_id)
        assert row is not None, "soft delete — kayıt DB'de kalmalı"
        assert row.deleted_at is not None

    def test_shift_schedule_assign_via_approval(self, db):
        """REGRESYON: hr.shift_schedule hücre ataması onaylanınca `_handle_shift_schedule`
        ShiftAssignment'ı GERÇEKTEN upsert etmeli (personel+gün+vardiya doğru)."""
        from datetime import time as _time

        from app.models.shift import ShiftDefinition
        from app.models.shift_assignment import ShiftAssignment

        _, req_role, req_client = _make_actor(db, {
            "hr.shift_schedule": {"view": True, "use": True},
            "system.approval": {"view": True, "use": False},
        })
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "hr.shift_schedule", req_role, app_role)

        p = self._mk_personnel(db)
        sh = ShiftDefinition(name=f"Rota T {uuid4().hex[:4]}", color="#0d9488",
                             start_time=_time(7, 0), end_time=_time(15, 0))
        db.add(sh)
        db.commit()
        pid, sid = p.id, sh.id

        resp = req_client.post("/api/hr/shift-schedule", json={
            "personnel_id": pid, "shift_id": sid, "work_date": "2026-07-02",
        })
        assert resp.status_code == 202, f"onaya düşmeli: {resp.text}"
        req_id = resp.json()["request_id"]

        # Onaydan önce: atama oluşmamalı
        db.expire_all()
        assert db.query(ShiftAssignment).filter(
            ShiftAssignment.personnel_id == pid).count() == 0

        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"_handle_shift_schedule hatası → 500: {ap.text}"

        db.expire_all()
        a = db.query(ShiftAssignment).filter(ShiftAssignment.personnel_id == pid).first()
        assert a is not None, "Onay sonrası rota ataması oluşmalıydı"
        assert a.shift_id == sid
        assert a.work_date.isoformat() == "2026-07-02"

    def test_shift_schedule_delete_via_approval(self, db):
        """REGRESYON: hr.shift_schedule hücre silme onaylanınca `_handle_shift_schedule`
        ShiftAssignment'ı GERÇEKTEN silmeli."""
        from datetime import date as _date
        from datetime import time as _time

        from app.models.shift import ShiftDefinition
        from app.models.shift_assignment import ShiftAssignment

        _, req_role, req_client = _make_actor(db, {
            "hr.shift_schedule": {"view": True, "use": True},
            "system.approval": {"view": True, "use": False},
        })
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "hr.shift_schedule", req_role, app_role)

        p = self._mk_personnel(db)
        sh = ShiftDefinition(name=f"Rota S {uuid4().hex[:4]}", color="#0d9488",
                             start_time=_time(7, 0), end_time=_time(15, 0))
        db.add(sh)
        db.flush()
        a = ShiftAssignment(personnel_id=p.id, shift_id=sh.id, work_date=_date(2026, 7, 3))
        db.add(a)
        db.commit()
        a_id = a.id

        r = req_client.delete(f"/api/hr/shift-schedule/{a_id}")
        assert r.status_code == 202, f"onaya düşmeli: {r.text}"
        req_id = r.json()["request_id"]

        # Onaydan önce: hâlâ var
        db.expire_all()
        assert db.get(ShiftAssignment, a_id) is not None

        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"_handle_shift_schedule delete hatası → 500: {ap.text}"

        db.expire_all()
        assert db.get(ShiftAssignment, a_id) is None, "Onay sonrası rota ataması silinmeliydi"


    def test_shift_create_via_approval(self, db):
        """REGRESYON (D1-2): hr.shifts vardiya tanımı onaylanınca _handle_shifts → hr_service
        ShiftDefinition oluşturmalı + time alanlarını payload ISO-string'inden coerce etmeli.
        hr.shifts create onay yolu daha önce hiç test edilmemişti (time-coercion AST testiyle yakalanamaz)."""
        from app.models.shift import ShiftDefinition

        _, req_role, req_client = _make_actor(db, {
            "hr.shifts": {"view": True, "use": True},
            "system.approval": {"view": True, "use": False},
        })
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "hr.shifts", req_role, app_role)

        name = f"Onay Vardiya {uuid4().hex[:5]}"
        resp = req_client.post("/api/hr/shifts", json={
            "name": name, "color": "#0d9488", "start_time": "07:00:00", "end_time": "15:00:00",
        })
        assert resp.status_code == 202, f"onaya düşmeli: {resp.text}"
        req_id = resp.json()["request_id"]
        db.expire_all()
        assert db.query(ShiftDefinition).filter(ShiftDefinition.name == name).count() == 0
        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"_handle_shifts create → 500: {ap.text}"
        db.expire_all()
        s = db.query(ShiftDefinition).filter(ShiftDefinition.name == name).first()
        assert s is not None, "Onay sonrası vardiya tanımı oluşmalıydı"
        assert s.start_time.hour == 7 and s.end_time.hour == 15
        assert s.is_active is True

    def test_attendance_update_via_approval(self, db):
        """REGRESYON (D1-2): hr.attendance kaydı düzenleme onaylanınca _handle_attendance → hr_service
        alanları uygulamalı + edited_at damgalamalı + punched_at ISO-string'ini coerce etmeli.
        attendance update onay yolu daha önce test edilmemişti."""
        from datetime import datetime as _dt
        from datetime import timedelta as _td

        import pytz as _pytz

        from app.models.personnel import TYPE_IN, AttendanceLog

        tz = _pytz.timezone("Europe/Istanbul")
        _, req_role, req_client = _make_actor(db, {
            "hr.attendance": {"view": True, "use": True},
            "system.approval": {"view": True, "use": False},
        })
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "hr.attendance", req_role, app_role)

        p = self._mk_personnel(db)
        orig_when = _dt.now(tz) - _td(hours=3)
        lg = AttendanceLog(personnel_id=p.id, type=TYPE_IN, source="manual",
                           punched_at=orig_when, note="eski not")
        db.add(lg)
        db.commit()
        lg_id = lg.id

        new_when = (orig_when + _td(hours=1)).isoformat()
        r = req_client.patch(f"/api/attendance/logs/{lg_id}", json={"punched_at": new_when, "note": "yeni not"})
        assert r.status_code == 202, f"onaya düşmeli: {r.text}"
        req_id = r.json()["request_id"]
        db.expire_all()
        assert db.get(AttendanceLog, lg_id).edited_at is None
        ap = app_client.post(f"{API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"_handle_attendance update → 500: {ap.text}"
        db.expire_all()
        row = db.get(AttendanceLog, lg_id)
        assert row.note == "yeni not"
        assert row.edited_at is not None, "update edited_at damgalamalı"


class TestExecutorImportIntegrity:
    def test_all_lazy_imports_resolve(self):
        """Executor handler'larındaki TÜM lazy import'lar geçerli modül yoluna işaret etmeli.

        Bu handler'lar yalnızca ilgili modülün onayı onaylandığında çalıştığı ve
        kapsam düşük olduğu için yanlış import yolları fark edilmeden kalabiliyordu
        (banks→bank_transaction, krediler→credit). Her biri o
        modülün onayını onaylayınca ImportError → 500'e yol açıyordu. Bu test, AST ile
        executor'daki her `from app...import` ifadesini çözerek bu hata sınıfını korur.
        """
        import ast
        import importlib
        import inspect as _inspect

        import app.utils.approval_executor as ax

        tree = ast.parse(_inspect.getsource(ax))
        failures = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
                for alias in node.names:
                    try:
                        mod = importlib.import_module(node.module)
                        getattr(mod, alias.name)
                    except (ImportError, AttributeError) as exc:
                        failures.append(f"satır {node.lineno}: {node.module}.{alias.name} → {exc}")
        assert not failures, "Çözülemeyen executor import'ları:\n" + "\n".join(failures)

    def test_all_model_constructions_use_valid_fields(self):
        """Executor'da kurulan her SQLAlchemy modelinin kwarg'ları gerçek kolon/ilişki
        olmalı. 'Model alanını tahmin etme' hatalarını kalıcı yakalar — departmanlar
        (eksik code + olmayan description), krediler (details_json), butce (amount,
        parent_id) hepsi bu sınıftı.
        Modeller executor'ın kendi lazy import'larından dinamik çözülür."""
        import ast
        import importlib
        import inspect as _inspect

        from sqlalchemy import inspect as sqla_inspect
        from sqlalchemy.orm import class_mapper

        import app.utils.approval_executor as ax

        tree = ast.parse(_inspect.getsource(ax))

        name_to_module = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app.models"):
                for alias in node.names:
                    name_to_module[alias.asname or alias.name] = node.module

        def resolve_model(name):
            mod_path = name_to_module.get(name)
            if not mod_path:
                return None
            try:
                cls = getattr(importlib.import_module(mod_path), name)
                class_mapper(cls)  # yalnızca SQLAlchemy mapped sınıfları
                return cls
            except Exception:
                return None

        problems = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                cls = resolve_model(node.func.id)
                if cls is None:
                    continue
                valid = {c.key for c in sqla_inspect(cls).columns}
                valid |= {r.key for r in sqla_inspect(cls).relationships}
                for kw in node.keywords:
                    if kw.arg and kw.arg not in valid:
                        problems.append(f"satır {node.lineno}: {node.func.id}({kw.arg}=...) — modelde yok")
        assert not problems, "Executor'da geçersiz model alanı kullanımı:\n" + "\n".join(problems)

    def test_all_approval_callers_have_executor_handler(self):
        """`check_approval(db, "module.code", ...)` çağıran HER modülün executor'da handler'ı olmalı.

        Eksikse o modüle onay workflow'u tanımlanınca son onayda handler bulunamaz →
        `db.rollback()` + HTTP 500 (kayıt asla uygulanamaz). Bu hata sınıfı, autouse
        `_disable_admin_approval_workflows` fixture'ı testlerde onayı kapattığı için
        diğer testlerde GÖRÜNMEZ — bu yüzden statik (AST) doğrulanır.

        Modül kodu DEĞİŞKEN ise (scheduled fabrikası `check_approval(db, module_code, ...)`)
        statik çözülemez → atlanır; o modüller `_SCHEDULED_SOURCE_MAP` üzerinden zaten kapsanır.
        Regresyon: oda tipi (bugün sales.acente_mahsup) handler'ı eksikti (modül-denetci yakaladı, 2026-06-17)."""
        import ast
        import pathlib

        from app.utils.approval_executor import _HANDLERS

        routers_dir = pathlib.Path(__file__).resolve().parent.parent / "app" / "routers"
        literal_module_codes = {}
        for py in routers_dir.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "check_approval"
                        and len(node.args) >= 2
                        and isinstance(node.args[1], ast.Constant)
                        and isinstance(node.args[1].value, str)):
                    literal_module_codes.setdefault(node.args[1].value, py.name)

        missing = sorted(mc for mc in literal_module_codes if mc not in _HANDLERS)
        assert not missing, (
            "check_approval çağıran ama approval_executor._HANDLERS'te handler'ı OLMAYAN "
            "modüller (onay tanımlanırsa 500 verir): "
            + ", ".join(f"{mc} ({literal_module_codes[mc]})" for mc in missing)
        )
