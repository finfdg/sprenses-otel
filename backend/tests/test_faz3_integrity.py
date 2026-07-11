"""Faz 3 bütünlük testleri (2026-07-12) — banka serbest bırakma + güvenli silme +
yaşlanma/tahmin-doğruluğu raporları + bakiye-zinciri kontrolü.

Kapsam:
A) bank_release_service.release_bank_transaction — eşleşmiş çek→pending, kredi taksiti
   (tekil FK + N-1 grup: iki btx'in ortak match_number izi temizlenir + anapara iadesi),
   avans→pending, KK ekstresi paid_amount geri düşer, cari match_number çifti çözülür
   (needs_vendor_sync=True); event_matches izleri silinir.
B) delete_bank_transaction — eşleşmemiş satır silinir + FE invalidate + öneri izi düşer;
   eşleşmiş satıra ValueError (kayıt DURUR — bilinçli sürtünme).
C) delete_bank_statement — ekstre + işlemleri silinir (FK SET NULL olduğundan işlemler
   AÇIKÇA silinir — Faz 3 bug düzeltmesi), bağlı çek pending'e döner, sayaçlar doğru.
D) delete_account (denetim C5 regresyonu) — hesap silinince eşleşmiş çek pending +
   bankasız kalır, source_type='bank' orphan FE kalmaz.
E) DELETE /banks/statements/{id} + /banks/transactions/{id} endpoint'leri — 200 sayaçlı,
   404, eşleşmişe 400, viewer 403 + onay akışı uçtan-uca regresyonu (202 → onay → executor).
F) upload_statement başlık doğrulaması (Faz 3 #22b) — yanlış IBAN → 400, para birimi
   uyuşmazlığı → 400, doğru IBAN (+ 'TL'→TRY normalizasyonu) → 200
   (_save_and_parse monkeypatch'li — gerçek dosya parse edilmez).
G) compute_aging + GET /cash-flow/reconciliation/aging — vadesi geçmiş açık tahminler
   gruplu/sayılı, taze kalem girmez; etiketsiz eski banka hareketi ayrı sayılır; izinler.
H) GET /cash-flow/forecast-accuracy — event_matches izinden tahmin↔gerçekleşme gecikmesi
   (by_type medyanı, vendor_payment by_vendor + suggested_payment_days |medyan|>=3 kuralı).
I) sedna_recon_service.check_balance_chains — tutarlı zincir kırılmasız; tutarsız bakiye
   tek kırılma (gap doğru); NULL-bakiyeli manuel satır köprü; run_reconciliation summary'ye
   balance_chain_breaks girer (Sedna fetch'leri enjekte — Sedna'ya bağlanılmaz).
"""
import itertools
from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.middleware.rate_limit import login_limiter
from app.models.advance import Advance
from app.models.approval import (
    STATUS_APPROVED,
    ApprovalWorkflow,
    ApprovalWorkflowApproverRole,
    ApprovalWorkflowRequestorRole,
)
from app.models.bank_account import BankAccount
from app.models.bank_statement import BankStatement
from app.models.bank_transaction import BankTransaction
from app.models.check import Check, CheckUpload
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_product import CreditPayment, CreditProduct
from app.models.event_match import MATCH_METHOD_SUGGESTION, EventMatch
from app.models.finance_event import FinanceEvent
from app.models.module import Module
from app.models.role import Role
from app.models.role_module_permission import RoleModulePermission
from app.models.user import User
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.models.vendor_upload import VendorUpload
from app.routers.finance.cash_flow.aging import compute_aging
from app.services import bank_account_service
from app.services.bank_release_service import (
    delete_bank_statement,
    delete_bank_transaction,
    release_bank_transaction,
)
from app.services.sedna_recon_service import (
    BALANCE_CHAIN_TOLERANCE,
    check_balance_chains,
    run_reconciliation,
)
from app.utils.finance_event_service import finance_event_svc
from app.utils.security import hash_password

API_BANKS = "/api/finance/banks"
API_CF = "/api/finance/cash-flow"
APPROVAL_API = "/api/system/approval"
TODAY = date.today()

_SEQ = itertools.count(973001)


# ─────────────────────────── Yardımcılar ───────────────────────────


def _mk_account(db, *, bank_name="Faz3 Test Bankası", currency="TRY", **kw):
    acc = BankAccount(
        bank_name=bank_name, iban=f"TR{uuid4().hex}"[:34].upper(), currency=currency,
        is_active=True, **kw,
    )
    db.add(acc)
    db.flush()
    return acc


def _mk_stmt(db, acc):
    stmt = BankStatement(
        account_id=acc.id, file_name=f"faz3-{next(_SEQ)}.xlsx",
        file_url="test://faz3", file_type="xlsx",
    )
    db.add(stmt)
    db.flush()
    return stmt


def _mk_btx(db, acc, *, amount, tx_date=None, desc="FAZ3 HAREKETİ",
            balance=0, statement_id=None, source="statement", fe=False):
    btx = BankTransaction(
        account_id=acc.id, statement_id=statement_id, date=tx_date or TODAY,
        description=desc, amount=amount, balance=balance,
        type="expense" if amount < 0 else "income",
        tx_hash=f"faz3-{uuid4().hex}", source=source,
    )
    db.add(btx)
    db.flush()
    if fe:
        finance_event_svc.upsert_bank_tx(db, btx, acc)
    return btx


