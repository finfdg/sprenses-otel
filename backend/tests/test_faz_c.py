"""Faz C testleri (2026-07-11) — cari bakiye mutabakatı + kredi/acente kod eşlemesi +
dönem kilidi (uyarı modu) + ters-bakiye kontrolü + avans kod-öncelikli eşleşme.

Kapsam:
A) run_vendor_reconciliation — cari NET bakiye ↔ Sedna 320 (fetch_balances enjekte):
   fark kaydı / tolerans / otomatik kapanma / 'bulunamadı' / ignore kalıcılığı
B) suggest_credit_mappings / set_credit_mapping — 300 leaf önerisi (tutar-adda sinyali)
   + 300-prefix doğrulaması + temizleme
C) suggest_agency_mappings / set_agency_mapping — 340 önerileri (çoklu para birimi)
   + 340-prefix doğrulaması + liste atama/temizleme
D) period_lock_service — set/get/clear + cache invalidation + run_reconciliation
   entegrasyonu (summary['locked_period_new'])
E) negative_balances — aktif hesapta negatif son bakiye görünür; KMH-bağlı hesap hariç
F) Endpoint'ler — GET/PATCH credit-mappings, agency-mappings, PATCH period-lock,
   items?entity_type=vendor_balance
G) Onay regresyonu — PATCH period-lock 202 → onayla → executor kilidi uygular
H) advances kod-öncelikli eşleşme — agency_groups.sedna_account_codes fuzzy'yi ezer,
   kodsuz acente eski fuzzy ile eşleşmeye devam eder

Tüm Sedna erişimi enjeksiyon/monkeypatch ile sahtelenir — tünele ASLA bağlanılmaz.
"""
from datetime import date, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytz
from fastapi.testclient import TestClient

from app.constants import ReconStatus
from app.main import app
from app.middleware.rate_limit import login_limiter
from app.models import (
    AgencyGroup,
    Advance,
    BankAccount,
    BankTransaction,
    CreditProduct,
    FinancePeriodLock,
    SednaBankRecon,
    Vendor,
    VendorTransaction,
    VendorUpload,
)
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
from app.services.period_lock_service import (
    get_lock_date,
    invalidate_lock_cache,
    set_lock_date,
)
from app.services.sedna_recon_service import (
    report_entity_diff,
    resolve_recon_item,
    run_reconciliation,
    run_vendor_reconciliation,
    set_agency_mapping,
    set_credit_mapping,
    suggest_agency_mappings,
    suggest_credit_mappings,
)
from app.utils.security import hash_password

API = "/api/accounting/mutabakat"
APPROVAL_API = "/api/system/approval"
ADVANCE_REC = "app.routers.finance.advances"

tz_istanbul = pytz.timezone("Europe/Istanbul")
TODAY = datetime.now(tz_istanbul).date()  # servis _today() ile aynı (İstanbul-açık)


# ─────────────────────────── Yardımcılar ───────────────────────────


def _mk_vendor(db, *, alacak=0.0, borc=0.0, name="FZC CARİ"):
    """Tek hareketli cari — run_vendor_reconciliation'ın kapsadığı en küçük evren."""
    code = "320.99.{}.{}".format(uuid4().hex[:2], uuid4().hex[:4])
    up = VendorUpload(file_name="fazc-seed", file_url="x")
    db.add(up)
    db.flush()
    v = Vendor(hesap_kodu=code, hesap_adi=f"{name} {code[-4:]}")
    db.add(v)
    db.flush()
    db.add(VendorTransaction(
        vendor_id=v.id, upload_id=up.id, date=date(2026, 5, 2),
        borc=borc, alacak=alacak, tx_hash="fazc-{}".format(uuid4().hex),
    ))
    db.flush()
    return v


def _vendor_diff(db, vendor_id):
    return (
        db.query(SednaBankRecon)
        .filter(SednaBankRecon.entity_type == "vendor_balance",
                SednaBankRecon.entity_id == vendor_id)
        .all()
    )


