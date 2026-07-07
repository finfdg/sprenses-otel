"""Kalıcı Öteleme (payment_deferrals) — servis + _upsert override + endpoint + runway overdue.

Kapsam:
- deferral_service apply/clear/cache
- finance_event_service._upsert deferral override (event_date → deferred_to; bank HARİÇ)
- vendor_fifo.effective_due_date artık overdue'yu Cuma'ya kaydırMIYOR (orijinal tarih kalır)
- POST /cash-flow/defer izin (401/403/viewer-403/use-200) + FE event_date değişimi + clear geri döner
- GET /cash-flow/runway overdue dizisi (vadesi geçen ödenmemiş) + deferred/original_date alanları
"""

import calendar
import itertools
from datetime import date, timedelta

import pytest

from app.middleware.rate_limit import heavy_limiter
from app.models.credit_product import CreditPayment, CreditProduct
from app.models.exchange_rate import ExchangeRate
from app.models.finance_event import FinanceEvent
from app.models.payment_deferral import PaymentDeferral
from app.services import deferral_service
from app.utils.finance_event_service import finance_event_svc
from app.utils.finance_helpers import MIN_DATE
from app.utils.vendor_fifo import effective_due_date

DEFER_URL = "/api/finance/cash-flow/defer"
RUNWAY_URL = "/api/finance/cash-flow/runway"

_SEQ = itertools.count(988001)


@pytest.fixture(autouse=True)
def _reset_heavy_limiter():
    heavy_limiter._requests.clear()
    yield


def _future_date(days=10):
    return date.today() + timedelta(days=days)


def _mk_credit_payment(db, due_date, amount=1000, is_paid=False):
    """CreditProduct + CreditPayment → finance_event üretmeye hazır minimal kredi taksiti."""
    product = CreditProduct(
        type="taksitli", name=f"DEFER TEST KREDİ {next(_SEQ)}",
        bank_name="Test Bankası", currency="TRY",
        total_amount=amount, remaining_amount=amount, status="active",
    )
    db.add(product)
    db.flush()
    payment = CreditPayment(
        credit_product_id=product.id, installment_no=1,
        due_date=due_date, amount=amount, is_paid=is_paid,
    )
    db.add(payment)
    db.flush()
    return product, payment


# ─────────────────────────── Servis birim testleri ───────────────────────────


class TestDeferralService:
    def test_apply_then_get_map(self, db):
        deferral_service.apply_deferral(db, "credit", 555001, _future_date(20), user_id=None)
        m = deferral_service.get_deferral_map(db)
        assert m.get(("credit", 555001)) == _future_date(20)

    def test_apply_is_upsert_natural_key(self, db):
        deferral_service.apply_deferral(db, "check", 555002, _future_date(5), user_id=None)
        deferral_service.apply_deferral(db, "check", 555002, _future_date(15), user_id=None)
        rows = db.query(PaymentDeferral).filter(
            PaymentDeferral.source_type == "check", PaymentDeferral.source_id == 555002
        ).all()
        assert len(rows) == 1  # ÇİFT kayıt yok
        assert rows[0].deferred_to == _future_date(15)

    def test_clear_removes_and_returns_true(self, db):
        deferral_service.apply_deferral(db, "tax", 555003, _future_date(9), user_id=None)
        assert deferral_service.clear_deferral(db, "tax", 555003) is True
        assert deferral_service.get_deferral_map(db).get(("tax", 555003)) is None
        # ikinci kez temizleme → False (yoktu)
        assert deferral_service.clear_deferral(db, "tax", 555003) is False

    def test_cache_invalidation_on_apply(self, db):
        # önce boş map cache'le
        deferral_service.get_deferral_map(db)
        deferral_service.apply_deferral(db, "credit", 555004, _future_date(3), user_id=None)
        # apply cache'i invalidate etmeli → yeni değer görünür
        assert deferral_service.get_deferral_map(db).get(("credit", 555004)) == _future_date(3)


# ─────────────────────────── _upsert override ───────────────────────────


