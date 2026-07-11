"""Faz 1 eşleştirme testleri (2026-07-11) — iki-eşikli bantlar + öneri kuyruğu +
cari matcher + çapraz-para çek önerisi + 1-N/N-1 gruplar + unmatch + planlı köprü + yarış.

Kapsam:
A) matching_service._match_vendors_to_bank — en temkinli matcher:
   OTOMATİK yalnız [tutar birebir + isim/vendor sinyali + vade ≤7g]; isimsiz → öneri;
   8-14 gün → öneri (isimli bile — VENDOR_AUTO_WINDOW_DAYS zorlaması); >14 gün → hiçbir şey.
B) Öneri yaşam döngüsü — _upsert_suggestion idempotent; cleanup_stale_suggestions;
   GET /cash-flow/match-suggestions şekli + zenginleştirme; accept → gerçek eşleşme;
   kapanmış hedefe accept → 409 + öneri düşer; reject → silinir; avans öneri bandı.
C) Çapraz-para çek önerisi — EUR çek × ledger_rate ±%1 TL bandı → YALNIZ öneri (skor 40);
   bant dışı → öneri yok.
D) 1-N çek — OTOMATİK grup (aynı vendor_code + vade ±2g, toplam ±0.02) +
   POST /cash-flow/match-checks-batch (manuel; yanlış toplam/uygunsuz çek → 400).
E) Kredi N-1 grup izi — ortak match_number TÜM banka satırlarında + satır başına
   event_matches izi (Faz 1 #10; dünkü 'yalnız ilk satır' davranışı değişti).
F) Geri alma — POST /cash-flow/unmatch-check + /cash-flow/unmatch-credit-payment
   (grup çözme + anapara iadesi) + 400/404 yolları.
G) Planlı gider köprüsü — 'Vergi/SGK' etiketi tek açık tax girişini banka kanıtıyla
   kapatır (çift sayım biter); iki aday → öneri; accept ile kapanış.
H) Yarış korumaları — apply_check_bank_match eşleşmiş çeke False; match-vendor-tx
   eşleşmiş vtx'e 409.

Dış servislere (Sedna/banka API) bağlanılmaz.
"""

import itertools
from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.models.advance import Advance
from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.check import Check, CheckUpload
from app.models.credit_product import CreditPayment, CreditProduct
from app.models.event_match import MATCH_METHOD_SUGGESTION, EventMatch
from app.models.exchange_rate import ExchangeRate
from app.models.finance_event import FinanceEvent
from app.models.scheduled import ScheduledDefinition, ScheduledEntry
from app.models.transaction_category import TransactionCategory
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.models.vendor_upload import VendorUpload
from app.utils.finance_event_service import finance_event_svc
from app.utils.matching_service import (
    _match_advances_to_bank,
    _match_checks_to_bank,
    _match_credits_to_bank,
    _match_vendors_to_bank,
    _upsert_suggestion,
    apply_check_bank_match,
    cleanup_stale_suggestions,
)
from app.utils.sync_vendor_fifo import sync_vendor_finance_events

API = "/api/finance/cash-flow"
TAGS_API = "/api/finance/tags"
TODAY = date.today()

_SEQ = itertools.count(988001)


# ─────────────────────────── Yardımcılar ───────────────────────────


def _mk_account(db, *, bank_name="Faz1 Test Bankası", currency="TRY"):
    acc = BankAccount(
        bank_name=bank_name, iban=f"TR{uuid4().hex}"[:34], currency=currency,
        is_active=True,
    )
    db.add(acc)
    db.flush()
    return acc


def _mk_btx(db, acc, *, amount, tx_date=None, desc="FAZ1 HAREKETİ", ttype=None):
    btx = BankTransaction(
        account_id=acc.id, date=tx_date or TODAY, description=desc,
        amount=amount, balance=0,
        type=ttype or ("expense" if amount < 0 else "income"),
        tx_hash=f"faz1-{uuid4().hex}",
    )
    db.add(btx)
    db.flush()
    return btx


def _mk_vendor_invoice(db, *, alacak, due, name=None, sync=True):
    """Cari + açık ALACAK faturası (payment_due_date'li). sync=True → vendor_payment FE üretilir."""
    n = next(_SEQ)
    up = VendorUpload(file_name="seed", file_url="x")
    db.add(up)
    db.flush()
    vendor = Vendor(hesap_kodu=f"320.F{n}", hesap_adi=name or f"FAZBIR DENEME FIRMASI {n}")
    db.add(vendor)
    db.flush()
    vtx = VendorTransaction(
        vendor_id=vendor.id, upload_id=up.id, date=due - timedelta(days=30),
        evrak_no=f"FZE{n}", alacak=alacak, borc=0,
        payment_due_date=due, tx_hash=f"faz1-vtx-{uuid4().hex}",
    )
    db.add(vtx)
    db.flush()
    if sync:
        sync_vendor_finance_events(db)
        db.flush()
    return vendor, vtx


