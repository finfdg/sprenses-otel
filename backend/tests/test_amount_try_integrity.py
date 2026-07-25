"""`finance_events.amount_try` bütünlüğü — FIN-001 regresyon ağı (2026-07 denetimi).

KÖK NEDEN: hiçbir `upsert_*` metodu alan sözlüğüne `amount_try` koymuyordu → `_upsert`'in
`ON CONFLICT DO UPDATE SET` bloğu bu kolona hiç dokunmuyordu. Kolonun tek yazıcısı
`update_amount_try` ise yalnız `currency='EUR' AND event_date=bugün` satırlarını günceller.
Sonuç: cari FIFO kırpması / KK kısmi ödemesi `amount`'ı küçültünce `amount_try` ESKİ TAM
TUTARDA DONUYORDU. Okuyucular (t_account/runway/aging) `amount_try`'ı `amount`'a tercih
ettiğinden bayat değer yönetim raporuna hayalet yükümlülük yazıyordu — canlıda 11 bayat TRY
kaydı (₺2.426.887 sapma), 6'sı açık → Panel/runway/aging'de **₺696.190,94 olmayan borç**.

İKİ KATMANLI DÜZELTME, ikisi de burada sabitlenir:
  1. YAZICI  — `finance_event_service._upsert` TRY kalemlerde `amount_try = amount` türetir.
  2. OKUYUCU — `t_account._event_eur` / `runway._event_eur` TRY dalını `amount_try`
     kontrolünden ÖNCE çalıştırır (bayat kolon gerçek tutarı ezemez).
"""

from datetime import date, timedelta

import pytest

from app.models.bank_account import BankAccount
from app.models.finance_event import FinanceEvent
from app.utils.finance_event_service import finance_event_svc


@pytest.fixture
def acc_try(db):
    """Gerçek TRY hesabı — finance_events.bank_account_id FK'sı sahte id kabul etmez."""
    return _make_account(db, "TRY", "TR900000000000000000000001")


@pytest.fixture
def acc_eur(db):
    return _make_account(db, "EUR", "TR900000000000000000000002")


def _make_account(db, currency, iban):
    acc = BankAccount(bank_name="TestBank", iban=iban, currency=currency, is_active=True)
    db.add(acc)
    db.flush()
    return acc


def _fe(db, source_id):
    return (
        db.query(FinanceEvent)
        .filter(FinanceEvent.source_type == "bank", FinanceEvent.source_id == source_id)
        .first()
    )


class _Tx:
    """upsert_bank_tx'in beklediği asgari işlem arayüzü."""

    def __init__(self, tx_id, amount, account_id):
        self.id = tx_id
        self.date = date.today()
        self.amount = amount
        self.type = "expense"
        self.description = "FIN-001 regresyon"
        self.receipt_no = None
        self.balance = None
        self.payment_method = None
        self.match_number = None
        self.tag_note = None
        self.tag_source = None
        self.account_id = account_id
        self.vendor_id = None
        self.category_id = None


class TestAmountTryWriter:
    """YAZICI katmanı — _upsert TRY kalemlerde amount_try'ı senkron tutar."""

    def test_try_event_gets_amount_try_on_insert(self, db, acc_try):
        finance_event_svc.upsert_bank_tx(db, _Tx(970001, -1000.00, acc_try.id), acc_try)
        db.flush()
        fe = _fe(db, 970001)
        assert fe.amount_try is not None, "TRY kaleminde amount_try doldurulmalı"
        assert float(fe.amount_try) == float(fe.amount) == 1000.00

    def test_amount_try_refreshed_when_amount_shrinks(self, db, acc_try):
        """FIN-001'in TAM SENARYOSU: büyük tutarla yaz → küçük tutarla yeniden yaz.

        Düzeltme öncesi amount_try 57.600'de donuyor, amount 178,58'e düşüyordu (canlı
        fe#1205 birebir bu). Fark doğrudan panele hayalet borç olarak yazılıyordu.
        """
        finance_event_svc.upsert_bank_tx(db, _Tx(970002, -57600.00, acc_try.id), acc_try)
        db.flush()
        assert float(_fe(db, 970002).amount_try) == 57600.00

        # FIFO kırpması / kısmi ödeme → aynı kaynak, küçülmüş tutarla yeniden upsert
        finance_event_svc.upsert_bank_tx(db, _Tx(970002, -178.58, acc_try.id), acc_try)
        db.flush()
        db.expire_all()

        fe = _fe(db, 970002)
        assert float(fe.amount) == 178.58
        assert float(fe.amount_try) == 178.58, (
            "amount_try bayat kaldı — ON CONFLICT DO UPDATE bu kolonu tazelemiyor "
            "(FIN-001 geri döndü)"
        )

    def test_foreign_currency_amount_try_not_fabricated(self, db, acc_eur):
        """Döviz kalemde amount_try UYDURULMAZ — TL karşılığı kur gerektirir."""
        finance_event_svc.upsert_bank_tx(db, _Tx(970003, -100.00, acc_eur.id), acc_eur)
        db.flush()
        fe = _fe(db, 970003)
        assert fe.currency == "EUR"
        assert fe.amount_try is None, "EUR kalemde amount_try 1:1 yazılmamalı"


