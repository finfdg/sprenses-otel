"""Manuel kredi eşleştirmesinde anapara bütünlüğü — ARCH-001 regresyonu (2026-07 denetimi).

KÖK NEDEN: kredi taksitini bankaya bağlayan ÜÇ giriş noktası vardı ama yalnız ikisi
ortak uygulayıcıyı (`matching_service.apply_credit_bank_match`) çağırıyordu:

  1. otomatik matcher        (matching_service._match_credits_to_bank)  → apply_* ✔
  2. öneri-Onayla            (cash_flow/matching.accept_match_suggestion) → apply_* ✔
  3. MANUEL uç               (cash_flow/matching.match_credit_payment)   → ELLE ✗

Manuel uç alanları elle set ediyor, ortak uygulayıcının İKİ işini atlıyordu:
  (a) anapara düşümü  → `product.remaining_amount -= payment.principal`
  (b) yarış koruması  → `is_paid=False AND bank_transaction_id IS NULL` + FOR UPDATE

Geri alma (`unmatch_credit_payment`) ise anaparayı KOŞULSUZ iade ediyordu. Asimetri:
manuel eşleştir (düşmez) → geri al (ekler) → `remaining_amount` her turda KALICI şişer.
Canlıda 33 manuel kredi eşleşmesi vardı; taksit planı olan tek üründe ₺22.963 sapma.

Bu testler üç davranışı sabitler: anapara düşümü · tur simetrisi · çift-eşleştirme guard'ı.
"""

from datetime import date, timedelta
from uuid import uuid4

from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.credit_product import CreditPayment, CreditProduct

API = "/api/finance"
TODAY = date.today()


def _mk_account(db):
    acc = BankAccount(bank_name="ARCH001 Test Bankası", iban=f"TR{uuid4().hex}"[:34],
                      currency="TRY", is_active=True)
    db.add(acc)
    db.flush()
    return acc


def _mk_btx(db, acc, amount, desc="KREDİ TAKSİT ÖDEMESİ"):
    btx = BankTransaction(
        account_id=acc.id, date=TODAY, description=desc, amount=amount, balance=0,
        type="expense" if amount < 0 else "income", tx_hash=f"arch001-{uuid4().hex}",
    )
    db.add(btx)
    db.flush()
    return btx


def _mk_credit(db, *, total=100000.0, principal=8000.0, amount=10000.0):
    """Anaparası TANIMLI taksit — mevcut testlerin helper'ı principal yazmıyordu,
    bu yüzden anapara düşümü hiç egzersiz edilmiyor ve bug testlerden kaçıyordu."""
    product = CreditProduct(
        type="taksitli", name=f"ARCH001 KREDİ {uuid4().hex[:6]}",
        bank_name="ARCH001 Test Bankası", currency="TRY",
        total_amount=total, remaining_amount=total, status="active",
    )
    db.add(product)
    db.flush()
    payment = CreditPayment(
        credit_product_id=product.id, installment_no=1,
        due_date=TODAY + timedelta(days=10), amount=amount,
        principal=principal, is_paid=False,
    )
    db.add(payment)
    db.flush()
    return product, payment


class TestManualMatchDecrementsPrincipal:
    def test_remaining_amount_drops_by_principal(self, client, auth_headers, db):
        acc = _mk_account(db)
        product, payment = _mk_credit(db, total=100000.0, principal=8000.0)
        btx = _mk_btx(db, acc, -10000.0)
        db.commit()

        resp = client.post(f"{API}/cash-flow/match-credit-payment", headers=auth_headers,
                           json={"bank_transaction_id": btx.id, "payment_id": payment.id})
        assert resp.status_code == 200, resp.text

        db.expire_all()
        assert float(db.get(CreditProduct, product.id).remaining_amount) == 92000.0, (
            "manuel eşleştirme anaparayı düşmedi — apply_credit_bank_match atlanıyor (ARCH-001)"
        )

    def test_manual_tagging_still_applied(self, client, auth_headers, db):
        """Ortak uygulayıcıya geçiş manuel yola özgü etiketlemeyi BOZMAMALI."""
        acc = _mk_account(db)
        product, payment = _mk_credit(db)
        btx = _mk_btx(db, acc, -10000.0)
        db.commit()

        client.post(f"{API}/cash-flow/match-credit-payment", headers=auth_headers,
                    json={"bank_transaction_id": btx.id, "payment_id": payment.id})

        db.expire_all()
        b = db.get(BankTransaction, btx.id)
        assert b.tag_source == "manual", "kullanıcı kararı 'auto'ya düşürüldü"
        assert b.tag_note == product.name
        assert b.payment_method == product.type