def _mk_check(db, *, due_date, amount_tl, amount_currency=None, currency="TL",
              check_no=None, vendor_code=None, status="pending",
              vendor_name="FAZ1 ÇEK FİRMASI"):
    up = CheckUpload(file_name="seed", file_url="x")
    db.add(up)
    db.flush()
    check = Check(
        upload_id=up.id, check_no=check_no or str(8800000 + next(_SEQ)),
        vendor_code=vendor_code, vendor_name=vendor_name, due_date=due_date,
        amount_tl=amount_tl,
        amount_currency=amount_currency if amount_currency is not None else amount_tl,
        currency=currency, status=status,
    )
    db.add(check)
    db.flush()
    return check


def _mk_credit_payment(db, *, due_date, amount=10000.0, bank_name="Faz1 Kredi Bankası",
                       currency="TRY", principal=None):
    product = CreditProduct(
        type="taksitli", name=f"FAZ1 KREDİ {next(_SEQ)}",
        bank_name=bank_name, currency=currency,
        total_amount=amount, remaining_amount=amount, status="active",
    )
    db.add(product)
    db.flush()
    payment = CreditPayment(
        credit_product_id=product.id, installment_no=1,
        due_date=due_date, amount=amount, principal=principal, is_paid=False,
    )
    db.add(payment)
    db.flush()
    return product, payment


def _mk_tax_entry(db, *, amount, on=None, source_type="tax", description=None):
    on = on or TODAY
    defn = ScheduledDefinition(
        source_type=source_type, name=f"FAZ1 VERGİ {next(_SEQ)}",
        amount=amount, year=on.year, frequency="monthly",
        payment_day=min(on.day, 28), start_month=1,
    )
    db.add(defn)
    db.flush()
    entry = ScheduledEntry(
        definition_id=defn.id, source_type=source_type, entry_date=on,
        period_month=on.month, period_year=on.year, amount=amount,
        currency="TRY", description=description or f"FAZ1 vergi girişi {defn.id}",
        is_paid=False,
    )
    db.add(entry)
    db.flush()
    return defn, entry


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


def _suggestions(db, *, target_type=None, target_id=None, bank_id=None):
    q = db.query(EventMatch).filter(EventMatch.method == MATCH_METHOD_SUGGESTION)
    if target_type is not None:
        q = q.filter(EventMatch.target_source_type == target_type)
    if target_id is not None:
        q = q.filter(EventMatch.target_source_id == target_id)
    if bank_id is not None:
        q = q.filter(EventMatch.bank_source_id == bank_id)
    return q.all()


def _traces(db, *, target_type, target_id):
    """Öneri OLMAYAN (gerçek eşleşme) event_matches izleri."""
    return (db.query(EventMatch)
            .filter(EventMatch.target_source_type == target_type,
                    EventMatch.target_source_id == target_id,
                    EventMatch.method != MATCH_METHOD_SUGGESTION)
            .all())


def _ensure_category(db, name, color="#0F766E"):
    cat = db.query(TransactionCategory).filter(TransactionCategory.name == name).first()
    if not cat:
        cat = TransactionCategory(name=name, color=color, sort_order=991)
        db.add(cat)
        db.flush()
    return cat


# ═══════════════ A) _match_vendors_to_bank — cari matcher ═══════════════


