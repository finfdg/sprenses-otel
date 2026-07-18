"""Nakit akım eşleştirme çekirdeği — regresyon test ağı (Revize Faz 0 R6, 2026-07-11).

Bugüne kadar hiç test edilmemiş eşleştirme çekirdeği + bugün eklenen davranışlar:

A) POST /cash-flow/match-vendor-tx (İLK KEZ):
   - match_number artık `nextval('match_number_seq')` — iki tarafta AYNI numara,
     ardışık eşleşmeler FARKLI ve ARTAN numara alır (max()+1 regresyonu).
   - Banka bacağı finance_events'e sync_tag ile yansır AMA is_matched DEĞİŞMEZ (cari kuralı).
   - event_matches'e method='manual' kalıcı iz düşer.
   - 404 yolları (btx/vtx yok).
B) POST /cash-flow/match-cc-payment + unmatch-cc-payment (İLK KEZ):
   - Kısmi ödeme paid_amount biriktirir; FE kalan borcu yansıtır; tam ödemede is_paid + FE gizlenir.
   - unmatch paid_amount'u geri düşürür + FE yeniden açılır.
C) POST /cash-flow/match-credit-payment (İLK KEZ):
   - Taksit is_paid + bank_transaction_id; kredi FE is_matched=True (çift sayım engeli);
     banka FE sync_tag ile etiketlenir.
D) matching_service._match_credits_to_bank N-1 grup eşleşmesi (İLK KEZ):
   - Aynı gün + aynı banka + aynı para birimindeki iki banka satırı (faiz+vergi) toplamı
     taksite ±0.02 eşitse taksit kapanır. MEVCUT davranış: yalnız İLK satır
     bank_transaction_id alır (düzeltme Faz 1'de — burada davranış sabitlenir).
E) matching_service.run_post_ingest_processing (YENİ orkestratör):
   - auto-tag matcher'lardan önce koşar; FE'ye sync_tag yazar (auto_tagger._sync_finance_events);
     auto-tag patlasa bile matcher'lar koşar (SAVEPOINT izolasyonu).
F) POST /cash-flow/rematch (YENİ endpoint): 200 + özet; viewer 403; audit kaydı.
G) eur_balances deferral regresyonu (R5): ötelenen çek/kredi/KK aylık toplamda ESKİ ayda
   değil YENİ ayda görünür; runway ile aynı (ötelenmiş) tarihi gösterir.
H) VakıfBank importu (monkeypatch'li client): yeni işlem yaratınca run_post_ingest_processing
   koşar (bekleyen çek paid olur); yeni işlem yoksa koşmaz.

Dış servislere (Sedna/VakıfBank) ASLA bağlanılmaz — tümü monkeypatch.
"""

import calendar
import itertools
from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.models.audit_log import AuditLog
from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.check import Check, CheckUpload
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_product import CreditPayment, CreditProduct
from app.models.event_match import EventMatch
from app.models.exchange_rate import ExchangeRate
from app.models.finance_event import FinanceEvent
from app.models.transaction_category import TransactionCategory
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.models.vendor_upload import VendorUpload
from app.services import deferral_service
from app.utils.finance_event_service import finance_event_svc
from app.utils.finance_helpers import MIN_DATE
from app.utils.matching_service import (
    _match_credits_to_bank,
    run_post_ingest_processing,
)

API = "/api/finance/cash-flow"
TODAY = date.today()

_SEQ = itertools.count(977001)


# ─────────────────────────── Yardımcılar ───────────────────────────


def _mk_account(db, *, bank_name="Eşleştirme Test Bankası", currency="TRY", account_no=None):
    acc = BankAccount(
        bank_name=bank_name, iban=f"TR{uuid4().hex}"[:34], currency=currency,
        is_active=True, account_no=account_no,
    )
    db.add(acc)
    db.flush()
    return acc


def _mk_btx(db, acc, *, amount, tx_date=None, desc="TEST HAREKETİ", ttype=None):
    btx = BankTransaction(
        account_id=acc.id, date=tx_date or TODAY, description=desc,
        amount=amount, balance=0,
        type=ttype or ("expense" if amount < 0 else "income"),
        tx_hash=f"test-cfm-{uuid4().hex}",
    )
    db.add(btx)
    db.flush()
    return btx


def _mk_vendor_with_tx(db, *, borc=0.0, alacak=0.0, tx_date=None):
    n = next(_SEQ)
    up = VendorUpload(file_name="seed", file_url="x")
    db.add(up)
    db.flush()
    vendor = Vendor(hesap_kodu=f"320.T{n}", hesap_adi=f"EŞLEŞTİRME TEST CARİ {n}")
    db.add(vendor)
    db.flush()
    vtx = VendorTransaction(
        vendor_id=vendor.id, upload_id=up.id, date=tx_date or TODAY,
        evrak_no=f"EVR{n}", borc=borc, alacak=alacak, tx_hash=f"vtx-{uuid4().hex}",
    )
    db.add(vtx)
    db.flush()
    return vendor, vtx


