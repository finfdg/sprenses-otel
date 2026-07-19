"""Pencere-öncesi tohum bakiyeleri + (date,id) son-bakiye sıralaması testleri (2026-07-19).

Ocak açılış artefaktı düzeltmesi: compute_eur_balances hesapları MIN_DATE öncesi son
bilinen ekstre bakiyesiyle tohumlar (seviye düzeltmesi — akım üretmez); "son bakiye"
tüketicileri (runway._compute_start_eur, mobile dashboard) max(id) yerine (date,id)
sırasını kullanır (backfill'li eski-tarihli satır bayat bakiyeyi "güncel" gösteremez).
"""
from datetime import date, timedelta
from uuid import uuid4

from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.check import Check, CheckUpload
from app.models.exchange_rate import ExchangeRate
from app.routers.finance.cash_flow.eur_balances import compute_eur_balances
from app.routers.finance.cash_flow.runway import _compute_start_eur
from app.utils.finance_helpers import MIN_DATE

TODAY = date.today()
PRE = MIN_DATE - timedelta(days=4)  # pencere-öncesi (2025-12-28)


def _mk_account(db, *, currency="TRY", blocked=0.0):
    acc = BankAccount(
        bank_name=f"Tohum Test Bankası {uuid4().hex[:6]}",
        iban=f"TR{uuid4().hex}"[:34],
        currency=currency, is_active=True,
        blocked_amount=blocked or None,
    )
    db.add(acc)
    db.flush()
    return acc


def _mk_btx(db, acc, *, tx_date, amount, balance, desc="TOHUM TEST"):
    btx = BankTransaction(
        account_id=acc.id, date=tx_date, description=desc,
        amount=amount, balance=balance,
        type="expense" if amount < 0 else "income",
        tx_hash=f"seed-{uuid4().hex}",
    )
    db.add(btx)
    db.flush()
    return btx


def _mk_rate(db, dt, value, code="EUR"):
    db.query(ExchangeRate).filter(
        ExchangeRate.date == dt, ExchangeRate.currency_code == code
    ).delete(synchronize_session=False)
    db.add(ExchangeRate(date=dt, currency_code=code, unit=1,
                        forex_buying=value, forex_selling=value))
    db.flush()


def _daily(db):
    return compute_eur_balances(db)["daily"]