class TestVendorMatcher:
    def test_auto_match_amount_name_same_day(self, db):
        """Tutar birebir + cari adı açıklamada + aynı gün → OTOMATİK eşleşir:
        vtx.match_number dolu, btx aynı numara, EventMatch method='auto',
        vendor_payment FE is_matched=False KALIR (cari kuralı)."""
        acc = _mk_account(db)
        vendor, vtx = _mk_vendor_invoice(db, alacak=15750.0, due=TODAY,
                                         name="PANDORA GIDA PAZARLAMA")
        btx = _mk_btx(db, acc, amount=-15750.0, tx_date=TODAY,
                      desc="PANDORA GIDA EFT ODEMESI")
        db.commit()

        res = _match_vendors_to_bank(db)
        assert res["matched"] == 1
        assert res["suggested"] == 0

        db.expire_all()
        v = db.get(VendorTransaction, vtx.id)
        b = db.get(BankTransaction, btx.id)
        assert v.match_number is not None
        assert b.match_number == v.match_number
        assert v.payment_method == b.payment_method == "havale_eft"

        trace = _traces(db, target_type="vendor_payment", target_id=vtx.id)
        assert len(trace) == 1
        assert trace[0].method == "auto"
        assert trace[0].bank_source_id == btx.id
        assert trace[0].match_number == v.match_number
        assert trace[0].score >= 80

        # Cari kuralı: eşleşme cari FE'sini GİZLEMEZ (FIFO açık kaldıkça görünür)
        fe = _fe(db, "vendor_payment", vtx.id)
        assert fe is not None
        assert fe.is_matched is False

        # Banka FE'sine sync_tag yansıdı ama is_matched değişmedi
        bank_fe = _fe(db, "bank", btx.id)
        assert bank_fe is not None
        assert bank_fe.match_number == v.match_number
        assert bank_fe.is_matched is False

    def test_no_name_signal_gives_suggestion_not_auto(self, db):
        """İsim/vendor sinyali YOK → tutar+gün uysa da otomatik DEĞİL, öneri
        (skor 70 → 50-79 bandı)."""
        acc = _mk_account(db)
        vendor, vtx = _mk_vendor_invoice(db, alacak=8200.0, due=TODAY)
        btx = _mk_btx(db, acc, amount=-8200.0, tx_date=TODAY,
                      desc="GIDEN EFT ODEMESI")
        db.commit()

        res = _match_vendors_to_bank(db)
        assert res["matched"] == 0
        assert res["suggested"] == 1

        db.expire_all()
        assert db.get(VendorTransaction, vtx.id).match_number is None
        assert db.get(BankTransaction, btx.id).match_number is None

        sugs = _suggestions(db, target_type="vendor_payment", target_id=vtx.id)
        assert len(sugs) == 1
        assert sugs[0].bank_source_id == btx.id
        assert 50 <= sugs[0].score < 80

    def test_btx_vendor_id_counts_as_signal(self, db):
        """Auto-tagger'ın btx'e atadığı vendor_id isim sinyali yerine geçer → otomatik."""
        acc = _mk_account(db)
        vendor, vtx = _mk_vendor_invoice(db, alacak=4300.0, due=TODAY)
        btx = _mk_btx(db, acc, amount=-4300.0, tx_date=TODAY,
                      desc="GIDEN EFT ODEMESI")
        btx.vendor_id = vendor.id  # auto_tagger sinyali
        db.commit()

        res = _match_vendors_to_bank(db)
        assert res["matched"] == 1

        db.expire_all()
        assert db.get(VendorTransaction, vtx.id).match_number is not None

    def test_wide_window_8_14_days_suggestion_even_with_name(self, db):
        """8-14 gün penceresi → isim sinyali olsa bile ÖNERİ (otomatik pencere ±7 gün)."""
        acc = _mk_account(db)
        vendor, vtx = _mk_vendor_invoice(db, alacak=6600.0, due=TODAY,
                                         name="MARTI YAPI MALZEMELERI")
        btx = _mk_btx(db, acc, amount=-6600.0, tx_date=TODAY + timedelta(days=10),
                      desc="MARTI YAPI EFT ODEMESI")
        db.commit()

        res = _match_vendors_to_bank(db)
        assert res["matched"] == 0
        assert res["suggested"] == 1

        db.expire_all()
        assert db.get(VendorTransaction, vtx.id).match_number is None
        sugs = _suggestions(db, target_type="vendor_payment", target_id=vtx.id)
        assert len(sugs) == 1

    def test_beyond_14_days_nothing(self, db):
        """>14 gün → ne otomatik ne öneri."""
        acc = _mk_account(db)
        vendor, vtx = _mk_vendor_invoice(db, alacak=5400.0, due=TODAY,
                                         name="KARDELEN AMBALAJ URUNLERI")
        _mk_btx(db, acc, amount=-5400.0, tx_date=TODAY + timedelta(days=16),
                desc="KARDELEN AMBALAJ EFT ODEMESI")
        db.commit()

        res = _match_vendors_to_bank(db)
        assert res["matched"] == 0
        assert res.get("suggested", 0) == 0

        db.expire_all()
        assert db.get(VendorTransaction, vtx.id).match_number is None
        assert _suggestions(db, target_type="vendor_payment", target_id=vtx.id) == []


# ═══════════════ B) Öneri yaşam döngüsü ═══════════════