def _mk_check(db, *, due_date=None, amount=25000.0, status="pending",
              vendor_name="FAZ3 ÇEK FİRMASI", vendor_code=None):
    up = CheckUpload(file_name="faz3-seed", file_url="test://faz3-cek")
    db.add(up)
    db.flush()
    check = Check(
        upload_id=up.id, check_no=str(7300000 + next(_SEQ)),
        vendor_code=vendor_code, vendor_name=vendor_name,
        due_date=due_date or TODAY, amount_tl=amount, amount_currency=amount,
        currency="TL", status=status,
    )
    db.add(check)
    db.flush()
    return check


def _match_check_to_btx(db, check, btx):
    """Çeki banka hareketiyle eşleşmiş duruma getir (matcher'ların yazdığı izlerle)."""
    check.status = "paid"
    check.bank_transaction_id = btx.id
    db.flush()
    acc = db.query(BankAccount).filter(BankAccount.id == btx.account_id).first()
    finance_event_svc.upsert_bank_tx(db, btx, acc)
    finance_event_svc.upsert_check(db, check, btx)
    finance_event_svc.match(db, "bank", btx.id, "check", check.id, method="auto", score=90)


def _mk_credit(db, *, amount=10000.0, principal=8000.0, total=100000.0):
    product = CreditProduct(
        type="taksitli", name=f"FAZ3 KREDİ {next(_SEQ)}",
        bank_name="Faz3 Kredi Bankası", currency="TRY",
        total_amount=total, remaining_amount=total, status="active",
    )
    db.add(product)
    db.flush()
    payment = CreditPayment(
        credit_product_id=product.id, installment_no=1,
        due_date=TODAY, amount=amount, principal=principal, is_paid=False,
    )
    db.add(payment)
    db.flush()
    return product, payment


def _mk_vendor_pair(db, *, match_number, amount=5000.0):
    """Cari alacak satırı + banka hareketi match_number çiftiyle eşlenmiş kur."""
    n = next(_SEQ)
    up = VendorUpload(file_name="faz3-seed", file_url="test://faz3-cari")
    db.add(up)
    db.flush()
    vendor = Vendor(hesap_kodu=f"320.F3.{n}", hesap_adi=f"FAZ3 CARİ {n}")
    db.add(vendor)
    db.flush()
    vtx = VendorTransaction(
        vendor_id=vendor.id, upload_id=up.id, date=TODAY - timedelta(days=20),
        evrak_no=f"F3E{n}", alacak=amount, borc=0,
        payment_due_date=TODAY, tx_hash=f"faz3-vtx-{uuid4().hex}",
        match_number=match_number, payment_method="havale_eft",
    )
    db.add(vtx)
    db.flush()
    return vendor, vtx


def _fe(db, source_type, source_id):
    return db.query(FinanceEvent).filter(
        FinanceEvent.source_type == source_type,
        FinanceEvent.source_id == source_id,
    ).first()


def _traces(db, *, target_type=None, target_id=None, bank_id=None,
            include_suggestions=False):
    q = db.query(EventMatch)
    if not include_suggestions:
        q = q.filter(EventMatch.method != MATCH_METHOD_SUGGESTION)
    if target_type is not None:
        q = q.filter(EventMatch.target_source_type == target_type)
    if target_id is not None:
        q = q.filter(EventMatch.target_source_id == target_id)
    if bank_id is not None:
        q = q.filter(EventMatch.bank_source_type == "bank",
                     EventMatch.bank_source_id == bank_id)
    return q.all()


# Onay akışı aktörleri (test_sedna_recon / test_approval_system deseni)

def _login_client(username, password="Test1234!"):
    login_limiter._requests.clear()
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"login başarısız: {r.text}"
    return c


def _make_actor(db, perms):
    uid = uuid4().hex[:8]
    role = Role(name=f"faz3role_{uid}", description="faz3 test rolü", is_active=True)
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
    username = f"faz3u_{uid}"
    user = User(
        username=username, email=f"{username}@test.local",
        first_name="Faz3", last_name=uid[:6],
        hashed_password=hash_password("Test1234!"), role_id=role.id, is_active=True,
    )
    db.add(user)
    db.commit()
    return user.id, role.id, _login_client(username)


def _make_workflow(db, module_code, requestor_role_id, approver_role_id):
    mod = db.query(Module).filter(Module.code == module_code).first()
    assert mod is not None, f"modül bulunamadı: {module_code}"
    wf = ApprovalWorkflow(
        name=f"wf_{uuid4().hex[:8]}", module_id=mod.id,
        entity_type=module_code, is_active=True,
    )
    db.add(wf)
    db.flush()
    db.add(ApprovalWorkflowRequestorRole(workflow_id=wf.id, role_id=requestor_role_id))
    db.add(ApprovalWorkflowApproverRole(workflow_id=wf.id, role_id=approver_role_id))
    db.commit()
    return wf


# ═══════════════ A) release_bank_transaction ═══════════════