class TestUpsertDeferralOverride:
    def test_credit_fe_event_date_becomes_deferred(self, db):
        natural = _future_date(4)
        deferred = _future_date(40)
        product, payment = _mk_credit_payment(db, due_date=natural)

        # öteleme yokken → doğal tarih
        fe = finance_event_svc.upsert_credit_payment(db, payment, product)
        assert fe.event_date == natural

        # öteleme uygula + re-upsert → ertelenmiş tarih
        deferral_service.apply_deferral(db, "credit", payment.id, deferred, user_id=None)
        fe = finance_event_svc.upsert_credit_payment(db, payment, product)
        assert fe.event_date == deferred

        # clear → doğal tarihe geri döner
        deferral_service.clear_deferral(db, "credit", payment.id)
        fe = finance_event_svc.upsert_credit_payment(db, payment, product)
        assert fe.event_date == natural

    def test_bank_source_is_never_deferred(self, db):
        """bank türü lookup dışı — deferral olsa bile event_date değişmez (override guard)."""
        from app.utils.finance_event_service import _dec  # noqa: F401 (import kontrolü)
        # doğrudan _upsert'e bank event yaz (deferral kaydı olsa bile uygulanmamalı)
        deferral_service.apply_deferral(db, "bank", 555010, _future_date(30), user_id=None)
        d = _future_date(2)
        fe = finance_event_svc._upsert(db, "bank", 555010, {
            "event_date": d, "amount": 100, "direction": -1, "currency": "TRY",
        })
        assert fe.event_date == d  # bank → öteleme UYGULANMADI


# ─────────────────────────── effective_due_date (Cuma roll-over kaldırıldı) ───────────────────────────


class TestEffectiveDueDateNoFridayRoll:
    def test_overdue_stays_original_not_friday(self):
        past = date.today() - timedelta(days=30)
        # Cuma'ya kaydırMAmalı → orijinal tarih aynen
        assert effective_due_date(past) == past

    def test_future_unchanged(self):
        fut = date.today() + timedelta(days=15)
        assert effective_due_date(fut) == fut

    def test_deferral_applied_when_map_given(self):
        past = date.today() - timedelta(days=5)
        target = date.today() + timedelta(days=20)
        got = effective_due_date(past, vtx_id=42, deferral_map={("vendor_payment", 42): target})
        assert got == target

    def test_no_deferral_in_map_returns_original(self):
        past = date.today() - timedelta(days=5)
        assert effective_due_date(past, vtx_id=42, deferral_map={}) == past


# ─────────────────────────── Endpoint izin + davranış ───────────────────────────


class TestDeferEndpointAuth:
    def test_requires_auth(self, client):
        assert client.post(DEFER_URL, json={"source_type": "credit", "source_id": 1}).status_code == 401

    def test_no_permission_403(self, client, no_perm_user_headers):
        resp = client.post(DEFER_URL, headers=no_perm_user_headers,
                           json={"source_type": "credit", "source_id": 1, "deferred_to": None})
        assert resp.status_code == 403

    def test_viewer_forbidden_use_required(self, client, viewer_user_headers):
        """Salt-görüntüleme yetmez — öteleme = use (mutasyon)."""
        resp = client.post(DEFER_URL, headers=viewer_user_headers,
                           json={"source_type": "credit", "source_id": 1, "deferred_to": None})
        assert resp.status_code == 403

    def test_invalid_source_type_400(self, client, auth_headers):
        resp = client.post(DEFER_URL, headers=auth_headers,
                           json={"source_type": "bank", "source_id": 1,
                                 "deferred_to": _future_date(5).isoformat()})
        assert resp.status_code == 400

    def test_invalid_date_400(self, client, auth_headers):
        resp = client.post(DEFER_URL, headers=auth_headers,
                           json={"source_type": "credit", "source_id": 1, "deferred_to": "2026/13/40"})
        assert resp.status_code == 400


