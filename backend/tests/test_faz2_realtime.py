"""Faz 2 gerçek-zamanlılık testleri (2026-07-12).

Kapsam:
- after_commit YAYIN SİGORTASI (finance_event_service): finance_events'e yazan her yol
  commit'te otomatik finance_updated yayınlar; rollback pending'i temizler; aynı modülün
  500ms içindeki ikinci commit'i bastırılır (notify_finance_update_sync süprese).
- Onay executor modül eventi (approval/requests._notify_executed_module): FE yazmayan
  modüllerde (accounting.mutabakat → 'recon') onay UYGULANINCA modül-özel WS eventi.
- run_sync_all_steps senkron çekirdeği: progress callback sırası + adım izolasyonu +
  adım-anında notify_finance_update_sync yayını.
- POST /sedna/sync-all yeni yanıt şekli ({started, total, steps}) + _run_sync_all_job
  arka plan işinin doğrudan (sahte adımlarla, DB'ye yazmadan) koşusu.
- GET /sedna/last-sync tazelik endpoint'i.
- cron_sedna_sync.py import edilebilirliği (çekirdek adım anahtarları _STEPS'te var).

Sedna'ya HİÇ bağlanılmaz — adımlar sahte, WS manager monkeypatch'lidir.
"""
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import settings
from app.constants import BroadcastModule, ReconStatus, WSEvent
from app.main import app
from app.middleware.rate_limit import login_limiter
from app.models import BankAccount, SednaBankRecon, SednaReconRun, VendorUpload
from app.models.approval import (
    STATUS_APPROVED,
    ApprovalWorkflow,
    ApprovalWorkflowApproverRole,
    ApprovalWorkflowRequestorRole,
)
from app.models.check import Check, CheckUpload
from app.models.module import Module
from app.models.role import Role
from app.models.role_module_permission import RoleModulePermission
from app.models.scheduled import ScheduledDefinition, ScheduledEntry
from app.models.user import User
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.routers.finance import sedna_sync
from app.utils import finance_broadcast, finance_event_service
from app.utils.finance_event_service import finance_event_svc
from app.utils.security import hash_password

PREFIX = "/api/finance/sedna"
APPROVAL_API = "/api/system/approval"
MUTABAKAT_API = "/api/accounting/mutabakat"


# ─────────────────────────── Yardımcılar ───────────────────────────

def _reset_broadcast_state():
    """Süprese sözlüğü + bekleyen modül seti testler arası sızmasın."""
    finance_broadcast._last_sync_sent.clear()
    finance_event_service._pending_ws_modules.clear()


@pytest.fixture
def ws_capture(monkeypatch):
    """manager.send_to_all_sync çağrılarını listeye toplar (WS bağlantısı gerekmez)."""
    _reset_broadcast_state()
    captured = []
    monkeypatch.setattr(
        finance_broadcast.manager, "send_to_all_sync",
        lambda event: captured.append(event),
    )
    yield captured
    _reset_broadcast_state()


def _mk_check(db):
    upload = CheckUpload(file_name="faz2.xlsx", file_url="test://faz2")
    db.add(upload)
    db.flush()
    chk = Check(
        upload_id=upload.id,
        check_no=f"F2{uuid4().hex[:8]}",
        vendor_code=f"320.F2.{uuid4().hex[:4]}",
        vendor_name="FAZ2 TEST CARİSİ",
        due_date=date.today() + timedelta(days=30),
        amount_tl=1000,
        currency="TL",
        amount_currency=1000,
        status="pending",
    )
    db.add(chk)
    db.flush()
    return chk


def _mk_vendor_tx(db):
    vendor = Vendor(hesap_kodu=f"320.F2.{uuid4().hex[:8]}", hesap_adi="FAZ2 SİGORTA CARİSİ")
    db.add(vendor)
    db.flush()
    up = VendorUpload(file_name="f2.xlsx", file_url="test://f2-cari")
    db.add(up)
    db.flush()
    vtx = VendorTransaction(
        vendor_id=vendor.id,
        upload_id=up.id,
        date=date.today(),
        evrak_no="F2-EV1",
        borc=0,
        alacak=500,
        tx_hash=uuid4().hex,
        payment_due_date=date.today() + timedelta(days=10),
    )
    db.add(vtx)
    db.flush()
    return vtx, vendor