class TestAmountTryReaders:
    """OKUYUCU katmanı — TRY kalemde bayat amount_try gerçek tutarı EZEMEZ.

    Bu testler GERÇEK bir EUR kuru tohumlar. Kur olmadan `_event_eur` None döner ve
    test sessizce boşa koşar (ilk yazımda bu tuzağa düşüldü — kanıtlanmayan yeşil).
    """

    RATE = 40.0          # 1 EUR = 40 TL (test tohumu)
    REAL = 178.58        # gerçek tutar
    STALE = 57600.00     # bayat amount_try (322×)

    @pytest.fixture
    def rate_day(self, db):
        """Dünün tarihine EUR alış kuru tohumla; okuyucular bunu bulmak zorunda."""
        from app.models.exchange_rate import ExchangeRate

        day = date.today() - timedelta(days=1)
        db.query(ExchangeRate).filter(
            ExchangeRate.currency_code == "EUR", ExchangeRate.date == day,
        ).delete(synchronize_session=False)
        db.add(ExchangeRate(
            currency_code="EUR", date=day, unit=1,
            forex_buying=self.RATE, forex_selling=self.RATE,
        ))
        db.flush()
        return day

    def _stale_try_event(self, day):
        """Bayat amount_try taşıyan TRY kalemi (saf fonksiyon girdisi, DB'ye yazılmaz)."""
        fe = FinanceEvent()
        fe.event_date = day
        fe.amount = self.REAL
        fe.amount_try = self.STALE
        fe.currency = "TRY"
        fe.direction = -1
        fe.source_type = "bank"
        fe.source_id = 970004
        return fe

    def test_t_account_prefers_amount_for_try(self, db, rate_day):
        from app.routers.finance.cash_flow import t_account

        value = t_account._event_eur(db, self._stale_try_event(rate_day), {})

        assert value is not None, "kur tohumlandı — çevrim None dönmemeli (test boşa koşuyor)"
        assert abs(value - self.REAL / self.RATE) < 0.01, (
            f"t_account bayat amount_try'ı kullandı (beklenen ~{self.REAL / self.RATE:.2f}, "
            f"gelen {value:.2f}) — TRY dalı önce gelmeli (FIN-001)"
        )

    def test_runway_prefers_amount_for_try(self, db, rate_day):
        from app.routers.finance.cash_flow import runway

        value = runway._event_eur(db, self._stale_try_event(rate_day), {}, {})

        assert value is not None, "kur tohumlandı — çevrim None dönmemeli (test boşa koşuyor)"
        assert abs(value - self.REAL / self.RATE) < 0.01, (
            f"runway bayat amount_try'ı kullandı (beklenen ~{self.REAL / self.RATE:.2f}, "
            f"gelen {value:.2f}) — TRY dalı önce gelmeli (FIN-001)"
        )

    def test_foreign_currency_still_uses_amount_try(self, db, rate_day):
        """GBP gibi USD-dışı dövizde amount_try YOLU KORUNUR (düzeltme onu bozmamalı)."""
        from app.routers.finance.cash_flow import t_account

        fe = self._stale_try_event(rate_day)
        fe.currency = "GBP"
        fe.amount = 100.00
        fe.amount_try = 5000.00   # GBP'nin TL karşılığı — meşru

        value = t_account._event_eur(db, fe, {})
        assert value is not None
        assert abs(value - 5000.00 / self.RATE) < 0.01, (
            "GBP kalemde amount_try yolu kırıldı — düzeltme yalnız TRY'yi etkilemeli"
        )


class TestNoStaleRowsRemain:
    """Kapanış kriteri: TRY kaleminde amount_try ile amount ayrışmamalı."""

    def test_no_try_event_has_divergent_amount_try(self, db):
        rows = (
            db.query(FinanceEvent)
            .filter(
                FinanceEvent.currency.in_(("TRY", "TL")),
                FinanceEvent.amount_try.isnot(None),
            )
            .all()
        )
        divergent = [
            (r.id, r.source_type, float(r.amount), float(r.amount_try))
            for r in rows
            if abs(float(r.amount_try) - float(r.amount)) > 0.01
        ]
        assert not divergent, (
            "TRY kaleminde amount_try ≠ amount (bayat kolon → rapora hayalet tutar): "
            + str(divergent[:5])
        )