def _mk_account(db, *, bank_name="FZC Test Bankası", currency="TRY",
                sedna_code=None, confirmed=False):
    acc = BankAccount(
        bank_name=bank_name,
        iban="TR{:024d}".format(uuid4().int % 10**24),
        currency=currency,
        is_active=True,
        sedna_account_code=sedna_code,
        sedna_code_confirmed=confirmed,
    )
    db.add(acc)
    db.flush()
    return acc


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
    code = "102.98.{}.{}".format(uuid4().hex[:2], uuid4().hex[:4])
    return _mk_account(db, currency=currency, sedna_code=code, confirmed=True)


def _mk_btx(db, acc, d, amount, *, balance=None, description="FZC test hareketi"):
    btx = BankTransaction(
        account_id=acc.id, date=d, amount=amount,
        type="income" if amount >= 0 else "expense",
        description=description, source="statement", balance=balance,
        tx_hash="fazc-{}".format(uuid4().hex),
    )
    db.add(btx)
    db.flush()
    return btx


def _run(db, rows, max_dates, **kw):
    """Sedna'ya dokunmadan banka mutabakat koşusu (fetch enjekte, bildirim kapalı)."""
    return run_reconciliation(
        db,
        fetch_rows=lambda codes, start: rows,
        fetch_max_dates=lambda codes: max_dates,
        notify=False,
        **kw,
    )


def _mk_credit(db, *, bank_name="HALK BANKASI", currency="TRY",
               total_amount=6000000, type_="spot_kredi", code=None):
    prod = CreditProduct(
        type=type_, name=f"FZC Kredi {uuid4().hex[:6]}", bank_name=bank_name,
        currency=currency, total_amount=total_amount, remaining_amount=0,
        status="active", sedna_account_code=code,
    )
    db.add(prod)
    db.flush()
    return prod


def _mk_group(db, *, name=None, members=None, codes=None):
    g = AgencyGroup(
        name=name or f"FZC Grup {uuid4().hex[:8]}",
        members=members or [],
        sedna_account_codes=codes,
    )
    db.add(g)
    db.flush()
    return g


def _uniq_300():
    return "300.90.{}.{}".format(uuid4().hex[:2], uuid4().hex[:4])


# Onay akışı aktörleri (test_sedna_recon deseninin birebir kopyası)


def _login_client(username, password="Test1234!"):
    login_limiter._requests.clear()  # çoklu aktörde rate-limit flakiness'ini önle
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"login başarısız: {r.text}"
    return c


