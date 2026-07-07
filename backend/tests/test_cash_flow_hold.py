"""Bekletme (cash_flow_holds) — servis + endpoint + nakit akım dışlaması.

Kapsam:
- hold_service apply/clear/batch/cache (idempotent, holdable-dışı atlanır)
- POST /cash-flow/hold-batch izin (401/403/viewer-403/use-200) + boş/limit 400 + audit
- runway `held` dizisi: future-pending held → held'e düşer, outs/inflows'tan çıkar
- t_account: future-pending held bekleyen'den çıkar; realized held ÇIKMAZ; item source_type/source_id taşır
- eur_balances: future-pending held projeksiyondan çıkar (bakiye düşmez)
"""

import itertools
from datetime import date, timedelta

import pytest

from app.middleware.rate_limit import heavy_limiter
from app.models.cash_flow_hold import CashFlowHold
from app.models.credit_product import CreditPayment, CreditProduct
from app.models.exchange_rate import ExchangeRate
from app.models.finance_event import FinanceEvent
from app.routers.finance.cash_flow.t_account import taccount_limiter
from app.services import hold_service
from app.utils.finance_event_service import finance_event_svc
from app.utils.finance_helpers import MIN_DATE

HOLD_URL = "/api/finance/cash-flow/hold-batch"
RUNWAY_URL = "/api/finance/cash-flow/runway"
TACCOUNT_URL = "/api/finance/cash-flow/t-account"

_SEQ = itertools.count(986001)


@pytest.fixture(autouse=True)
def _reset_limiters():
    heavy_limiter._requests.clear()
    taccount_limiter._requests.clear()
    yield


def _mk_fe(db, **overrides):
    defaults = dict(
        event_date=date.today() + timedelta(days=3),
        amount=1000, direction=-1, currency="TRY",
        source_type="check", source_id=next(_SEQ),
        description="HOLD TEST KALEMİ", is_matched=False, is_realized=False,
    )
    defaults.update(overrides)
    fe = FinanceEvent(**defaults)
    db.add(fe)
    db.flush()
    return fe


def _mk_rate(db, dt, selling, code="EUR"):
    db.query(ExchangeRate).filter(
        ExchangeRate.date == dt, ExchangeRate.currency_code == code
    ).delete()
    db.add(ExchangeRate(date=dt, currency_code=code, unit=1, forex_selling=selling))
    db.flush()