class TestDeferEndpointBehavior:
    def test_defer_moves_fe_event_date(self, client, auth_headers, db):
        natural = _future_date(4)
        deferred = _future_date(45)
        product, payment = _mk_credit_payment(db, due_date=natural)
        finance_event_svc.upsert_credit_payment(db, payment, product)
        db.commit()

        resp = client.post(DEFER_URL, headers=auth_headers, json={
            "source_type": "credit", "source_id": payment.id,
            "deferred_to": deferred.isoformat(),
        })
        assert resp.status_code == 200
        assert resp.json()["deferred_to"] == deferred.isoformat()

        fe = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == "credit", FinanceEvent.source_id == payment.id
        ).first()
        assert fe.event_date == deferred

    def test_clear_restores_original(self, client, auth_headers, db):
        natural = _future_date(6)
        deferred = _future_date(50)
        product, payment = _mk_credit_payment(db, due_date=natural)
        finance_event_svc.upsert_credit_payment(db, payment, product)
        deferral_service.apply_deferral(db, "credit", payment.id, deferred, user_id=None)
        finance_event_svc.upsert_credit_payment(db, payment, product)
        db.commit()

        resp = client.post(DEFER_URL, headers=auth_headers, json={
            "source_type": "credit", "source_id": payment.id, "deferred_to": None,
        })
        assert resp.status_code == 200
        assert resp.json()["deferred_to"] is None
        assert resp.json()["cleared"] is True

        fe = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == "credit", FinanceEvent.source_id == payment.id
        ).first()
        assert fe.event_date == natural  # doğal tarihe geri döndü

    def test_audit_logged(self, client, auth_headers, db):
        from app.models.audit_log import AuditLog
        natural = _future_date(4)
        product, payment = _mk_credit_payment(db, due_date=natural)
        finance_event_svc.upsert_credit_payment(db, payment, product)
        db.commit()

        before = db.query(AuditLog).filter(AuditLog.entity_type == "payment_deferral").count()
        client.post(DEFER_URL, headers=auth_headers, json={
            "source_type": "credit", "source_id": payment.id,
            "deferred_to": _future_date(30).isoformat(),
        })
        after = db.query(AuditLog).filter(AuditLog.entity_type == "payment_deferral").count()
        assert after == before + 1


# ─────────────────────────── Runway overdue ───────────────────────────


def _mk_rate(db, dt, selling, code="EUR"):
    db.query(ExchangeRate).filter(
        ExchangeRate.date == dt, ExchangeRate.currency_code == code
    ).delete()
    db.add(ExchangeRate(date=dt, currency_code=code, unit=1, forex_selling=selling))
    db.flush()


def _mk_fe(db, **overrides):
    defaults = dict(
        event_date=date.today() + timedelta(days=2),
        amount=1000, direction=-1, currency="TRY",
        source_type="check", source_id=next(_SEQ),
        description="DEFER RW KALEM", is_matched=False, is_realized=False,
    )
    defaults.update(overrides)
    fe = FinanceEvent(**defaults)
    db.add(fe)
    db.flush()
    return fe


class TestRunwayOverdue:
    def test_overdue_contains_past_due_unpaid(self, client, auth_headers, db):
        _mk_rate(db, MIN_DATE, 50)
        past = date.today() - timedelta(days=7)
        if past < MIN_DATE:
            pytest.skip("ay başı MIN_DATE'e çok yakın")
        _mk_fe(db, event_date=past, amount=5000, source_type="check",
               description="RW VADESİ GEÇEN")
        db.commit()
        heavy_limiter._requests.clear()

        body = client.get(RUNWAY_URL, headers=auth_headers).json()
        assert "overdue" in body
        names = [o["name"] for o in body["overdue"]]
        assert "RW VADESİ GEÇEN" in names

    def test_overdue_income_separate_from_expenses(self, client, auth_headers, db):
        """Vadesi geçmiş GELİR (beklenen ama gelmemiş tahsilat) `overdue_income`'a düşer —
        `overdue` (gider) listesine KARIŞMAZ (kullanıcı isteği 2026-07-07)."""
        _mk_rate(db, MIN_DATE, 50)
        past = date.today() - timedelta(days=5)
        if past < MIN_DATE:
            pytest.skip("ay başı MIN_DATE'e çok yakın")
        _mk_fe(db, event_date=past, amount=21800, currency="EUR", direction=1,
               source_type="advance", description="RW VADESİ GEÇEN AVANS")
        db.commit()
        heavy_limiter._requests.clear()

        body = client.get(RUNWAY_URL, headers=auth_headers).json()
        assert "overdue_income" in body
        inc_names = [o["name"] for o in body["overdue_income"]]
        exp_names = [o["name"] for o in body["overdue"]]
        assert "RW VADESİ GEÇEN AVANS" in inc_names       # gelir → tahsilat listesinde
        assert "RW VADESİ GEÇEN AVANS" not in exp_names    # gider listesine karışmaz
        # ay-içi outs'ta OLMAMALI (geçmiş tarih)
        assert "RW VADESİ GEÇEN" not in [o["name"] for o in body["outs"]]

    def test_items_have_deferred_and_original_date(self, client, auth_headers, db):
        _mk_rate(db, MIN_DATE, 50)
        d = date.today() + timedelta(days=3)
        fe = _mk_fe(db, event_date=d, amount=3000, source_type="credit",
                    description="RW ÖTELENEN")
        db.commit()
        heavy_limiter._requests.clear()

        body = client.get(RUNWAY_URL, headers=auth_headers).json()
        item = next(i for i in body["outs"] if i["name"] == "RW ÖTELENEN")
        assert item["deferred"] is False
        assert item["original_date"] == d.isoformat()

    def test_deferred_item_flagged(self, client, auth_headers, db):
        _mk_rate(db, MIN_DATE, 50)
        natural = date.today() + timedelta(days=3)
        product, payment = _mk_credit_payment(db, due_date=natural)
        # öteleme uygula + FE yaz (event_date ertelenmiş olur)
        moved = date.today() + timedelta(days=6)
        deferral_service.apply_deferral(db, "credit", payment.id, moved, user_id=None)
        _mk_rate(db, moved, 50)
        finance_event_svc.upsert_credit_payment(db, payment, product)
        db.commit()
        heavy_limiter._requests.clear()

        body = client.get(RUNWAY_URL, headers=auth_headers).json()
        item = next(
            (i for i in body["outs"] if i["id"] == f"credit:{payment.id}"), None
        )
        assert item is not None
        assert item["deferred"] is True
        assert item["date"] == moved.isoformat()
        assert item["original_date"] == natural.isoformat()  # doğal vade


