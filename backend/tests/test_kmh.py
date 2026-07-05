"""KMH (Kredili Mevduat Hesabı) — ÇEYREKLİK faiz hesabı + nakit akım senkronu.

Banka KMH faizini ÇEYREKLİK tahsil eder (kullanıcı kararı 2026-07-04). `calculate_kmh_status`
period'ları çeyrek çeyrek üretir; `sync_kmh_to_finance_events` YALNIZ mevcut çeyreği nakit
akıma yansıtır — geçmiş çeyrekler bankaca zaten tahsil edildi (gerçek "Faiz Tahakkuku" banka
hareketi asıl kaynak), sistem projeksiyonu da eklenirse ÇİFT SAYIM olur.
"""
import uuid
from datetime import date, timedelta

from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.credit_product import CreditPayment, CreditProduct
from app.utils.kmh_calculator import (
    _next_quarter_first,
    _quarter_first,
    _quarter_last,
    _quarter_num,
    calculate_kmh_status,
    sync_kmh_to_finance_events,
)


class TestQuarterHelpers:
    def test_quarter_first(self):
        assert _quarter_first(date(2026, 2, 15)) == date(2026, 1, 1)    # Q1
        assert _quarter_first(date(2026, 5, 10)) == date(2026, 4, 1)    # Q2
        assert _quarter_first(date(2026, 7, 5)) == date(2026, 7, 1)     # Q3
        assert _quarter_first(date(2026, 12, 31)) == date(2026, 10, 1)  # Q4

    def test_quarter_last(self):
        assert _quarter_last(date(2026, 2, 15)) == date(2026, 3, 31)
        assert _quarter_last(date(2026, 5, 10)) == date(2026, 6, 30)
        assert _quarter_last(date(2026, 8, 1)) == date(2026, 9, 30)
        assert _quarter_last(date(2026, 11, 20)) == date(2026, 12, 31)

    def test_next_quarter_first(self):
        assert _next_quarter_first(date(2026, 2, 15)) == date(2026, 4, 1)
        assert _next_quarter_first(date(2026, 8, 1)) == date(2026, 10, 1)
        assert _next_quarter_first(date(2026, 11, 20)) == date(2027, 1, 1)  # Q4 → sonraki yıl Q1

    def test_quarter_num(self):
        assert _quarter_num(date(2026, 3, 31)) == 1
        assert _quarter_num(date(2026, 6, 30)) == 2
        assert _quarter_num(date(2026, 9, 30)) == 3
        assert _quarter_num(date(2026, 12, 31)) == 4


def _mk_kmh(db, *, negative=True):
    """KMH ürünü + bağlı hesap; negative=True ise mevcut çeyrek başında negatif bakiye."""
    acc = BankAccount(bank_name="Test KMH Bank", iban=f"TR{uuid.uuid4().hex}", currency="TRY")
    db.add(acc)
    db.flush()
    kmh = CreditProduct(
        type="kmh", name="Test KMH", linked_account_id=acc.id,
        total_amount=250000, interest_rate=52, bsmv_rate=5, commission_rate=1.1,
        start_date=date.today() - timedelta(days=200), status="active",
    )
    db.add(kmh)
    db.flush()
    bal = -100000 if negative else 100000
    btx = BankTransaction(
        account_id=acc.id, date=_quarter_first(date.today()), amount=bal, balance=bal,
        type="expense" if negative else "income", tx_hash=f"kmh-{uuid.uuid4().hex}",
        description="KMH test hareketi",
    )
    db.add(btx)
    db.flush()
    return kmh, acc


class TestKmhQuarterly:
    def test_periods_are_quarter_aligned(self, db):
        kmh, _ = _mk_kmh(db)
        st = calculate_kmh_status(kmh, db)
        assert st is not None
        for p in st["periods"]:
            pe = date.fromisoformat(p["period_end"])
            assert pe == _quarter_last(pe)          # her period çeyreğin son gününde biter
            assert "-Ç" in p["month_label"]          # "YYYY-ÇN" çeyrek etiketi
        # Mevcut çeyrek period_end = bu çeyreğin sonu
        cur = st["current_period"]
        assert cur is not None
        assert date.fromisoformat(cur["period_end"]) == _quarter_last(date.today())

    def test_sync_only_current_quarter(self, db):
        # Mevcut çeyrekte negatif bakiye → tek taksit (mevcut çeyrek), geçmiş/gelecek YOK
        kmh, _ = _mk_kmh(db, negative=True)
        sync_kmh_to_finance_events(kmh, db)
        pays = db.query(CreditPayment).filter(CreditPayment.credit_product_id == kmh.id).all()
        assert len(pays) == 1
        assert pays[0].due_date == _quarter_last(date.today())  # mevcut çeyrek sonu
        assert pays[0].is_paid is False
        assert "çeyrek" in (pays[0].notes or "").lower()

    def test_sync_no_payment_when_positive(self, db):
        # Hesap pozitif → adat yok → taksit oluşmaz (mevcut çeyrekte de sıfır tahakkuk)
        kmh, _ = _mk_kmh(db, negative=False)
        sync_kmh_to_finance_events(kmh, db)
        pays = db.query(CreditPayment).filter(CreditPayment.credit_product_id == kmh.id).all()
        assert len(pays) == 0