class TestSuggestionLifecycle:
    def test_upsert_suggestion_idempotent(self, db):
        """Aynı (banka, hedef) çifti ikinci kez önerilince yeni satır AÇILMAZ, skor güncellenir."""
        acc = _mk_account(db)
        check = _mk_check(db, due_date=TODAY, amount_tl=1234.0)
        btx = _mk_btx(db, acc, amount=-1234.0)
        db.flush()

        _upsert_suggestion(db, btx.id, "check", check.id, 1234.0, "TRY", 12)
        _upsert_suggestion(db, btx.id, "check", check.id, 1234.0, "TRY", 18)

        sugs = _suggestions(db, target_type="check", target_id=check.id, bank_id=btx.id)
        assert len(sugs) == 1
        assert sugs[0].score == 18

    def test_cleanup_removes_suggestions_whose_target_closed(self, db):
        """Hedefi kapanan (ödenen çek / eşleşen cari) öneri silinir; açık hedef kalır."""
        acc = _mk_account(db)
        btx1 = _mk_btx(db, acc, amount=-100.0)
        btx2 = _mk_btx(db, acc, amount=-200.0)
        btx3 = _mk_btx(db, acc, amount=-300.0)

        paid_check = _mk_check(db, due_date=TODAY, amount_tl=100.0)
        vendor, vtx = _mk_vendor_invoice(db, alacak=200.0, due=TODAY, sync=False)
        open_check = _mk_check(db, due_date=TODAY, amount_tl=300.0)
        db.flush()

        _upsert_suggestion(db, btx1.id, "check", paid_check.id, 100.0, "TRY", 10)
        _upsert_suggestion(db, btx2.id, "vendor_payment", vtx.id, 200.0, "TRY", 60)
        _upsert_suggestion(db, btx3.id, "check", open_check.id, 300.0, "TRY", 10)

        # Hedefleri kapat
        paid_check.status = "paid"
        vtx.match_number = 111111
        db.flush()

        removed = cleanup_stale_suggestions(db)
        assert removed == 2
        assert _suggestions(db, target_type="check", target_id=paid_check.id) == []
        assert _suggestions(db, target_type="vendor_payment", target_id=vtx.id) == []
        assert len(_suggestions(db, target_type="check", target_id=open_check.id)) == 1

    def test_list_suggestions_shape_and_enrichment(self, client, auth_headers, db):
        """GET /match-suggestions: pagination şekli + check/vendor/scheduled türlerinde
        target_description zenginleştirmesi dolu."""
        acc = _mk_account(db)
        check = _mk_check(db, due_date=TODAY, amount_tl=500.0,
                          vendor_name="ZENGINLESTIRME ÇEK FİRMASI")
        vendor, vtx = _mk_vendor_invoice(db, alacak=600.0, due=TODAY, sync=False,
                                         name="ZENGINLESTIRME CARI FIRMASI")
        defn, entry = _mk_tax_entry(db, amount=700.0, description="Temmuz KDV tahakkuku")
        btx_c = _mk_btx(db, acc, amount=-500.0, desc="ÇEK ADAYI")
        btx_v = _mk_btx(db, acc, amount=-600.0, desc="CARİ ADAYI")
        btx_s = _mk_btx(db, acc, amount=-700.0, desc="VERGİ ADAYI")
        db.flush()

        _upsert_suggestion(db, btx_c.id, "check", check.id, 500.0, "TRY", 15)
        _upsert_suggestion(db, btx_v.id, "vendor_payment", vtx.id, 600.0, "TRY", 60)
        _upsert_suggestion(db, btx_s.id, "tax", entry.id, 700.0, "TRY", 50)
        db.commit()

        resp = client.get(f"{API}/match-suggestions", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        for key in ("items", "total", "page", "page_size", "pages"):
            assert key in body
        assert body["total"] >= 3

        by_target = {(i["target_source_type"], i["target_source_id"]): i
                     for i in body["items"]}

        it_c = by_target[("check", check.id)]
        assert check.check_no in it_c["target_description"]
        assert "ZENGINLESTIRME ÇEK FİRMASI" in it_c["target_description"]
        assert it_c["bank_transaction_id"] == btx_c.id
        assert it_c["bank_description"] == "ÇEK ADAYI"
        assert it_c["bank_date"] == TODAY.isoformat()
        assert it_c["amount"] == 500.0
        assert it_c["currency"] == "TRY"
        assert it_c["target_date"] == TODAY.isoformat()

        it_v = by_target[("vendor_payment", vtx.id)]
        assert "ZENGINLESTIRME CARI FIRMASI" in it_v["target_description"]

        it_s = by_target[("tax", entry.id)]
        assert it_s["target_description"] == "Temmuz KDV tahakkuku"
        assert it_s["target_date"] == entry.entry_date.isoformat()

    def test_accept_builds_real_match_and_removes_suggestion(self, client, auth_headers, db):
        """Accept → apply_check_bank_match ile gerçek eşleşme (method='manual' izi)
        + öneri satırı silinir."""
        acc = _mk_account(db)
        check = _mk_check(db, due_date=TODAY, amount_tl=2600.0)
        btx = _mk_btx(db, acc, amount=-2600.0, desc="ÇEK ÖDEME ADAYI")
        db.flush()
        _upsert_suggestion(db, btx.id, "check", check.id, 2600.0, "TRY", 15)
        db.commit()
        sug_id = _suggestions(db, target_type="check", target_id=check.id)[0].id

        resp = client.post(f"{API}/match-suggestions/{sug_id}/accept", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"ok": True, "target_source_type": "check",
                               "target_source_id": check.id}

        db.expire_all()
        c = db.get(Check, check.id)
        assert c.status == "paid"
        assert c.bank_transaction_id == btx.id

        # Öneri düştü; yerine gerçek (manual) iz geldi
        assert _suggestions(db, target_type="check", target_id=check.id) == []
        traces = _traces(db, target_type="check", target_id=check.id)
        assert len(traces) == 1
        assert traces[0].method == "manual"
        assert traces[0].score == 15
        assert traces[0].created_by is not None

        fe = _fe(db, "check", check.id)
        assert fe.is_matched is True
        assert fe.event_status == "paid"

    def test_accept_closed_target_409_and_suggestion_removed(self, client, auth_headers, db):
        """Hedef bu arada kapanmışsa accept 409 döner ve öneri silinmiş olur."""
        acc = _mk_account(db)
        check = _mk_check(db, due_date=TODAY, amount_tl=990.0)
        btx = _mk_btx(db, acc, amount=-990.0)
        db.flush()
        _upsert_suggestion(db, btx.id, "check", check.id, 990.0, "TRY", 15)
        check.status = "paid"  # hedef başka yoldan kapandı
        db.commit()
        sug_id = _suggestions(db, target_type="check", target_id=check.id)[0].id

        resp = client.post(f"{API}/match-suggestions/{sug_id}/accept", headers=auth_headers)
        assert resp.status_code == 409

        db.expire_all()
        assert db.query(EventMatch).filter(EventMatch.id == sug_id).first() is None
        assert db.get(Check, check.id).bank_transaction_id is None  # eşleşme kurulmadı

    def test_reject_removes_suggestion(self, client, auth_headers, db):
        acc = _mk_account(db)
        check = _mk_check(db, due_date=TODAY, amount_tl=770.0)
        btx = _mk_btx(db, acc, amount=-770.0)
        db.flush()
        _upsert_suggestion(db, btx.id, "check", check.id, 770.0, "TRY", 15)
        db.commit()
        sug_id = _suggestions(db, target_type="check", target_id=check.id)[0].id

        resp = client.post(f"{API}/match-suggestions/{sug_id}/reject", headers=auth_headers)
        assert resp.status_code == 200
        assert db.query(EventMatch).filter(EventMatch.id == sug_id).first() is None
        # Çek dokunulmadan bekliyor
        db.expire_all()
        assert db.get(Check, check.id).status == "pending"

    def test_accept_reject_404_unknown_suggestion(self, client, auth_headers):
        assert client.post(f"{API}/match-suggestions/99999999/accept",
                           headers=auth_headers).status_code == 404
        assert client.post(f"{API}/match-suggestions/99999999/reject",
                           headers=auth_headers).status_code == 404

    def test_advance_matcher_mid_band_writes_suggestion(self, db):
        """Avans öneri bandı: isimsiz + 9 gün geç gelen aynı tutarlı havale
        (skor 15 → 8-19 bandı) otomatik EŞLEŞMEZ, öneri yazılır."""
        acc = _mk_account(db, currency="TRY")
        adv = Advance(agency_name="FAZBIR SEYAHAT ACENTESI", amount=2500.0,
                      currency="TRY", advance_date=TODAY, status="pending")
        db.add(adv)
        db.flush()
        btx = _mk_btx(db, acc, amount=2500.0, tx_date=TODAY + timedelta(days=9),
                      desc="GELEN HAVALE", ttype="income")
        db.commit()

        res = _match_advances_to_bank(db)
        assert res["matched"] == 0

        db.expire_all()
        a = db.get(Advance, adv.id)
        assert a.status == "pending"
        assert a.bank_transaction_id is None
        sugs = _suggestions(db, target_type="advance", target_id=adv.id)
        assert len(sugs) == 1
        assert sugs[0].bank_source_id == btx.id
        assert 8 <= sugs[0].score < 20


# ═══════════════ C) Çapraz-para çek önerisi ═══════════════


class TestCrossCurrencyCheckSuggestion:
    def test_eur_check_tl_expense_in_band_creates_suggestion_only(self, db):
        """EUR çek + defter kuru bandındaki (±%1) TL gider → YALNIZ öneri (skor 40);
        çek pending kalır, otomatik eşleşme kurulmaz."""
        _mk_rate(db, TODAY - timedelta(days=1), 50.0, code="EUR")  # ledger_rate(TODAY) = 50
        acc = _mk_account(db, currency="TRY")
        check = _mk_check(db, due_date=TODAY, amount_tl=49000.0,
                          amount_currency=1000.0, currency="EUR")
        btx = _mk_btx(db, acc, amount=-50250.0, tx_date=TODAY,
                      desc="YURTDISI TRANSFER")  # beklenen 50.000 ±%1 içinde
        db.commit()

        res = _match_checks_to_bank(db)
        assert res["matched"] == 0

        db.expire_all()
        c = db.get(Check, check.id)
        assert c.status == "pending"
        assert c.bank_transaction_id is None

        sugs = _suggestions(db, target_type="check", target_id=check.id)
        assert len(sugs) == 1
        assert sugs[0].bank_source_id == btx.id
        assert sugs[0].score == 40
        assert sugs[0].currency == "EUR"
        assert float(sugs[0].amount) == 1000.0

    def test_eur_check_outside_band_no_suggestion(self, db):
        """Bandın dışında (%2 sapma) → öneri oluşmaz."""
        _mk_rate(db, TODAY - timedelta(days=1), 50.0, code="EUR")
        acc = _mk_account(db, currency="TRY")
        check = _mk_check(db, due_date=TODAY, amount_tl=49000.0,
                          amount_currency=1000.0, currency="EUR")
        _mk_btx(db, acc, amount=-51000.0, tx_date=TODAY, desc="YURTDISI TRANSFER")
        db.commit()

        res = _match_checks_to_bank(db)
        assert res["matched"] == 0
        assert _suggestions(db, target_type="check", target_id=check.id) == []
        db.expire_all()
        assert db.get(Check, check.id).status == "pending"


# ═══════════════ D) 1-N çek — otomatik grup + manuel batch ═══════════════


class TestCheckOneToMany:
    def test_auto_group_same_vendor_sum_matches(self, db):
        """Aynı vendor_code + aynı vadeli 2 TL çekin toplamı banka giderine eşit →
        ikisi de paid + AYNI banka hareketine bağlı + event_matches izli."""
        acc = _mk_account(db)
        c1 = _mk_check(db, due_date=TODAY, amount_tl=3000.0, vendor_code="320.GRUP")
        c2 = _mk_check(db, due_date=TODAY, amount_tl=2000.0, vendor_code="320.GRUP")
        btx = _mk_btx(db, acc, amount=-5000.0, tx_date=TODAY, desc="TOPLU EFT")
        db.commit()

        res = _match_checks_to_bank(db)
        assert res["matched"] == 2

        db.expire_all()
        for cid in (c1.id, c2.id):
            c = db.get(Check, cid)
            assert c.status == "paid"
            assert c.bank_transaction_id == btx.id
            fe = _fe(db, "check", cid)
            assert fe.is_matched is True
            traces = _traces(db, target_type="check", target_id=cid)
            assert len(traces) == 1
            assert traces[0].bank_source_id == btx.id
            assert traces[0].method == "auto"

    def test_auto_group_sum_off_no_match(self, db):
        """Toplam banka giderinden saparsa grup kurulmaz — çekler pending kalır."""
        acc = _mk_account(db)
        c1 = _mk_check(db, due_date=TODAY, amount_tl=3000.0, vendor_code="320.GRUPX")
        c2 = _mk_check(db, due_date=TODAY, amount_tl=2000.0, vendor_code="320.GRUPX")
        _mk_btx(db, acc, amount=-5000.75, tx_date=TODAY, desc="TOPLU EFT")
        db.commit()

        assert _match_checks_to_bank(db)["matched"] == 0
        db.expire_all()
        assert db.get(Check, c1.id).status == "pending"
        assert db.get(Check, c2.id).status == "pending"

    def test_manual_batch_success(self, client, auth_headers, db):
        acc = _mk_account(db)
        c1 = _mk_check(db, due_date=TODAY, amount_tl=1200.0)
        c2 = _mk_check(db, due_date=TODAY, amount_tl=800.0)
        btx = _mk_btx(db, acc, amount=-2000.0, desc="İKİ ÇEK TEK EFT")
        db.commit()

        resp = client.post(f"{API}/match-checks-batch", headers=auth_headers, json={
            "bank_transaction_id": btx.id, "check_ids": [c1.id, c2.id],
        })
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"ok": True, "matched_checks": 2}

        db.expire_all()
        for cid in (c1.id, c2.id):
            c = db.get(Check, cid)
            assert c.status == "paid"
            assert c.bank_transaction_id == btx.id
            assert _fe(db, "check", cid).is_matched is True

    def test_manual_batch_wrong_total_400(self, client, auth_headers, db):
        acc = _mk_account(db)
        c1 = _mk_check(db, due_date=TODAY, amount_tl=1200.0)
        c2 = _mk_check(db, due_date=TODAY, amount_tl=800.0)
        btx = _mk_btx(db, acc, amount=-2500.0)
        db.commit()

        resp = client.post(f"{API}/match-checks-batch", headers=auth_headers, json={
            "bank_transaction_id": btx.id, "check_ids": [c1.id, c2.id],
        })
        assert resp.status_code == 400
        assert "Toplam uyuşmuyor" in resp.json()["detail"]
        db.expire_all()
        assert db.get(Check, c1.id).status == "pending"

    def test_manual_batch_ineligible_check_400(self, client, auth_headers, db):
        acc = _mk_account(db)
        c1 = _mk_check(db, due_date=TODAY, amount_tl=1200.0)
        c2 = _mk_check(db, due_date=TODAY, amount_tl=800.0, status="paid")
        btx = _mk_btx(db, acc, amount=-2000.0)
        db.commit()

        resp = client.post(f"{API}/match-checks-batch", headers=auth_headers, json={
            "bank_transaction_id": btx.id, "check_ids": [c1.id, c2.id],
        })
        assert resp.status_code == 400
        assert "uygun değil" in resp.json()["detail"]

    def test_manual_batch_404_and_empty_400(self, client, auth_headers, db):
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-2000.0)
        db.commit()
        assert client.post(f"{API}/match-checks-batch", headers=auth_headers, json={
            "bank_transaction_id": btx.id, "check_ids": [99999999],
        }).status_code == 404
        assert client.post(f"{API}/match-checks-batch", headers=auth_headers, json={
            "bank_transaction_id": btx.id, "check_ids": [],
        }).status_code == 400


