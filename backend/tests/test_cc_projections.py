"""Kredi kartı ekstresi projeksiyonu — cc_projection_service + endpoint.

Yüklü ekstresi olmayan aylar için tahmini ekstre kalemleri: cari ay = kart limiti (rezerv),
ileri aylar = 0 (yalnız kesim/son-ödeme tarih göstergesi). Kesim/son-ödeme günleri en son
yüklü ekstreden türetilir (yoksa details). Determinizm için `today` parametresi sabitlenir.
"""

import json
from datetime import date

from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_product import CreditProduct
from app.services.cc_projection_service import compute_cc_projections, due_reserve_projections


def _card(db, *, name="Test Kart", limit=100000.0, status="active", details=None):
    c = CreditProduct(
        type="kredi_karti", name=name, bank_name="Test Bank",
        total_amount=limit, remaining_amount=0, status=status,
        details=json.dumps(details) if details else None,
    )
    db.add(c)
    db.flush()
    return c


def _stmt(db, card, *, kesim, son_odeme, toplam=50000.0):
    s = CreditCardStatement(
        credit_product_id=card.id, kesim_tarihi=kesim, son_odeme_tarihi=son_odeme,
        toplam_borc=toplam, is_paid=False, paid_amount=0,
    )
    db.add(s)
    db.flush()
    return s


def _due(proj, card_id):
    """Kartın son-ödeme (due) projeksiyon kalemleri (tarih sırasında)."""
    return [p for p in proj if p["card_id"] == card_id and p["projection_kind"] == "due"]


def _cut(proj, card_id):
    """Kartın kesim (Ekstre yükleyin) hatırlatıcı kalemleri."""
    return [p for p in proj if p["card_id"] == card_id and p["projection_kind"] == "cut"]


class TestCcProjectionService:
    def test_current_month_uses_limit_future_zero(self, db):
        c = _card(db, limit=100000.0, details={"ekstre_kesim_gunu": 10, "son_odeme_gunu": 15})
        due = _due(compute_cc_projections(db, today=date(2026, 7, 4), horizon_months=3), c.id)
        assert len(due) == 3
        cur = due[0]
        assert cur["is_current_month"] is True
        assert cur["amount"] == 100000.0
        assert cur["date"] == "2026-07-15"
        assert cur["kesim_date"] == "2026-07-10"
        assert cur["is_projected"] is True
        assert cur["source"] == "cc_payment"
        # ileri aylar → 0
        assert due[1]["amount"] == 0.0 and due[1]["is_current_month"] is False
        assert due[1]["date"] == "2026-08-15"
        assert due[2]["amount"] == 0.0 and due[2]["date"] == "2026-09-15"

    def test_cut_reminder_daily_current_month_only(self, db):
        # Kesim 10, son ödeme 15, bugün 07-04 → hatırlatıcı 07-10..07-15 HER GÜN (6 kalem),
        # YALNIZ cari ay (ileri aylarda kesim hatırlatıcısı yok)
        c = _card(db, limit=100000.0, details={"ekstre_kesim_gunu": 10, "son_odeme_gunu": 15})
        cut = _cut(compute_cc_projections(db, today=date(2026, 7, 4), horizon_months=3), c.id)
        dates = sorted(p["date"] for p in cut)
        assert dates == ["2026-07-10", "2026-07-11", "2026-07-12", "2026-07-13", "2026-07-14", "2026-07-15"]
        assert all(p["amount"] == 0.0 and p["son_odeme_date"] == "2026-07-15" for p in cut)
        assert all(p["date"][:7] == "2026-07" for p in cut)  # ileri aylarda YOK

    def test_cut_reminder_starts_today_if_cut_passed(self, db):
        # Bugün kesimden sonra (07-12), son ödeme 15 → hatırlatıcı bugünden (07-12) 07-15'e (4 gün)
        c = _card(db, limit=100000.0, details={"ekstre_kesim_gunu": 10, "son_odeme_gunu": 15})
        cut = _cut(compute_cc_projections(db, today=date(2026, 7, 12), horizon_months=1), c.id)
        assert sorted(p["date"] for p in cut) == ["2026-07-12", "2026-07-13", "2026-07-14", "2026-07-15"]

    def test_cut_reminder_none_after_due(self, db):
        # Bugün son ödemeyi geçmiş (07-20 > 15) → "Ekstre yükleyin" hatırlatıcısı YOK
        c = _card(db, limit=100000.0, details={"ekstre_kesim_gunu": 10, "son_odeme_gunu": 15})
        cut = _cut(compute_cc_projections(db, today=date(2026, 7, 20), horizon_months=1), c.id)
        assert cut == []

    def test_cut_reminder_gone_when_statement_uploaded(self, db):
        # Cari ay ekstresi yüklüyse o ay komple atlanır → kesim hatırlatıcısı da çıkmaz
        c = _card(db, limit=100000.0, details={"ekstre_kesim_gunu": 10, "son_odeme_gunu": 15})
        _stmt(db, c, kesim=date(2026, 7, 9), son_odeme=date(2026, 7, 15))
        proj = compute_cc_projections(db, today=date(2026, 7, 4), horizon_months=2)
        assert _cut(proj, c.id) == []

    def test_derives_days_from_latest_statement(self, db):
        # details 10/15 ama EN SON ekstre 9/14 → ekstreden türetilir
        c = _card(db, details={"ekstre_kesim_gunu": 10, "son_odeme_gunu": 15})
        _stmt(db, c, kesim=date(2026, 5, 9), son_odeme=date(2026, 5, 14))
        _stmt(db, c, kesim=date(2026, 6, 9), son_odeme=date(2026, 6, 14))
        due = _due(compute_cc_projections(db, today=date(2026, 7, 4), horizon_months=2), c.id)
        assert due[0]["kesim_date"] == "2026-07-09"
        assert due[0]["date"] == "2026-07-14"

    def test_falls_back_to_details_without_statements(self, db):
        c = _card(db, details={"ekstre_kesim_gunu": 25, "son_odeme_gunu": 30})
        due = _due(compute_cc_projections(db, today=date(2026, 7, 4), horizon_months=1), c.id)
        assert due[0]["kesim_date"] == "2026-07-25"
        assert due[0]["date"] == "2026-07-30"

    def test_skips_month_with_real_statement(self, db):
        c = _card(db, details={"ekstre_kesim_gunu": 10, "son_odeme_gunu": 15})
        # Temmuz ekstresi zaten yüklü → cari ay projeksiyonu atlanır
        _stmt(db, c, kesim=date(2026, 7, 9), son_odeme=date(2026, 7, 15))
        due = _due(compute_cc_projections(db, today=date(2026, 7, 4), horizon_months=3), c.id)
        months = [p["date"][:7] for p in due]
        assert "2026-07" not in months  # gerçek ekstre → projeksiyon yok
        assert "2026-08" in months

    def test_skips_closed_card(self, db):
        c = _card(db, status="closed", details={"ekstre_kesim_gunu": 10, "son_odeme_gunu": 15})
        proj = [p for p in compute_cc_projections(db, today=date(2026, 7, 4)) if p["card_id"] == c.id]
        assert proj == []

    def test_skips_card_without_days(self, db):
        c = _card(db, details=None)  # ekstre yok + details yok → türetilemez
        proj = [p for p in compute_cc_projections(db, today=date(2026, 7, 4)) if p["card_id"] == c.id]
        assert proj == []

    def test_due_day_clamped_to_month_end(self, db):
        # son ödeme günü 31 → Şubat'ta 28'e kırpılır (2026 artık yıl değil)
        c = _card(db, details={"ekstre_kesim_gunu": 28, "son_odeme_gunu": 31})
        due = _due(compute_cc_projections(db, today=date(2026, 2, 1), horizon_months=1), c.id)
        assert due[0]["date"] == "2026-02-28"

    def test_due_next_month_when_due_day_before_cut(self, db):
        # kesim 26, son ödeme 5 → ödeme sonraki aya taşar (offset 1)
        c = _card(db, details={"ekstre_kesim_gunu": 26, "son_odeme_gunu": 5})
        proj = compute_cc_projections(db, today=date(2026, 7, 4), horizon_months=1)
        due = _due(proj, c.id)
        assert due[0]["date"] == "2026-07-05"       # due-ay Temmuz
        assert due[0]["kesim_date"] == "2026-06-26"  # kesim bir önceki ay
        # kesim geçen ay (06-26) ama son ödeme bu ay (07-05) → hatırlatıcı bugünden (07-04)
        # son ödemeye (07-05) kadar cari ayda çıkar (geçmiş aya düşmez, bugünden başlar)
        assert sorted(p["date"] for p in _cut(proj, c.id)) == ["2026-07-04", "2026-07-05"]

    def test_current_month_zero_when_no_limit(self, db):
        c = _card(db, limit=0.0, details={"ekstre_kesim_gunu": 10, "son_odeme_gunu": 15})
        due = _due(compute_cc_projections(db, today=date(2026, 7, 4), horizon_months=1), c.id)
        assert due[0]["amount"] == 0.0
        assert due[0]["has_limit"] is False