def _mk_check(db, *, due_date, amount, check_no=None, status="pending"):
    up = CheckUpload(file_name="seed", file_url="x")
    db.add(up)
    db.flush()
    check = Check(
        upload_id=up.id, check_no=check_no or str(7700000 + next(_SEQ)),
        vendor_name="ÇEK TEST FİRMASI", due_date=due_date,
        amount_tl=amount, amount_currency=amount, currency="TL", status=status,
    )
    db.add(check)
    db.flush()
    return check


def _mk_credit_payment(db, *, due_date, amount=10000.0, bank_name="Grup Test Bankası",
                       currency="TRY", ptype="taksitli", installment_no=1):
    product = CreditProduct(
        type=ptype, name=f"EŞLEŞTİRME TEST KREDİ {next(_SEQ)}",
        bank_name=bank_name, currency=currency,
        total_amount=amount, remaining_amount=amount, status="active",
    )
    db.add(product)
    db.flush()
    payment = CreditPayment(
        credit_product_id=product.id, installment_no=installment_no,
        due_date=due_date, amount=amount, is_paid=False,
    )
    db.add(payment)
    db.flush()
    return product, payment


def _mk_cc_statement(db, *, toplam_borc, kesim, son_odeme, limit=0.0, name=None):
    prod = CreditProduct(
        type="kredi_karti", name=name or f"EŞLEŞTİRME TEST KART {next(_SEQ)}",
        total_amount=limit, remaining_amount=0, status="active",
    )
    db.add(prod)
    db.flush()
    stmt = CreditCardStatement(
        credit_product_id=prod.id, kesim_tarihi=kesim, son_odeme_tarihi=son_odeme,
        toplam_borc=toplam_borc, is_paid=False, paid_amount=0,
    )
    db.add(stmt)
    db.flush()
    return prod, stmt


def _mk_rate(db, dt, value, code="EUR"):
    db.query(ExchangeRate).filter(
        ExchangeRate.date == dt, ExchangeRate.currency_code == code
    ).delete(synchronize_session=False)
    db.add(ExchangeRate(date=dt, currency_code=code, unit=1,
                        forex_buying=value, forex_selling=value))
    db.flush()


def _fe(db, source_type, source_id):
    return db.query(FinanceEvent).filter(
        FinanceEvent.source_type == source_type,
        FinanceEvent.source_id == source_id,
    ).first()


def _plus_months(d, n, day=10):
    """d'den n ay sonrası (sabit gün — ay taşması güvenli)."""
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(day, calendar.monthrange(y, m)[1]))


def _ensure_category(db, name, color="#0F766E"):
    cat = db.query(TransactionCategory).filter(TransactionCategory.name == name).first()
    if not cat:
        cat = TransactionCategory(name=name, color=color, sort_order=990)
        db.add(cat)
        db.flush()
    return cat


# ═══════════════ A) match_vendor_tx — manuel cari eşleştirme ═══════════════


