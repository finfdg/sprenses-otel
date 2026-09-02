"""Kredi taksiti geniş-bant ÖNERİ testleri (2026-07-28).

Canlı bulgu: "Eximbank EUR Kredi 2 (375K) — Taksit #1" (vade 20.07.2026, plan
€136.437,50) 24.07'de €136.703,65 ile ödendi (+€127,44 aynı gün iade). Otomatik
matcher iki sert kapıdan geçemedi:
  - tarih farkı 4 gün  → ±3 gün penceresi dışı
  - tutar birebir değil → tutar-anahtarlı index'te HİÇ aday yok
Sonuç: taksit öneri kuyruğuna BİLE düşmeden Panel "Vadesi Geçenler"de kaldı ve
elle eşleştirilmek zorunda kalındı.

Kapsam:
A) Geniş-bant öneri üretimi (gecikme + kuruş farkı) ve bandın sınırları
   (tutar oranı / tarih penceresi / banka / para birimi).
B) Bu yol ASLA otomatik eşleşme kurmaz — skor tavanı CREDIT_AUTO_MIN altında,
   taksit açık kalır, anapara düşülmez.
C) Mevcut otomatik davranış DEĞİŞMEDİ (birebir tutar + aynı gün → auto).
D) `suggested` anahtarı dönüş sözleşmesinde — orkestratör yalnız-öneri koşusunu
   commit edebilsin (eskiden kredi/çek/avans önerileri SAVEPOINT rollback'iyle
   sessizce kayboluyordu).
"""

import itertools
from datetime import date, timedelta
from uuid import uuid4

from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.credit_product import CreditPayment, CreditProduct
from app.models.event_match import MATCH_METHOD_SUGGESTION, EventMatch
from app.services.matching_service import (
    CREDIT_AUTO_MIN,
    CREDIT_SUGGEST_MIN,
    _match_advances_to_bank,
    _match_checks_to_bank,
    _match_credits_to_bank,
)

TODAY = date.today()
_SEQ = itertools.count(771001)

BANK = "Türk Eximbank"
PLAN_AMOUNT = 136437.50     # taksit planındaki tutar
BANK_AMOUNT = -136703.65    # bankadan çıkan gerçek tutar (gecikme faizi/komisyon dahil)


# ─────────────────────────── Yardımcılar ───────────────────────────


def _mk_account(db, *, bank_name=BANK, currency="EUR"):
    acc = BankAccount(
        bank_name=bank_name, iban=f"TR{uuid4().hex}"[:34], currency=currency,
        is_active=True,
    )
    db.add(acc)
    db.flush()
    return acc


def _mk_btx(db, acc, *, amount, tx_date):
    btx = BankTransaction(
        account_id=acc.id, date=tx_date, description="Kredi Ödemesi",
        amount=amount, balance=0,
        type="expense" if amount < 0 else "income",
        tx_hash=f"loose-{uuid4().hex}",
    )
    db.add(btx)
    db.flush()
    return btx