class TestDueReserveProjections:
    """EUR bakiye + runway'in kullandığı yardımcı — yalnız tutar taşıyan (cari ay) due kalemleri."""

    def test_only_current_month_due_with_amount(self, db):
        c = _card(db, limit=100000.0, details={"ekstre_kesim_gunu": 10, "son_odeme_gunu": 15})
        reserves = [p for p in due_reserve_projections(db, today=date(2026, 7, 4)) if p["card_id"] == c.id]
        # yalnız 1 kalem: cari ay son ödemesi (limit); ileri-ay 0 ve kesim hatırlatıcıları hariç
        assert len(reserves) == 1
        assert reserves[0]["amount"] == 100000.0
        assert reserves[0]["projection_kind"] == "due"
        assert reserves[0]["date"] == "2026-07-15"

    def test_empty_when_no_limit(self, db):
        c = _card(db, limit=0.0, details={"ekstre_kesim_gunu": 10, "son_odeme_gunu": 15})
        reserves = [p for p in due_reserve_projections(db, today=date(2026, 7, 4)) if p["card_id"] == c.id]
        assert reserves == []  # limit 0 → rezerv yok


class TestCcProjectionEndpoint:
    def test_requires_view_permission(self, client, no_perm_user_headers):
        r = client.get("/api/finance/cash-flow/cc-projections", headers=no_perm_user_headers)
        assert r.status_code == 403

    def test_returns_items(self, client, auth_headers, db):
        _card(db, name="EP Projeksiyon Kart", details={"ekstre_kesim_gunu": 10, "son_odeme_gunu": 15})
        db.commit()
        r = client.get("/api/finance/cash-flow/cc-projections", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert any(it["description"].endswith("EP Projeksiyon Kart") for it in data["items"])