def _make_actor(db, perms):
    """Rol + kullanıcı + modül izinleri oluştur, login olmuş client döndür."""
    uid = uuid4().hex[:8]
    role = Role(name=f"fazcrole_{uid}", description="faz c test rolü", is_active=True)
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

    username = f"fazcu_{uid}"
    user = User(
        username=username, email=f"{username}@test.local",
        first_name="FazC", last_name=uid[:6],
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


# ═══════════════════ A) run_vendor_reconciliation ═══════════════════


class TestVendorReconciliation:
    def test_balance_diff_created_with_signed_amount(self, db):
        """Bizim net ≠ Sedna net (fark > 1 TL) → 'vendor_balance' balance_diff kaydı,
        amount = işaretli fark (bizim − Sedna)."""
        v = _mk_vendor(db, alacak=5000.0)  # bizim net = −5000
        summary = run_vendor_reconciliation(
            db, fetch_balances=lambda: {v.hesap_kodu: {"borc": 0.0, "alacak": 2000.0}})
        assert summary["balance_diffs"] >= 1
        assert summary["vendors_scanned"] >= 1

        rows = _vendor_diff(db, v.id)
        assert len(rows) == 1
        item = rows[0]
        assert item.status == ReconStatus.BALANCE_DIFF
        assert item.resolved_at is None
        assert float(item.amount) == pytest.approx(-3000.0)  # −5000 − (−2000)
        assert v.hesap_kodu in (item.description or "")

    def test_within_tolerance_no_record(self, db):
        """Fark ≤ 1 TL (kuruş yuvarlaması) → kayıt AÇILMAZ."""
        v = _mk_vendor(db, alacak=5000.0)
        run_vendor_reconciliation(
            db, fetch_balances=lambda: {v.hesap_kodu: {"borc": 0.0, "alacak": 5000.5}})
        assert _vendor_diff(db, v.id) == []

    def test_diff_auto_closes_when_gap_resolved(self, db):
        """İkinci koşuda fark kapanmış → kayıt OTOMATİK kapanır (matched/auto)."""
        v = _mk_vendor(db, alacak=5000.0)
        run_vendor_reconciliation(
            db, fetch_balances=lambda: {v.hesap_kodu: {"borc": 0.0, "alacak": 2000.0}})
        item = _vendor_diff(db, v.id)[0]
        assert item.resolved_at is None

        summary2 = run_vendor_reconciliation(
            db, fetch_balances=lambda: {v.hesap_kodu: {"borc": 0.0, "alacak": 5000.0}})
        assert summary2["vendor_auto_closed"] >= 1
        db.expire_all()
        item = db.query(SednaBankRecon).filter(SednaBankRecon.id == item.id).one()
        assert item.status == ReconStatus.MATCHED
        assert item.resolution == "auto"
        assert item.resolved_at is not None

    def test_missing_sedna_account_reports_bulunamadi(self, db):
        """Sedna'da hesap yok + bizde net ≠ 0 → fark kaydı + 'bulunamadı' metni."""
        v = _mk_vendor(db, alacak=750.0)
        run_vendor_reconciliation(db, fetch_balances=lambda: {})
        rows = _vendor_diff(db, v.id)
        assert len(rows) == 1
        assert rows[0].status == ReconStatus.BALANCE_DIFF
        assert float(rows[0].amount) == pytest.approx(-750.0)
        assert "bulunamadı" in (rows[0].sedna_description or "")

    def test_ignored_balance_diff_not_reopened(self, db):
        """'Yoksay' işaretlenen bakiye farkı sonraki koşuda yeniden açılmaz, mükerrer olmaz."""
        v = _mk_vendor(db, alacak=5000.0)
        fetch = lambda: {v.hesap_kodu: {"borc": 0.0, "alacak": 2000.0}}  # noqa: E731
        run_vendor_reconciliation(db, fetch_balances=fetch)
        item = _vendor_diff(db, v.id)[0]
        resolve_recon_item(db, item.id, "ignore", "bilinçli fark", None)
        db.flush()

        run_vendor_reconciliation(db, fetch_balances=fetch)
        db.expire_all()
        rows = _vendor_diff(db, v.id)
        assert len(rows) == 1  # yeni kayıt açılmadı
        assert rows[0].resolution == "ignored"
        assert rows[0].resolved_at is not None


# ═══════════════════ B) Kredi kod eşlemesi ═══════════════════


class TestCreditMappings:
    def test_suggestion_with_amount_in_leaf_name(self, db):
        """Banka adı + para birimi + tutar-adda ('6.000.000' remark'ta) → score ≥ 45 öneri."""
        prod = _mk_credit(db, bank_name="HALK BANKASI", total_amount=6000000, currency="TRY")
        leafs = [{"code": "300.01.01.0004",
                  "remark": "HALK BANKASI L0004813 6.000.000 TL KREDİ", "curr": "TL"}]
        result = suggest_credit_mappings(db, leafs=leafs)
        entry = next(p for p in result["products"] if p["product_id"] == prod.id)
        assert entry["suggestion"] is not None
        assert entry["suggestion"]["code"] == "300.01.01.0004"
        assert entry["suggestion"]["score"] >= 45
        assert "tutar adda" in entry["suggestion"]["reason"]
        # Önerilen leaf 'eşlenmemiş Sedna' listesine düşmez
        assert all(l["code"] != "300.01.01.0004" for l in result["unmatched_sedna"])

    def test_low_signal_leaf_no_suggestion(self, db):
        """Banka adı örtüşmüyor + tutar remark'ta geçmiyor → skor eşiğin altında, öneri None."""
        prod = _mk_credit(db, bank_name="HALK BANKASI", total_amount=6000000, currency="TRY")
        leafs = [{"code": "300.02.01.0009",
                  "remark": "GARANTİ BBVA 1.000.000 TL KREDİ", "curr": "TL"}]
        result = suggest_credit_mappings(db, leafs=leafs)
        entry = next(p for p in result["products"] if p["product_id"] == prod.id)
        assert entry["suggestion"] is None

    def test_set_credit_mapping_rejects_non_300(self, db):
        prod = _mk_credit(db)
        with pytest.raises(ValueError):
            set_credit_mapping(db, prod.id, "102.01.01.0001")
        db.expire_all()
        assert db.query(CreditProduct).filter(
            CreditProduct.id == prod.id).one().sedna_account_code is None

    def test_set_credit_mapping_assign_and_clear(self, db):
        prod = _mk_credit(db)
        code = _uniq_300()
        set_credit_mapping(db, prod.id, code)
        assert prod.sedna_account_code == code

        set_credit_mapping(db, prod.id, None)  # temizleme
        assert prod.sedna_account_code is None

    def test_set_credit_mapping_unknown_product(self, db):
        with pytest.raises(ValueError):
            set_credit_mapping(db, 99999999, _uniq_300())


# ═══════════════════ C) Acente kod eşlemesi ═══════════════════


class TestAgencyMappings:
    def test_suggestions_multi_currency(self, db):
        """Grup adı token örtüşmesi → para birimi başına AYRI hesap önerisi (liste)."""
        g = _mk_group(db, name=f"FZC Anex Tour {uuid4().hex[:6]}",
                      members=["Anex Deutschland"])
        accounts = [
            {"code": "340.01.01.0001", "name": "ANEX EUR AVANS HESABI", "currency": "EUR"},
            {"code": "340.01.01.0002", "name": "ANEX USD AVANS HESABI", "currency": "USD"},
            {"code": "340.01.01.0003", "name": "CORAL TRAVEL AVANS", "currency": "TL"},
        ]
        result = suggest_agency_mappings(db, accounts=accounts)
        entry = next(x for x in result["groups"] if x["group_id"] == g.id)
        codes = {s["code"] for s in entry["suggestions"]}
        assert {"340.01.01.0001", "340.01.01.0002"} <= codes
        assert "340.01.01.0003" not in codes
        currencies = {s["currency"] for s in entry["suggestions"]}
        assert {"EUR", "USD"} <= currencies

    def test_member_token_also_matches(self, db):
        """Grup üyesinin adı da eşleşme sinyalidir."""
        g = _mk_group(db, name=f"FZC Grup {uuid4().hex[:6]}", members=["Coral Travel"])
        accounts = [{"code": "340.01.01.0011", "name": "CORAL TRAVEL EUR", "currency": "EUR"}]
        result = suggest_agency_mappings(db, accounts=accounts)
        entry = next(x for x in result["groups"] if x["group_id"] == g.id)
        assert [s["code"] for s in entry["suggestions"]] == ["340.01.01.0011"]

    def test_mapped_group_gets_no_suggestions(self, db):
        """Zaten kodu atanmış grup için öneri listesi BOŞ döner (current_codes dolu)."""
        g = _mk_group(db, name=f"FZC Anex {uuid4().hex[:6]}",
                      codes=["340.01.01.0034"])
        accounts = [{"code": "340.01.01.0001", "name": "ANEX EUR AVANS", "currency": "EUR"}]
        result = suggest_agency_mappings(db, accounts=accounts)
        entry = next(x for x in result["groups"] if x["group_id"] == g.id)
        assert entry["current_codes"] == ["340.01.01.0034"]
        assert entry["suggestions"] == []

    def test_set_agency_mapping_rejects_non_340(self, db):
        g = _mk_group(db)
        with pytest.raises(ValueError):
            set_agency_mapping(db, g.id, ["120.01.01.0001"])

    def test_set_agency_mapping_assign_and_clear(self, db):
        g = _mk_group(db)
        set_agency_mapping(db, g.id, ["340.01.01.0034", "340.01.01.0035"])
        assert list(g.sedna_account_codes) == ["340.01.01.0034", "340.01.01.0035"]

        set_agency_mapping(db, g.id, [])  # temizleme
        assert g.sedna_account_codes is None

    def test_set_agency_mapping_unknown_group(self, db):
        with pytest.raises(ValueError):
            set_agency_mapping(db, 99999999, ["340.01.01.0034"])


# ═══════════════════ D) Dönem kilidi servisi ═══════════════════


class TestPeriodLockService:
    def test_set_get_clear_and_cache_invalidation(self, db):
        d1, d2, d3 = date(2026, 5, 31), date(2026, 6, 30), date(2026, 4, 30)

        set_lock_date(db, d1, None)
        assert get_lock_date(db) == d1

        set_lock_date(db, d2, None)  # tek satır upsert (update yolu)
        assert get_lock_date(db) == d2
        assert db.query(FinancePeriodLock).count() == 1

        # Cache kanıtı: doğrudan DB değişikliği invalidate edilmeden GÖRÜNMEZ
        db.query(FinancePeriodLock).update({"lock_date": d3}, synchronize_session=False)
        db.flush()
        assert get_lock_date(db) == d2  # bayat (cache'ten)
        invalidate_lock_cache()
        assert get_lock_date(db) == d3  # taze

        set_lock_date(db, None, None)  # kaldır
        assert get_lock_date(db) is None
        assert db.query(FinancePeriodLock).count() == 0

    def test_run_reconciliation_flags_locked_period_new(self, db):
        """Kilit tarihi geçmişte + kilit-öncesi event_date'li YENİ bulgu →
        summary['locked_period_new'] sayar; kilit-sonrası bulgu sayılmaz."""
        set_lock_date(db, TODAY - timedelta(days=10), None)
        acc = _mapped_account(db)
        _mk_btx(db, acc, TODAY - timedelta(days=20), 1500.0)  # kilit-ÖNCESİ
        _mk_btx(db, acc, TODAY - timedelta(days=2), 800.0)    # kilit-SONRASI

        summary = _run(db, [], {acc.sedna_account_code: TODAY})
        assert summary["new"] == 2
        assert summary["locked_period_new"] == 1

    def test_run_reconciliation_no_lock_zero(self, db):
        """Kilit yoksa locked_period_new = 0."""
        set_lock_date(db, None, None)
        acc = _mapped_account(db)
        _mk_btx(db, acc, TODAY - timedelta(days=20), 1500.0)
        summary = _run(db, [], {acc.sedna_account_code: TODAY})
        assert summary["locked_period_new"] == 0


# ═══════════════════ E) Ters-bakiye kontrolü ═══════════════════


class TestNegativeBalances:
    def test_negative_last_balance_reported(self, db):
        acc = _mapped_account(db)  # koşunun tarayacağı hesap (erken dönüşü aşmak için)
        neg = _mk_account(db, bank_name="FZC Negatif Bankası")
        _mk_btx(db, neg, TODAY - timedelta(days=8), 100.0, balance=250.0)
        _mk_btx(db, neg, TODAY - timedelta(days=3), -1484.56, balance=-1234.56)  # SON bakiye

        summary = _run(db, [], {acc.sedna_account_code: TODAY})
        hit = next((n for n in summary["negative_balances"] if n["account_id"] == neg.id), None)
        assert hit is not None
        assert hit["balance"] == pytest.approx(-1234.56)
        assert hit["bank_name"] == "FZC Negatif Bankası"

    def test_kmh_linked_account_excluded(self, db):
        """KMH'ye bağlı hesabın negatif bakiyesi doğaldır → listeye GİRMEZ."""
        acc = _mapped_account(db)
        kmh_acc = _mk_account(db, bank_name="FZC KMH Bankası")
        _mk_btx(db, kmh_acc, TODAY - timedelta(days=3), -2000.0, balance=-2000.0)
        db.add(CreditProduct(
            type="kmh", name="FZC KMH", currency="TRY", total_amount=0,
            remaining_amount=0, status="active", linked_account_id=kmh_acc.id,
        ))
        db.flush()

        summary = _run(db, [], {acc.sedna_account_code: TODAY})
        assert not any(n["account_id"] == kmh_acc.id for n in summary["negative_balances"])

    def test_positive_last_balance_not_reported(self, db):
        acc = _mapped_account(db)
        pos = _mk_account(db, bank_name="FZC Pozitif Bankası")
        _mk_btx(db, pos, TODAY - timedelta(days=3), 500.0, balance=500.0)

        summary = _run(db, [], {acc.sedna_account_code: TODAY})
        assert not any(n["account_id"] == pos.id for n in summary["negative_balances"])


# ═══════════════════ F) Endpoint'ler ═══════════════════


class TestFazCEndpoints:
    def test_get_credit_mappings(self, client, auth_headers, db, monkeypatch):
        import app.utils.sedna_client as sedna_client_module

        prod = _mk_credit(db, bank_name="HALK BANKASI", total_amount=6000000)
        db.commit()
        monkeypatch.setattr(sedna_client_module, "fetch_credit_leaf_accounts", lambda: [
            {"code": "300.01.01.0004",
             "remark": "HALK BANKASI L0004813 6.000.000 TL KREDİ", "curr": "TL"},
        ])
        r = client.get(f"{API}/credit-mappings", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert {"products", "unmatched_sedna"} <= set(d.keys())
        entry = next(p for p in d["products"] if p["product_id"] == prod.id)
        assert entry["suggestion"] is not None
        assert entry["suggestion"]["code"] == "300.01.01.0004"

    def test_patch_credit_mapping_assign_and_invalid(self, client, auth_headers, db):
        prod = _mk_credit(db)
        db.commit()
        code = _uniq_300()
        r = client.patch(f"{API}/credit-mappings/{prod.id}",
                         json={"sedna_account_code": code}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["sedna_account_code"] == code
        db.expire_all()
        assert db.query(CreditProduct).filter(
            CreditProduct.id == prod.id).one().sedna_account_code == code

        # 300 dışı kod → 400
        r2 = client.patch(f"{API}/credit-mappings/{prod.id}",
                          json={"sedna_account_code": "102.01.01.0001"},
                          headers=auth_headers)
        assert r2.status_code == 400
        assert "300" in r2.json()["detail"]

    def test_get_agency_mappings(self, client, auth_headers, db, monkeypatch):
        import app.utils.sedna_client as sedna_client_module

        g = _mk_group(db, name=f"FZC Anex Endpoint {uuid4().hex[:6]}")
        db.commit()
        monkeypatch.setattr(sedna_client_module, "fetch_advance_accounts", lambda: [
            {"code": "340.01.01.0001", "name": "ANEX EUR AVANS", "currency": "EUR"},
        ])
        r = client.get(f"{API}/agency-mappings", headers=auth_headers)
        assert r.status_code == 200, r.text
        entry = next(x for x in r.json()["groups"] if x["group_id"] == g.id)
        assert [s["code"] for s in entry["suggestions"]] == ["340.01.01.0001"]

    def test_patch_agency_mapping_assign_and_invalid(self, client, auth_headers, db):
        g = _mk_group(db)
        db.commit()
        r = client.patch(f"{API}/agency-mappings/{g.id}",
                         json={"sedna_account_codes": ["340.01.01.0034"]},
                         headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["sedna_account_codes"] == ["340.01.01.0034"]
        db.expire_all()
        assert list(db.query(AgencyGroup).filter(
            AgencyGroup.id == g.id).one().sedna_account_codes) == ["340.01.01.0034"]

        # 340 dışı kod → 400
        r2 = client.patch(f"{API}/agency-mappings/{g.id}",
                          json={"sedna_account_codes": ["120.01.01.0001"]},
                          headers=auth_headers)
        assert r2.status_code == 400
        assert "340" in r2.json()["detail"]

    def test_patch_period_lock_set_and_clear_reflected_in_summary(self, client, auth_headers, db):
        # SET
        r = client.patch(f"{API}/period-lock", json={"lock_date": "2026-06-30"},
                         headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["lock_date"] == "2026-06-30"
        s = client.get(f"{API}/summary", headers=auth_headers)
        assert s.status_code == 200
        assert s.json()["lock_date"] == "2026-06-30"

        # CLEAR
        r2 = client.patch(f"{API}/period-lock", json={"lock_date": None},
                          headers=auth_headers)
        assert r2.status_code == 200, r2.text
        assert r2.json()["lock_date"] is None
        s2 = client.get(f"{API}/summary", headers=auth_headers)
        assert s2.json()["lock_date"] is None

    def test_items_entity_type_vendor_balance_filter(self, client, auth_headers, db):
        v = _mk_vendor(db, alacak=5000.0)
        report_entity_diff(
            db, "vendor_balance", v.id, amount=-3000.0, currency="TRY",
            event_date=TODAY, description="FZC bakiye farkı",
            sedna_description="Sedna net −2000", status=ReconStatus.BALANCE_DIFF,
        )
        db.commit()
        r = client.get(f"{API}/items?entity_type=vendor_balance", headers=auth_headers)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert all(it["entity_type"] == "vendor_balance" for it in items)
        ours = next(it for it in items if it["entity_id"] == v.id)
        assert ours["status"] == ReconStatus.BALANCE_DIFF

    def test_mutation_endpoints_view_only_403(self, client, viewer_user_headers):
        assert client.patch(f"{API}/credit-mappings/1",
                            json={"sedna_account_code": "300.01.01.0001"},
                            headers=viewer_user_headers).status_code == 403
        assert client.patch(f"{API}/agency-mappings/1",
                            json={"sedna_account_codes": []},
                            headers=viewer_user_headers).status_code == 403
        assert client.patch(f"{API}/period-lock", json={"lock_date": None},
                            headers=viewer_user_headers).status_code == 403


# ═══════════════════ G) Onay akışı regresyonu ═══════════════════


class TestFazCApprovalRegression:
    def test_period_lock_via_approval_regression(self, db):
        """REGRESYON: accounting.mutabakat workflow'u varken PATCH period-lock 202 döner,
        kilit onaydan ÖNCE uygulanmaz; onaylanınca executor (_handle_accounting_mutabakat,
        payload {"op":"period_lock",...}) kilidi uygular → FinancePeriodLock satırı oluşur."""
        db.query(FinancePeriodLock).delete(synchronize_session=False)
        db.flush()
        invalidate_lock_cache()

        _, req_role, req_client = _make_actor(db, {
            "accounting.mutabakat": {"view": True, "use": True},
            "system.approval": {"view": True, "use": False},
        })
        _, app_role, app_client = _make_actor(db, {"system.approval": {"view": True, "use": True}})
        _make_workflow(db, "accounting.mutabakat", req_role, app_role)

        r = req_client.patch(f"{API}/period-lock", json={"lock_date": "2026-06-30"})
        assert r.status_code == 202, f"onaya düşmeli: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("requires_approval") is True
        req_id = body["request_id"]

        db.expire_all()
        assert db.query(FinancePeriodLock).count() == 0, "onaydan ÖNCE kilit uygulanmamalı"

        ap = app_client.post(f"{APPROVAL_API}/requests/{req_id}/approve", json={})
        assert ap.status_code == 200, f"executor handler hatası: {ap.text}"
        assert ap.json()["status"] == STATUS_APPROVED

        db.expire_all()
        row = db.query(FinancePeriodLock).order_by(FinancePeriodLock.id).first()
        assert row is not None
        assert row.lock_date == date(2026, 6, 30)
        invalidate_lock_cache()
        assert get_lock_date(db) == date(2026, 6, 30)


# ═══════════════════ H) Avans kod-öncelikli eşleşme ═══════════════════


class TestAdvanceCodePriority:
    def test_code_mapping_beats_fuzzy_and_fuzzy_fallback_kept(self, client, auth_headers, db):
        """agency_groups.sedna_account_codes'lu acente, Sedna hesabının ADI bambaşka olsa
        bile KOD ile eşleşir; kod eşlemesi olmayan acente eski fuzzy ile eşleşmeye devam eder."""
        gname = f"FZC Kodlu Grup {uuid4().hex[:6]}"
        _mk_group(db, name=gname, codes=["340.01.01.0034"])
        db.add(Advance(agency_name=gname, amount=1000, currency="EUR", status="received",
                       received_amount=1000, advance_date=date(2026, 1, 5)))
        db.add(Advance(agency_name="Alltours", amount=500, currency="EUR", status="received",
                       received_amount=500, advance_date=date(2026, 2, 1)))
        db.flush()

        fake = [
            # Kodlu hesap — adı grup adıyla HİÇ örtüşmüyor (fuzzy bunu bulamazdı)
            {"code": "340.01.01.0034", "name": "TAMAMEN BAMBASKA UNVAN", "currency": "EUR",
             "received": 900, "consumed": 100},
            # Kodsuz acentenin fuzzy hedefi
            {"code": "340.02.01.0017", "name": "ALLTOURS FLUGREISEN", "currency": "EUR",
             "received": 480, "consumed": 0},
        ]
        with patch(f"{ADVANCE_REC}.sedna_configured", return_value=True), \
             patch(f"{ADVANCE_REC}.fetch_advance_accounts", return_value=fake):
            r = client.get("/api/finance/avanslar/sedna-reconciliation", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()

        coded = next(x for x in d["matched"] if x["agency_name"] == gname)
        assert coded["matched"] is True
        assert coded["sedna_code"] == "340.01.01.0034", "kod-öncelikli eşleşme fuzzy'yi ezmeli"
        assert coded["sedna_received"] == 900.0
        assert coded["sedna_remaining"] == 800.0  # 900 − 100

        fuzzy = next(x for x in d["matched"] if x["agency_name"] == "Alltours")
        assert fuzzy["matched"] is True
        assert fuzzy["sedna_code"] == "340.02.01.0017", "kodsuz acente fuzzy ile eşleşmeli"

    def test_code_mapping_prefers_currency_matching_account(self, client, auth_headers, db):
        """Grup kod listesinde birden çok hesap varsa avansın para birimiyle eşleşen seçilir."""
        gname = f"FZC Çok Para {uuid4().hex[:6]}"
        _mk_group(db, name=gname, codes=["340.01.01.0040", "340.01.01.0041"])
        db.add(Advance(agency_name=gname, amount=2000, currency="USD", status="received",
                       received_amount=2000, advance_date=date(2026, 3, 1)))
        db.flush()

        fake = [
            {"code": "340.01.01.0040", "name": "GRUP EUR HESABI", "currency": "EUR",
             "received": 5000, "consumed": 0},
            {"code": "340.01.01.0041", "name": "GRUP USD HESABI", "currency": "USD",
             "received": 2000, "consumed": 0},
        ]
        with patch(f"{ADVANCE_REC}.sedna_configured", return_value=True), \
             patch(f"{ADVANCE_REC}.fetch_advance_accounts", return_value=fake):
            r = client.get("/api/finance/avanslar/sedna-reconciliation", headers=auth_headers)
        assert r.status_code == 200, r.text
        m = next(x for x in r.json()["matched"] if x["agency_name"] == gname)
        assert m["matched"] is True
        assert m["sedna_code"] == "340.01.01.0041"  # USD hesabı (para birimi önceliği)