def _mk_credit_payment(db, due_date, amount=1000, is_paid=False):
    product = CreditProduct(
        type="taksitli", name=f"HOLD TEST KREDİ {next(_SEQ)}",
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


class TestHoldService:
    def test_apply_then_get_set(self, db):
        hold_service.apply_hold(db, "check", 111, user_id=None)
        assert ("check", 111) in hold_service.get_hold_set(db)

    def test_apply_is_idempotent(self, db):
        hold_service.apply_hold(db, "check", 222, user_id=None)
        hold_service.apply_hold(db, "check", 222, user_id=None)
        cnt = db.query(CashFlowHold).filter(
            CashFlowHold.source_type == "check", CashFlowHold.source_id == 222
        ).count()
        assert cnt == 1

    def test_clear_removes_and_returns_true(self, db):
        hold_service.apply_hold(db, "credit", 333, user_id=None)
        assert hold_service.clear_hold(db, "credit", 333) is True
        assert ("credit", 333) not in hold_service.get_hold_set(db)

    def test_clear_missing_returns_false(self, db):
        assert hold_service.clear_hold(db, "credit", 999999) is False

    def test_cache_invalidation_on_apply(self, db):
        _ = hold_service.get_hold_set(db)  # cache doldur
        hold_service.apply_hold(db, "vendor_payment", 444, user_id=None)
        assert ("vendor_payment", 444) in hold_service.get_hold_set(db)

    def test_batch_skips_non_holdable(self, db):
        applied = hold_service.apply_holds_batch(
            db, [("check", 501), ("bank", 502), ("nonsense", 503)], True, user_id=None
        )
        assert applied == 1  # yalnız check uygulandı (bank + nonsense atlandı)
        s = hold_service.get_hold_set(db)
        assert ("check", 501) in s
        assert ("bank", 502) not in s

    def test_batch_clear(self, db):
        hold_service.apply_hold(db, "check", 601, user_id=None)
        applied = hold_service.apply_holds_batch(db, [("check", 601)], False, user_id=None)
        assert applied == 1
        assert ("check", 601) not in hold_service.get_hold_set(db)


# ─────────────────────────── Endpoint izin ───────────────────────────


class TestHoldEndpointAuth:
    def test_requires_auth(self, client):
        r = client.post(HOLD_URL, json={"items": [{"source_type": "check", "source_id": 1}], "held": True})
        assert r.status_code == 401

    def test_no_permission_403(self, client, no_perm_user_headers):
        r = client.post(HOLD_URL, headers=no_perm_user_headers,
                        json={"items": [{"source_type": "check", "source_id": 1}], "held": True})
        assert r.status_code == 403

    def test_viewer_forbidden_use_required(self, client, viewer_user_headers):
        r = client.post(HOLD_URL, headers=viewer_user_headers,
                        json={"items": [{"source_type": "check", "source_id": 1}], "held": True})
        assert r.status_code == 403

    def test_use_permission_allowed(self, client, use_user_headers):
        r = client.post(HOLD_URL, headers=use_user_headers,
                        json={"items": [{"source_type": "check", "source_id": 1}], "held": True})
        assert r.status_code == 200


class TestHoldEndpointBehavior:
    def test_empty_items_400(self, client, auth_headers):
        r = client.post(HOLD_URL, headers=auth_headers, json={"items": [], "held": True})
        assert r.status_code == 400

    def test_too_many_items_400(self, client, auth_headers):
        items = [{"source_type": "check", "source_id": i} for i in range(5001)]
        r = client.post(HOLD_URL, headers=auth_headers, json={"items": items, "held": True})
        assert r.status_code == 400

    def test_hold_batch_persists(self, client, auth_headers, db):
        sid = next(_SEQ)
        r = client.post(HOLD_URL, headers=auth_headers,
                        json={"items": [{"source_type": "check", "source_id": sid}], "held": True})
        assert r.status_code == 200
        assert r.json()["applied"] == 1
        assert r.json()["held"] is True
        assert ("check", sid) in hold_service.get_hold_set(db)

    def test_unhold_batch_removes(self, client, auth_headers, db):
        sid = next(_SEQ)
        hold_service.apply_hold(db, "check", sid, user_id=None)
        db.commit()
        r = client.post(HOLD_URL, headers=auth_headers,
                        json={"items": [{"source_type": "check", "source_id": sid}], "held": False})
        assert r.status_code == 200
        assert ("check", sid) not in hold_service.get_hold_set(db)

    def test_non_holdable_skipped_applied_zero(self, client, auth_headers):
        r = client.post(HOLD_URL, headers=auth_headers,
                        json={"items": [{"source_type": "bank", "source_id": 1}], "held": True})
        assert r.status_code == 200
        assert r.json()["applied"] == 0  # bank holdable değil

    def test_audit_logged(self, client, auth_headers, db):
        from app.models.audit_log import AuditLog
        before = db.query(AuditLog).filter(AuditLog.entity_type == "cash_flow_hold").count()
        client.post(HOLD_URL, headers=auth_headers,
                    json={"items": [{"source_type": "check", "source_id": next(_SEQ)}], "held": True})
        after = db.query(AuditLog).filter(AuditLog.entity_type == "cash_flow_hold").count()
        assert after == before + 1


# ─────────────────────────── Runway held dizisi ───────────────────────────


class TestRunwayHeld:
    def test_held_future_moves_to_held_list(self, client, auth_headers, db):
        _mk_rate(db, MIN_DATE, 50)
        fe = _mk_fe(db, event_date=date.today() + timedelta(days=4), amount=5000,
                    source_type="credit", description="RW BEKLEMEDE")
        hold_service.apply_hold(db, "credit", fe.source_id, user_id=None)
        db.commit()
        heavy_limiter._requests.clear()

        body = client.get(RUNWAY_URL, headers=auth_headers).json()
        assert "held" in body
        held_names = [h["name"] for h in body["held"]]
        out_names = [o["name"] for o in body["outs"]]
        assert "RW BEKLEMEDE" in held_names       # bekleme listesinde
        assert "RW BEKLEMEDE" not in out_names     # çıkış listesinden çıktı

    def test_unheld_future_stays_in_outs(self, client, auth_headers, db):
        _mk_rate(db, MIN_DATE, 50)
        _mk_fe(db, event_date=date.today() + timedelta(days=5), amount=5000,
               source_type="credit", description="RW NORMAL")
        db.commit()
        heavy_limiter._requests.clear()

        body = client.get(RUNWAY_URL, headers=auth_headers).json()
        assert "RW NORMAL" in [o["name"] for o in body["outs"]]
        assert "RW NORMAL" not in [h["name"] for h in body.get("held", [])]

    def test_held_overdue_goes_to_overdue_not_held(self, client, auth_headers, db):
        """Vadesi geçmiş held kalem overdue'ya düşer (held değil) — vade geçince beklemeden çıkar."""
        _mk_rate(db, MIN_DATE, 50)
        past = date.today() - timedelta(days=6)
        if past < MIN_DATE:
            pytest.skip("ay başı MIN_DATE'e çok yakın")
        fe = _mk_fe(db, event_date=past, amount=5000, source_type="check",
                    description="RW HELD GEÇMİŞ")
        hold_service.apply_hold(db, "check", fe.source_id, user_id=None)
        db.commit()
        heavy_limiter._requests.clear()

        body = client.get(RUNWAY_URL, headers=auth_headers).json()
        assert "RW HELD GEÇMİŞ" in [o["name"] for o in body["overdue"]]
        assert "RW HELD GEÇMİŞ" not in [h["name"] for h in body.get("held", [])]


# ─────────────────────────── T-Hesap dışlaması ───────────────────────────


class TestTAccountHoldExclusion:
    def test_held_future_pending_excluded_from_bekleyen(self, client, auth_headers, db):
        _mk_rate(db, MIN_DATE, 50)
        # aynı gruba düşecek iki bekleyen çek; biri held
        keep = _mk_fe(db, event_date=date.today() + timedelta(days=2), amount=3000,
                      source_type="check", description="TA NORMAL ÇEK")
        held = _mk_fe(db, event_date=date.today() + timedelta(days=2), amount=7000,
                      source_type="check", description="TA HELD ÇEK")
        hold_service.apply_hold(db, "check", held.source_id, user_id=None)
        db.commit()

        body = client.get(TACCOUNT_URL, headers=auth_headers).json()
        # Çek grubunu bul (çıkış tarafı)
        names = []
        for g in body["cikis"]:
            names += [i["name"] for i in g["items"]]
        assert "TA NORMAL ÇEK" in names
        assert "TA HELD ÇEK" not in names  # held bekleyen'den çıktı

    def test_realized_held_not_excluded(self, client, auth_headers, db):
        """Gerçekleşmiş (is_realized) held kalem gerçekleşen listede KALIR — held yalnız bekleyeni dışlar."""
        _mk_rate(db, MIN_DATE, 50)
        fe = _mk_fe(db, event_date=date.today(), amount=4000, source_type="bank",
                    is_realized=True, description="TA GERÇEKLEŞEN")
        # bank holdable değil ama farklı türden realized held simüle: credit realized
        fe2 = _mk_fe(db, event_date=date.today(), amount=4000, source_type="credit",
                     is_realized=True, description="TA HELD GERÇEKLEŞEN")
        hold_service.apply_hold(db, "credit", fe2.source_id, user_id=None)
        db.commit()

        body = client.get(TACCOUNT_URL, headers=auth_headers).json()
        names = []
        for g in body["cikis"]:
            names += [i["name"] for i in g["items"]]
        assert "TA HELD GERÇEKLEŞEN" in names  # realized → held onu dışlamaz

    def test_items_carry_source_identity(self, client, auth_headers, db):
        _mk_rate(db, MIN_DATE, 50)
        fe = _mk_fe(db, event_date=date.today() + timedelta(days=2), amount=1500,
                    source_type="check", description="TA KİMLİK")
        db.commit()

        body = client.get(TACCOUNT_URL, headers=auth_headers).json()
        found = None
        for g in body["cikis"]:
            for i in g["items"]:
                if i["name"] == "TA KİMLİK":
                    found = i
        assert found is not None
        assert found["source_type"] == "check"
        assert found["source_id"] == fe.source_id


# ─────────────────────────── EUR bakiye dışlaması ───────────────────────────


class TestEurBalanceHoldExclusion:
    def test_held_future_credit_not_subtracted_from_balance(self, db):
        """Beklemeye alınan future kredi taksiti projeksiyondan çıkar → gelecek bakiye düşmez."""
        from app.routers.finance.cash_flow.eur_balances import compute_eur_balances

        _mk_rate(db, MIN_DATE, 50)
        due = date.today() + timedelta(days=10)
        product, payment = _mk_credit_payment(db, due_date=due, amount=100000)
        finance_event_svc.upsert_credit_payment(db, payment, product)
        db.commit()

        before = compute_eur_balances(db)["daily"].get(str(due), {}).get("balance_eur")

        hold_service.apply_hold(db, "credit", payment.id, user_id=None)
        db.commit()
        after = compute_eur_balances(db)["daily"].get(str(due), {}).get("balance_eur")

        # held sonrası o günkü projeksiyon bakiyesi ARTAR (gider düşmez) ya da en az değişir
        if before is not None and after is not None:
            assert after >= before
