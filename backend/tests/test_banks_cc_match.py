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
from app.models.transaction_category import TransactionCategory
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

    def test_masked_pan_anywhere(self):
        # Maskeli PAN açıklamanın ortasında + sonda referans no (mobil/internet havalesi)
        assert _extract_last4_from_desc("Diğer Internet - Mobil INT 650837******7261 3006") == "7261"
        assert _extract_last4_from_desc("Diğer Diğer OTO 650837****7261 GECIKMELI") == "7261"
        # Yıldız (maske) yoksa düz sayı kart sayılmaz → yanlış-pozitif yok
        assert _extract_last4_from_desc("EFT GIDEN HAVALE 3006") is None
        assert _extract_last4_from_desc("MAAS ODEMESI 12345") is None

    def test_written_last4_ile_biten(self):
        # Yazıyla verilen kart son-4'ü (yıldızsız) — QNB Corporate "…{son4} ile biten …" deseni
        assert _extract_last4_from_desc("Kart İşlemleri - 6075 ile biten QNB Corporate ödemesi - Virman") == "6075"
        assert _extract_last4_from_desc("979203 6075 ile biten kart") == "6075"  # önünde başka rakam olsa da son-4
        assert _extract_last4_from_desc("EFT ile biten") is None  # rakam yoksa eşleşmez


class TestCcPaymentDesc:
    def test_positive(self):
        assert _is_cc_payment_desc("K.Kartı Ödeme") is True       # "k.kartı"
        assert _is_cc_payment_desc("Mastercard borç ödemesi") is True  # "mastercard"
        assert _is_cc_payment_desc("VISA KART ODEME *1234") is True     # "visa kart" / "kart od"
        assert _is_cc_payment_desc("Kredi Karti Odeme") is True         # "kredi karti" (ASCII)

    def test_positive_ile_biten_odeme(self):
        # "…{son4} ile biten … ödeme(si)" — QNB Corporate yazılı kart-no ödemesi (kısmi eşleşme için kelime yolu)
        assert _is_cc_payment_desc("Kart İşlemleri - 6075 ile biten QNB Corporate ödemesi - Virman") is True

    def test_negative(self):
        assert _is_cc_payment_desc("Market alışverişi") is False
        assert _is_cc_payment_desc("EFT - tedarikçi ödemesi") is False
        assert _is_cc_payment_desc("") is False
        assert _is_cc_payment_desc(None) is False
        # "ile biten" var ama "ödeme" yok → kart-ödemesi kelimesi sayılmaz (aidat/virman kısmi yanlış-eşleşme olmasın)
        assert _is_cc_payment_desc("6075 ile biten hesaba virman") is False


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


