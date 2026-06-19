"""Banka ↔ Kredi Kartı otomatik eşleştirme (banks_cc_match).

Banka ekstresi yüklenince çağrılan `_match_cc_to_bank` eşleştirme mantığını + saf
yardımcıları (son-4-hane çıkarımı, KK-ödemesi açıklama tespiti) doğrular. Audit'te
'testi olmayan finansal modül' (Yüksek) olarak işaretlenmişti.
"""

import json
from datetime import date
from uuid import uuid4

from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_product import CreditProduct
from app.utils.matching_service import (
    _extract_last4_from_desc,
    _get_card_last4,
    _is_cc_payment_desc,
    _match_cc_to_bank,
)


class TestLast4Extraction:
    def test_patterns(self):
        assert _extract_last4_from_desc("K.Kartı Ödeme **** 1028") == "1028"
        assert _extract_last4_from_desc("VISA KART ODEME *1234") == "1234"
        assert _extract_last4_from_desc("KK BORC ODEME ...5678") == "5678"
        assert _extract_last4_from_desc("5400 **** **** 1028") == "1028"

    def test_no_match(self):
        assert _extract_last4_from_desc("Market alışverişi") is None
        assert _extract_last4_from_desc("") is None
        assert _extract_last4_from_desc(None) is None


class TestCcPaymentDesc:
    def test_positive(self):
        assert _is_cc_payment_desc("K.Kartı Ödeme") is True       # "k.kartı"
        assert _is_cc_payment_desc("Mastercard borç ödemesi") is True  # "mastercard"
        assert _is_cc_payment_desc("VISA KART ODEME *1234") is True     # "visa kart" / "kart od"
        assert _is_cc_payment_desc("Kredi Karti Odeme") is True         # "kredi karti" (ASCII)

    def test_negative(self):
        assert _is_cc_payment_desc("Market alışverişi") is False
        assert _is_cc_payment_desc("EFT - tedarikçi ödemesi") is False
        assert _is_cc_payment_desc("") is False
        assert _is_cc_payment_desc(None) is False


class TestGetCardLast4:
    def test_from_details(self):
        p = CreditProduct(type="kredi_karti", name="Test Kart",
                          details=json.dumps({"kart_no_son4": "1028"}))
        assert _get_card_last4(p) == "1028"

    def test_no_details(self):
        assert _get_card_last4(CreditProduct(type="kredi_karti", name="X", details=None)) is None

    def test_invalid_json(self):
        assert _get_card_last4(CreditProduct(type="kredi_karti", name="X", details="{bozuk")) is None


class TestMatchCcToBank:
    @staticmethod
    def _setup(db, *, amount, last4="1028", toplam_borc=5000.0, desc=None):
        prod = CreditProduct(type="kredi_karti", name="İş Bankası Kart",
                             details=json.dumps({"kart_no_son4": last4}))
        db.add(prod)
        db.flush()
        stmt = CreditCardStatement(
            credit_product_id=prod.id, kesim_tarihi=date(2026, 5, 1),
            son_odeme_tarihi=date(2026, 5, 20), toplam_borc=toplam_borc,
            is_paid=False, paid_amount=0,
        )
        acc = BankAccount(bank_name="İş Bankası", iban=f"TR{uuid4().hex}", currency="TRY")
        db.add(acc)
        db.add(stmt)
        db.flush()
        btx = BankTransaction(
            account_id=acc.id, date=date(2026, 5, 18),
            description=desc if desc is not None else f"[Kart Ödemesi] K.Kartı Ödeme 5400 **** **** {last4}",
            amount=-amount, balance=0, type="expense", tx_hash=f"test-cc-{uuid4().hex}",
        )
        db.add(btx)
        db.commit()
        return prod, stmt, btx

    def test_full_match_marks_paid(self, db):
        prod, stmt, btx = self._setup(db, amount=5000.0)
        result = _match_cc_to_bank(db)
        assert result["matched"] == 1
        db.expire_all()
        s = db.get(CreditCardStatement, stmt.id)
        assert s.is_paid is True
        assert float(s.paid_amount) == 5000.0
        b = db.get(BankTransaction, btx.id)
        assert b.payment_method == "kredi_karti"
        assert b.tag_source == "auto"

    def test_partial_payment_not_fully_paid(self, db):
        # Banka ödemesi kalan borçtan az → kısmi, is_paid False kalır
        prod, stmt, btx = self._setup(db, amount=2000.0, toplam_borc=5000.0)
        assert _match_cc_to_bank(db)["matched"] == 1
        db.expire_all()
        s = db.get(CreditCardStatement, stmt.id)
        assert s.is_paid is False
        assert float(s.paid_amount) == 2000.0

    def test_no_match_when_desc_not_cc(self, db):
        prod, stmt, _ = self._setup(db, amount=5000.0, desc="Market alışverişi")
        assert _match_cc_to_bank(db)["matched"] == 0
        db.expire_all()
        assert db.get(CreditCardStatement, stmt.id).is_paid is False

    def test_no_match_when_last4_differs(self, db):
        # Açıklama KK ödemesi ama son-4 ekstreyle eşleşmiyor
        prod, stmt, _ = self._setup(db, amount=5000.0,
                                    desc="[Kart Ödemesi] K.Kartı Ödeme **** 9999")
        assert _match_cc_to_bank(db)["matched"] == 0
        db.expire_all()
        assert db.get(CreditCardStatement, stmt.id).is_paid is False

    def test_already_paid_not_rematched(self, db):
        # Ödenmiş ekstre eşleştirmeye dahil edilmez
        prod, stmt, btx = self._setup(db, amount=5000.0)
        s = db.get(CreditCardStatement, stmt.id)
        s.is_paid = True
        s.paid_amount = 5000.0
        db.commit()
        assert _match_cc_to_bank(db)["matched"] == 0