class TestMatchUnmatchRoundTrip:
    """ARCH-001'in TAM SENARYOSU — asıl para hatası burada oluşuyordu."""

    def test_remaining_amount_unchanged_after_roundtrip(self, client, auth_headers, db):
        acc = _mk_account(db)
        product, payment = _mk_credit(db, total=100000.0, principal=8000.0)
        btx = _mk_btx(db, acc, -10000.0)
        db.commit()
        before = float(db.get(CreditProduct, product.id).remaining_amount)

        r1 = client.post(f"{API}/cash-flow/match-credit-payment", headers=auth_headers,
                         json={"bank_transaction_id": btx.id, "payment_id": payment.id})
        assert r1.status_code == 200, r1.text

        r2 = client.post(f"{API}/cash-flow/unmatch-credit-payment", headers=auth_headers,
                         json={"payment_id": payment.id})
        assert r2.status_code == 200, r2.text

        db.expire_all()
        after = float(db.get(CreditProduct, product.id).remaining_amount)
        assert after == before, (
            f"eşleştir→geri-al turu kalan borcu değiştirdi ({before} → {after}) — "
            "düşülmeyen anapara iade ediliyor (ARCH-001)"
        )

    def test_repeated_roundtrips_do_not_accumulate(self, client, auth_headers, db):
        """Sapma birikimlidir: her tur anaparayı bir kez daha ekliyordu."""
        acc = _mk_account(db)
        product, payment = _mk_credit(db, total=100000.0, principal=8000.0)
        db.commit()
        before = float(db.get(CreditProduct, product.id).remaining_amount)

        for i in range(3):
            btx = _mk_btx(db, acc, -10000.0, desc=f"TAKSİT TUR {i}")
            db.commit()
            assert client.post(f"{API}/cash-flow/match-credit-payment", headers=auth_headers,
                               json={"bank_transaction_id": btx.id,
                                     "payment_id": payment.id}).status_code == 200
            assert client.post(f"{API}/cash-flow/unmatch-credit-payment", headers=auth_headers,
                               json={"payment_id": payment.id}).status_code == 200

        db.expire_all()
        after = float(db.get(CreditProduct, product.id).remaining_amount)
        assert after == before, (
            f"3 tur sonunda kalan borç {before} → {after} (tur başına +anapara birikimi)"
        )


class TestDoubleMatchGuard:
    def test_second_match_returns_409(self, client, auth_headers, db):
        """Guard yokluğu aynı taksitin iki kez eşleştirilmesine izin veriyordu."""
        acc = _mk_account(db)
        product, payment = _mk_credit(db, total=100000.0, principal=8000.0)
        btx1 = _mk_btx(db, acc, -10000.0, desc="İLK ÖDEME")
        btx2 = _mk_btx(db, acc, -10000.0, desc="İKİNCİ ÖDEME")
        db.commit()

        assert client.post(f"{API}/cash-flow/match-credit-payment", headers=auth_headers,
                           json={"bank_transaction_id": btx1.id,
                                 "payment_id": payment.id}).status_code == 200

        r2 = client.post(f"{API}/cash-flow/match-credit-payment", headers=auth_headers,
                         json={"bank_transaction_id": btx2.id, "payment_id": payment.id})
        assert r2.status_code == 409, (
            f"eşleşmiş taksit yeniden eşleşti (HTTP {r2.status_code}) — guard yok (ARCH-001)"
        )

        db.expire_all()
        # Anapara YALNIZ BİR KEZ düşmüş olmalı, ilk eşleşme bozulmamalı
        assert float(db.get(CreditProduct, product.id).remaining_amount) == 92000.0
        assert db.get(CreditPayment, payment.id).bank_transaction_id == btx1.id