class TestMatchCcNoKeyword:
    """Kelime-yok yolu (2026-07-04): maskeli PAN ile tanıma + YÜKSEK GÜVEN şartı
    (TAM ödeme ≈ ekstre toplamı + ödeme tarihi ekstre penceresinde). Mobil/internet
    havalesiyle yapılan kart ödemeleri açıklamada kart ifadesi taşımaz ama maskeli PAN
    taşır; kelime kapısı kaldırıldı. Aşırı eşleşme (oto-ödeme kartlarındaki bol kısmi/
    farklı-ay borcunun açık ekstrelere yığılması) tam-ödeme + pencere şartıyla engellenir.
    """

    @staticmethod
    def _setup(db, *, amount, btx_date, last4="7261", toplam_borc=100000.0,
               kesim=date(2026, 6, 26), son_odeme=date(2026, 6, 30), desc=None):
        prod = CreditProduct(type="kredi_karti", name="Yapı Kredi World",
                             details=json.dumps({"kart_no_son4": last4}))
        db.add(prod)
        db.flush()
        stmt = CreditCardStatement(
            credit_product_id=prod.id, kesim_tarihi=kesim,
            son_odeme_tarihi=son_odeme, toplam_borc=toplam_borc,
            is_paid=False, paid_amount=0,
        )
        acc = BankAccount(bank_name="Yapı Kredi", iban=f"TR{uuid4().hex}", currency="TRY")
        db.add(acc)
        db.add(stmt)
        db.flush()
        # Varsayılan açıklama: kart ifadesi YOK, maskeli PAN VAR (canlı örnek biçimi)
        btx = BankTransaction(
            account_id=acc.id, date=btx_date,
            description=desc if desc is not None else f"Diğer Internet - Mobil INT 650837******{last4} 3006",
            amount=-amount, balance=0, type="expense", tx_hash=f"test-ccnk-{uuid4().hex}",
        )
        db.add(btx)
        db.commit()
        return prod, stmt, btx

    def test_masked_pan_full_payment_in_window_matches(self, db):
        # Kelime yok ama maskeli PAN + tam ödeme + pencere içi → eşleşir (canlı btx 5722 → stmt 16)
        prod, stmt, btx = self._setup(db, amount=100000.0, btx_date=date(2026, 6, 30))
        assert _match_cc_to_bank(db)["matched"] == 1
        db.expire_all()
        assert db.get(CreditCardStatement, stmt.id).is_paid is True

    def test_slight_overpayment_matches_and_caps(self, db):
        # Ödeme toplamı %2 içinde aşarsa (faiz/masraf) tam ödeme sayılır; paid toplama kırpılır
        prod, stmt, btx = self._setup(db, amount=101500.0, btx_date=date(2026, 6, 30),
                                      toplam_borc=100000.0)  # +%1.5
        assert _match_cc_to_bank(db)["matched"] == 1
        db.expire_all()
        s = db.get(CreditCardStatement, stmt.id)
        assert s.is_paid is True
        assert float(s.paid_amount) == 100000.0  # fazlası banka hareketinde kalır

    def test_overpayment_beyond_tolerance_no_match(self, db):
        # %2'yi aşan fazla ödeme (+%10) tam ödeme sayılmaz → eşleşmez
        prod, stmt, _ = self._setup(db, amount=110000.0, btx_date=date(2026, 6, 30),
                                    toplam_borc=100000.0)
        assert _match_cc_to_bank(db)["matched"] == 0

    def test_partial_no_keyword_does_not_match(self, db):
        # Kelime yok + kısmi ödeme (toplamın çok altında) → aşırı-eşleşme önleme, eşleşmez
        prod, stmt, _ = self._setup(db, amount=30000.0, btx_date=date(2026, 6, 30),
                                    toplam_borc=100000.0)
        assert _match_cc_to_bank(db)["matched"] == 0

    def test_payment_before_kesim_no_match(self, db):
        # Ödeme kesim tarihinden ÖNCE (farklı ay ödemesi) → pencere dışı, eşleşmez (canlı btx 5364)
        prod, stmt, _ = self._setup(db, amount=100000.0, btx_date=date(2026, 6, 1),
                                    kesim=date(2026, 6, 26), son_odeme=date(2026, 6, 30))
        assert _match_cc_to_bank(db)["matched"] == 0

    def test_payment_long_after_due_no_match(self, db):
        # Ödeme son ödemeden çok sonra (grace aşıldı) → pencere dışı, eşleşmez
        prod, stmt, _ = self._setup(db, amount=100000.0, btx_date=date(2026, 8, 15),
                                    kesim=date(2026, 6, 26), son_odeme=date(2026, 6, 30))
        assert _match_cc_to_bank(db)["matched"] == 0

    def test_wrong_card_last4_no_match(self, db):
        # Maskeli PAN var ama bilinen ekstre kartıyla eşleşmiyor → eşleşmez
        prod, stmt, _ = self._setup(db, amount=100000.0, btx_date=date(2026, 6, 30),
                                    last4="7261",
                                    desc="Diğer Internet - Mobil INT 650837******9999 3006")
        assert _match_cc_to_bank(db)["matched"] == 0