# ─────────────── EUR bakiye: vadesi geçen cari overdue (roll-over kaldırma regresyonu) ───────────────


class TestEurBalanceOverdueVendor:
    """Vadesi geçmiş ödenmemiş cari/çek bakiyeden DÜŞÜLMEZ (kullanıcı kararı 2026-07-06:
    "ödenmedi, para hâlâ bankada"). compute_eur_balances gerçek banka nakdini gösterir; vadesi
    geçen ödenene kadar banka hareketiyle düşer. (Eski "bloke düş" davranışı kaldırıldı — bkz
    eur_balances.py; Panel runway grafiği de overdue'yu bakiyeye katmaz → iki görünüm tutarlı.)"""

    def _seed_bank(self, db, balance_try):
        from datetime import date, timedelta
        from app.models.bank_account import BankAccount
        from app.models.bank_transaction import BankTransaction
        acc = BankAccount(bank_name="OD Test Bank", iban="TR990000000000000000000077",
                          currency="TRY", is_active=True)
        db.add(acc)
        db.flush()
        db.add(BankTransaction(account_id=acc.id, date=date.today(),
                               amount=balance_try, type="income", balance=balance_try,
                               description="AÇILIŞ", tx_hash="od-vendor-seed"))
        db.flush()
        return acc

    def _rate(self, db, selling=50.0):
        from app.models.exchange_rate import ExchangeRate
        from app.utils.finance_helpers import MIN_DATE
        db.query(ExchangeRate).filter(ExchangeRate.currency_code == "EUR").delete()
        db.add(ExchangeRate(currency_code="EUR", date=MIN_DATE, unit=1, forex_selling=selling))
        db.flush()

    def test_overdue_vendor_not_subtracted_from_balance(self, db):
        from datetime import date, timedelta
        from app.routers.finance.cash_flow.eur_balances import compute_eur_balances
        from app.models.finance_event import FinanceEvent

        self._seed_bank(db, 100000)   # 100.000 TL = 2000 EUR @50
        self._rate(db, 50.0)
        today = date.today()
        base = compute_eur_balances(db)["daily"].get(str(today), {}).get("balance_eur", 0)

        # Vadesi 10 gün geçmiş, ÖDENMEMİŞ cari ödemesi (50.000 TL = 1000 EUR)
        past = today - timedelta(days=10)
        db.add(FinanceEvent(event_date=past, amount=50000, direction=-1, currency="TRY",
                            source_type="vendor_payment", source_id=778001,
                            description="VADESİ GEÇEN CARİ", is_matched=False, is_realized=False))
        db.flush()

        after = compute_eur_balances(db)["daily"].get(str(today), {}).get("balance_eur", 0)
        # Bugünkü bakiye DEĞİŞMEZ — vadesi geçmiş ödenmemiş para hâlâ bankada (düşülmez)
        assert round(base - after) == 0, f"overdue cari yanlışlıkla bakiyeden düşüldü: base={base} after={after}"
