"""Sedna Mutabakat (accounting.mutabakat — Uyuşmayan Veriler) testleri.

Kapsam:
- classify_sedna_row / _match_account: saf eşleştirme çekirdeği (DB'siz)
- suggest_account_mappings: hesap eşleme önerileri (leafs enjekte — Sedna'ya bağlanılmaz)
- run_reconciliation: koşu bütünlüğü + otomatik kapanma + ignore kalıcılığı
  (fetch_rows/fetch_max_dates enjekte — sedna_client'a HİÇ dokunulmaz)
- Endpoint'ler: summary/items/PATCH item/PATCH mapping/POST run + izin kontrolleri
- Onay akışı uçtan-uca regresyonu (_handle_accounting_mutabakat executor handler'ı)

Tüm Sedna erişimi enjeksiyon/monkeypatch ile sahtelenir — tünel gerekmez.
"""
from datetime import date, timedelta
from uuid import uuid4

import pytest
import pytz
from datetime import datetime

from fastapi.testclient import TestClient

from app.constants import ReconStatus
from app.main import app
from app.middleware.rate_limit import login_limiter
from app.models import BankAccount, BankTransaction, SednaBankRecon, SednaReconRun
from app.models.approval import (
    STATUS_APPROVED,
    ApprovalWorkflow,
    ApprovalWorkflowApproverRole,
    ApprovalWorkflowRequestorRole,
)
from app.models.module import Module
from app.models.role import Role
from app.models.role_module_permission import RoleModulePermission
from app.models.user import User
from app.services.sedna_recon_service import (
    _match_account,
    classify_sedna_row,
    resolve_recon_item,
    run_reconciliation,
    suggest_account_mappings,
)
from app.utils.sedna_client import SednaUnavailable
from app.utils.security import hash_password

API = "/api/accounting/mutabakat"
APPROVAL_API = "/api/system/approval"

tz_istanbul = pytz.timezone("Europe/Istanbul")
TODAY = datetime.now(tz_istanbul).date()  # servis _today() ile aynı (İstanbul-açık)


# ─────────────────────────── Yardımcılar ───────────────────────────

def _b(i, d, a):
    """_match_account banka satırı."""
    return {"id": i, "date": d, "amount": float(a), "description": f"banka {i}"}


def _s(i, d, a):
    """_match_account Sedna satırı (yalnız eşleştirmede kullanılan alanlar)."""
    return {"rec_id": i, "owner_id": i * 10, "voucher": i, "fiche_date": d,
            "amount": float(a), "remark": f"sedna {i}", "record_user": "sednauser",
            "change_date": None}


def _mk_account(db, *, bank_name="Mutabakat Test Bankası", currency="TRY",
                iban=None, account_no=None, sedna_code=None, confirmed=False):
    acc = BankAccount(
        bank_name=bank_name,
        iban=iban or "TR{:024d}".format(uuid4().int % 10**24),
        account_no=account_no,
        currency=currency,
        is_active=True,
        sedna_account_code=sedna_code,
        sedna_code_confirmed=confirmed,
    )
    db.add(acc)
    db.flush()
    return acc


def _mk_btx(db, acc, d, amount, description="Mutabakat test hareketi"):
    btx = BankTransaction(
        account_id=acc.id, date=d, amount=amount,
        type="income" if amount >= 0 else "expense",
        description=description, source="statement",
        tx_hash=f"recon-{uuid4().hex}",
    )
    db.add(btx)
    db.flush()
    return btx


def _mk_item(db, acc, *, status=ReconStatus.SEDNA_MISSING, amount=1500.0,
             event_date=None, description="Banka test satırı"):
    item = SednaBankRecon(
        bank_account_id=acc.id, status=status, amount=amount,
        currency=acc.currency or "TRY",
        event_date=event_date or (TODAY - timedelta(days=3)),
        description=description,
    )
    db.add(item)
    db.flush()
    return item