# ═══════════════ E) Kredi N-1 grup izi (Faz 1 #10) ═══════════════


class TestCreditGroupTrace:
    def _setup_group(self, db, *, principal=None):
        due = TODAY + timedelta(days=5)
        product, payment = _mk_credit_payment(
            db, due_date=due, amount=10000.0,
            bank_name="Faz1 Grup Bankası", principal=principal,
        )
        acc = _mk_account(db, bank_name="Faz1 Grup Bankası")
        b1 = _mk_btx(db, acc, amount=-9000.0, tx_date=due, desc="KREDİ FAİZ")
        b2 = _mk_btx(db, acc, amount=-1000.0, tx_date=due, desc="KREDİ BSMV")
        finance_event_svc.upsert_credit_payment(db, payment, product)
        db.commit()
        return product, payment, b1, b2

    def test_group_match_stamps_common_number_and_traces_all_rows(self, db):
        """Faiz+vergi 2 satır → taksit kapanır; ortak match_number HER İKİ banka
        satırında; her satır için event_matches izi (target=credit)."""
        product, payment, b1, b2 = self._setup_group(db, principal=4000.0)

        assert _match_credits_to_bank(db)["matched"] == 1

        db.expire_all()
        p = db.get(CreditPayment, payment.id)
        assert p.is_paid is True
        assert p.bank_transaction_id in (b1.id, b2.id)

        tb1 = db.get(BankTransaction, b1.id)
        tb2 = db.get(BankTransaction, b2.id)
        assert tb1.match_number is not None
        assert tb1.match_number == tb2.match_number

        traces = _traces(db, target_type="credit", target_id=payment.id)
        assert len(traces) == 2
        assert {t.bank_source_id for t in traces} == {b1.id, b2.id}
        assert all(t.method == "auto" for t in traces)

        # Anapara düşümü + FE gizleme
        assert float(db.get(CreditProduct, product.id).remaining_amount) == pytest.approx(6000.0)
        assert _fe(db, "credit", payment.id).is_matched is True


