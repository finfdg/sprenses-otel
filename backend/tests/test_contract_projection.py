"""Kontrat nakit projeksiyonu (Faz 2) testleri.

Kapsam: contract_projection_service (advances netleme, guarantee_check hariç tutma,
koşullu bayrak), runway'e kontrat kalemlerinin düşmesi (overdue dahil),
taksit↔banka otomatik eşleştirici.
"""
from datetime import date, timedelta
from uuid import uuid4

from app.models.advance import Advance
from app.models.agency_group import AgencyGroup
from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.contract import (
    AgencyContract, ContractInstallment, ContractPaymentPlan,
)
from app.services.contract_projection_service import (
    contract_inflow_projections, invalidate_cache,
)


def _mk_contract(db, group_name=None):
    g = AgencyGroup(name=group_name or f"PTEST{uuid4().hex[:6].upper()}",
                    members=["PTEST ACENTE"], term_days=21)
    db.add(g)
    db.flush()
    c = AgencyContract(agency_group_id=g.id, code=f"PT-{uuid4().hex[:6].upper()}",
                       season_code="S26", currency="EUR",
                       valid_from=date(2026, 3, 1), valid_to=date(2026, 10, 31))
    db.add(c)
    db.flush()
    return g, c


def _mk_plan(db, contract, plan_type="advance"):
    p = ContractPaymentPlan(contract_id=contract.id, plan_type=plan_type, currency="EUR")
    db.add(p)
    db.flush()
    return p


def _mk_inst(db, plan, due, amount, **kw):
    i = ContractInstallment(plan_id=plan.id, due_date=due, amount=amount,
                            currency="EUR", **kw)
    db.add(i)
    db.flush()
    return i


class TestProjectionService:
    def test_advance_netting_and_flags(self, db):
        """Aynı grubun pending advance'ı taksitlere FIFO netlenir; teminat planı hiç
        girmez; koşullu bayrak taşınır."""
        g, c = _mk_contract(db)
        plan = _mk_plan(db, c)
        future = date.today() + timedelta(days=40)
        _mk_inst(db, plan, future, 500000)
        _mk_inst(db, plan, future + timedelta(days=30), 300000,
                 is_conditional=True, condition_note="%70 şartı")
        # Aynı grup için 200k pending advance → ilk taksitten düşer
        db.add(Advance(agency_name=g.name, amount=200000, currency="EUR",
                       advance_date=future, status="pending"))
        # Teminat çeki planı — projeksiyona GİRMEMELİ
        gplan = _mk_plan(db, c, plan_type="guarantee_check")
        _mk_inst(db, gplan, future, 999999)
        db.commit()
        invalidate_cache()

        p = contract_inflow_projections(db)
        items = [i for i in p["installments"] if i["contract_code"] == c.code]
        assert len(items) == 2, items
        assert items[0]["amount_eur"] == 300000  # 500k - 200k advance havuzu
        assert items[0]["netted_from_advance"] is True
        assert items[1]["amount_eur"] == 300000
        assert items[1]["conditional"] is True
        assert not any(i["gross_eur"] == 999999 for i in items), "teminat çeki projeksiyona girmemeli"

    def test_paid_and_non_eur_excluded(self, db):
        g, c = _mk_contract(db)
        plan = _mk_plan(db, c)
        future = date.today() + timedelta(days=25)
        _mk_inst(db, plan, future, 100000, status="paid")
        tl = ContractInstallment(plan_id=plan.id, due_date=future, amount=50000,
                                 currency="TL")
        db.add(tl)
        db.commit()
        invalidate_cache()
        p = contract_inflow_projections(db)
        assert not [i for i in p["installments"] if i["contract_code"] == c.code]


class TestRunwayIntegration:
    def test_overdue_installment_in_runway(self, client, auth_headers, db):
        """Vadesi geçmiş pending taksit runway 'Vadesi Geçen Tahsilatlar'a kalem düşer."""
        g, c = _mk_contract(db)
        plan = _mk_plan(db, c)
        past = date.today() - timedelta(days=10)
        inst = _mk_inst(db, plan, past, 123456)
        db.commit()
        invalidate_cache()

        r = client.get("/api/finance/cash-flow/runway", headers=auth_headers)
        assert r.status_code == 200
        oi = r.json().get("overdue_income", [])
        hit = [i for i in oi if i.get("id") == f"contract_installment:{inst.id}"]
        assert hit, "Vadesi geçmiş kontrat taksiti overdue_income'da olmalı"
        assert hit[0]["amount_eur"] == 123456
        assert hit[0]["source_type"] == "contract_installment"


class TestBankMatcher:
    def test_installment_matched_to_bank_income(self, db):
        """Tutar+PB birebir ve grup adı açıklamada → taksit paid + banka bağı kurulur."""
        from app.utils.matching_service import _match_contract_installments_to_bank

        g, c = _mk_contract(db)
        plan = _mk_plan(db, c)
        due = date.today() - timedelta(days=3)
        inst = _mk_inst(db, plan, due, 77777)

        acc = BankAccount(bank_name="Test Bank", iban=f"TR{uuid4().hex[:24].upper()}",
                          currency="EUR")
        db.add(acc)
        db.flush()
        tx = BankTransaction(account_id=acc.id, date=due + timedelta(days=1),
                             description=f"{g.name} avans odemesi swift",
                             amount=77777, type="income",
                             tx_hash=f"th-{uuid4().hex[:16]}")
        db.add(tx)
        db.commit()

        res = _match_contract_installments_to_bank(db)
        db.commit()
        assert res["matched"] >= 1
        db.refresh(inst)
        assert inst.status == "paid"
        assert inst.bank_transaction_id == tx.id
        assert inst.paid_date == tx.date