class TestReleaseBankTransaction:
    def test_release_matched_check_returns_pending(self, db):
        """Eşleşmiş çek → release sonrası pending + FK boş + FE is_matched=False +
        event_matches izleri (banka bacağı dahil) silinmiş."""
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-25000.0)
        check = _mk_check(db, amount=25000.0)
        _match_check_to_btx(db, check, btx)
        assert len(_traces(db, target_type="check", target_id=check.id)) == 1

        counts = release_bank_transaction(db, btx)

        assert counts["checks"] == 1
        assert counts["needs_vendor_sync"] is False
        db.expire_all()
        c = db.get(Check, check.id)
        assert c.status == "pending"
        assert c.bank_transaction_id is None

        fe = _fe(db, "check", check.id)
        assert fe is not None
        assert fe.is_matched is False
        assert fe.is_realized is False
        assert fe.event_status == "pending"

        assert _traces(db, target_type="check", target_id=check.id) == []
        assert _traces(db, bank_id=btx.id, include_suggestions=True) == []

    def test_release_credit_payment_single_fk(self, db):
        """Tekil (yalnız FK bağlı) ödenmiş taksit → unpaid + anapara iadesi + FE açılır."""
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-10000.0, fe=True)
        product, payment = _mk_credit(db, amount=10000.0, principal=8000.0, total=100000.0)
        payment.is_paid = True
        payment.paid_date = TODAY
        payment.bank_transaction_id = btx.id
        product.remaining_amount = 92000.0  # anapara düşülmüş hali
        db.flush()
        finance_event_svc.upsert_credit_payment(db, payment, product)

        counts = release_bank_transaction(db, btx)

        assert counts["credits"] == 1
        db.expire_all()
        p = db.get(CreditPayment, payment.id)
        assert p.is_paid is False
        assert p.paid_date is None
        assert p.bank_transaction_id is None
        assert float(db.get(CreditProduct, product.id).remaining_amount) == 100000.0

        fe = _fe(db, "credit", payment.id)
        assert fe is not None
        assert fe.is_matched is False
        assert fe.event_status == "pending"

    def test_release_credit_group_clears_all_bank_match_numbers(self, db):
        """N-1 grup (iki btx toplamı bir taksiti kapattı): birini release et →
        taksit unpaid + anapara iade + İKİ btx'in de match_number'ı None."""
        acc = _mk_account(db)
        btx1 = _mk_btx(db, acc, amount=-6000.0, fe=True)
        btx2 = _mk_btx(db, acc, amount=-4000.0, fe=True)
        product, payment = _mk_credit(db, amount=10000.0, principal=7500.0, total=50000.0)
        group_no = 973900000 + next(_SEQ)
        payment.is_paid = True
        payment.paid_date = TODAY
        payment.bank_transaction_id = btx1.id
        product.remaining_amount = 42500.0
        btx1.match_number = group_no
        btx2.match_number = group_no
        db.flush()
        for b in (btx1, btx2):
            db.add(EventMatch(
                match_number=group_no, bank_source_type="bank", bank_source_id=b.id,
                target_source_type="credit", target_source_id=payment.id,
                amount=abs(float(b.amount)), currency="TRY", method="auto", score=85,
            ))
        db.flush()
        finance_event_svc.upsert_credit_payment(db, payment, product)

        counts = release_bank_transaction(db, btx1)

        assert counts["credits"] == 1
        db.expire_all()
        p = db.get(CreditPayment, payment.id)
        assert p.is_paid is False
        assert p.bank_transaction_id is None
        assert float(db.get(CreditProduct, product.id).remaining_amount) == 50000.0
        # Grup izi: İKİ banka satırının da ortak match_number'ı temizlendi
        assert db.get(BankTransaction, btx1.id).match_number is None
        assert db.get(BankTransaction, btx2.id).match_number is None
        # unmatch kredi tarafındaki TÜM izleri sildi
        assert _traces(db, target_type="credit", target_id=payment.id) == []
        fe = _fe(db, "credit", payment.id)
        assert fe.is_matched is False

    def test_release_advance_returns_pending(self, db):
        """Alınmış avans → release sonrası pending + received_* boş + FE açılır."""
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=5000.0, fe=True)
        adv = Advance(
            agency_name="FAZ3 ACENTE", amount=5000.0, currency="EUR",
            advance_date=TODAY - timedelta(days=5), status="received",
            received_date=TODAY - timedelta(days=2), received_amount=5000.0,
            bank_transaction_id=btx.id,
        )
        db.add(adv)
        db.flush()
        finance_event_svc.upsert_advance(db, adv)
        assert _fe(db, "advance", adv.id).is_matched is True

        counts = release_bank_transaction(db, btx)

        assert counts["advances"] == 1
        db.expire_all()
        a = db.get(Advance, adv.id)
        assert a.status == "pending"
        assert a.received_date is None
        assert a.received_amount is None
        assert a.bank_transaction_id is None
        fe = _fe(db, "advance", adv.id)
        assert fe.is_matched is False
        assert fe.event_status == "pending"

    def test_release_vendor_match_pair(self, db):
        """Cari match_number çifti → karşı cari satırı serbest (match_number +
        payment_method temizlenir) + needs_vendor_sync=True döner."""
        acc = _mk_account(db)
        pair_no = 973800000 + next(_SEQ)
        vendor, vtx = _mk_vendor_pair(db, match_number=pair_no)
        btx = _mk_btx(db, acc, amount=-5000.0, fe=True)
        btx.match_number = pair_no
        db.flush()

        counts = release_bank_transaction(db, btx)

        assert counts["vendor"] == 1
        assert counts["needs_vendor_sync"] is True
        db.expire_all()
        v = db.get(VendorTransaction, vtx.id)
        assert v.match_number is None
        assert v.payment_method is None

    def test_release_cc_statement_rolls_back_paid_amount(self, db):
        """KK ekstresi: banka ödemesiyle paid_amount birikmiş + is_paid=True →
        release sonrası tutar geri düşer + is_paid=False + FE yeniden açılır."""
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-50000.0, fe=True)
        product, _ = _mk_credit(db, total=200000.0)
        stmt = CreditCardStatement(
            credit_product_id=product.id, kesim_tarihi=TODAY - timedelta(days=10),
            son_odeme_tarihi=TODAY + timedelta(days=10), toplam_borc=50000.0,
            paid_amount=50000.0, is_paid=True, paid_date=TODAY - timedelta(days=1),
        )
        db.add(stmt)
        db.flush()
        finance_event_svc.upsert_cc_statement(db, stmt, product)
        finance_event_svc.match(db, "bank", btx.id, "cc_payment", stmt.id, method="auto")

        counts = release_bank_transaction(db, btx)

        assert counts["cc"] == 1
        db.expire_all()
        s = db.get(CreditCardStatement, stmt.id)
        assert float(s.paid_amount or 0) == 0.0
        assert s.is_paid is False
        assert s.paid_date is None
        fe = _fe(db, "cc_payment", stmt.id)
        assert fe.is_matched is False
        assert fe.event_status == "pending"
        assert _traces(db, target_type="cc_payment", target_id=stmt.id) == []