class TestMatchVendorTx:
    def _match(self, client, auth_headers, btx, vtx, vendor):
        return client.post(f"{API}/match-vendor-tx", headers=auth_headers, json={
            "bank_transaction_id": btx.id,
            "vendor_transaction_id": vtx.id,
            "vendor_id": vendor.id,
        })

    def test_same_number_both_sides_and_sequence_increases(self, client, auth_headers, db):
        """Sequence regresyonu: iki taraf AYNI numarayı alır; ardışık eşleşmeler
        FARKLI ve ARTAN numara alır (eski max()+1 eşzamanlılıkta çakışıyordu)."""
        acc = _mk_account(db)
        btx1 = _mk_btx(db, acc, amount=-1000, desc="EFT ÖDEME BİR")
        vendor1, vtx1 = _mk_vendor_with_tx(db, borc=1000)
        btx2 = _mk_btx(db, acc, amount=-2000, desc="EFT ÖDEME İKİ")
        vendor2, vtx2 = _mk_vendor_with_tx(db, borc=2000)
        db.commit()

        r1 = self._match(client, auth_headers, btx1, vtx1, vendor1)
        assert r1.status_code == 200, r1.text
        m1 = r1.json()["match_number"]
        assert m1 and m1 > 0

        db.expire_all()
        assert db.get(BankTransaction, btx1.id).match_number == m1
        assert db.get(VendorTransaction, vtx1.id).match_number == m1

        r2 = self._match(client, auth_headers, btx2, vtx2, vendor2)
        assert r2.status_code == 200, r2.text
        m2 = r2.json()["match_number"]
        assert m2 != m1
        assert m2 > m1  # sequence artan — numara asla tekrar kullanılmaz

    def test_bank_fe_synced_but_is_matched_stays_false(self, client, auth_headers, db):
        """R2: sync_tag banka FE'sine match_number + cari bilgisi yazar AMA is_matched'a
        DOKUNMAZ — cari eşleştirmesi banka hareketini nakit akımdan gizlemez (cari kuralı)."""
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-1500, desc="EFT CARİ ÖDEMESİ")
        vendor, vtx = _mk_vendor_with_tx(db, borc=1500)
        db.commit()

        resp = self._match(client, auth_headers, btx, vtx, vendor)
        assert resp.status_code == 200, resp.text
        m = resp.json()["match_number"]

        db.expire_all()
        fe = _fe(db, "bank", btx.id)
        assert fe is not None, "banka bacağı finance_events'e yansımadı (sync_tag eksik)"
        assert fe.match_number == m
        assert fe.vendor_id == vendor.id
        assert fe.vendor_code == vendor.hesap_kodu
        assert fe.tag_note == vendor.hesap_adi
        assert fe.payment_method == "havale_eft"
        assert fe.is_matched is False  # KRİTİK: cari eşleşmesi banka hareketini GİZLEMEZ

    def test_event_match_trace_manual(self, client, auth_headers, db):
        """event_matches'e method='manual' kalıcı iz düşer; kimlikler doğru."""
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-750, desc="EFT İZ TESTİ")
        vendor, vtx = _mk_vendor_with_tx(db, borc=750)
        db.commit()

        resp = self._match(client, auth_headers, btx, vtx, vendor)
        assert resp.status_code == 200, resp.text
        m = resp.json()["match_number"]

        trace = db.query(EventMatch).filter(
            EventMatch.bank_source_type == "bank",
            EventMatch.bank_source_id == btx.id,
        ).first()
        assert trace is not None, "event_matches izi yazılmadı"
        assert trace.method == "manual"
        assert trace.target_source_type == "vendor_payment"
        assert trace.target_source_id == vtx.id
        assert trace.match_number == m
        assert trace.created_by is not None

    def test_404_bank_tx_missing(self, client, auth_headers, db):
        vendor, vtx = _mk_vendor_with_tx(db, borc=100)
        db.commit()
        resp = client.post(f"{API}/match-vendor-tx", headers=auth_headers, json={
            "bank_transaction_id": 99999999,
            "vendor_transaction_id": vtx.id,
            "vendor_id": vendor.id,
        })
        assert resp.status_code == 404

    def test_404_vendor_tx_missing(self, client, auth_headers, db):
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-100)
        db.commit()
        resp = client.post(f"{API}/match-vendor-tx", headers=auth_headers, json={
            "bank_transaction_id": btx.id,
            "vendor_transaction_id": 99999999,
            "vendor_id": 1,
        })
        assert resp.status_code == 404


# ═══════════════ B) match-cc-payment + unmatch-cc-payment ═══════════════