# ═══════════════ F) Geri alma — unmatch-check / unmatch-credit-payment ═══════════════


class TestUnmatch:
    def test_unmatch_check_reopens_check_and_clears_traces(self, client, auth_headers, db):
        acc = _mk_account(db)
        check = _mk_check(db, due_date=TODAY, amount_tl=4400.0)
        btx = _mk_btx(db, acc, amount=-4400.0, desc="ÇEK ÖDEMESİ")
        db.flush()
        assert apply_check_bank_match(db, check, btx, method="manual") is True
        db.commit()
        db.expire_all()
        assert db.get(Check, check.id).status == "paid"

        resp = client.post(f"{API}/unmatch-check", headers=auth_headers,
                           json={"check_id": check.id})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"ok": True, "check_id": check.id, "status": "pending"}

        db.expire_all()
        c = db.get(Check, check.id)
        assert c.status == "pending"
        assert c.bank_transaction_id is None

        fe = _fe(db, "check", check.id)
        assert fe.is_matched is False
        assert fe.event_status == "pending"
        assert _traces(db, target_type="check", target_id=check.id) == []
        # Banka hareketi serbest: başka çek bu btx'e bağlı değil
        assert db.query(Check).filter(Check.bank_transaction_id == btx.id).count() == 0

    def test_unmatch_check_400_and_404(self, client, auth_headers, db):
        check = _mk_check(db, due_date=TODAY, amount_tl=100.0)
        db.commit()
        assert client.post(f"{API}/unmatch-check", headers=auth_headers,
                           json={"check_id": check.id}).status_code == 400
        assert client.post(f"{API}/unmatch-check", headers=auth_headers,
                           json={"check_id": 99999999}).status_code == 404

    def test_unmatch_credit_group_releases_all_rows_and_restores_principal(
            self, client, auth_headers, db):
        """N-1 grup çözme: taksit açılır, anapara iade edilir, HER İKİ banka satırının
        match_number'ı temizlenir, event_matches izleri silinir."""
        helper = TestCreditGroupTrace()
        product, payment, b1, b2 = helper._setup_group(db, principal=4000.0)
        assert _match_credits_to_bank(db)["matched"] == 1
        db.commit()
        db.expire_all()
        assert float(db.get(CreditProduct, product.id).remaining_amount) == pytest.approx(6000.0)

        resp = client.post(f"{API}/unmatch-credit-payment", headers=auth_headers,
                           json={"payment_id": payment.id})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert set(body["released_bank_txs"]) == {b1.id, b2.id}

        db.expire_all()
        p = db.get(CreditPayment, payment.id)
        assert p.is_paid is False
        assert p.paid_date is None
        assert p.bank_transaction_id is None
        assert float(db.get(CreditProduct, product.id).remaining_amount) == pytest.approx(10000.0)
        assert db.get(BankTransaction, b1.id).match_number is None
        assert db.get(BankTransaction, b2.id).match_number is None
        assert _traces(db, target_type="credit", target_id=payment.id) == []

        fe = _fe(db, "credit", payment.id)
        assert fe.is_matched is False
        assert fe.event_status == "pending"

    def test_unmatch_credit_400_and_404(self, client, auth_headers, db):
        product, payment = _mk_credit_payment(db, due_date=TODAY, amount=500.0)
        db.commit()
        assert client.post(f"{API}/unmatch-credit-payment", headers=auth_headers,
                           json={"payment_id": payment.id}).status_code == 400
        assert client.post(f"{API}/unmatch-credit-payment", headers=auth_headers,
                           json={"payment_id": 99999999}).status_code == 404