class TestMatchCcWrittenLast4:
    """Yazıyla kart-no verilen ödeme deseni (QNB Corporate "…{son4} ile biten … ödemesi - Virman").
    Kelime yolu (partial'a izin verir) → hem TAM (Şubat/Mart) hem KISMİ (Nisan) ödeme eşleşir.
    Canlı bulgu (2026-07-05): QNB *6075 Şub/Mar tam, Nisan kısmi ödemeler eşleşmemişti (matcher
    ne 'kart' kelimesini ne yıldızsız son-4'ü tanıyordu). Ürün details.kart_no_son4='6075'.
    """

    @staticmethod
    def _setup(db, *, amount, toplam_borc, last4="6075",
               kesim=date(2026, 4, 9), son_odeme=date(2026, 4, 14), btx_date=date(2026, 4, 14)):
        prod = CreditProduct(type="kredi_karti", name="QNB Corporate Kart",
                             details=json.dumps({"kart_no_son4": last4}))
        db.add(prod)
        db.flush()
        stmt = CreditCardStatement(
            credit_product_id=prod.id, kesim_tarihi=kesim, son_odeme_tarihi=son_odeme,
            toplam_borc=toplam_borc, is_paid=False, paid_amount=0,
        )
        acc = BankAccount(bank_name="QNB", iban=f"TR{uuid4().hex}", currency="TRY")
        db.add(acc)
        db.add(stmt)
        db.flush()
        btx = BankTransaction(
            account_id=acc.id, date=btx_date,
            description=f"Kart İşlemleri - {last4} ile biten QNB Corporate ödemesi - Virman",
            amount=-amount, balance=0, type="expense", tx_hash=f"test-ccw-{uuid4().hex}",
        )
        db.add(btx)
        db.commit()
        return prod, stmt, btx

    def test_full_payment_matches_and_marks_paid(self, db):
        # Şubat/Mart deseni: birebir tutar → tam eşleşme, is_paid=True
        prod, stmt, btx = self._setup(db, amount=1052051.11, toplam_borc=1052051.11)
        assert _match_cc_to_bank(db)["matched"] == 1
        db.expire_all()
        s = db.get(CreditCardStatement, stmt.id)
        assert s.is_paid is True
        assert float(s.paid_amount) == 1052051.11

    def test_partial_payment_matches_and_reduces(self, db):
        # Nisan deseni: kısmi ödeme (kelime yolu partial'a izin verir) → paid_amount artar, is_paid=False
        prod, stmt, btx = self._setup(db, amount=272000.0, toplam_borc=778215.89)
        assert _match_cc_to_bank(db)["matched"] == 1
        db.expire_all()
        s = db.get(CreditCardStatement, stmt.id)
        assert s.is_paid is False
        assert float(s.paid_amount) == 272000.0

    def test_virman_without_odeme_partial_no_match(self, db):
        # "ile biten" var ama "ödeme" yok (saf virman) → kelime yok → kısmi eşleşmez (güvenlik)
        prod, stmt, btx = self._setup(db, amount=272000.0, toplam_borc=778215.89)
        btx.description = "Kart İşlemleri - 6075 ile biten hesaba virman"
        db.commit()
        assert _match_cc_to_bank(db)["matched"] == 0