def _unmap_all(db):
    """Deterministik koşu: DB'deki tüm hesapların Sedna eşlemesini kaldır (SAVEPOINT içinde)."""
    db.query(BankAccount).update(
        {"sedna_account_code": None, "sedna_code_confirmed": False},
        synchronize_session=False,
    )
    db.flush()


def _mapped_account(db, currency="TRY"):
    """Yalnız BU hesabın taranacağı, onaylı Sedna kodlu aktif hesap kur."""
    _unmap_all(db)
    code = "102.90.{}.{}".format(uuid4().hex[:2], uuid4().hex[:4])
    return _mk_account(db, currency=currency, sedna_code=code, confirmed=True)


def _sedna_ledger_row(code, fiche_date, amount, rec_id):
    """run_reconciliation fetch_rows satırı (TRY hesap: Debit/Credit taşır)."""
    return {
        "rec_id": rec_id, "owner_id": rec_id * 10, "voucher": rec_id,
        "fiche_date": fiche_date, "record_date": fiche_date, "change_date": None,
        "record_user": "sednauser", "owner_type": 0, "code": code,
        "debit": amount if amount > 0 else 0, "credit": -amount if amount < 0 else 0,
        "curr": "TL", "rate": 1, "curr_debit": 0, "curr_credit": 0,
        "remark": "Sedna test fişi",
    }


def _run(db, rows, max_dates, **kw):
    """Sedna'ya dokunmadan koşu (fetch enjekte, bildirim kapalı)."""
    return run_reconciliation(
        db,
        fetch_rows=lambda codes, start: rows,
        fetch_max_dates=lambda codes: max_dates,
        notify=False,
        **kw,
    )


# Onay akışı aktörleri (test_approval_system deseninin birebir kopyası)

def _login_client(username, password="Test1234!"):
    login_limiter._requests.clear()  # çoklu aktörde rate-limit flakiness'ini önle
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"login başarısız: {r.text}"
    return c