class TestMatchCcPayment:
    def _setup(self, db, *, borc=5000.0):
        acc = _mk_account(db, bank_name="KK Test Bankası")
        prod, stmt = _mk_cc_statement(
            db, toplam_borc=borc,
            kesim=TODAY + timedelta(days=1), son_odeme=TODAY + timedelta(days=20),
        )
        db.commit()
        return acc, prod, stmt

    def _match(self, client, auth_headers, btx, stmt):
        return client.post(f"{API}/match-cc-payment", headers=auth_headers, json={
            "bank_transaction_id": btx.id, "statement_id": stmt.id,
        })

    def test_partial_payment_accumulates_and_fe_shows_remaining(self, client, auth_headers, db):
        acc, prod, stmt = self._setup(db, borc=5000.0)
        btx1 = _mk_btx(db, acc, amount=-2000, desc="KK KISMİ ÖDEME 1")
        db.commit()

        r1 = self._match(client, auth_headers, btx1, stmt)
        assert r1.status_code == 200, r1.text
        body = r1.json()
        assert body["ok"] is True
        assert body["paid_amount"] == 2000.0
        assert body["total_paid"] == 2000.0
        assert body["remaining"] == 3000.0
        assert body["is_fully_paid"] is False
        assert body["card_name"] == prod.name

        db.expire_all()
        s = db.get(CreditCardStatement, stmt.id)
        assert float(s.paid_amount) == 2000.0
        assert s.is_paid is False

        # FE kalan borcu yansıtır, hâlâ görünür
        fe = _fe(db, "cc_payment", stmt.id)
        assert fe is not None
        assert float(fe.amount) == 3000.0
        assert fe.is_matched is False
        assert fe.event_status == "pending"

        # Banka bacağı etiketlendi + FE'ye yansıdı
        b = db.get(BankTransaction, btx1.id)
        assert b.payment_method == "kredi_karti"
        assert b.tag_source == "manual"
        bank_fe = _fe(db, "bank", btx1.id)
        assert bank_fe is not None and bank_fe.payment_method == "kredi_karti"

        # İkinci kısmi ödeme → birikim tamamlar
        btx2 = _mk_btx(db, acc, amount=-3000, desc="KK KISMİ ÖDEME 2")
        db.commit()
        r2 = self._match(client, auth_headers, btx2, stmt)
        assert r2.status_code == 200, r2.text
        body2 = r2.json()
        assert body2["total_paid"] == 5000.0
        assert body2["remaining"] == 0
        assert body2["is_fully_paid"] is True

        db.expire_all()
        s = db.get(CreditCardStatement, stmt.id)
        assert s.is_paid is True
        assert float(s.paid_amount) == 5000.0
        assert s.paid_date == btx2.date

        # Tam ödeme → FE gizlenir
        fe = _fe(db, "cc_payment", stmt.id)
        assert fe.is_matched is True
        assert fe.event_status == "paid"

    def test_unmatch_reverts_paid_amount_and_reopens_fe(self, client, auth_headers, db):
        acc, prod, stmt = self._setup(db, borc=5000.0)
        btx = _mk_btx(db, acc, amount=-5000, desc="KK TAM ÖDEME")
        db.commit()

        assert self._match(client, auth_headers, btx, stmt).status_code == 200
        db.expire_all()
        assert db.get(CreditCardStatement, stmt.id).is_paid is True

        resp = client.post(f"{API}/unmatch-cc-payment", headers=auth_headers, json={
            "bank_transaction_id": btx.id, "statement_id": stmt.id,
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert body["card_name"] == prod.name

        db.expire_all()
        s = db.get(CreditCardStatement, stmt.id)
        assert float(s.paid_amount) == 0.0  # ödeme geri düştü
        assert s.is_paid is False
        assert s.paid_date is None

        # Banka etiketi temizlendi
        b = db.get(BankTransaction, btx.id)
        assert b.payment_method is None
        assert b.tag_source is None
        assert b.category_id is None

        # FE yeniden açıldı — tam borç görünür
        fe = _fe(db, "cc_payment", stmt.id)
        assert fe.is_matched is False
        assert fe.event_status == "pending"
        assert float(fe.amount) == 5000.0

    def test_404_paths(self, client, auth_headers, db):
        acc, prod, stmt = self._setup(db)
        btx = _mk_btx(db, acc, amount=-100)
        db.commit()
        assert client.post(f"{API}/match-cc-payment", headers=auth_headers, json={
            "bank_transaction_id": 99999999, "statement_id": stmt.id,
        }).status_code == 404
        assert client.post(f"{API}/match-cc-payment", headers=auth_headers, json={
            "bank_transaction_id": btx.id, "statement_id": 99999999,
        }).status_code == 404
        assert client.post(f"{API}/unmatch-cc-payment", headers=auth_headers, json={
            "bank_transaction_id": btx.id, "statement_id": 99999999,
        }).status_code == 404


# ═══════════════ C) match-credit-payment — manuel kredi taksit ═══════════════


class TestMatchCreditPayment:
    def test_match_marks_paid_links_bank_and_hides_credit_fe(self, client, auth_headers, db):
        acc = _mk_account(db, bank_name="Kredi Test Bankası")
        product, payment = _mk_credit_payment(
            db, due_date=TODAY + timedelta(days=15), amount=12345.5,
            bank_name="Kredi Test Bankası",
        )
        btx = _mk_btx(db, acc, amount=-12345.5, desc="KREDİ TAKSİT ÖDEMESİ")
        db.commit()

        resp = client.post(f"{API}/match-credit-payment", headers=auth_headers, json={
            "bank_transaction_id": btx.id, "payment_id": payment.id,
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert body["product_name"] == product.name
        assert body["installment_no"] == 1
        assert body["payment_amount"] == 12345.5
        assert body["bank_amount"] == 12345.5

        db.expire_all()
        p = db.get(CreditPayment, payment.id)
        assert p.is_paid is True
        assert p.paid_date == btx.date
        assert p.bank_transaction_id == btx.id

        # Kredi FE gizlenir (çift sayım engeli) + gerçekleşmiş sayılır
        credit_fe = _fe(db, "credit", payment.id)
        assert credit_fe is not None
        assert credit_fe.is_matched is True
        assert credit_fe.is_realized is True
        assert credit_fe.event_status == "paid"

        # Banka FE sync_tag etkisi: etiket + ödeme yöntemi (kredi tipi) yansır
        bank_fe = _fe(db, "bank", btx.id)
        assert bank_fe is not None
        assert bank_fe.tag_note == product.name
        assert bank_fe.payment_method == product.type
        assert bank_fe.is_realized is True  # match() banka bacağını realized yapar

        b = db.get(BankTransaction, btx.id)
        assert b.tag_source == "manual"

    def test_404_paths(self, client, auth_headers, db):
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-100)
        product, payment = _mk_credit_payment(db, due_date=TODAY, amount=100)
        db.commit()
        assert client.post(f"{API}/match-credit-payment", headers=auth_headers, json={
            "bank_transaction_id": 99999999, "payment_id": payment.id,
        }).status_code == 404
        assert client.post(f"{API}/match-credit-payment", headers=auth_headers, json={
            "bank_transaction_id": btx.id, "payment_id": 99999999,
        }).status_code == 404


# ═══════════════ D) _match_credits_to_bank — N-1 grup eşleşmesi ═══════════════


class TestCreditGroupMatch:
    """Faiz+vergi ayrı banka satırı senaryosu: aynı gün + aynı banka + aynı para
    biriminde iki satırın toplamı taksite ±0.02 eşitse taksit kapanır.
    Faz 1 #10 (2026-07-11) davranışı: grup eşleşmesinde ortak match_number TÜM banka
    satırlarına yazılır + her satır için event_matches izi düşer (eskiden yalnız
    ilk satır bağ alıyordu — mutabakat denetiminde kanıtsız satır kalıyordu).
    Ayrıntılı grup-izi testleri: tests/test_faz1_matching.py (E bölümü)."""

    def test_two_rows_sum_matches_installment(self, db):
        due = TODAY + timedelta(days=5)
        product, payment = _mk_credit_payment(
            db, due_date=due, amount=10000.0, bank_name="Grup Test Bankası",
        )
        acc = _mk_account(db, bank_name="Grup Test Bankası")
        btx_faiz = _mk_btx(db, acc, amount=-9000, tx_date=due, desc="KREDİ FAİZ TAHAKKUKU")
        btx_vergi = _mk_btx(db, acc, amount=-1000, tx_date=due, desc="KREDİ BSMV KESİNTİSİ")
        # FE'ler önceden var olsun ki match() etkisi doğrulanabilsin
        finance_event_svc.upsert_credit_payment(db, payment, product)
        finance_event_svc.upsert_bank_tx(db, btx_faiz, acc)
        finance_event_svc.upsert_bank_tx(db, btx_vergi, acc)
        db.commit()

        result = _match_credits_to_bank(db)
        assert result["matched"] == 1

        db.expire_all()
        p = db.get(CreditPayment, payment.id)
        assert p.is_paid is True
        assert p.paid_date == due
        # FK bağı grubun İLK satırına yazılır (tek kolon); diğer satır taksite FK almaz
        assert p.bank_transaction_id in (btx_faiz.id, btx_vergi.id)
        linked = p.bank_transaction_id
        other = btx_vergi.id if linked == btx_faiz.id else btx_faiz.id
        assert db.query(CreditPayment).filter(
            CreditPayment.bank_transaction_id == other
        ).count() == 0

        # Faz 1 #10: ortak match_number grubun TÜM banka satırlarında
        b1 = db.get(BankTransaction, btx_faiz.id)
        b2 = db.get(BankTransaction, btx_vergi.id)
        assert b1.match_number is not None
        assert b1.match_number == b2.match_number

        # Her satır için event_matches izi (target=credit, method=auto)
        traces = db.query(EventMatch).filter(
            EventMatch.target_source_type == "credit",
            EventMatch.target_source_id == payment.id,
        ).all()
        assert len(traces) == 2
        assert {t.bank_source_id for t in traces} == {btx_faiz.id, btx_vergi.id}
        assert all(t.method == "auto" for t in traces)

        # Kredi FE gizlendi (çift sayım engeli)
        credit_fe = _fe(db, "credit", payment.id)
        assert credit_fe.is_matched is True

    def test_group_tolerance_two_kurus(self, db):
        """Toplam taksitten 0.01 saparsa (kuruş yuvarlaması) yine eşleşir (<0.02)."""
        due = TODAY + timedelta(days=3)
        product, payment = _mk_credit_payment(
            db, due_date=due, amount=10000.0, bank_name="Tolerans Test Bankası",
        )
        acc = _mk_account(db, bank_name="Tolerans Test Bankası")
        _mk_btx(db, acc, amount=-9000, tx_date=due, desc="KREDİ FAİZ")
        _mk_btx(db, acc, amount=-999.99, tx_date=due, desc="KREDİ VERGİ")
        db.commit()

        assert _match_credits_to_bank(db)["matched"] == 1
        db.expire_all()
        assert db.get(CreditPayment, payment.id).is_paid is True

    def test_group_sum_off_no_match(self, db):
        """Toplam ±0.02 dışına düşerse (0.05 sapma) grup eşleşmez."""
        due = TODAY + timedelta(days=3)
        product, payment = _mk_credit_payment(
            db, due_date=due, amount=10000.0, bank_name="Sapan Test Bankası",
        )
        acc = _mk_account(db, bank_name="Sapan Test Bankası")
        _mk_btx(db, acc, amount=-9000, tx_date=due, desc="KREDİ FAİZ")
        _mk_btx(db, acc, amount=-999.95, tx_date=due, desc="KREDİ VERGİ")
        db.commit()

        assert _match_credits_to_bank(db)["matched"] == 0
        db.expire_all()
        assert db.get(CreditPayment, payment.id).is_paid is False


# ═══════════════ E) run_post_ingest_processing — ortak orkestratör ═══════════════


class TestRunPostIngestProcessing:
    def test_auto_tag_syncs_fe_and_matchers_run(self, db):
        """Auto-tag matcher'lardan önce koşar, FE'ye sync_tag yazar (A4 düzeltmesi);
        ardından matcher'lar koşar (çek eşleşmesi kanıt)."""
        _ensure_category(db, "Kredi/Leasing")
        acc = _mk_account(db, bank_name="Orkestratör Bankası")
        # Auto-tag kuralına uyan etiketlenmemiş gider ("kredi" kelimesi)
        btx_kredi = _mk_btx(db, acc, amount=-777, desc="XKURUM KREDI TAKSIT KESINTISI")
        # Bekleyen çek + açıklamasında çek no geçen banka gideri (matcher kanıtı)
        check = _mk_check(db, due_date=TODAY, amount=4321.5)
        btx_cek = _mk_btx(db, acc, amount=-4321.5, tx_date=TODAY,
                          desc=f"CEK NO {check.check_no} ODEMESI")
        db.commit()

        results = run_post_ingest_processing(db)

        assert results.get("auto_tagged", 0) >= 1
        assert results.get("checks_matched") == 1

        db.expire_all()
        # auto_tagger sync_tag kanıtı: FE'de kategori adı dolu
        fe = _fe(db, "bank", btx_kredi.id)
        assert fe is not None, "auto-tag FE'ye yansımadı (_sync_finance_events)"
        assert fe.category_name == "Kredi/Leasing"
        assert fe.tag_source == "auto"
        # Çek matcher gerçekten koştu
        c = db.get(Check, check.id)
        assert c.status == "paid"
        assert c.bank_transaction_id == btx_cek.id

    def test_auto_tag_failure_does_not_block_matchers(self, db, monkeypatch):
        """Auto-tag exception fırlatsa bile matcher'lar koşar (SAVEPOINT izolasyonu)."""
        acc = _mk_account(db, bank_name="İzolasyon Bankası")
        check = _mk_check(db, due_date=TODAY, amount=6543.25)
        _mk_btx(db, acc, amount=-6543.25, tx_date=TODAY,
                desc=f"CEK NO {check.check_no} ODEMESI")
        db.commit()

        def _boom(*args, **kwargs):
            raise RuntimeError("auto-tag patladı (test)")

        # run_post_ingest_processing fonksiyon içinde import eder → kaynak modülü patch'le
        monkeypatch.setattr("app.utils.auto_tagger.auto_tag_transactions", _boom)

        results = run_post_ingest_processing(db)

        assert "auto_tagged" not in results  # etiketleme adımı düştü
        assert results.get("checks_matched") == 1  # matcher yine koştu

        db.expire_all()
        assert db.get(Check, check.id).status == "paid"


# ═══════════════ F) POST /cash-flow/rematch — elle tetik ═══════════════


class TestRematchEndpoint:
    def test_rematch_200_returns_summary_and_matches(self, client, auth_headers, db):
        acc = _mk_account(db, bank_name="Rematch Bankası")
        check = _mk_check(db, due_date=TODAY, amount=8888.0)
        _mk_btx(db, acc, amount=-8888.0, tx_date=TODAY,
                desc=f"CEK NO {check.check_no} ODEMESI")
        db.commit()

        resp = client.post(f"{API}/rematch", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("checks_matched") == 1
        assert "auto_tagged" in body  # etiketleme adımı da koştu (özet anahtarı)

        db.expire_all()
        assert db.get(Check, check.id).status == "paid"

    def test_rematch_viewer_403(self, client, viewer_user_headers):
        resp = client.post(f"{API}/rematch", headers=viewer_user_headers)
        assert resp.status_code == 403

    def test_rematch_requires_auth(self, client):
        client.cookies.clear()
        assert client.post(f"{API}/rematch").status_code == 401

    def test_rematch_audit_logged(self, client, auth_headers, db):
        before = db.query(AuditLog).filter(
            AuditLog.entity_type == "bank_transaction",
            AuditLog.details.like("Yeniden eşleştirme%"),
        ).count()
        resp = client.post(f"{API}/rematch", headers=auth_headers)
        assert resp.status_code == 200
        after = db.query(AuditLog).filter(
            AuditLog.entity_type == "bank_transaction",
            AuditLog.details.like("Yeniden eşleştirme%"),
        ).count()
        assert after == before + 1


# ═══════════════ G) eur_balances deferral regresyonu (R5) ═══════════════


class TestEurBalancesDeferral:
    """Ötelenen çek/kredi/KK kalemi /cash-flow/eur-balances aylık toplamında ESKİ ayda
    değil YENİ ayda görünür (R5: ham tablolar deferral_map ile hizalanır). Runway zaten
    FE üzerinden deferral'lı — iki görünüm aynı tarihi göstermeli."""

    @staticmethod
    def _monthly_expenses(db):
        from app.routers.finance.cash_flow.eur_balances import compute_eur_balances
        monthly = compute_eur_balances(db)["monthly"]
        return {k: v["expense_eur"] for k, v in monthly.items()}

    def _seed(self, db):
        _mk_rate(db, MIN_DATE, 50.0)
        acc = _mk_account(db, bank_name="Deferral Test Bankası")
        db.add(BankTransaction(
            account_id=acc.id, date=TODAY, amount=100000, balance=100000,
            type="income", description="AÇILIŞ", tx_hash=f"defer-seed-{uuid4().hex}",
        ))
        db.flush()
        return acc

    def test_deferred_check_appears_in_new_month(self, db):
        self._seed(db)
        natural = _plus_months(TODAY, 1)
        deferred = _plus_months(TODAY, 2)
        k_old, k_new = natural.strftime("%Y-%m"), deferred.strftime("%Y-%m")

        base = self._monthly_expenses(db)
        check = _mk_check(db, due_date=natural, amount=50000.0)  # 1000 EUR @50
        deferral_service.apply_deferral(db, "check", check.id, deferred, user_id=None)
        db.flush()

        after = self._monthly_expenses(db)
        assert after.get(k_old, 0) - base.get(k_old, 0) == pytest.approx(0, abs=0.05), \
            "ötelenen çek ESKİ ayda görünmemeli"
        assert after.get(k_new, 0) - base.get(k_new, 0) == pytest.approx(1000, abs=0.05), \
            "ötelenen çek YENİ ayda görünmeli"

    def test_deferred_credit_appears_in_new_month(self, db):
        self._seed(db)
        natural = _plus_months(TODAY, 1)
        deferred = _plus_months(TODAY, 2)
        k_old, k_new = natural.strftime("%Y-%m"), deferred.strftime("%Y-%m")

        base = self._monthly_expenses(db)
        product, payment = _mk_credit_payment(db, due_date=natural, amount=50000.0)
        deferral_service.apply_deferral(db, "credit", payment.id, deferred, user_id=None)
        db.flush()

        after = self._monthly_expenses(db)
        assert after.get(k_old, 0) - base.get(k_old, 0) == pytest.approx(0, abs=0.05)
        assert after.get(k_new, 0) - base.get(k_new, 0) == pytest.approx(1000, abs=0.05)

    def test_deferred_cc_statement_appears_in_new_month(self, db):
        self._seed(db)
        natural = _plus_months(TODAY, 1)
        deferred = _plus_months(TODAY, 2)
        k_old, k_new = natural.strftime("%Y-%m"), deferred.strftime("%Y-%m")

        base = self._monthly_expenses(db)
        prod, stmt = _mk_cc_statement(
            db, toplam_borc=50000.0, kesim=natural - timedelta(days=15),
            son_odeme=natural, limit=0.0,  # limitsiz → cc-projeksiyon rezerv gürültüsü yok
        )
        deferral_service.apply_deferral(db, "cc_payment", stmt.id, deferred, user_id=None)
        db.flush()

        after = self._monthly_expenses(db)
        assert after.get(k_old, 0) - base.get(k_old, 0) == pytest.approx(0, abs=0.05)
        assert after.get(k_new, 0) - base.get(k_new, 0) == pytest.approx(1000, abs=0.05)

    def test_deferred_check_same_date_in_runway_and_eur_balances(self, client, auth_headers, db):
        """Runway (FE-tabanlı, zaten deferral'lı) ile eur-balances (ham tablo + R5 haritası)
        AYNI ötelenmiş tarihi/ayı gösterir."""
        if (TODAY + timedelta(days=8)).month != TODAY.month:
            pytest.skip("ay sonuna çok yakın — ay-içi öteleme penceresi kurulamıyor")
        from app.routers.finance.cash_flow.eur_balances import compute_eur_balances

        self._seed(db)
        natural = TODAY + timedelta(days=2)
        deferred = TODAY + timedelta(days=8)

        base_daily = compute_eur_balances(db)["daily"]
        base_nat = base_daily.get(str(natural), {}).get("expense_eur", 0)
        base_def = base_daily.get(str(deferred), {}).get("expense_eur", 0)

        check = _mk_check(db, due_date=natural, amount=50000.0)
        deferral_service.apply_deferral(db, "check", check.id, deferred, user_id=None)
        finance_event_svc.upsert_check(db, check)  # FE event_date → ötelenmiş tarih (override)
        db.commit()

        # Runway: kalem ötelenmiş tarihte, deferred bayraklı, doğal vade original_date'te
        body = client.get(f"{API}/runway", headers=auth_headers).json()
        item = next((i for i in body["outs"] if i["id"] == f"check:{check.id}"), None)
        assert item is not None, "ötelenen çek runway outs'ta yok"
        assert item["date"] == deferred.isoformat()
        assert item["deferred"] is True
        assert item["original_date"] == natural.isoformat()

        # eur-balances: gider AYNI ötelenmiş günde; doğal günde değil
        daily = compute_eur_balances(db)["daily"]
        got_def = daily.get(str(deferred), {}).get("expense_eur", 0) - base_def
        got_nat = daily.get(str(natural), {}).get("expense_eur", 0) - base_nat
        assert got_def == pytest.approx(1000, abs=0.05)
        assert got_nat == pytest.approx(0, abs=0.05)


# ═══════════════ H) VakıfBank importu → post-ingest zinciri ═══════════════


class _FakeVBClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def fetch_account_transactions(self, account_no, start, end):
        self.calls.append((account_no, start, end))
        return self.rows


class TestVakifbankPostIngest:
    API = "/api/finance/vakifbank"

    def _setup(self, db, monkeypatch, rows):
        acc = _mk_account(db, bank_name="VakıfBank", account_no="00158000000000901")
        db.commit()
        fake = _FakeVBClient(rows)
        monkeypatch.setattr("app.routers.finance.vakifbank.vakifbank_configured", lambda: True)
        monkeypatch.setattr("app.routers.finance.vakifbank.get_vakifbank_client", lambda: fake)
        return acc, fake

    def test_sync_new_transactions_trigger_matching(self, client, auth_headers, db, monkeypatch):
        """API'den gelen yeni işlem, ekstre yolundaki gibi run_post_ingest_processing'den
        geçer: bekleyen çek + eşleşen tutar → çek 'paid' olur."""
        check = _mk_check(db, due_date=TODAY, amount=50000.0)
        db.flush()
        rows = [{
            "date": TODAY, "amount": -50000.0, "balance": 50000.0,
            "description": f"CEK NO {check.check_no} ODEMESI",
            "type": "expense", "receipt_no": "VB-TEST-1",
        }]
        acc, fake = self._setup(db, monkeypatch, rows)

        resp = client.post(f"{self.API}/sync", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["new_transactions"] == 1
        assert body.get("checks_matched") == 1  # post-ingest koştu
        assert fake.calls and fake.calls[0][0] == "00158000000000901"

        db.expire_all()
        c = db.get(Check, check.id)
        assert c.status == "paid"
        assert c.bank_transaction_id is not None

    def test_post_ingest_skipped_when_no_new_transactions(self, client, auth_headers, db, monkeypatch):
        """Dedup tüm satırları atlarsa (yeni işlem yok) post-ingest ÇAĞRILMAZ."""
        rows = [{
            "date": TODAY, "amount": -123.45, "balance": 999.0,
            "description": "EFT GIDEN", "type": "expense", "receipt_no": "VB-TEST-2",
        }]
        acc, fake = self._setup(db, monkeypatch, rows)

        calls = {"n": 0}

        def _counting_post_ingest(db_arg):
            calls["n"] += 1
            return {}

        # run_vakifbank_import fonksiyon içinde import eder → kaynak modülü patch'le
        monkeypatch.setattr(
            "app.utils.matching_service.run_post_ingest_processing", _counting_post_ingest,
        )

        r1 = client.post(f"{self.API}/sync", headers=auth_headers)
        assert r1.status_code == 200 and r1.json()["new_transactions"] == 1
        assert calls["n"] == 1

        # Aynı satırlar ikinci kez → bakiye-bazlı dedup, yeni işlem yok → post-ingest yok
        r2 = client.post(f"{self.API}/sync", headers=auth_headers)
        assert r2.status_code == 200
        assert r2.json()["new_transactions"] == 0
        assert calls["n"] == 1