def _mk_installment(db, *, due_date, amount=PLAN_AMOUNT, bank_name=BANK,
                    currency="EUR", principal=125000.0):
    product = CreditProduct(
        type="taksitli_kredi", name=f"EXIM TEST KREDİSİ {next(_SEQ)}",
        bank_name=bank_name, currency=currency,
        total_amount=amount * 3, remaining_amount=amount * 3, status="active",
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


def _suggestions(db, payment_id):
    return (db.query(EventMatch)
            .filter(EventMatch.method == MATCH_METHOD_SUGGESTION,
                    EventMatch.target_source_type == "credit",
                    EventMatch.target_source_id == payment_id)
            .all())


# ═════════════ A) Geniş-bant öneri üretimi + bant sınırları ═════════════


class TestLooseCreditSuggestion:

    def test_late_and_drifted_installment_becomes_suggestion(self, db):
        """CANLI SENARYO: 4 gün geç + €266 fazla ödeme → öneri (eskiden hiçbir şey)."""
        due = TODAY - timedelta(days=8)
        product, payment = _mk_installment(db, due_date=due)
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=BANK_AMOUNT, tx_date=due + timedelta(days=4))

        result = _match_credits_to_bank(db)

        assert result["matched"] == 0, "geniş bant otomatik eşleştirmemeli"
        assert result["suggested"] >= 1

        sug = _suggestions(db, payment.id)
        assert len(sug) == 1
        assert sug[0].bank_source_id == btx.id
        assert sug[0].currency == "EUR"

    def test_loose_suggestion_never_auto_matches(self, db):
        """Skor tavanı yapısal: taksit açık kalır, anapara düşülmez, iz yazılmaz."""
        due = TODAY - timedelta(days=8)
        product, payment = _mk_installment(db, due_date=due)
        acc = _mk_account(db)
        _mk_btx(db, acc, amount=BANK_AMOUNT, tx_date=due + timedelta(days=4))
        remaining_before = float(product.remaining_amount)

        _match_credits_to_bank(db)
        db.refresh(payment)
        db.refresh(product)

        assert payment.is_paid is False
        assert payment.bank_transaction_id is None
        assert float(product.remaining_amount) == remaining_before

        sug = _suggestions(db, payment.id)[0]
        assert CREDIT_SUGGEST_MIN <= sug.score < CREDIT_AUTO_MIN, (
            "geniş-bant skoru otomatik eşiğe ULAŞMAMALI"
        )

    def test_amount_outside_band_no_suggestion(self, db):
        """Oran bandı (0.85–1.15) dışı → öneri yok (gürültü üretme)."""
        due = TODAY - timedelta(days=8)
        _product, payment = _mk_installment(db, due_date=due)
        acc = _mk_account(db)
        _mk_btx(db, acc, amount=-(PLAN_AMOUNT * 1.5), tx_date=due + timedelta(days=4))

        _match_credits_to_bank(db)
        assert _suggestions(db, payment.id) == []

    def test_date_outside_window_no_suggestion(self, db):
        """±15 gün penceresi dışı → öneri yok."""
        due = TODAY - timedelta(days=40)
        _product, payment = _mk_installment(db, due_date=due)
        acc = _mk_account(db)
        _mk_btx(db, acc, amount=BANK_AMOUNT, tx_date=due + timedelta(days=25))

        _match_credits_to_bank(db)
        assert _suggestions(db, payment.id) == []

    def test_different_bank_no_suggestion(self, db):
        """Kredinin taksiti başka bankadan ödenmez → banka adı eşleşmeli."""
        due = TODAY - timedelta(days=8)
        _product, payment = _mk_installment(db, due_date=due)
        acc = _mk_account(db, bank_name="Başka Banka A.Ş.")
        _mk_btx(db, acc, amount=BANK_AMOUNT, tx_date=due + timedelta(days=4))

        _match_credits_to_bank(db)
        assert _suggestions(db, payment.id) == []

    def test_different_currency_no_suggestion(self, db):
        """EUR kredi ↔ TRY hesap: çapraz-para bu yolda kapsam dışı."""
        due = TODAY - timedelta(days=8)
        _product, payment = _mk_installment(db, due_date=due, currency="EUR")
        acc = _mk_account(db, currency="TRY")
        _mk_btx(db, acc, amount=BANK_AMOUNT, tx_date=due + timedelta(days=4))

        _match_credits_to_bank(db)
        assert _suggestions(db, payment.id) == []


# ═════════════ B) Mevcut otomatik davranış korunuyor ═════════════


class TestAutoBehaviourUnchanged:

    def test_exact_amount_same_day_still_auto_matches(self, db):
        """Regresyon: birebir tutar + aynı gün → hâlâ OTOMATİK (öneri değil)."""
        due = TODAY - timedelta(days=2)
        _product, payment = _mk_installment(db, due_date=due)
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-PLAN_AMOUNT, tx_date=due)

        result = _match_credits_to_bank(db)
        db.refresh(payment)

        assert result["matched"] == 1
        assert payment.is_paid is True
        assert payment.bank_transaction_id == btx.id
        assert _suggestions(db, payment.id) == []

    def test_matched_tx_not_offered_to_another_installment(self, db):
        """Bir taksite bağlanan hareket başka taksite önerilmez."""
        due = TODAY - timedelta(days=2)
        _p1, paid = _mk_installment(db, due_date=due)
        acc = _mk_account(db)
        _mk_btx(db, acc, amount=-PLAN_AMOUNT, tx_date=due)
        assert _match_credits_to_bank(db)["matched"] == 1
        db.refresh(paid)

        # Aynı bankada, aynı bant içinde ikinci bir açık taksit
        _p2, other = _mk_installment(db, due_date=due + timedelta(days=1))

        _match_credits_to_bank(db)
        assert _suggestions(db, other.id) == [], "kullanılmış hareket yeniden önerilmemeli"


# ═════════════ C) Dönüş sözleşmesi — orkestratör commit koşulu ═════════════


class TestSuggestedKeyContract:
    """`run_all_matchers` yalnız `matched>0 VEYA suggested>0` ise commit eder.

    Anahtarı DÖNDÜRMEYEN matcher'ın önerileri SAVEPOINT rollback'iyle sessizce
    kayboluyordu — kredi/çek/avans üçü de anahtarı döndürmüyordu.
    """

    def test_credit_matcher_reports_suggested(self, db):
        due = TODAY - timedelta(days=8)
        _product, _payment = _mk_installment(db, due_date=due)
        acc = _mk_account(db)
        _mk_btx(db, acc, amount=BANK_AMOUNT, tx_date=due + timedelta(days=4))

        result = _match_credits_to_bank(db)
        assert result["suggested"] >= 1

    def test_check_matcher_reports_suggested_key(self, db):
        assert "suggested" in _match_checks_to_bank(db)

    def test_advance_matcher_reports_suggested_key(self, db):
        assert "suggested" in _match_advances_to_bank(db)