# ═══════════════ B) delete_bank_transaction (service) ═══════════════


class TestDeleteBankTransactionService:
    def test_unmatched_deleted_with_fe_and_suggestion(self, db):
        """Eşleşmemiş satır silinir: kayıt + FE + öneri izi düşer."""
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-1234.56, fe=True)
        check = _mk_check(db, amount=1234.56)
        db.add(EventMatch(
            bank_source_type="bank", bank_source_id=btx.id,
            target_source_type="check", target_source_id=check.id,
            method=MATCH_METHOD_SUGGESTION, score=15,
        ))
        db.flush()
        btx_id = btx.id

        res = delete_bank_transaction(db, btx)

        assert res == {"ok": True}
        assert db.get(BankTransaction, btx_id) is None
        assert _fe(db, "bank", btx_id) is None
        assert _traces(db, bank_id=btx_id, include_suggestions=True) == []

    def test_matched_raises_and_record_survives(self, db):
        """Eşleşmiş satır silinemez — ValueError + kayıt DURUR (bilinçli sürtünme)."""
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-25000.0, fe=True)
        check = _mk_check(db, amount=25000.0)
        _match_check_to_btx(db, check, btx)

        with pytest.raises(ValueError):
            delete_bank_transaction(db, btx)

        db.expire_all()
        assert db.get(BankTransaction, btx.id) is not None
        assert db.get(Check, check.id).status == "paid"  # eşleşme bozulmadı

    def test_vendor_match_number_also_blocks(self, db):
        """match_number'lı (cari eşleşmeli) satır da silinemez."""
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-100.0, fe=True)
        btx.match_number = 973700000 + next(_SEQ)
        db.flush()
        with pytest.raises(ValueError):
            delete_bank_transaction(db, btx)
        assert db.get(BankTransaction, btx.id) is not None


# ═══════════════ C) delete_bank_statement (service) ═══════════════


class TestDeleteBankStatement:
    def test_delete_releases_matches_and_removes_transactions(self, db):
        """2 işlemli ekstre (biri çekle eşleşmiş) silinir: çek pending, İKİ işlem de
        gerçekten silinmiş (FK SET NULL — orphan kalmamalı), FE'ler düşmüş, sayaçlar doğru."""
        acc = _mk_account(db)
        stmt = _mk_stmt(db, acc)
        btx1 = _mk_btx(db, acc, amount=-25000.0, statement_id=stmt.id)
        btx2 = _mk_btx(db, acc, amount=7000.0, statement_id=stmt.id, fe=True)
        check = _mk_check(db, amount=25000.0)
        _match_check_to_btx(db, check, btx1)
        stmt_id, b1, b2 = stmt.id, btx1.id, btx2.id

        totals = delete_bank_statement(db, stmt)

        assert totals == {"transactions": 2, "checks": 1, "credits": 0,
                          "advances": 0, "cc": 0, "vendor": 0,
                          "needs_vendor_sync": False}
        db.expire_all()
        assert db.get(BankStatement, stmt_id) is None
        # İşlemler orphan (statement_id=NULL) KALMAZ — gerçekten silinir
        assert db.get(BankTransaction, b1) is None
        assert db.get(BankTransaction, b2) is None
        assert _fe(db, "bank", b1) is None
        assert _fe(db, "bank", b2) is None
        c = db.get(Check, check.id)
        assert c.status == "pending"
        assert c.bank_transaction_id is None
        fe = _fe(db, "check", check.id)
        assert fe.is_matched is False