# ═══════════════ G) Planlı gider köprüsü — Vergi/SGK etiketi ═══════════════


class TestScheduledBridge:
    def _tag(self, client, auth_headers, btx, cat):
        return client.patch(f"{TAGS_API}/transactions/{btx.id}", headers=auth_headers,
                            json={"category_id": cat.id, "payment_method": "havale_eft"})

    def test_single_open_entry_closed_via_tagging(self, client, auth_headers, db):
        """'Vergi/SGK' etiketi + uygun TEK açık tax girişi (aynı ay, tutar ±%2) →
        giriş banka kanıtıyla kapanır + FE is_matched=True (çift sayım biter)."""
        cat = _ensure_category(db, "Vergi/SGK")
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-20000.0, tx_date=TODAY, desc="KDV TAHAKKUK ÖDEMESİ")
        defn, entry = _mk_tax_entry(db, amount=20000.0, on=TODAY)
        db.commit()

        resp = self._tag(client, auth_headers, btx, cat)
        assert resp.status_code == 200, resp.text
        assert resp.json()["match_number"] is not None

        db.expire_all()
        e = db.get(ScheduledEntry, entry.id)
        assert e.is_paid is True
        assert e.paid_date == btx.date

        fe = _fe(db, "tax", entry.id)
        assert fe is not None
        assert fe.is_matched is True
        assert fe.is_realized is True
        assert fe.event_status == "paid"

        traces = _traces(db, target_type="tax", target_id=entry.id)
        assert len(traces) == 1
        assert traces[0].bank_source_id == btx.id
        assert traces[0].method == "auto"

    def test_amount_out_of_band_entry_not_closed(self, client, auth_headers, db):
        """Tutar ±%2 dışındaysa giriş aday bile olmaz — açık kalır, öneri de yazılmaz."""
        cat = _ensure_category(db, "Vergi/SGK")
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-20000.0, tx_date=TODAY, desc="KDV ÖDEMESİ")
        defn, entry = _mk_tax_entry(db, amount=25000.0, on=TODAY)
        db.commit()

        assert self._tag(client, auth_headers, btx, cat).status_code == 200
        db.expire_all()
        assert db.get(ScheduledEntry, entry.id).is_paid is False
        assert _suggestions(db, target_type="tax", target_id=entry.id) == []

    def test_two_candidates_become_suggestions_none_closed(self, client, auth_headers, db):
        """İki uygun aday → İKİSİ de öneri olarak yazılır, hiçbiri kapanmaz."""
        cat = _ensure_category(db, "Vergi/SGK")
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-18000.0, tx_date=TODAY, desc="VERGİ ÖDEMESİ")
        defn1, e1 = _mk_tax_entry(db, amount=18000.0, on=TODAY, description="KDV")
        defn2, e2 = _mk_tax_entry(db, amount=18000.0, on=TODAY, description="Muhtasar")
        db.commit()

        assert self._tag(client, auth_headers, btx, cat).status_code == 200

        db.expire_all()
        assert db.get(ScheduledEntry, e1.id).is_paid is False
        assert db.get(ScheduledEntry, e2.id).is_paid is False
        sugs = _suggestions(db, bank_id=btx.id, target_type="tax")
        assert {s.target_source_id for s in sugs} == {e1.id, e2.id}

    def test_accept_scheduled_suggestion_closes_entry(self, client, auth_headers, db):
        """Öneri accept edilince close_entry_via_bank koşar: giriş kapanır + FE gizlenir."""
        cat = _ensure_category(db, "Vergi/SGK")
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-9500.0, tx_date=TODAY, desc="SGK ÖDEMESİ")
        defn1, e1 = _mk_tax_entry(db, amount=9500.0, on=TODAY, description="KDV 1")
        defn2, e2 = _mk_tax_entry(db, amount=9500.0, on=TODAY, description="KDV 2")
        db.commit()
        assert self._tag(client, auth_headers, btx, cat).status_code == 200

        sug = next(s for s in _suggestions(db, bank_id=btx.id, target_type="tax")
                   if s.target_source_id == e1.id)
        resp = client.post(f"{API}/match-suggestions/{sug.id}/accept", headers=auth_headers)
        assert resp.status_code == 200, resp.text

        db.expire_all()
        assert db.get(ScheduledEntry, e1.id).is_paid is True
        assert db.get(ScheduledEntry, e2.id).is_paid is False
        assert _fe(db, "tax", e1.id).is_matched is True
        assert _suggestions(db, target_type="tax", target_id=e1.id) == []