def _make_actor(db, perms):
    """Rol + kullanıcı + modül izinleri oluştur, login olmuş client döndür."""
    uid = uuid4().hex[:8]
    role = Role(name=f"reconrole_{uid}", description="mutabakat test rolü", is_active=True)
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

    username = f"reconu_{uid}"
    user = User(
        username=username, email=f"{username}@test.local",
        first_name="Mutabakat", last_name=uid[:6],
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


# ─────────────── A) classify_sedna_row (saf, DB'siz) ───────────────

class TestClassifySednaRow:
    def test_tl_debit_positive(self):
        """TL hesapta Borç=giriş → ('cash', +tutar)."""
        kind, amount = classify_sedna_row({"debit": 100, "credit": 0, "owner_type": 0}, "TRY")
        assert (kind, amount) == ("cash", 100.0)

    def test_tl_credit_negative(self):
        """TL hesapta Alacak=çıkış → ('cash', -tutar)."""
        kind, amount = classify_sedna_row({"debit": 0, "credit": 50, "owner_type": 0}, "TRY")
        assert (kind, amount) == ("cash", -50.0)

    def test_tl_owner_type_4_is_valuation(self):
        """Ay sonu kur farkı fişi (Owner.Type=4) TL hesapta bile değerlemedir."""
        kind, _ = classify_sedna_row({"debit": 100, "credit": 0, "owner_type": 4}, "TRY")
        assert kind == "valuation"

    def test_fx_amount_from_curr_columns(self):
        """Döviz hesabında tutar CurrDebit'ten gelir — Debit (TL karşılığı) yok sayılır."""
        row = {"debit": 4800, "credit": 0, "curr_debit": 100, "curr_credit": 0,
               "rate": 48, "owner_type": 0}
        kind, amount = classify_sedna_row(row, "EUR")
        assert (kind, amount) == ("cash", 100.0)

    def test_fx_valuation_row(self):
        """Dövizde Rate=0 & CurrDebit=CurrCredit=0 ama TL Debit dolu → değerleme satırı."""
        row = {"debit": 324607.78, "credit": 0, "curr_debit": 0, "curr_credit": 0,
               "rate": 0, "owner_type": 0}
        kind, amount = classify_sedna_row(row, "EUR")
        assert kind == "valuation"
        assert amount == 0.0

    def test_try_maps_to_sedna_tl(self):
        """Hesap para birimi 'TRY' → Sedna 'TL' çevrimi (Debit/Credit dalı kullanılır)."""
        row = {"debit": 100, "credit": 0, "curr_debit": 999, "curr_credit": 0,
               "rate": 1, "owner_type": 0}
        kind, amount = classify_sedna_row(row, "TRY")
        # TL dalı seçildiği için curr_debit=999 DEĞİL debit=100 esas alınır
        assert (kind, amount) == ("cash", 100.0)


# ─────────────── B) _match_account (saf, DB'siz) ───────────────

class TestMatchAccount:
    def test_exact_match_no_findings(self):
        """Aynı gün + aynı tutar birebir eşleşir — bulgu (matched kayıt) üretilmez."""
        d = date(2026, 6, 26)
        findings = _match_account([_b(1, d, 1995.0)], [_s(1, d, 1995.0)], sedna_max_date=TODAY)
        assert findings == []

    def test_count_aware_equal_counts(self):
        """Bankada 3× aynı (gün,tutar), Sedna'da 3× → adetle korunur, bulgu yok."""
        d = date(2026, 6, 15)
        bank = [_b(i, d, 1000.0) for i in (1, 2, 3)]
        sedna = [_s(i, d, 1000.0) for i in (1, 2, 3)]
        assert _match_account(bank, sedna, sedna_max_date=TODAY) == []

    def test_count_aware_extra_sedna_is_duplicate_suspect(self):
        """Sedna adedi 4 > banka adedi 3 → fark 1 adet DUPLICATE_SUSPECT."""
        d = date(2026, 6, 15)
        bank = [_b(i, d, 1000.0) for i in (1, 2, 3)]
        sedna = [_s(i, d, 1000.0) for i in (1, 2, 3, 4)]
        findings = _match_account(bank, sedna, sedna_max_date=TODAY)
        assert len(findings) == 1
        assert findings[0]["status"] == ReconStatus.DUPLICATE_SUSPECT
        assert findings[0]["btx"] is None
        assert findings[0]["sedna"] is not None

    def test_date_window_3_days_matches(self):
        """Banka 26.06 +1995, Sedna 29.06 +1995 → ±3 gün penceresinde eşleşir."""
        findings = _match_account(
            [_b(1, date(2026, 6, 26), 1995.0)],
            [_s(1, date(2026, 6, 29), 1995.0)],
            sedna_max_date=TODAY,
        )
        assert findings == []

    def test_date_window_5_days_no_match(self):
        """5 gün fark pencere dışı → eşleşmez (banka MISSING + Sedna EXTRA)."""
        findings = _match_account(
            [_b(1, date(2026, 6, 26), 1995.0)],
            [_s(1, date(2026, 7, 1), 1995.0)],
            sedna_max_date=date(2026, 7, 1),
        )
        statuses = sorted(f["status"] for f in findings)
        assert statuses == sorted([ReconStatus.SEDNA_MISSING, ReconStatus.SEDNA_EXTRA])

    def test_direction_flip(self):
        """Banka -5000, Sedna +5000 aynı gün → TEK kayıtta iki taraf, DIRECTION_FLIP."""
        d = date(2026, 6, 20)
        findings = _match_account([_b(1, d, -5000.0)], [_s(1, d, 5000.0)], sedna_max_date=TODAY)
        assert len(findings) == 1
        f = findings[0]
        assert f["status"] == ReconStatus.DIRECTION_FLIP
        assert f["btx"] is not None and f["sedna"] is not None

    def test_subset_bank_one_sedna_many(self):
        """Banka tek -171601; Sedna aynı gün -170810 + -791 (KDV+damga bölmesi) → eşleşir."""
        d = date(2026, 6, 10)
        findings = _match_account(
            [_b(1, d, -171601.0)],
            [_s(1, d, -170810.0), _s(2, d, -791.0)],
            sedna_max_date=TODAY,
        )
        assert findings == []

    def test_subset_bank_many_sedna_one(self):
        """Banka -1.14 + -0.06 (ücret+BSMV); Sedna tek -1.20 → eşleşir."""
        d = date(2026, 6, 11)
        findings = _match_account(
            [_b(1, d, -1.14), _b(2, d, -0.06)],
            [_s(1, d, -1.20)],
            sedna_max_date=TODAY,
        )
        assert findings == []

    def test_pending_vs_missing_threshold(self):
        """sedna_max_date SONRASI banka işlemi PENDING; öncesi MISSING; None → PENDING."""
        max_d = TODAY - timedelta(days=5)
        # Sonrası → Sedna henüz oraya gelmedi (gecikme)
        after = _match_account([_b(1, TODAY - timedelta(days=1), 700.0)], [], sedna_max_date=max_d)
        assert [f["status"] for f in after] == [ReconStatus.SEDNA_PENDING]
        # Öncesi → dönem içi, girilmemiş (gerçek eksik)
        before = _match_account([_b(1, TODAY - timedelta(days=10), 700.0)], [], sedna_max_date=max_d)
        assert [f["status"] for f in before] == [ReconStatus.SEDNA_MISSING]
        # Hiç Sedna verisi yok → PENDING
        none_case = _match_account([_b(1, TODAY - timedelta(days=10), 700.0)], [], sedna_max_date=None)
        assert [f["status"] for f in none_case] == [ReconStatus.SEDNA_PENDING]

    def test_sedna_only_row_is_extra(self):
        """Yalnız Sedna'da kalan satır → SEDNA_EXTRA."""
        findings = _match_account([], [_s(1, date(2026, 6, 18), 333.0)], sedna_max_date=TODAY)
        assert len(findings) == 1
        assert findings[0]["status"] == ReconStatus.SEDNA_EXTRA
        assert findings[0]["btx"] is None


# ─────────────── C) suggest_account_mappings (db + enjekte leafs) ───────────────

class TestSuggestAccountMappings:
    def test_suggestion_by_account_number(self, db):
        """Remark'a gömülü hesap no bizim IBAN rakamlarında geçiyor → öneri dolu, score>=60."""
        acc = _mk_account(db, bank_name="TEB", currency="EUR",
                          iban="TR520003200000000048909295")
        leafs = [{"code": "102.02.03.0002", "remark": "TEB MANAVGAT ŞB 48909295 EUR", "curr": "EUR"}]
        result = suggest_account_mappings(db, leafs=leafs)
        entry = next(a for a in result["accounts"] if a["account_id"] == acc.id)
        assert entry["suggestion"] is not None
        assert entry["suggestion"]["code"] == "102.02.03.0002"
        assert entry["suggestion"]["score"] >= 60
        # Önerilen leaf 'eşlenmemiş Sedna' listesine düşmez
        assert all(l["code"] != "102.02.03.0002" for l in result["unmatched_sedna"])

    def test_no_suggestion_without_digit_match(self, db):
        """Rakam grubu bizde YOK → banka adı + para birimi (25+15=40) yetmez, öneri None."""
        acc = _mk_account(db, bank_name="TEB", currency="EUR",
                          iban="TR520003200000000048909295")
        leafs = [{"code": "102.02.03.0009", "remark": "TEB MANAVGAT ŞB 99999999 EUR", "curr": "EUR"}]
        result = suggest_account_mappings(db, leafs=leafs)
        entry = next(a for a in result["accounts"] if a["account_id"] == acc.id)
        assert entry["suggestion"] is None

    def test_try_account_matches_sedna_tl_currency(self, db):
        """TRY hesap ↔ Sedna curr 'TL' eşleşmesi puan alır (para birimi çevrimi)."""
        acc = _mk_account(db, bank_name="Ziraat Katılım", currency="TRY",
                          iban="TR001234567800000000000001")
        leafs = [{"code": "102.01.05.0009", "remark": "HESAP 12345678 VADESIZ", "curr": "TL"}]
        result = suggest_account_mappings(db, leafs=leafs)
        entry = next(a for a in result["accounts"] if a["account_id"] == acc.id)
        assert entry["suggestion"] is not None
        assert entry["suggestion"]["score"] == 75  # 60 (hesap no) + 15 (para birimi)
        assert "para birimi" in entry["suggestion"]["reason"]


# ─────────────── D) run_reconciliation (db + enjekte fetch) ───────────────

class TestRunReconciliation:
    def test_missing_creates_record_and_run_row(self, db):
        """Sedna'da olmayan banka işlemi → SEDNA_MISSING kaydı + SednaReconRun satırı."""
        acc = _mapped_account(db)
        btx = _mk_btx(db, acc, TODAY - timedelta(days=5), 2500.0)

        summary = _run(db, [], {acc.sedna_account_code: TODAY})
        assert summary["accounts_scanned"] == 1
        assert summary["new"] == 1

        item = db.query(SednaBankRecon).filter(
            SednaBankRecon.bank_transaction_id == btx.id).one()
        assert item.status == ReconStatus.SEDNA_MISSING
        assert item.resolved_at is None
        assert float(item.amount) == 2500.0

        run_row = db.query(SednaReconRun).order_by(SednaReconRun.id.desc()).first()
        assert run_row is not None
        assert run_row.accounts_scanned == 1
        assert run_row.new_count == 1

    def test_pending_when_no_sedna_max_date(self, db):
        """Sedna'da hiç fişi olmayan hesap (max_date yok) → PENDING (gecikme, eksik değil)."""
        acc = _mapped_account(db)
        btx = _mk_btx(db, acc, TODAY - timedelta(days=5), 800.0)
        _run(db, [], {})
        item = db.query(SednaBankRecon).filter(
            SednaBankRecon.bank_transaction_id == btx.id).one()
        assert item.status == ReconStatus.SEDNA_PENDING

    def test_auto_close_when_sedna_arrives(self, db):
        """Sedna satırı sonradan girilince kayıt OTOMATİK kapanır (kullanıcı kuralı:
        'giderilince listeden otomatik kalksın') — status=matched, resolution=auto."""
        acc = _mapped_account(db)
        d = TODAY - timedelta(days=5)
        btx = _mk_btx(db, acc, d, 2500.0)

        _run(db, [], {acc.sedna_account_code: TODAY})
        item = db.query(SednaBankRecon).filter(
            SednaBankRecon.bank_transaction_id == btx.id).one()
        item_id = item.id
        assert item.resolved_at is None

        # Koşu 2: düzeltilmiş fetch — Sedna satırı artık VAR
        rows = [_sedna_ledger_row(acc.sedna_account_code, d, 2500.0, rec_id=71)]
        summary2 = _run(db, rows, {acc.sedna_account_code: TODAY})
        assert summary2["auto_closed"] == 1
        assert summary2["new"] == 0

        db.expire_all()
        item = db.query(SednaBankRecon).filter(SednaBankRecon.id == item_id).one()
        assert item.status == ReconStatus.MATCHED
        assert item.resolution == "auto"
        assert item.resolved_at is not None

    def test_ignored_item_not_reopened(self, db):
        """'Yoksay' işaretlenen kayıt sonraki koşuda yeniden açılmaz, mükerrer kayıt da oluşmaz."""
        acc = _mapped_account(db)
        btx = _mk_btx(db, acc, TODAY - timedelta(days=5), 999.5)
        _run(db, [], {acc.sedna_account_code: TODAY})
        item = db.query(SednaBankRecon).filter(
            SednaBankRecon.bank_transaction_id == btx.id).one()

        resolve_recon_item(db, item.id, "ignore", "bilinçli fark", None)
        db.flush()

        summary2 = _run(db, [], {acc.sedna_account_code: TODAY})
        assert summary2["new"] == 0

        db.expire_all()
        rows = db.query(SednaBankRecon).filter(
            SednaBankRecon.bank_transaction_id == btx.id).all()
        assert len(rows) == 1  # yeni kayıt açılmadı
        assert rows[0].resolution == "ignored"
        assert rows[0].resolved_at is not None

    def test_no_mapped_accounts_scans_zero(self, db):
        """Eşlenmiş (onaylı) hesap yoksa exception yok: accounts_scanned=0 + not düşülür."""
        _unmap_all(db)

        def _boom(*args, **kwargs):
            raise AssertionError("Eşlenmiş hesap yokken Sedna sorgulanmamalı")

        summary = run_reconciliation(db, fetch_rows=_boom, fetch_max_dates=_boom, notify=False)
        assert summary["accounts_scanned"] == 0
        run_row = db.query(SednaReconRun).order_by(SednaReconRun.id.desc()).first()
        assert run_row is not None
        assert run_row.note is not None and "Eşlenmiş" in run_row.note

    def test_fetch_failure_leaves_records_untouched(self, db):
        """Tünel koparsa SednaUnavailable yükselir; mevcut kayıtlar ve koşu sayısı DEĞİŞMEZ."""
        acc = _mapped_account(db)
        btx = _mk_btx(db, acc, TODAY - timedelta(days=5), 4321.0)
        _run(db, [], {acc.sedna_account_code: TODAY})
        item = db.query(SednaBankRecon).filter(
            SednaBankRecon.bank_transaction_id == btx.id).one()
        item_id = item.id
        runs_before = db.query(SednaReconRun).count()

        def _fail(codes, start=None):
            raise SednaUnavailable("Sedna tüneli kapalı (test)")

        with pytest.raises(SednaUnavailable):
            run_reconciliation(db, fetch_rows=_fail,
                               fetch_max_dates=lambda codes: {}, notify=False)

        db.expire_all()
        item = db.query(SednaBankRecon).filter(SednaBankRecon.id == item_id).one()
        assert item.status == ReconStatus.SEDNA_MISSING  # dokunulmadı
        assert item.resolved_at is None
        assert db.query(SednaReconRun).count() == runs_before  # yeni koşu satırı yazılmadı


# ─────────────── E) Endpoint'ler ───────────────

class TestEndpoints:
    def test_summary_returns_expected_fields(self, client, auth_headers):
        r = client.get(f"{API}/summary", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        for key in ("open_by_status", "open_total", "oldest_open_date",
                    "mapped_accounts", "total_accounts", "last_run"):
            assert key in d, f"summary alanı eksik: {key}"

    def test_items_pagination_shape(self, client, auth_headers, db):
        acc = _mk_account(db)
        item = _mk_item(db, acc)
        db.commit()
        r = client.get(f"{API}/items", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert {"items", "total", "page", "page_size", "pages"} <= set(d.keys())
        assert any(it["id"] == item.id for it in d["items"])

    def test_items_sort_by_whitelist_rejects_unknown(self, client, auth_headers):
        r = client.get(f"{API}/items?sort_by=evil_column", headers=auth_headers)
        assert r.status_code == 422

    def test_patch_item_resolve(self, client, auth_headers, db):
        acc = _mk_account(db)
        item = _mk_item(db, acc)
        db.commit()
        r = client.patch(f"{API}/items/{item.id}",
                         json={"action": "resolve", "note": "elle çözüldü"},
                         headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["resolution"] == "manual"
        assert body["resolved_at"] is not None
        assert body["resolution_note"] == "elle çözüldü"

    def test_patch_item_404(self, client, auth_headers):
        r = client.patch(f"{API}/items/99999999", json={"action": "resolve"},
                         headers=auth_headers)
        assert r.status_code == 404

    def test_patch_account_mapping(self, client, auth_headers, db):
        acc = _mk_account(db)
        db.commit()
        code = "102.91.{}.{}".format(uuid4().hex[:2], uuid4().hex[:4])
        r = client.patch(f"{API}/account-mappings/{acc.id}",
                         json={"sedna_account_code": code, "confirmed": True},
                         headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sedna_account_code"] == code
        assert body["sedna_code_confirmed"] is True

    def test_patch_account_mapping_invalid_code_400(self, client, auth_headers, db):
        acc = _mk_account(db)
        db.commit()
        r = client.patch(f"{API}/account-mappings/{acc.id}",
                         json={"sedna_account_code": "320.01.01.0001", "confirmed": True},
                         headers=auth_headers)
        assert r.status_code == 400
        assert "102" in r.json()["detail"]

    def test_run_endpoint_with_mocked_sedna(self, client, auth_headers, db, monkeypatch):
        """POST /run — sedna_client fonksiyonları sahtelenir, 200 + özet döner."""
        import app.utils.sedna_client as sedna_client_module

        acc = _mapped_account(db)
        _mk_btx(db, acc, TODAY - timedelta(days=2), 100.0)
        db.commit()

        monkeypatch.setattr(sedna_client_module, "fetch_bank_ledger_rows",
                            lambda codes, start: [])
        monkeypatch.setattr(sedna_client_module, "fetch_bank_ledger_max_dates",
                            lambda codes: {})
        r = client.post(f"{API}/run", json={"window_days": 30}, headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["accounts_scanned"] == 1
        assert d["new"] == 1  # Sedna boş → 1 PENDING bulgusu

    def test_no_permission_403(self, client, no_perm_user_headers):
        assert client.get(f"{API}/summary", headers=no_perm_user_headers).status_code == 403
        assert client.get(f"{API}/items", headers=no_perm_user_headers).status_code == 403

    def test_view_only_cannot_mutate_403(self, client, viewer_user_headers):
        assert client.post(f"{API}/run", json={}, headers=viewer_user_headers).status_code == 403
        assert client.patch(f"{API}/items/1", json={"action": "resolve"},
                            headers=viewer_user_headers).status_code == 403


# ─────────────── F) Onay akışı uçtan-uca regresyonu ───────────────

class TestMutabakatApprovalRegression:
    def test_resolve_item_via_approval_regression(self, db):
        """REGRESYON: accounting.mutabakat update onaya bağlandığında PATCH 202 döner,
        kayıt onay öncesi DEĞİŞMEZ; onaylanınca executor (_handle_accounting_mutabakat,
        payload {"op":"resolve_item",...}) resolve'u uygular → resolution='manual'."""
        acc = _mk_account(db)
        item = _mk_item(db, acc)
        db.commit()
        item_id = item.id

        _, req_role, req_client = _make_actor(db, {
            "accounting.mutabakat": {"view": True, "use": True},
            "system.approval": {"view": True, "use": False},
        })
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "accounting.mutabakat", req_role, app_role)

        r = req_client.patch(f"{API}/items/{item_id}",
                             json={"action": "resolve", "note": "onay üzerinden çözüm"})
        assert r.status_code == 202, f"onaya düşmeli: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("requires_approval") is True
        req_id = body["request_id"]

        db.expire_all()
        fresh = db.query(SednaBankRecon).filter(SednaBankRecon.id == item_id).one()
        assert fresh.resolution is None, "onaydan ÖNCE kayıt değişmemeli"
        assert fresh.resolved_at is None

        ap = app_client.post(f"{APPROVAL_API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"executor handler hatası: {ap.text}"
        assert ap.json()["status"] == STATUS_APPROVED

        db.expire_all()
        fresh = db.query(SednaBankRecon).filter(SednaBankRecon.id == item_id).one()
        assert fresh.resolution == "manual"
        assert fresh.resolved_at is not None
        assert fresh.resolution_note == "onay üzerinden çözüm"