# ═══════════════ D) delete_account temizliği (denetim C5) ═══════════════


class TestDeleteAccountCleanup:
    def test_account_delete_releases_matched_check(self, db):
        """Hesap silinince eşleşmiş çek 'bankasız ödendi' KALMAZ: pending + FK boş;
        hesabın işlemlerinin source_type='bank' FE'si kalmaz."""
        acc = _mk_account(db)
        stmt = _mk_stmt(db, acc)
        btx = _mk_btx(db, acc, amount=-25000.0, statement_id=stmt.id)
        check = _mk_check(db, amount=25000.0)
        _match_check_to_btx(db, check, btx)
        acc_id, btx_id = acc.id, btx.id

        bank_account_service.delete_account(db, acc)

        db.expire_all()
        assert db.get(BankAccount, acc_id) is None
        assert db.get(BankTransaction, btx_id) is None
        c = db.get(Check, check.id)
        assert c.status == "pending"
        assert c.bank_transaction_id is None
        assert _fe(db, "bank", btx_id) is None
        fe = _fe(db, "check", check.id)
        assert fe is not None
        assert fe.is_matched is False
        assert _traces(db, bank_id=btx_id, include_suggestions=True) == []


# ═══════════════ E) DELETE endpoint'leri + onay akışı ═══════════════