def _mk_tax_entry(db):
    dfn = ScheduledDefinition(source_type="tax", name="FAZ2 Vergi", amount=250, year=2026)
    db.add(dfn)
    db.flush()
    entry = ScheduledEntry(
        definition_id=dfn.id,
        source_type="tax",
        entry_date=date.today() + timedelta(days=5),
        period_month=date.today().month,
        period_year=2026,
        amount=250,
    )
    db.add(entry)
    db.flush()
    return entry


def _events_for(captured, module):
    return [e for e in captured
            if e.get("type") == WSEvent.FINANCE_UPDATED and e.get("module") == module]


# ─────────────── A) after_commit yayın sigortası ───────────────

class TestAfterCommitBroadcastInsurance:
    def test_upsert_check_commit_broadcasts_checks(self, db, ws_capture):
        chk = _mk_check(db)
        finance_event_svc.upsert_check(db, chk)
        assert _events_for(ws_capture, "checks") == [], "yayın COMMIT'ten önce gitmemeli"
        db.commit()
        evs = _events_for(ws_capture, "checks")
        assert len(evs) == 1, f"tek 'checks' yayını beklenirdi: {ws_capture}"
        assert evs[0]["action"] == "update"

    def test_upsert_vendor_tx_commit_broadcasts_cariler(self, db, ws_capture):
        vtx, vendor = _mk_vendor_tx(db)
        finance_event_svc.upsert_vendor_tx(db, vtx, vendor, 500.0)
        db.commit()
        assert len(_events_for(ws_capture, "cariler")) == 1

    def test_upsert_scheduled_tax_commit_broadcasts_accounting(self, db, ws_capture):
        entry = _mk_tax_entry(db)
        finance_event_svc.upsert_scheduled_entry(db, entry)
        db.commit()
        assert len(_events_for(ws_capture, "accounting")) == 1

    def test_rollback_drops_pending_no_broadcast(self, db, ws_capture):
        chk = _mk_check(db)
        finance_event_svc.upsert_check(db, chk)
        db.rollback()  # after_rollback → pending temizlenir
        assert finance_event_service._pending_ws_modules == set()
        db.commit()  # boş pending → yayın yok
        assert _events_for(ws_capture, "checks") == []

    def test_second_commit_within_500ms_suppressed(self, db, ws_capture):
        chk = _mk_check(db)
        finance_event_svc.upsert_check(db, chk)
        db.commit()
        # Hemen ardından aynı modülde ikinci commit → süprese (tek yayın kalır)
        chk2 = _mk_check(db)
        finance_event_svc.upsert_check(db, chk2)
        db.commit()
        assert len(_events_for(ws_capture, "checks")) == 1, \
            "500ms süprese ikinci yayını bastırmalıydı"

    def test_invalidate_also_marks_module(self, db, ws_capture):
        """invalidate() yolu da sigortadan geçer (silme yayını unutulamaz)."""
        chk = _mk_check(db)
        finance_event_svc.upsert_check(db, chk)
        db.commit()
        _reset_broadcast_state()  # süprese sıfırla — silme yayını ayrı ölçülsün
        del ws_capture[:]
        finance_event_svc.invalidate(db, "check", chk.id)
        db.commit()
        assert len(_events_for(ws_capture, "checks")) == 1


# ─────────────── B) Onay executor modül eventi (Faz 2 #17) ───────────────

def _login_client(username, password="Test1234!"):
    login_limiter._requests.clear()
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"login başarısız: {r.text}"
    return c


def _make_actor(db, perms):
    """Rol + kullanıcı + modül izinleri oluştur, login olmuş client döndür
    (test_sedna_recon deseninin kopyası)."""
    uid = uuid4().hex[:8]
    role = Role(name=f"faz2role_{uid}", description="faz2 test rolü", is_active=True)
    db.add(role)
    db.flush()

    mods = {m.code: m for m in db.query(Module).all()}
    for code, spec in perms.items():
        m = mods.get(code)
        assert m is not None, f"modül bulunamadı: {code}"
        db.add(RoleModulePermission(
            role_id=role.id, module_id=m.id,
            can_view=spec.get("view", False), can_use=spec.get("use", False),
        ))

    username = f"faz2u_{uid}"
    user = User(
        username=username, email=f"{username}@test.local",
        first_name="Faz2", last_name=uid[:6],
        hashed_password=hash_password("Test1234!"), role_id=role.id, is_active=True,
    )
    db.add(user)
    db.commit()
    return user.id, role.id, _login_client(username)


