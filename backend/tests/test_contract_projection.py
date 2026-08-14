"""Kontrat nakit projeksiyonu (Faz 2) testleri.

Kapsam: contract_projection_service (advances netleme, guarantee_check hariç tutma,
koşullu bayrak, gün-hassasiyetli acente-bazlı ciro serisi), runway'e kontrat
kalemlerinin düşmesi (overdue dahil), taksit↔banka otomatik eşleştirici.
"""
import random
from datetime import date, timedelta
from uuid import uuid4

from app.models.advance import Advance
from app.models.agency_group import AgencyGroup
from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.contract import (
    AgencyContract, ContractInstallment, ContractPaymentPlan,
)
from app.models.reservation import Reservation
from app.services.contract_projection_service import (
    contract_inflow_projections, invalidate_cache,
)
from app.utils.vendor_fifo import _next_friday


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


def _mk_reservation(db, agency, checkout, eur_total):
    r = Reservation(
        rec_id=random.randint(10_000_000, 99_000_000),
        agency=agency, checkin_date=checkout - timedelta(days=7),
        checkout_date=checkout, record_date=checkout - timedelta(days=60),
        eur_total=eur_total)
    db.add(r)
    db.flush()
    return r


class TestCiroDailySeries:
    """Gün-hassasiyetli acente-bazlı ciro serisi (2026-08-13 kullanıcı kararı):
    çıkış + term_days sonrası İLK CUMA'ya acente adıyla yazılır."""

    def _same_year_checkout(self, offset_days):
        today = date.today()
        co = today + timedelta(days=offset_days)
        if co.year != today.year:  # yıl sonu koruması
            co = today - timedelta(days=5)
        return co

    def test_ciro_written_to_first_friday_after_term(self, db):
        gname = f"PGTEST{uuid4().hex[:6].upper()}"
        g = AgencyGroup(name=gname, members=[gname], term_days=21)
        db.add(g)
        db.flush()
        co = self._same_year_checkout(10)
        _mk_reservation(db, g.name, co, 1000)
        db.commit()
        invalidate_cache()

        p = contract_inflow_projections(db)
        hits = [i for i in p["ciro_items"] if i["agency"] == g.name]
        assert len(hits) == 1, hits
        expected_due = _next_friday(co + timedelta(days=21))
        assert hits[0]["date"] == expected_due.isoformat()
        assert expected_due.weekday() == 4  # Cuma
        assert hits[0]["amount_eur"] == 1000
        assert g.name in hits[0]["label"]

    def test_past_due_ciro_excluded(self, db):
        gname = f"PGTEST{uuid4().hex[:6].upper()}"
        g = AgencyGroup(name=gname, members=[gname], term_days=21)
        db.add(g)
        db.flush()
        _mk_reservation(db, g.name, date.today() - timedelta(days=60), 500)
        db.commit()
        invalidate_cache()

        p = contract_inflow_projections(db)
        assert not [i for i in p["ciro_items"] if i["agency"] == g.name]

    def test_pending_advance_trims_earliest_ciro(self, db):
        """Koruma [3]: bekleyen avans kaydı ciro serisinin başından FIFO düşülür."""
        gname = f"PGTEST{uuid4().hex[:6].upper()}"
        g = AgencyGroup(name=gname, members=[gname], term_days=21)
        db.add(g)
        db.flush()
        co = self._same_year_checkout(10)
        _mk_reservation(db, g.name, co, 1000)
        db.add(Advance(agency_name=g.name, amount=300, currency="EUR",
                       advance_date=co, status="pending"))
        db.commit()
        invalidate_cache()

        p = contract_inflow_projections(db)
        hits = [i for i in p["ciro_items"] if i["agency"] == g.name]
        assert len(hits) == 1
        assert hits[0]["amount_eur"] == 700  # 1000 − 300 pending avans kırpması

    def test_month_end_alignment(self, db):
        """payment_alignment='month_end' (ör. Nordic): vade Cuma'ya değil vadenin
        düştüğü ayın SON GÜNÜNE yazılır."""
        from calendar import monthrange

        gname = f"PGTEST{uuid4().hex[:6].upper()}"
        g = AgencyGroup(name=gname, members=[gname], term_days=30,
                        payment_alignment="month_end")
        db.add(g)
        db.flush()
        co = self._same_year_checkout(10)
        _mk_reservation(db, g.name, co, 800)
        db.commit()
        invalidate_cache()

        p = contract_inflow_projections(db)
        hits = [i for i in p["ciro_items"] if i["agency"] == g.name]
        assert len(hits) == 1
        raw = co + timedelta(days=30)
        expected = date(raw.year, raw.month, monthrange(raw.year, raw.month)[1])
        assert hits[0]["date"] == expected.isoformat()
        assert hits[0]["amount_eur"] == 800

    def test_day_of_month_alignment(self, db):
        """payment_alignment='day_27' (ör. Nordic): vade ayın 27'sine yazılır; vade
        günü 27'yi geçtiyse ertesi ayın 27'sine kayar."""
        gname = f"PGTEST{uuid4().hex[:6].upper()}"
        g = AgencyGroup(name=gname, members=[gname], term_days=30,
                        payment_alignment="day_27")
        db.add(g)
        db.flush()
        co = self._same_year_checkout(10)
        _mk_reservation(db, g.name, co, 600)
        db.commit()
        invalidate_cache()

        p = contract_inflow_projections(db)
        hits = [i for i in p["ciro_items"] if i["agency"] == g.name]
        assert len(hits) == 1
        raw = co + timedelta(days=30)
        if raw.day > 27:
            y, m = (raw.year + 1, 1) if raw.month == 12 else (raw.year, raw.month + 1)
        else:
            y, m = raw.year, raw.month
        assert hits[0]["date"] == date(y, m, 27).isoformat()
        assert hits[0]["amount_eur"] == 600

    def test_align_due_helper(self):
        """_align_due saf yardımcısı: friday / month_end / day_N / bozuk değer."""
        from app.services.contract_projection_service import _align_due

        wed = date(2026, 8, 12)   # Çarşamba
        assert _align_due("friday", wed) == date(2026, 8, 14)
        assert _align_due("month_end", wed) == date(2026, 8, 31)
        assert _align_due("day_27", wed) == date(2026, 8, 27)
        assert _align_due("day_27", date(2026, 8, 28)) == date(2026, 9, 27)
        assert _align_due("day_27", date(2026, 12, 30)) == date(2027, 1, 27)
        assert _align_due("day_31", date(2026, 2, 1)) == date(2026, 2, 28)
        assert _align_due("day_x", wed) == date(2026, 8, 14)  # bozuk → friday

    def test_checkin_alignment_daily(self, db):
        """payment_alignment='checkin' (Expedia/Münferit): tahsilat GİRİŞ gününe
        günlük yazılır; girişi bugünden önce/bugün olan misafir zaten ödedi → girmez."""
        gname = f"PGTEST{uuid4().hex[:6].upper()}"
        g = AgencyGroup(name=gname, members=[gname], term_days=0,
                        payment_alignment="checkin")
        db.add(g)
        db.flush()
        today = date.today()
        co = self._same_year_checkout(12)
        # gelecek girişli misafir (giriş = çıkış - 7)
        _mk_reservation(db, g.name, co, 500)
        # girişi geçmiş (konaklamakta olan) misafir — girişte ödedi, projeksiyona girmez
        r2 = _mk_reservation(db, g.name, today + timedelta(days=3), 400)
        # _mk_reservation girişi çıkış-7 yapar → r2 girişi geçmişte
        db.commit()
        invalidate_cache()

        p = contract_inflow_projections(db)
        hits = [i for i in p["ciro_items"] if i["agency"] == g.name]
        assert len(hits) == 1, hits
        assert hits[0]["date"] == (co - timedelta(days=7)).isoformat()  # GİRİŞ günü
        assert hits[0]["amount_eur"] == 500

    def test_per_invoice_deduction_applied(self, db):
        """Aktif kontrattaki per_invoice % kesinti (ör. Nordic %2 rehber+web) ciro
        kalemine NET uygulanır."""
        from app.models.contract import ContractDeduction

        g, c = _mk_contract(db)
        db.add(ContractDeduction(contract_id=c.id, deduction_type="representative_fee",
                                 percent=2, currency="EUR", applies="per_invoice"))
        co = self._same_year_checkout(10)
        _mk_reservation(db, "PTEST ACENTE", co, 1000)
        db.commit()
        invalidate_cache()

        p = contract_inflow_projections(db)
        hits = [i for i in p["ciro_items"] if i["agency"] == g.name]
        assert len(hits) == 1
        assert hits[0]["amount_eur"] == 980.0  # 1000 × (1 − %2)

    def test_advance_trim_is_group_scoped(self, db):
        """A grubunun bekleyen avansı B grubunun cirosunu KIRPMAZ (2026-08-13)."""
        ga_name = f"PGTEST{uuid4().hex[:6].upper()}"
        gb_name = f"PGTEST{uuid4().hex[:6].upper()}"
        ga = AgencyGroup(name=ga_name, members=[ga_name], term_days=21)
        gb = AgencyGroup(name=gb_name, members=[gb_name], term_days=21)
        db.add_all([ga, gb])
        db.flush()
        co = self._same_year_checkout(10)
        _mk_reservation(db, gb.name, co, 1000)
        # Avans A grubuna ait — B'nin cirosuna dokunmamalı
        db.add(Advance(agency_name=ga.name, amount=900, currency="EUR",
                       advance_date=co, status="pending"))
        db.commit()
        invalidate_cache()

        p = contract_inflow_projections(db)
        hits = [i for i in p["ciro_items"] if i["agency"] == gb.name]
        assert len(hits) == 1
        assert hits[0]["amount_eur"] == 1000  # kırpılmadı


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