# ═══════════════ H) Yarış korumaları ═══════════════


class TestRaceGuards:
    def test_apply_check_match_false_when_already_matched(self, db):
        """Zaten eşleşmiş çeke apply_check_bank_match False döner; kayıt DEĞİŞMEZ."""
        acc = _mk_account(db)
        check = _mk_check(db, due_date=TODAY, amount_tl=3100.0)
        btx1 = _mk_btx(db, acc, amount=-3100.0, desc="İLK ÖDEME")
        btx2 = _mk_btx(db, acc, amount=-3100.0, desc="İKİNCİ ADAY")
        db.flush()
        assert apply_check_bank_match(db, check, btx1, method="manual") is True
        db.commit()

        assert apply_check_bank_match(db, check, btx2, method="manual") is False

        db.expire_all()
        c = db.get(Check, check.id)
        assert c.status == "paid"
        assert c.bank_transaction_id == btx1.id  # ilk eşleşme korunur
        traces = _traces(db, target_type="check", target_id=check.id)
        assert len(traces) == 1
        assert traces[0].bank_source_id == btx1.id

    def test_match_vendor_tx_409_when_vtx_already_matched(self, client, auth_headers, db):
        """Eşleşmiş (match_number dolu) cari işlemine match-vendor-tx 409 döner."""
        acc = _mk_account(db)
        vendor, vtx = _mk_vendor_invoice(db, alacak=1500.0, due=TODAY, sync=False)
        vtx.match_number = 987654
        btx = _mk_btx(db, acc, amount=-1500.0, desc="EFT ÖDEME")
        db.commit()

        resp = client.post(f"{API}/match-vendor-tx", headers=auth_headers, json={
            "bank_transaction_id": btx.id,
            "vendor_transaction_id": vtx.id,
            "vendor_id": vendor.id,
        })
        assert resp.status_code == 409

        db.expire_all()
        assert db.get(BankTransaction, btx.id).match_number is None  # yan etki yok
        assert db.get(VendorTransaction, vtx.id).match_number == 987654