def _make_workflow(db, module_code, requestor_role_id, approver_role_id):
    mod = db.query(Module).filter(Module.code == module_code).first()
    assert mod is not None, f"modül bulunamadı: {module_code}"
    wf = ApprovalWorkflow(
        name=f"wf_faz2_{uuid4().hex[:8]}", module_id=mod.id,
        entity_type=module_code, is_active=True,
    )
    db.add(wf)
    db.flush()
    db.add(ApprovalWorkflowRequestorRole(workflow_id=wf.id, role_id=requestor_role_id))
    db.add(ApprovalWorkflowApproverRole(workflow_id=wf.id, role_id=approver_role_id))
    db.commit()
    return wf


class TestExecutedModuleEvent:
    def test_mutabakat_approve_emits_recon_module_event(self, db, monkeypatch):
        """accounting.mutabakat onayı UYGULANINCA 'recon' modüllü finance_updated yayını
        gider (_EXECUTED_MODULE_EVENTS eşlemesi — FE yazmayan modülün gerçek event'i)."""
        acc = BankAccount(
            bank_name="Faz2 Mutabakat Bankası",
            iban="TR{:024d}".format(uuid4().int % 10**24),
            currency="TRY", is_active=True,
        )
        db.add(acc)
        db.flush()
        item = SednaBankRecon(
            bank_account_id=acc.id, status=ReconStatus.SEDNA_MISSING, amount=1500.0,
            currency="TRY", event_date=date.today() - timedelta(days=3),
            description="Faz2 banka test satırı",
        )
        db.add(item)
        db.commit()
        item_id = item.id

        _, req_role, req_client = _make_actor(db, {
            "accounting.mutabakat": {"view": True, "use": True},
            "system.approval": {"view": True, "use": False},
        })
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "accounting.mutabakat", req_role, app_role)

        r = req_client.patch(f"{MUTABAKAT_API}/items/{item_id}",
                             json={"action": "resolve", "note": "faz2 onaylı çözüm"})
        assert r.status_code == 202, f"onaya düşmeli: {r.status_code} {r.text}"
        req_id = r.json()["request_id"]

        # Onay UYGULANIRKEN gönderilecek async yayınları yakala
        from app.websocket.manager import manager
        captured = []

        async def fake_send_to_all(event):
            captured.append(event)

        monkeypatch.setattr(manager, "send_to_all", fake_send_to_all)

        ap = app_client.post(f"{APPROVAL_API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"approve başarısız: {ap.text}"
        assert ap.json()["status"] == STATUS_APPROVED

        recon_events = [e for e in captured
                        if e.get("type") == WSEvent.FINANCE_UPDATED
                        and e.get("module") == BroadcastModule.RECON]
        assert len(recon_events) == 1, f"'recon' modül eventi beklenirdi: {captured}"

        # Mutasyon gerçekten uygulandı (executor çalıştı)
        db.expire_all()
        fresh = db.query(SednaBankRecon).filter(SednaBankRecon.id == item_id).one()
        assert fresh.resolution == "manual"


# ─────────────── C) run_sync_all_steps senkron çekirdeği ───────────────

def _fake_steps(broadcast_module="checks"):
    def _boom(db, user, ip):
        raise HTTPException(status_code=503, detail="Sedna kapalı")

    return [
        {"key": "s_ok", "label": "Sahte Adım 1", "module": "finance.checks",
         "run": lambda db, user, ip: {"x": 1}, "broadcast": broadcast_module},
        {"key": "s_err", "label": "Sahte Adım 2", "module": "finance.checks",
         "run": _boom, "broadcast": broadcast_module},
    ]


def _admin(db):
    admin = db.query(User).filter(User.username == "admin").first()
    assert admin is not None
    return admin


class TestRunSyncAllSteps:
    def test_progress_sequence_isolation_and_step_broadcast(self, db, monkeypatch):
        monkeypatch.setattr(sedna_sync, "_STEPS", _fake_steps())
        notify_calls = []
        monkeypatch.setattr(sedna_sync, "notify_finance_update_sync",
                            lambda module, action="update": notify_calls.append((module, action)))
        progress_events = []

        result = sedna_sync.run_sync_all_steps(db, _admin(db), "test",
                                               progress=progress_events.append)

        # Sonuç: adım izolasyonu — biri patladı, diğeri tamam
        assert result["ok_count"] == 1
        assert result["total"] == 2
        by = {s["key"]: s for s in result["steps"]}
        assert by["s_ok"]["ok"] is True and by["s_ok"]["skipped"] is False
        assert by["s_err"]["ok"] is False
        assert by["s_err"]["summary"] == "Sedna kapalı"

        # Progress sırası: running/ok (adım 1) → running/error (adım 2) → done
        assert [e["status"] for e in progress_events] == \
            ["running", "ok", "running", "error", "done"]
        assert all(e["type"] == WSEvent.SEDNA_SYNC_PROGRESS for e in progress_events)
        assert progress_events[0]["key"] == "s_ok" and progress_events[2]["key"] == "s_err"
        assert progress_events[-1]["ok_count"] == 1 and progress_events[-1]["total"] == 2

        # Adım yayını ANINDA: yalnız başarılı adım için (hatalı adım yayınlamaz)
        assert notify_calls == [("checks", "upload")]

    def test_unpermitted_steps_skipped(self, db, monkeypatch):
        """İzinsiz kullanıcının TÜM adımları 'Yetki yok' ile atlanır (koşulmadan)."""
        monkeypatch.setattr(sedna_sync, "_STEPS", _fake_steps())
        role = Role(name=f"faz2noperm_{uuid4().hex[:8]}", description="izinsiz", is_active=True)
        db.add(role)
        db.flush()
        user = User(
            username=f"faz2np_{uuid4().hex[:8]}", email=f"np{uuid4().hex[:8]}@test.local",
            first_name="Yetkisiz", last_name="Kullanıcı",
            hashed_password=hash_password("Test1234!"), role_id=role.id, is_active=True,
        )
        db.add(user)
        db.flush()

        result = sedna_sync.run_sync_all_steps(db, user, "test")
        assert result["ok_count"] == 0
        assert all(s["skipped"] and s["summary"] == "Yetki yok" for s in result["steps"])


# ─────────────── D) POST /sync-all + arka plan job ───────────────

class TestSyncAllEndpointAndJob:
    def test_post_sync_all_returns_started_shape(self, client, auth_headers, monkeypatch):
        """Endpoint artık bloklamaz: hemen {started, total, steps} döner; adımlar
        arka plan işinde koşar (sahte adımlar DB'ye yazmaz → test-DB temiz kalır)."""
        monkeypatch.setattr(sedna_sync, "_STEPS", _fake_steps())
        monkeypatch.setattr(settings, "sedna_password", "testpw")
        _reset_broadcast_state()
        r = client.post(f"{PREFIX}/sync-all", headers=auth_headers)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["started"] is True
        assert j["total"] == 2
        assert j["steps"] == [{"key": "s_ok", "label": "Sahte Adım 1"},
                              {"key": "s_err", "label": "Sahte Adım 2"}]
        _reset_broadcast_state()  # bg job notify süprese sözlüğünü kirletmesin

    def test_run_sync_all_job_directly(self, db, monkeypatch):
        """_run_sync_all_job kendi SessionLocal'ini açar; sahte adımlar DB'ye yazmadığından
        kirlilik olmaz. WS ilerleme yayınları send_to_all_sync üzerinden gider."""
        monkeypatch.setattr(sedna_sync, "_STEPS", _fake_steps())
        _reset_broadcast_state()
        captured = []
        from app.websocket.manager import manager
        monkeypatch.setattr(manager, "send_to_all_sync", lambda event: captured.append(event))

        admin_id = _admin(db).id
        sedna_sync._run_sync_all_job(admin_id, "test")

        progress = [e for e in captured if e.get("type") == WSEvent.SEDNA_SYNC_PROGRESS]
        assert [e["status"] for e in progress] == ["running", "ok", "running", "error", "done"]
        assert progress[-1]["ok_count"] == 1 and progress[-1]["total"] == 2
        # Başarılı adımın modül yayını da gitti (notify_finance_update_sync → send_to_all_sync)
        assert len([e for e in captured
                    if e.get("type") == WSEvent.FINANCE_UPDATED
                    and e.get("module") == "checks"]) == 1
        _reset_broadcast_state()

    def test_run_sync_all_job_unknown_user_noop(self, monkeypatch):
        """Silinmiş kullanıcı id'siyle job sessizce döner (patlamaz, yayın yapmaz)."""
        monkeypatch.setattr(sedna_sync, "_STEPS", _fake_steps())
        captured = []
        from app.websocket.manager import manager
        monkeypatch.setattr(manager, "send_to_all_sync", lambda event: captured.append(event))
        sedna_sync._run_sync_all_job(999999999, "test")
        assert captured == []


# ─────────────── E) GET /sedna/last-sync ───────────────

class TestLastSync:
    def test_last_sync_empty_returns_nulls(self, client, auth_headers, db):
        from app.models.check import CheckUpload as CU
        db.query(VendorUpload).filter(VendorUpload.file_url == "sedna://import").delete()
        db.query(CU).filter(CU.file_url == "sedna://import").delete()
        db.query(SednaReconRun).delete()
        db.flush()

        r = client.get(f"{PREFIX}/last-sync", headers=auth_headers)
        assert r.status_code == 200
        j = r.json()
        assert j["last_cari_sync"] is None
        assert j["last_check_sync"] is None
        assert j["last_bank_recon"] is None
        assert j["oldest_hours"] is None

    def test_last_sync_populated_fields_and_age(self, client, auth_headers, db):
        from app.models.check import CheckUpload as CU
        db.query(VendorUpload).filter(VendorUpload.file_url == "sedna://import").delete()
        db.query(CU).filter(CU.file_url == "sedna://import").delete()
        db.query(SednaReconRun).delete()
        db.flush()

        now_utc = datetime.now(timezone.utc)
        db.add(VendorUpload(file_name="Sedna içe aktarma", file_url="sedna://import",
                            uploaded_at=now_utc - timedelta(hours=5)))
        db.add(CU(file_name="Sedna çek içe aktarma", file_url="sedna://import",
                  uploaded_at=now_utc - timedelta(hours=2)))
        db.add(SednaReconRun(run_at=now_utc - timedelta(hours=1),
                             window_start=date.today() - timedelta(days=45),
                             window_end=date.today()))
        db.flush()

        r = client.get(f"{PREFIX}/last-sync", headers=auth_headers)
        assert r.status_code == 200
        j = r.json()
        assert j["last_cari_sync"] is not None
        assert j["last_check_sync"] is not None
        assert j["last_bank_recon"] is not None
        # oldest_hours = kritik adımların en eskisi (cari, 5 saat) — negatif olamaz
        assert j["oldest_hours"] is not None
        assert 4.5 <= j["oldest_hours"] <= 6.0

    def test_last_sync_requires_auth(self, client):
        assert client.get(f"{PREFIX}/last-sync").status_code == 401


# ─────────────── F) cron_sedna_sync import edilebilirliği ───────────────

class TestCronSednaSync:
    def test_cron_module_importable_and_step_keys_valid(self):
        """Cron modülü import edilebilir; çekirdek adım anahtarları _STEPS'te mevcut
        (adım yeniden adlandırılırsa cron sessizce hiçbir şey koşmasın diye)."""
        import cron_sedna_sync

        assert callable(cron_sedna_sync.main)
        step_keys = {s["key"] for s in sedna_sync._STEPS}
        assert cron_sedna_sync._CRON_STEP_KEYS <= step_keys, \
            f"cron adım anahtarları _STEPS'te yok: {cron_sedna_sync._CRON_STEP_KEYS - step_keys}"