class TestDeleteEndpoints:
    def test_delete_statement_endpoint_returns_counters(self, client, auth_headers, db):
        acc = _mk_account(db)
        stmt = _mk_stmt(db, acc)
        _mk_btx(db, acc, amount=7000.0, statement_id=stmt.id, fe=True)
        btx = _mk_btx(db, acc, amount=-25000.0, statement_id=stmt.id)
        check = _mk_check(db, amount=25000.0)
        _match_check_to_btx(db, check, btx)
        db.commit()

        r = client.delete(f"{API_BANKS}/statements/{stmt.id}", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["transactions"] == 2
        assert body["checks"] == 1
        assert "needs_vendor_sync" not in body

        db.expire_all()
        assert db.get(BankStatement, stmt.id) is None
        assert db.get(Check, check.id).status == "pending"

    def test_delete_statement_endpoint_404(self, client, auth_headers):
        r = client.delete(f"{API_BANKS}/statements/98765432", headers=auth_headers)
        assert r.status_code == 404

    def test_delete_transaction_endpoint_ok(self, client, auth_headers, db):
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-99.0, fe=True)
        db.commit()
        btx_id = btx.id

        r = client.delete(f"{API_BANKS}/transactions/{btx_id}", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        db.expire_all()
        assert db.get(BankTransaction, btx_id) is None
        assert _fe(db, "bank", btx_id) is None

    def test_delete_transaction_endpoint_matched_400(self, client, auth_headers, db):
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-25000.0)
        check = _mk_check(db, amount=25000.0)
        _match_check_to_btx(db, check, btx)
        db.commit()

        r = client.delete(f"{API_BANKS}/transactions/{btx.id}", headers=auth_headers)
        assert r.status_code == 400
        assert "eşleşmiş" in r.json()["detail"]
        db.expire_all()
        assert db.get(BankTransaction, btx.id) is not None

    def test_delete_transaction_endpoint_404(self, client, auth_headers):
        r = client.delete(f"{API_BANKS}/transactions/98765432", headers=auth_headers)
        assert r.status_code == 404

    def test_delete_endpoints_viewer_403(self, client, viewer_user_headers, db):
        acc = _mk_account(db)
        stmt = _mk_stmt(db, acc)
        btx = _mk_btx(db, acc, amount=-1.0)
        db.commit()
        assert client.delete(f"{API_BANKS}/statements/{stmt.id}",
                             headers=viewer_user_headers).status_code == 403
        assert client.delete(f"{API_BANKS}/transactions/{btx.id}",
                             headers=viewer_user_headers).status_code == 403

    def test_delete_statement_via_approval_regression(self, db):
        """REGRESYON: finance.banks delete onaya bağlıyken DELETE /statements 202 döner,
        veri DEĞİŞMEZ; onaylanınca executor (_handle_finance_banks, op=delete_statement)
        ekstreyi temizlikli siler — çek pending, işlemler silinmiş."""
        acc = _mk_account(db)
        stmt = _mk_stmt(db, acc)
        btx = _mk_btx(db, acc, amount=-25000.0, statement_id=stmt.id)
        check = _mk_check(db, amount=25000.0)
        _match_check_to_btx(db, check, btx)
        db.commit()
        stmt_id, btx_id = stmt.id, btx.id

        _, req_role, req_client = _make_actor(db, {
            "finance.banks": {"view": True, "use": True},
            "system.approval": {"view": True, "use": False},
        })
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "finance.banks", req_role, app_role)

        r = req_client.delete(f"{API_BANKS}/statements/{stmt_id}")
        assert r.status_code == 202, f"onaya düşmeli: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("requires_approval") is True
        req_id = body["request_id"]

        db.expire_all()
        assert db.get(BankStatement, stmt_id) is not None, "onaydan ÖNCE ekstre silinmemeli"
        assert db.get(BankTransaction, btx_id) is not None
        assert db.get(Check, check.id).status == "paid"

        ap = app_client.post(f"{APPROVAL_API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"executor handler hatası: {ap.text}"
        assert ap.json()["status"] == STATUS_APPROVED

        db.expire_all()
        assert db.get(BankStatement, stmt_id) is None
        assert db.get(BankTransaction, btx_id) is None
        c = db.get(Check, check.id)
        assert c.status == "pending"
        assert c.bank_transaction_id is None


# ═══════════════ F) upload_statement başlık doğrulaması (#22b) ═══════════════


def _install_fake_parse(monkeypatch, *, iban, currency, amount=-1000.0, balance=None):
    """banks.upload_statement'ın kullandığı _save_and_parse'ı sahte parsed ile değiştir
    (gerçek dosya parse edilmez — test_bank_manual_transaction deseninin endpoint hali)."""
    from app.utils.bank_parser import ParsedHeader, ParsedTransaction, ParseResult, compute_tx_hash

    tx_date = TODAY - timedelta(days=1)
    parsed = ParseResult(
        header=ParsedHeader(iban=iban, currency=currency),
        transactions=[ParsedTransaction(
            date=tx_date, receipt_no=None, description=f"FAZ3 UPLOAD {uuid4().hex[:6]}",
            amount=amount, balance=balance, type="expense" if amount < 0 else "income",
            tx_hash=compute_tx_hash(tx_date, None, amount, f"faz3-{uuid4().hex}"),
        )],
    )

    async def _fake(file):
        return ("/tmp/faz3-nonexistent.xlsx", parsed, "xlsx", "faz3-fake.xlsx")

    monkeypatch.setattr("app.routers.finance.banks._save_and_parse", _fake)


_UPLOAD_FILE = {"file": ("faz3.xlsx", b"dummy", "application/vnd.ms-excel")}


class TestUploadHeaderValidation:
    def test_wrong_iban_rejected_400(self, client, auth_headers, db, monkeypatch):
        acc = _mk_account(db, currency="TRY")
        db.commit()
        _install_fake_parse(monkeypatch, iban=f"TR{'9' * 24}", currency="TL")

        r = client.post(f"{API_BANKS}/accounts/{acc.id}/upload",
                        files=_UPLOAD_FILE, headers=auth_headers)
        assert r.status_code == 400, r.text
        assert "uyuşmuyor" in r.json()["detail"]
        # Ekstre kaydı OLUŞMADI
        assert db.query(BankStatement).filter(BankStatement.account_id == acc.id).count() == 0

    def test_currency_mismatch_rejected_400(self, client, auth_headers, db, monkeypatch):
        acc = _mk_account(db, currency="TRY")
        db.commit()
        # IBAN doğru (boşluklu/küçük harfli — normalizasyon da test edilir), para birimi yanlış
        spaced_iban = " ".join([acc.iban[i:i + 4] for i in range(0, len(acc.iban), 4)]).lower()
        _install_fake_parse(monkeypatch, iban=spaced_iban, currency="USD")

        r = client.post(f"{API_BANKS}/accounts/{acc.id}/upload",
                        files=_UPLOAD_FILE, headers=auth_headers)
        assert r.status_code == 400, r.text
        assert "para birimi" in r.json()["detail"]

    def test_matching_iban_and_tl_alias_passes(self, client, auth_headers, db, monkeypatch):
        """Doğru IBAN + başlıkta 'TL' (hesap TRY) → normalizasyonla geçer, işlem yazılır."""
        acc = _mk_account(db, currency="TRY")
        db.commit()
        _install_fake_parse(monkeypatch, iban=acc.iban, currency="TL", balance=99000.0)

        r = client.post(f"{API_BANKS}/accounts/{acc.id}/upload",
                        files=_UPLOAD_FILE, headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["new_transactions"] == 1
        assert db.query(BankTransaction).filter(
            BankTransaction.account_id == acc.id).count() == 1


# ═══════════════ G) Yaşlanan eşleşmemişler (aging) ═══════════════


class TestAging:
    def test_compute_aging_groups_and_items(self, db):
        """10 gün vadesi geçmiş açık çek FE'si sayılır (grup + item + days_overdue);
        taze FE girmez; etiketsiz eski banka hareketi unmatched_bank'ta."""
        old_check = _mk_check(db, due_date=TODAY - timedelta(days=10), amount=12000.0)
        fresh_check = _mk_check(db, due_date=TODAY, amount=500.0)
        finance_event_svc.upsert_check(db, old_check)
        finance_event_svc.upsert_check(db, fresh_check)

        acc = _mk_account(db)
        old_btx = _mk_btx(db, acc, amount=-3000.0, tx_date=TODAY - timedelta(days=10),
                          desc="FAZ3 ETİKETSİZ ESKİ")
        _mk_btx(db, acc, amount=-1.0, tx_date=TODAY, desc="FAZ3 TAZE")
        db.flush()

        res = compute_aging(db, days=7)

        assert res["days"] == 7
        assert res["cutoff"] == (TODAY - timedelta(days=7)).isoformat()
        groups = res["stale_forecasts"]["by_source"]
        assert groups["check"]["count"] == 1
        assert groups["check"]["label"] == "Çek"
        assert groups["check"]["total_try"] == 12000.0
        assert groups["check"]["oldest_date"] == (TODAY - timedelta(days=10)).isoformat()
        assert res["stale_forecasts"]["total_count"] == 1

        items = res["stale_forecasts"]["items"]
        assert len(items) == 1
        assert items[0]["source_type"] == "check"
        assert items[0]["source_id"] == old_check.id
        assert items[0]["days_overdue"] == 10

        ub = res["unmatched_bank"]
        assert ub["count"] == 1
        assert ub["total"] == 3000.0
        assert [i["id"] for i in ub["items"]] == [old_btx.id]
        assert ub["items"][0]["days_old"] == 10

    def test_matched_or_realized_forecast_not_stale(self, db):
        """Eşleşmiş (is_matched) veya gerçekleşmiş çek FE'si yaşlananlara girmez."""
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-4000.0, tx_date=TODAY - timedelta(days=9))
        paid_check = _mk_check(db, due_date=TODAY - timedelta(days=9), amount=4000.0)
        _match_check_to_btx(db, paid_check, btx)  # is_matched=True + realized
        db.flush()

        res = compute_aging(db, days=7)
        assert res["stale_forecasts"]["total_count"] == 0

    def test_aging_endpoint_permissions(self, client, viewer_user_headers,
                                        no_perm_user_headers):
        r = client.get(f"{API_CF}/reconciliation/aging?days=7", headers=viewer_user_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert {"days", "cutoff", "stale_forecasts", "unmatched_bank"} <= set(body.keys())
        assert client.get(f"{API_CF}/reconciliation/aging",
                          headers=no_perm_user_headers).status_code == 403


# ═══════════════ H) Tahmin doğruluğu (forecast-accuracy) ═══════════════


class TestForecastAccuracy:
    def _seed(self, db):
        """check gecikme 3g; cari A gecikme 5g (öneri var); cari B gecikme 1g (öneri yok)."""
        acc = _mk_account(db)
        # Çek: vade 5 gün önce, banka 2 gün önce → delay 3
        chk_btx = _mk_btx(db, acc, amount=-10000.0, tx_date=TODAY - timedelta(days=2))
        check = _mk_check(db, due_date=TODAY - timedelta(days=5), amount=10000.0)
        db.add(EventMatch(bank_source_type="bank", bank_source_id=chk_btx.id,
                          target_source_type="check", target_source_id=check.id,
                          method="auto", score=90))
        # Cari A: vade 7 gün önce, banka 2 gün önce → delay 5 (|medyan|>=3 → öneri)
        vendor_a, vtx_a = _mk_vendor_pair(db, match_number=None, amount=5000.0)
        vendor_a.payment_days = 30
        vtx_a.payment_due_date = TODAY - timedelta(days=7)
        va_btx = _mk_btx(db, acc, amount=-5000.0, tx_date=TODAY - timedelta(days=2))
        db.add(EventMatch(bank_source_type="bank", bank_source_id=va_btx.id,
                          target_source_type="vendor_payment", target_source_id=vtx_a.id,
                          method="manual", score=None))
        # Cari B: vade 3 gün önce, banka 2 gün önce → delay 1 (öneri YOK)
        vendor_b, vtx_b = _mk_vendor_pair(db, match_number=None, amount=800.0)
        vtx_b.payment_due_date = TODAY - timedelta(days=3)
        vb_btx = _mk_btx(db, acc, amount=-800.0, tx_date=TODAY - timedelta(days=2))
        db.add(EventMatch(bank_source_type="bank", bank_source_id=vb_btx.id,
                          target_source_type="vendor_payment", target_source_id=vtx_b.id,
                          method="manual", score=None))
        db.flush()
        return check, vendor_a, vendor_b

    def test_by_type_median_and_vendor_suggestion(self, client, auth_headers, db):
        check, vendor_a, vendor_b = self._seed(db)
        db.commit()

        r = client.get(f"{API_CF}/forecast-accuracy", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["months"] == 6
        assert body["total_matches"] == 3

        by_type = {row["source_type"]: row for row in body["by_type"]}
        assert by_type["check"]["count"] == 1
        assert by_type["check"]["median_delay_days"] == 3.0
        assert by_type["check"]["label"] == "Çek"
        assert by_type["vendor_payment"]["count"] == 2
        assert by_type["vendor_payment"]["median_delay_days"] == 3.0  # medyan([5,1])

        by_vendor = {row["vendor_id"]: row for row in body["by_vendor"]}
        va = by_vendor[vendor_a.id]
        assert va["count"] == 1
        assert va["median_delay_days"] == 5.0
        assert va["current_payment_days"] == 30
        assert va["suggested_payment_days"] == 35  # 30 + medyan 5
        vb = by_vendor[vendor_b.id]
        assert vb["median_delay_days"] == 1.0
        assert vb["suggested_payment_days"] is None  # |medyan| < 3 → öneri yok

    def test_suggestions_excluded_and_permissions(self, client, viewer_user_headers,
                                                  no_perm_user_headers, db):
        """method='suggestion' izleri hesaba KATILMAZ; view yeterli, izinsiz 403."""
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-70.0, tx_date=TODAY - timedelta(days=1))
        check = _mk_check(db, due_date=TODAY - timedelta(days=4), amount=70.0)
        db.add(EventMatch(bank_source_type="bank", bank_source_id=btx.id,
                          target_source_type="check", target_source_id=check.id,
                          method=MATCH_METHOD_SUGGESTION, score=12))
        db.commit()

        r = client.get(f"{API_CF}/forecast-accuracy", headers=viewer_user_headers)
        assert r.status_code == 200
        assert r.json()["total_matches"] == 0
        assert client.get(f"{API_CF}/forecast-accuracy",
                          headers=no_perm_user_headers).status_code == 403


# ═══════════════ I) Bakiye zinciri kontrolü (#22a) ═══════════════


def _acc_breaks(breaks, acc_id):
    return [b for b in breaks if b["account_id"] == acc_id]


class TestBalanceChains:
    def test_consistent_chain_no_breaks(self, db):
        acc = _mk_account(db)
        _mk_btx(db, acc, amount=100.0, tx_date=TODAY - timedelta(days=3), balance=100.0)
        _mk_btx(db, acc, amount=50.0, tx_date=TODAY - timedelta(days=2), balance=150.0)
        _mk_btx(db, acc, amount=-30.0, tx_date=TODAY - timedelta(days=1), balance=120.0)
        db.flush()
        assert _acc_breaks(check_balance_chains(db), acc.id) == []

    def test_inconsistent_balance_single_break_with_gap(self, db):
        """Ortadaki satırın bakiyesi Σtutar'la uyuşmuyor → TEK kırılma, gap doğru."""
        acc = _mk_account(db)
        t1 = _mk_btx(db, acc, amount=100.0, tx_date=TODAY - timedelta(days=3), balance=100.0)
        t2 = _mk_btx(db, acc, amount=50.0, tx_date=TODAY - timedelta(days=2), balance=160.0)
        # t3, t2'nin GERÇEK bakiyesiyle tutarlı → ikinci kırılma üretmez
        _mk_btx(db, acc, amount=-30.0, tx_date=TODAY - timedelta(days=1), balance=130.0)
        db.flush()

        breaks = _acc_breaks(check_balance_chains(db), acc.id)
        assert len(breaks) == 1
        b = breaks[0]
        assert b["expected_balance"] == 150.0
        assert b["actual_balance"] == 160.0
        assert b["gap"] == 10.0
        assert b["after_tx_id"] == t1.id
        assert b["tx_id"] == t2.id
        assert b["bank_name"] == acc.bank_name

    def test_null_balance_manual_row_bridges(self, db):
        """Bakiyesi NULL manuel satır köprüdür: iki bakiyeli satır arasındaki TÜM
        tutarların toplamı bakiye farkına eşitse kırılma YOK."""
        acc = _mk_account(db)
        _mk_btx(db, acc, amount=100.0, tx_date=TODAY - timedelta(days=3), balance=100.0)
        _mk_btx(db, acc, amount=20.0, tx_date=TODAY - timedelta(days=2),
                balance=None, source="manual")
        _mk_btx(db, acc, amount=30.0, tx_date=TODAY - timedelta(days=1), balance=150.0)
        db.flush()
        assert _acc_breaks(check_balance_chains(db), acc.id) == []

    def test_tolerance_swallows_rounding(self, db):
        """Kuruş yuvarlaması (≤ tolerans) kırılma sayılmaz."""
        acc = _mk_account(db)
        _mk_btx(db, acc, amount=10.0, tx_date=TODAY - timedelta(days=2), balance=10.0)
        _mk_btx(db, acc, amount=5.0, tx_date=TODAY - timedelta(days=1),
                balance=15.0 + BALANCE_CHAIN_TOLERANCE)
        db.flush()
        assert _acc_breaks(check_balance_chains(db), acc.id) == []

    def test_run_reconciliation_summary_includes_chain_breaks(self, db):
        """run_reconciliation (Sedna fetch'leri enjekte) summary'ye balance_chain_breaks
        koyar — kırık zincirli hesap listede görünür."""
        acc = _mk_account(db, sedna_account_code=f"102.F3.{uuid4().hex[:8]}",
                          sedna_code_confirmed=True)
        _mk_btx(db, acc, amount=100.0, tx_date=TODAY - timedelta(days=3), balance=100.0)
        _mk_btx(db, acc, amount=50.0, tx_date=TODAY - timedelta(days=2), balance=160.0)
        db.commit()

        summary = run_reconciliation(
            db,
            fetch_rows=lambda codes, start: [],
            fetch_max_dates=lambda codes: {},
            notify=False,
        )
        assert "balance_chain_breaks" in summary
        ours = _acc_breaks(summary["balance_chain_breaks"], acc.id)
        assert len(ours) == 1
        assert ours[0]["gap"] == 10.0