class TestAutoTaggedRescan:
    """Auto-tag'lenmiş giderler matcher'dan saklanmaz (2026-07-14 canlı bulgu).

    Orkestratörde auto-tag matcher'lardan ÖNCE koşar; "kart ödemesi" açıklamalı gider
    POS kelime kuralına ("kart ") düşünce eski salt-`category_id IS NULL` filtresi onu
    KK matcher'ından kalıcı saklıyordu → ₺1,9M QNB ödemesi eşleşmedi, ekstre FE'si
    bekleyen kalıp bakiyeyi çift düşürdü. Kural: auto etiket yeniden taranır (KK
    kategorisindekiler hariç — zaten eşleşmiş), manuel etiket kullanıcı kararıdır.
    """

    @staticmethod
    def _get_or_create_cat(db, name):
        cat = db.query(TransactionCategory).filter(TransactionCategory.name == name).first()
        if cat is None:
            cat = TransactionCategory(name=name, color="gray")
            db.add(cat)
            db.flush()
        return cat

    @staticmethod
    def _setup(db, *, amount, toplam_borc, category, tag_source, last4="6075"):
        prod = CreditProduct(type="kredi_karti", name="QNB Corporate",
                             details=json.dumps({"kart_no_son4": last4}))
        db.add(prod)
        db.flush()
        stmt = CreditCardStatement(
            credit_product_id=prod.id, kesim_tarihi=date(2026, 7, 9),
            son_odeme_tarihi=date(2026, 7, 14), toplam_borc=toplam_borc,
            is_paid=False, paid_amount=0,
        )
        acc = BankAccount(bank_name="QNB", iban=f"TR{uuid4().hex}", currency="TRY")
        db.add(acc)
        db.add(stmt)
        db.flush()
        # Canlı biçim: kelime ("kart ödemesi") + maskeli PAN birlikte
        btx = BankTransaction(
            account_id=acc.id, date=date(2026, 7, 13),
            description=f"Kart İşlemleri - CEP_ŞUBE 979203******{last4} nolu kart ödemesi",
            amount=-amount, balance=0, type="expense", tx_hash=f"test-ccat-{uuid4().hex}",
            category_id=category.id if category else None, tag_source=tag_source,
        )
        db.add(btx)
        db.commit()
        return prod, stmt, btx

    def test_auto_tagged_expense_still_matches(self, db):
        # Canlı senaryo (btx 6233): auto-tag POS etiketi vurmuş → matcher yine görmeli
        pos = self._get_or_create_cat(db, "POS")
        prod, stmt, btx = self._setup(db, amount=1909336.13, toplam_borc=1909336.13,
                                      category=pos, tag_source="auto")
        assert _match_cc_to_bank(db)["matched"] == 1
        db.expire_all()
        assert db.get(CreditCardStatement, stmt.id).is_paid is True

    def test_sedna_tagged_expense_still_matches(self, db):
        # Sedna karşı-hesap köprüsü (2026-07-23) etiketi de makine etiketidir — köprü
        # bir KK ödemesini yanlış sınıflarsa matcher yine görebilmeli ('auto' kuralı)
        pos = self._get_or_create_cat(db, "POS")
        prod, stmt, btx = self._setup(db, amount=75000.0, toplam_borc=75000.0,
                                      category=pos, tag_source="sedna")
        assert _match_cc_to_bank(db)["matched"] == 1
        db.expire_all()
        assert db.get(CreditCardStatement, stmt.id).is_paid is True

    def test_manual_tagged_expense_not_touched(self, db):
        # Manuel etiket kullanıcı kararı → matcher dokunmaz
        cari = self._get_or_create_cat(db, "Cari")
        prod, stmt, btx = self._setup(db, amount=50000.0, toplam_borc=50000.0,
                                      category=cari, tag_source="manual")
        assert _match_cc_to_bank(db)["matched"] == 0
        db.expire_all()
        assert db.get(CreditCardStatement, stmt.id).is_paid is False

    def test_already_matched_kk_auto_not_reapplied(self, db):
        # KK kategorili auto etiket = önceki koşuda eşleşmiş ödeme → yeniden taranıp
        # başka açık ekstreye paid_amount mükerrer yazılmasın
        kk = self._get_or_create_cat(db, "Kredi Kartı Borç Ödeme")
        prod, stmt, btx = self._setup(db, amount=50000.0, toplam_borc=50000.0,
                                      category=kk, tag_source="auto")
        assert _match_cc_to_bank(db)["matched"] == 0
        db.expire_all()
        assert db.get(CreditCardStatement, stmt.id).is_paid is False