class TestEurBalancesPreWindowSeed:
    def test_seed_carries_pre_window_balance(self, db):
        """Yalnız 2025 satırı olan hesap, pencere-içi ilk günden itibaren devir
        bakiyesiyle toplamda yer alır (0 değil)."""
        _mk_rate(db, MIN_DATE, 50.0)
        seeded = _mk_account(db)
        _mk_btx(db, seeded, tx_date=PRE, amount=100000, balance=100000)
        other = _mk_account(db)
        first_day = MIN_DATE + timedelta(days=5)
        _mk_btx(db, other, tx_date=first_day, amount=10000, balance=10000)

        bal = _daily(db)[str(first_day)]["balance_eur"]
        # 100.000 TL tohum @50 = 2.000 € + diğer hesabın 200 €'su
        assert round(bal) == 2200, f"tohum eksik: {bal}"

    def test_seed_uses_date_id_order_not_max_id(self, db):
        """Sonradan eklenen (yüksek id'li) ESKİ tarihli satır tohumu belirlemez —
        (date,id) son satırı kazanır (canlı hesap 9/10 backfill senaryosu)."""
        _mk_rate(db, MIN_DATE, 50.0)
        acc = _mk_account(db)
        _mk_btx(db, acc, tx_date=PRE, amount=100000, balance=100000)         # 28 Ara, küçük id
        _mk_btx(db, acc, tx_date=PRE - timedelta(days=8), amount=500000,
                balance=500000)                                              # 20 Ara, BÜYÜK id
        anchor = _mk_account(db)
        first_day = MIN_DATE + timedelta(days=3)
        _mk_btx(db, anchor, tx_date=first_day, amount=0.01, balance=0.01)

        bal = _daily(db)[str(first_day)]["balance_eur"]
        assert round(bal) == 2000, f"(date,id) yerine max(id) kullanılmış: {bal}"

    def test_seed_overridden_by_first_in_window_tx(self, db):
        """Tohumlu hesabın pencere-içi ilk satırı geldiği gün kendi ekstre bakiyesi
        devralır (süreklilik)."""
        _mk_rate(db, MIN_DATE, 50.0)
        acc = _mk_account(db)
        _mk_btx(db, acc, tx_date=PRE, amount=100000, balance=100000)
        own_day = MIN_DATE + timedelta(days=10)
        _mk_btx(db, acc, tx_date=own_day, amount=-50000, balance=50000)

        bal = _daily(db)[str(own_day)]["balance_eur"]
        assert round(bal) == 1000, f"pencere-içi satır tohumu devralmadı: {bal}"

    def test_seed_respects_blocked_amount(self, db):
        """Tohumlu hesapta da effective = tohum − blocked_amount."""
        _mk_rate(db, MIN_DATE, 50.0)
        acc = _mk_account(db, blocked=50000.0)
        _mk_btx(db, acc, tx_date=PRE, amount=100000, balance=100000)
        anchor = _mk_account(db)
        first_day = MIN_DATE + timedelta(days=2)
        _mk_btx(db, anchor, tx_date=first_day, amount=0.01, balance=0.01)

        bal = _daily(db)[str(first_day)]["balance_eur"]
        assert round(bal) == 1000, f"blocked düşülmemiş: {bal}"

    def test_seed_produces_no_income_expense(self, db):
        """Devir gelir değildir — tohum monthly income/expense toplamlarını DEĞİŞTİRMEZ,
        yalnız balance düzeltir."""
        _mk_rate(db, MIN_DATE, 50.0)
        anchor = _mk_account(db)
        first_day = MIN_DATE + timedelta(days=2)
        _mk_btx(db, anchor, tx_date=first_day, amount=5000, balance=5000)
        before = compute_eur_balances(db)["monthly"]

        seeded = _mk_account(db)
        _mk_btx(db, seeded, tx_date=PRE, amount=100000, balance=100000)
        after = compute_eur_balances(db)["monthly"]

        key = f"{MIN_DATE.year}-{MIN_DATE.month:02d}"
        assert after[key]["income_eur"] == before[key]["income_eur"]
        assert after[key]["expense_eur"] == before[key]["expense_eur"]
        assert after[key]["balance_eur"] > before[key]["balance_eur"]

    def test_planned_day_before_first_bank_day_uses_seed_level(self, db):
        """Pencere-öncesi bakiyeli hesap + ilk banka günü sonra + arada vadeli bekleyen
        çek → çek günü noktası tohum seviyesinden hesaplanır (0'dan negatif değil)."""
        _mk_rate(db, MIN_DATE, 50.0)
        acc = _mk_account(db)
        _mk_btx(db, acc, tx_date=PRE, amount=100000, balance=100000)
        first_bank_day = MIN_DATE + timedelta(days=6)
        _mk_btx(db, acc, tx_date=first_bank_day, amount=-1000, balance=99000)
        up = CheckUpload(file_name="seed", file_url="x")
        db.add(up)
        db.flush()
        db.add(Check(upload_id=up.id, check_no=f"9{uuid4().hex[:6]}",
                     vendor_name="TOHUM ÇEK", due_date=MIN_DATE + timedelta(days=2),
                     amount_tl=10000, amount_currency=10000, currency="TL",
                     status="pending"))
        db.flush()

        bal = _daily(db)[str(MIN_DATE + timedelta(days=2))]["balance_eur"]
        # Geçmiş gün (bugünden önce) → projeksiyon düşmez; seviye = tohum 2.000 €
        assert round(bal) == 2000, f"çek günü tohum seviyesini görmedi: {bal}"

    def test_seed_converted_at_window_day_rate(self, db):
        """Tohum, kendi 2025 tarihinin değil GÖSTERİM gününün kuruyla çevrilir."""
        _mk_rate(db, PRE, 40.0)
        _mk_rate(db, MIN_DATE, 50.0)
        acc = _mk_account(db)
        _mk_btx(db, acc, tx_date=PRE, amount=100000, balance=100000)
        anchor = _mk_account(db)
        first_day = MIN_DATE + timedelta(days=1)
        _mk_rate(db, first_day, 50.0)
        _mk_btx(db, anchor, tx_date=first_day, amount=0.01, balance=0.01)

        bal = _daily(db)[str(first_day)]["balance_eur"]
        assert round(bal) == 2000, f"tohum 2025 kuruyla çevrilmiş (2.500 beklenmezdi): {bal}"


class TestLastBalanceDateIdOrder:
    def test_start_eur_ignores_backfilled_old_row(self, db):
        """_compute_start_eur: sonradan eklenen eski-tarihli satır (yüksek id) güncel
        bakiye sayılmaz — (date,id) son satırı kazanır."""
        _mk_rate(db, TODAY, 50.0)
        acc = _mk_account(db)
        _mk_btx(db, acc, tx_date=TODAY, amount=50000, balance=50000)
        # Backfill: DÜN tarihli satır sonradan eklendi (daha yüksek id)
        _mk_btx(db, acc, tx_date=TODAY - timedelta(days=1), amount=999999, balance=999999)

        start = _compute_start_eur(db)
        assert round(start) == 1000, f"max(id) bayat bakiyeyi seçti: {start}"
