"""Faz B testleri (2026-07-11) — Sedna defter kuru + eşleşme izi + kur farkı +
entity sapma raporlama + rec_id-kimlikli import akışları + tam aynalama + endpoint'ler.

Kapsam:
A) fx_service.ledger_rate — Sedna-eşdeğer defter kuru (value_date−1, en yakın önceki, TRY→1.0)
B) finance_event_svc.match/unmatch/invalidate — event_matches kalıcı izi
C) Çapraz-para eşleşme → fx_differences (646/656 işaret kuralı); aynı para → kayıt YOK
D) sedna_recon_service.report_entity_diff / close_stale_entity_diffs — upsert/ignore/reopen
E) Cari Sedna import rec_id akışı — güncelleme / korunan sapma / otomatik kapanma / geri-doldurma
F) Çek Sedna import — eşleşmiş çekte Sedna farkı → 'check' entity sapması + rec_id damgası
G) Satış faturası TAM AYNALAMA — rec_id update / silme / 300-tavan iptali / hash damgalama
H) accounting/mutabakat endpoint'leri — fx-differences, fx-revaluation, items?entity_type

Tüm Sedna erişimi patch/monkeypatch ile sahtelenir — tünele ASLA bağlanılmaz.
"""
from datetime import date, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytz
from sqlalchemy import text

from app.constants import ReconStatus
from app.models import BankAccount, BankTransaction, SednaBankRecon
from app.models.check import Check, CheckUpload
from app.models.event_match import EventMatch, FxDifference
from app.models.exchange_rate import ExchangeRate
from app.models.finance_event import FinanceEvent
from app.models.sales_invoice import SalesCollection, SalesInvoice
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.services import fx_service
from app.services.sedna_recon_service import (
    close_stale_entity_diffs,
    report_entity_diff,
    resolve_recon_item,
)
from app.utils.finance_event_service import finance_event_svc
from app.utils.sedna_client import SednaUnavailable

tz_istanbul = pytz.timezone("Europe/Istanbul")
TODAY = datetime.now(tz_istanbul).date()

MUTABAKAT_API = "/api/accounting/mutabakat"
CARI_TARGET = "app.routers.finance.cariler.sedna_import"
CHECK_TARGET = "app.routers.finance.check_import"
SALES_TARGET = "app.routers.finance.sales_invoices"


# ─────────────────────────── Yardımcılar ───────────────────────────


def _sid() -> int:
    """Çakışmasız FinanceEvent source_id (BigInteger aralığında benzersiz)."""
    return 900_000_000 + (uuid4().int % 90_000_000)


def _eid() -> int:
    """Çakışmasız entity_id (sedna_bank_recon.entity_id için)."""
    return 800_000_000 + (uuid4().int % 90_000_000)


def _clear_rates(db, ccy, start, end):
    db.query(ExchangeRate).filter(
        ExchangeRate.currency_code == ccy,
        ExchangeRate.date >= start,
        ExchangeRate.date <= end,
    ).delete(synchronize_session=False)
    db.flush()


def _seed_rate(db, d, ccy, value, unit=1):
    db.query(ExchangeRate).filter(
        ExchangeRate.currency_code == ccy, ExchangeRate.date == d,
    ).delete(synchronize_session=False)
    db.add(ExchangeRate(date=d, currency_code=ccy, forex_buying=value, unit=unit))
    db.flush()


def _mk_fe(db, source_type, source_id, *, amount, direction, event_date,
           currency="TRY", description=None):
    fe = FinanceEvent(
        source_type=source_type, source_id=source_id, event_date=event_date,
        amount=amount, direction=direction, currency=currency, description=description,
    )
    db.add(fe)
    db.flush()
    return fe


def _unmap_all_accounts(db):
    """Deterministik değerleme: DB'deki tüm hesapların Sedna eşlemesini kaldır (SAVEPOINT içinde)."""
    db.query(BankAccount).update(
        {"sedna_account_code": None, "sedna_code_confirmed": False},
        synchronize_session=False,
    )
    db.flush()


def _mk_fx_account(db, currency="EUR"):
    """Onaylı Sedna kodlu, aktif DÖVİZ hesabı (değerleme kapsamına giren tek hesap)."""
    _unmap_all_accounts(db)
    acc = BankAccount(
        bank_name="Faz B Döviz Bankası",
        iban="TR{:024d}".format(uuid4().int % 10**24),
        currency=currency,
        is_active=True,
        sedna_account_code="102.95.{}.{}".format(uuid4().hex[:2], uuid4().hex[:4]),
        sedna_code_confirmed=True,
    )
    db.add(acc)
    db.flush()
    return acc


# ═══════════════════ A) ledger_rate ═══════════════════


class TestLedgerRate:
    def test_previous_day_forex_buying(self, db):
        """ledger_rate(G) = bizim (G−1) satırının forex_buying'i (Sedna 1 gün kayık semantiği)."""
        _clear_rates(db, "EUR", date(2026, 6, 25), date(2026, 7, 10))
        _seed_rate(db, date(2026, 7, 6), "EUR", 53.3716)
        assert fx_service.ledger_rate(db, date(2026, 7, 7), "EUR") == pytest.approx(53.3716)

    def test_weekend_gap_falls_back_to_previous(self, db):
        """(G−1) gününde kur yoksa (hafta sonu boşluğu) en yakın ÖNCEKİ günün kuru alınır."""
        _clear_rates(db, "EUR", date(2026, 6, 25), date(2026, 7, 10))
        _seed_rate(db, date(2026, 7, 3), "EUR", 52.5)   # boşluktan önceki son yayın
        # value_date=06.07 → boundary 05.07; 04-05.07 boş → 03.07 satırı döner
        assert fx_service.ledger_rate(db, date(2026, 7, 6), "EUR") == pytest.approx(52.5)

    def test_try_and_tl_return_one(self, db):
        assert fx_service.ledger_rate(db, TODAY, "TRY") == 1.0
        assert fx_service.ledger_rate(db, TODAY, "TL") == 1.0    # Sedna 'TL' çevrimi
        assert fx_service.ledger_rate(db, TODAY, None) == 1.0    # boş → TRY varsayımı

    def test_no_rate_returns_none(self, db):
        """Hiç kur satırı yoksa None döner (sessiz 0 üretilmez)."""
        db.query(ExchangeRate).filter(
            ExchangeRate.currency_code == "XXX").delete(synchronize_session=False)
        db.flush()
        assert fx_service.ledger_rate(db, TODAY, "XXX") is None


# ═══════════════════ B) event_matches izi ═══════════════════


class TestEventMatchTrace:
    def _pair(self, db, *, check_currency="TRY", check_amount=750.0, bank_amount=750.0,
              event_date=None):
        d = event_date or date(2026, 6, 10)
        bid, cid = _sid(), _sid()
        _mk_fe(db, "bank", bid, amount=bank_amount, direction=-1, event_date=d)
        _mk_fe(db, "check", cid, amount=check_amount, direction=-1,
               event_date=d, currency=check_currency)
        return bid, cid

    def test_match_creates_event_match_row(self, db):
        """match() → event_matches satırı: banka/hedef kimlikleri + hedef FE tutar/para birimi."""
        bid, cid = self._pair(db)
        finance_event_svc.match(db, "bank", bid, "check", cid, method="manual")

        m = db.query(EventMatch).filter(
            EventMatch.bank_source_type == "bank", EventMatch.bank_source_id == bid).one()
        assert m.target_source_type == "check" and m.target_source_id == cid
        assert float(m.amount) == 750.0
        assert m.currency == "TRY"
        assert m.method == "manual"
        # aynı para birimi (TRY↔TRY) → kur farkı kaydı OLUŞMAZ
        assert db.query(FxDifference).filter(
            FxDifference.event_match_id == m.id).count() == 0

    def test_unmatch_deletes_trace(self, db):
        bid, cid = self._pair(db)
        finance_event_svc.match(db, "bank", bid, "check", cid)
        assert db.query(EventMatch).filter(EventMatch.bank_source_id == bid).count() == 1

        finance_event_svc.unmatch(db, "check", cid)
        assert db.query(EventMatch).filter(EventMatch.bank_source_id == bid).count() == 0
        fe = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == "check", FinanceEvent.source_id == cid).one()
        assert fe.is_matched is False

    def test_invalidate_deletes_trace(self, db):
        bid, cid = self._pair(db)
        finance_event_svc.match(db, "bank", bid, "check", cid)
        finance_event_svc.invalidate(db, "check", cid)
        assert db.query(EventMatch).filter(EventMatch.target_source_id == cid).count() == 0
        assert db.query(FinanceEvent).filter(
            FinanceEvent.source_type == "check", FinanceEvent.source_id == cid).count() == 0


# ═══════════════════ C) Çapraz-para kur farkı ═══════════════════


class TestCrossCurrencyFxDiff:
    def _setup_rate(self, db, d, rate=50.0):
        _clear_rates(db, "EUR", d - timedelta(days=10), d + timedelta(days=3))
        _seed_rate(db, d - timedelta(days=1), "EUR", rate)

    def test_expense_paid_more_try_is_loss(self, db):
        """1000 EUR çek (defter kuru 50 → beklenen 50.000 TL), banka 51.000 TL ödedi →
        gider için fazla TL = kambiyo ZARARI: amount_try = 50.000 − 51.000 = −1.000."""
        d = date(2026, 7, 7)
        self._setup_rate(db, d, 50.0)
        bid, cid = _sid(), _sid()
        _mk_fe(db, "bank", bid, amount=51000.0, direction=-1, event_date=d)
        _mk_fe(db, "check", cid, amount=1000.0, direction=-1, event_date=d, currency="EUR")

        finance_event_svc.match(db, "bank", bid, "check", cid)

        m = db.query(EventMatch).filter(EventMatch.bank_source_id == bid).one()
        assert float(m.rate_used) == pytest.approx(50.0)   # hedef FE defter kuru
        fx = db.query(FxDifference).filter(FxDifference.event_match_id == m.id).one()
        assert float(fx.amount_try) == pytest.approx(-1000.0)   # zarar (−)
        assert float(fx.expected_try) == pytest.approx(50000.0)
        assert float(fx.realized_try) == pytest.approx(51000.0)
        assert float(fx.rate_estimate) == pytest.approx(50.0)
        assert float(fx.rate_realized) == pytest.approx(51.0)
        assert fx.source == fx_service.FX_SOURCE_MATCH
        assert fx.period == d

    def test_expense_paid_less_try_is_gain(self, db):
        """Gider beklenenden AZ TL ile kapandıysa kambiyo KARI (+)."""
        d = date(2026, 7, 7)
        self._setup_rate(db, d, 50.0)
        bid, cid = _sid(), _sid()
        _mk_fe(db, "bank", bid, amount=49000.0, direction=-1, event_date=d)
        _mk_fe(db, "check", cid, amount=1000.0, direction=-1, event_date=d, currency="EUR")

        finance_event_svc.match(db, "bank", bid, "check", cid)
        fx = db.query(FxDifference).join(
            EventMatch, FxDifference.event_match_id == EventMatch.id,
        ).filter(EventMatch.bank_source_id == bid).one()
        assert float(fx.amount_try) == pytest.approx(1000.0)   # kar (+)

    def test_same_currency_match_no_fx_diff(self, db):
        """TRY banka ↔ TRY hedef eşleşmesinde fx_differences kaydı OLUŞMAZ."""
        d = date(2026, 7, 7)
        bid, cid = _sid(), _sid()
        _mk_fe(db, "bank", bid, amount=1000.0, direction=-1, event_date=d)
        _mk_fe(db, "check", cid, amount=1000.0, direction=-1, event_date=d, currency="TRY")

        finance_event_svc.match(db, "bank", bid, "check", cid)
        m = db.query(EventMatch).filter(EventMatch.bank_source_id == bid).one()
        assert db.query(FxDifference).filter(
            FxDifference.event_match_id == m.id).count() == 0

    def test_unmatch_cascades_fx_diff(self, db):
        """unmatch → event_matches izi silinir, fx_differences FK CASCADE ile düşer."""
        d = date(2026, 7, 7)
        self._setup_rate(db, d, 50.0)
        bid, cid = _sid(), _sid()
        _mk_fe(db, "bank", bid, amount=51000.0, direction=-1, event_date=d)
        _mk_fe(db, "check", cid, amount=1000.0, direction=-1, event_date=d, currency="EUR")
        finance_event_svc.match(db, "bank", bid, "check", cid)
        m_id = db.query(EventMatch).filter(EventMatch.bank_source_id == bid).one().id
        assert db.query(FxDifference).filter(FxDifference.event_match_id == m_id).count() == 1

        finance_event_svc.unmatch(db, "check", cid)
        db.expire_all()
        assert db.query(EventMatch).filter(EventMatch.id == m_id).count() == 0
        assert db.query(FxDifference).filter(FxDifference.event_match_id == m_id).count() == 0


# ═══════════════════ D) report_entity_diff / close_stale ═══════════════════


class TestEntityDiffReporting:
    def _report(self, db, entity_type, entity_id, sedna_desc="Sedna: farklı"):
        return report_entity_diff(
            db, entity_type, entity_id,
            amount=1234.5, currency="TRY", event_date=TODAY,
            description="Yerel: kayıt", sedna_description=sedna_desc, sedna_rec_id=42,
        )

    def test_new_report_opens_sedna_diff(self, db):
        eid = _eid()
        item = self._report(db, "check", eid)
        assert item.status == ReconStatus.SEDNA_DIFF
        assert item.entity_type == "check" and item.entity_id == eid
        assert item.sedna_trans_rec_id == 42
        assert item.resolved_at is None
        assert float(item.amount) == 1234.5

    def test_second_report_upserts_no_duplicate(self, db):
        eid = _eid()
        first = self._report(db, "vendor_tx", eid)
        second = self._report(db, "vendor_tx", eid, sedna_desc="Sedna: güncel fark")
        assert second.id == first.id
        assert db.query(SednaBankRecon).filter(
            SednaBankRecon.entity_type == "vendor_tx",
            SednaBankRecon.entity_id == eid).count() == 1
        assert second.sedna_description == "Sedna: güncel fark"

    def test_ignored_item_not_reopened(self, db):
        eid = _eid()
        item = self._report(db, "check", eid)
        resolve_recon_item(db, item.id, "ignore", "bilinçli fark", None)

        again = self._report(db, "check", eid)
        assert again.id == item.id
        assert again.resolution == "ignored"           # yeniden AÇILMADI
        assert again.resolved_at is not None
        assert db.query(SednaBankRecon).filter(
            SednaBankRecon.entity_type == "check",
            SednaBankRecon.entity_id == eid).count() == 1

    def test_close_stale_closes_unseen_and_keeps_seen(self, db):
        eid_gone, eid_kept = _eid(), _eid()
        gone = self._report(db, "check", eid_gone)
        kept = self._report(db, "check", eid_kept)

        closed = close_stale_entity_diffs(db, "check", {eid_kept})
        assert closed >= 1
        db.expire_all()
        gone = db.query(SednaBankRecon).filter(SednaBankRecon.id == gone.id).one()
        kept = db.query(SednaBankRecon).filter(SednaBankRecon.id == kept.id).one()
        assert gone.status == ReconStatus.MATCHED and gone.resolution == "auto"
        assert gone.resolved_at is not None
        assert kept.resolved_at is None and kept.status == ReconStatus.SEDNA_DIFF

    def test_closed_diff_reopens_when_back(self, db):
        """Kapanan sapma geri gelirse aynı kayıt yeniden AÇILIR (yeni satır değil)."""
        eid = _eid()
        item = self._report(db, "vendor_tx", eid)
        close_stale_entity_diffs(db, "vendor_tx", set())
        db.expire_all()
        assert db.query(SednaBankRecon).filter(
            SednaBankRecon.id == item.id).one().resolved_at is not None

        again = self._report(db, "vendor_tx", eid)
        assert again.id == item.id
        assert again.resolved_at is None and again.resolution is None
        assert again.status == ReconStatus.SEDNA_DIFF
        assert db.query(SednaBankRecon).filter(
            SednaBankRecon.entity_type == "vendor_tx",
            SednaBankRecon.entity_id == eid).count() == 1


# ═══════════════════ E) Cari import rec_id akışı ═══════════════════


CARI_CODE = "320.66.01.R001"


def _crow(evrak, alacak=0, borc=0, rec_id=None, tarih=date(2026, 5, 4)):
    return {"hesap_kodu": CARI_CODE, "hesap_adi": "REC ID CARİ", "tarih": tarih,
            "evrak_no": evrak, "islem_tipi": None, "fis_no": None,
            "aciklama": "ev{}".format(evrak), "borc": borc, "alacak": alacak,
            "pay_day": 0, "rec_id": rec_id}


def _cimport(client, headers, rows, deleted=None):
    with patch(f"{CARI_TARGET}.sedna_configured", return_value=True), \
         patch(f"{CARI_TARGET}.fetch_cari_transactions", return_value=rows), \
         patch(f"{CARI_TARGET}.fetch_cari_deleted_rows", return_value=deleted or []):
        return client.post("/api/finance/cariler/sedna-import", headers=headers)


class TestCariRecIdImport:
    def _vendor_rows(self, db):
        v = db.query(Vendor).filter(Vendor.hesap_kodu == CARI_CODE).one()
        return v, db.query(VendorTransaction).filter(VendorTransaction.vendor_id == v.id).all()

    def test_rec_id_update_guard_and_autoclose_flow(self, client, auth_headers, db):
        """Uçtan uca rec_id akışı: damga → korumasız UPDATE → korunan sapma → otomatik kapanma."""
        # 1) İlk import: satır sedna_rec_id ile damgalanır
        r1 = _cimport(client, auth_headers, [_crow("R1", alacak=1000, rec_id=9101)])
        assert r1.status_code == 200, r1.text
        assert r1.json()["new_transactions"] == 1
        v, rows = self._vendor_rows(db)
        assert len(rows) == 1 and rows[0].sedna_rec_id == 9101
        row_id = rows[0].id

        # 2) Aynı rec_id + farklı tutar (korumasız) → AYNI satır güncellenir, mükerrer yok
        r2 = _cimport(client, auth_headers, [_crow("R1", alacak=1500, rec_id=9101)])
        assert r2.status_code == 200, r2.text
        assert r2.json()["new_transactions"] == 0
        db.expire_all()
        _, rows = self._vendor_rows(db)
        assert len(rows) == 1, "rec_id güncellemesi mükerrer satır üretmemeli"
        assert rows[0].id == row_id                      # id sabit → UPDATE
        assert float(rows[0].alacak) == 1500.0
        assert rows[0].payment_due_date is not None      # alacak → vade yeniden hesaplandı

        # 3) Satır korunuyor (match_number dolu) + Sedna farklı tutar → satır DEĞİŞMEZ,
        #    'vendor_tx' sapması açılır, mükerrer insert engellenir
        # (ORM attribute ataması — bulk update identity map'i tazelemez, import aynı
        #  session'da bayat match_number=None görürdü)
        rows[0].match_number = 777
        db.flush()
        r3 = _cimport(client, auth_headers, [_crow("R1", alacak=2000, rec_id=9101)])
        assert r3.status_code == 200, r3.text
        assert r3.json()["new_transactions"] == 0
        db.expire_all()
        _, rows = self._vendor_rows(db)
        assert len(rows) == 1 and rows[0].id == row_id
        assert float(rows[0].alacak) == 1500.0, "korunan satır Sedna'ya hizalanmamalı"
        recon = db.query(SednaBankRecon).filter(
            SednaBankRecon.entity_type == "vendor_tx",
            SednaBankRecon.entity_id == row_id).one()
        assert recon.status == ReconStatus.SEDNA_DIFF and recon.resolved_at is None
        assert recon.sedna_trans_rec_id == 9101
        assert "alacak 2000" in (recon.sedna_description or "")

        # 4) Sedna düzeltildi (fark kalmadı) → sapma kaydı OTOMATİK kapanır
        r4 = _cimport(client, auth_headers, [_crow("R1", alacak=1500, rec_id=9101)])
        assert r4.status_code == 200, r4.text
        db.expire_all()
        recon = db.query(SednaBankRecon).filter(SednaBankRecon.id == recon.id).one()
        assert recon.resolved_at is not None
        assert recon.resolution == "auto"
        assert recon.status == ReconStatus.MATCHED

    def test_rec_id_backfill_on_hash_match(self, client, auth_headers, db):
        """rec_id'siz eski satır, hash'i eşleşen Sedna satırının rec_id'siyle damgalanır."""
        assert _cimport(client, auth_headers, [_crow("B1", alacak=400)]).status_code == 200
        _, rows = self._vendor_rows(db)
        assert len(rows) == 1 and rows[0].sedna_rec_id is None

        j = _cimport(client, auth_headers, [_crow("B1", alacak=400, rec_id=9202)]).json()
        assert j["new_transactions"] == 0
        db.expire_all()
        _, rows = self._vendor_rows(db)
        assert len(rows) == 1 and rows[0].sedna_rec_id == 9202

    def test_guarded_row_deleted_in_sedna_reports_diff(self, client, auth_headers, db):
        """Korunan (eşleşmiş) satır Sedna'da SİLİNMİŞSE sapma raporlanır, satır silinmez."""
        assert _cimport(client, auth_headers, [
            _crow("D1", alacak=300, rec_id=9301),
            _crow("D2", alacak=50, rec_id=9302),
        ]).status_code == 200
        _, rows = self._vendor_rows(db)
        target = next(r for r in rows if r.evrak_no == "D1")
        target.match_number = 888
        db.flush()

        deleted = [{"hesap_kodu": CARI_CODE, "tarih": date(2026, 5, 4),
                    "evrak_no": "D1", "borc": 0, "alacak": 300}]
        r = _cimport(client, auth_headers, [_crow("D2", alacak=50, rec_id=9302)], deleted=deleted)
        assert r.status_code == 200, r.text
        db.expire_all()
        _, rows = self._vendor_rows(db)
        assert any(x.id == target.id for x in rows), "eşleşmiş satır silinmemeli"
        recon = db.query(SednaBankRecon).filter(
            SednaBankRecon.entity_type == "vendor_tx",
            SednaBankRecon.entity_id == target.id).one()
        assert recon.status == ReconStatus.SEDNA_DIFF and recon.resolved_at is None
        assert "SİLİNMİŞ" in (recon.sedna_description or "")


# ═══════════════════ F) Çek import entity sapması ═══════════════════


def _chimport(client, headers, rows):
    with patch(f"{CHECK_TARGET}.sedna_configured", return_value=True), \
         patch(f"{CHECK_TARGET}.fetch_issued_checks", return_value=rows):
        return client.post("/api/finance/checks/sedna-import", headers=headers)


class TestCheckEntityDiff:
    def _seed_matched_check(self, db):
        """Bankayla eşleşmiş (bank_transaction_id dolu) yerel çek."""
        acc = BankAccount(bank_name="Faz B Çek Bankası",
                          iban="TR{:024d}".format(uuid4().int % 10**24), currency="TRY")
        db.add(acc)
        db.flush()
        btx = BankTransaction(account_id=acc.id, date=date(2026, 6, 5),
                              description="ÇEK FZBCHK1 ödeme", amount=-10000,
                              type="expense", tx_hash="fazb-{}".format(uuid4().hex))
        db.add(btx)
        db.flush()
        up = CheckUpload(file_name="fazb-seed", file_url="x")
        db.add(up)
        db.flush()
        chk = Check(upload_id=up.id, check_no="FZBCHK1", vendor_code="320.88.01.0001",
                    vendor_name="FZB ÇEK CARİ", due_date=date(2026, 6, 5),
                    amount_tl=10000, currency="TL", amount_currency=10000,
                    transaction_type="Verilen Çek", status="paid",
                    bank_transaction_id=btx.id)
        db.add(chk)
        db.flush()
        return chk

    def _sedna_row(self, due, rec_id=4242):
        return {"vendor_code": "320.88.01.0001", "vendor_name": "FZB ÇEK CARİ",
                "check_no": "FZBCHK1", "bank": None, "city": None, "due_date": due,
                "amount_tl": 10000, "currency": "TL", "amount_currency": 10000,
                "max_pos": 100, "check_rec_id": rec_id}

    def test_matched_check_diff_reported_stamped_then_autoclosed(self, client, auth_headers, db):
        chk = self._seed_matched_check(db)

        # Sedna'da vade FARKLI → 'skipped' ama sapma açılır + rec_id damgalanır
        r = _chimport(client, auth_headers, [self._sedna_row(date(2026, 7, 10))])
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["new_checks"] == 0 and j["skipped_checks"] >= 1
        db.expire_all()
        fresh = db.query(Check).filter(Check.id == chk.id).one()
        assert fresh.due_date == date(2026, 6, 5), "eşleşmiş çek DEĞİŞMEMELİ"
        assert fresh.sedna_check_rec_id == 4242            # kalıcı kimlik damgası
        recon = db.query(SednaBankRecon).filter(
            SednaBankRecon.entity_type == "check",
            SednaBankRecon.entity_id == chk.id).one()
        assert recon.status == ReconStatus.SEDNA_DIFF and recon.resolved_at is None
        assert recon.sedna_trans_rec_id == 4242
        assert "2026-07-10" in (recon.sedna_description or "")

        # Sedna düzeltildi (vade aynı) → sapma OTOMATİK kapanır
        r2 = _chimport(client, auth_headers, [self._sedna_row(date(2026, 6, 5))])
        assert r2.status_code == 200, r2.text
        db.expire_all()
        recon = db.query(SednaBankRecon).filter(SednaBankRecon.id == recon.id).one()
        assert recon.resolved_at is not None and recon.resolution == "auto"
        assert recon.status == ReconStatus.MATCHED

    def test_matched_check_same_data_no_diff(self, client, auth_headers, db):
        """Eşleşmiş çekte fark yoksa sapma kaydı AÇILMAZ."""
        chk = self._seed_matched_check(db)
        r = _chimport(client, auth_headers, [self._sedna_row(date(2026, 6, 5))])
        assert r.status_code == 200, r.text
        assert db.query(SednaBankRecon).filter(
            SednaBankRecon.entity_type == "check",
            SednaBankRecon.entity_id == chk.id).count() == 0


# ═══════════════════ G) Satış faturası tam aynalama ═══════════════════


def _simport(client, headers, fake, accounts=None):
    with patch(f"{SALES_TARGET}.sedna_configured", return_value=True), \
         patch(f"{SALES_TARGET}.fetch_sales_invoices", return_value=fake), \
         patch(f"{SALES_TARGET}.fetch_advance_accounts", return_value=accounts or []), \
         patch("app.utils.sedna_client.fetch_agency_acc_codes", return_value=[]):
        return client.post("/api/finance/sales-invoices/sedna-import", headers=headers)


def _sinv(no, amount, rec_id=None, code="120.55.01.0001", d=date(2026, 3, 1)):
    row = {"customer_code": code, "customer_name": "FZB SATIŞ ACENTE",
           "invoice_date": d, "invoice_no": no, "amount": amount, "aciklama": "x"}
    if rec_id is not None:
        row["rec_id"] = rec_id
    return row


class TestSalesMirror:
    def test_rec_id_correction_updates_single_row(self, client, auth_headers, db):
        j1 = _simport(client, auth_headers,
                      {"invoices": [_sinv("FZ1", 1000, rec_id=7001)], "collections": []}).json()
        assert j1["invoices_new"] == 1

        j2 = _simport(client, auth_headers,
                      {"invoices": [_sinv("FZ1", 1200, rec_id=7001)], "collections": []}).json()
        assert j2["invoices_updated"] == 1
        assert j2["invoices_new"] == 0 and j2["invoices_removed"] == 0
        db.expire_all()
        rows = db.query(SalesInvoice).filter(SalesInvoice.sedna_rec_id == 7001).all()
        assert len(rows) == 1 and float(rows[0].amount) == 1200.0
        assert db.query(SalesInvoice).filter(SalesInvoice.invoice_no == "FZ1").count() == 1

    def test_rec_id_row_gone_from_sedna_is_deleted(self, client, auth_headers, db):
        j1 = _simport(client, auth_headers, {"invoices": [
            _sinv("FZ1", 1000, rec_id=7001), _sinv("FZ2", 2000, rec_id=7002),
        ], "collections": []}).json()
        assert j1["invoices_new"] == 2

        j2 = _simport(client, auth_headers,
                      {"invoices": [_sinv("FZ1", 1000, rec_id=7001)], "collections": []}).json()
        assert j2["invoices_removed"] == 1
        db.expire_all()
        assert db.query(SalesInvoice).filter(SalesInvoice.sedna_rec_id == 7002).count() == 0
        assert db.query(SalesInvoice).filter(SalesInvoice.sedna_rec_id == 7001).count() == 1

    def test_mirror_sweep_cap_aborts_deletion(self, client, auth_headers, db):
        """300'den fazla rec_id'li satır kaybolursa silme İPTAL edilir (kısmi veri sigortası)."""
        db.query(SalesInvoice).delete(synchronize_session=False)
        db.flush()
        db.add_all([
            SalesInvoice(customer_code="120.55.01.0001", customer_name="CAP TEST",
                         invoice_no="CAP{}".format(i), invoice_date=date(2026, 1, 1),
                         amount=10, tx_hash="fazb-cap-{}".format(i),
                         sedna_rec_id=810_000 + i)
            for i in range(301)
        ])
        db.flush()

        j = _simport(client, auth_headers, {"invoices": [], "collections": []}).json()
        assert j["invoices_removed"] == 0, "tavan aşımında silme iptal edilmeli"
        db.expire_all()
        assert db.query(SalesInvoice).filter(
            SalesInvoice.customer_code == "120.55.01.0001").count() == 301

    def test_hash_match_stamps_rec_id_on_legacy_row(self, client, auth_headers, db):
        """rec_id'siz eski satır, hash'i eşleşen Sedna satırıyla rec_id damgası alır."""
        j1 = _simport(client, auth_headers,
                      {"invoices": [_sinv("FZ4", 500)], "collections": []}).json()
        assert j1["invoices_new"] == 1
        row = db.query(SalesInvoice).filter(SalesInvoice.invoice_no == "FZ4").one()
        assert row.sedna_rec_id is None

        j2 = _simport(client, auth_headers,
                      {"invoices": [_sinv("FZ4", 500, rec_id=7100)], "collections": []}).json()
        assert j2["invoices_new"] == 0 and j2["invoices_skipped"] == 1
        db.expire_all()
        rows = db.query(SalesInvoice).filter(SalesInvoice.invoice_no == "FZ4").all()
        assert len(rows) == 1 and rows[0].sedna_rec_id == 7100

    def test_collection_rec_id_update_and_removal(self, client, auth_headers, db):
        """Tahsilat tarafında da aynalama: rec_id update + Sedna'dan kaybolunca silme."""
        col = {"customer_code": "120.55.01.0001", "customer_name": "FZB SATIŞ ACENTE",
               "collection_date": date(2026, 4, 1), "amount": 800, "aciklama": "t",
               "fis_no": 5, "rec_id": 7301}
        j1 = _simport(client, auth_headers, {"invoices": [], "collections": [col]}).json()
        assert j1["collections_new"] == 1

        j2 = _simport(client, auth_headers,
                      {"invoices": [], "collections": [dict(col, amount=900)]}).json()
        assert j2["collections_updated"] == 1 and j2["collections_new"] == 0
        db.expire_all()
        rows = db.query(SalesCollection).filter(SalesCollection.sedna_rec_id == 7301).all()
        assert len(rows) == 1 and float(rows[0].amount) == 900.0

        j3 = _simport(client, auth_headers, {"invoices": [], "collections": []}).json()
        assert j3["collections_removed"] == 1
        db.expire_all()
        assert db.query(SalesCollection).filter(
            SalesCollection.sedna_rec_id == 7301).count() == 0


# ═══════════════════ H) Mutabakat endpoint'leri ═══════════════════


class TestMutabakatFazBEndpoints:
    def test_fx_differences_endpoint_shape(self, client, auth_headers, db):
        db.add(FxDifference(period=date(2026, 7, 7), amount_try=-1000.0,
                            rate_estimate=50.0, rate_realized=51.0,
                            expected_try=50000.0, realized_try=51000.0,
                            source="match", description="fazb test"))
        db.flush()
        r = client.get(f"{MUTABAKAT_API}/fx-differences", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert {"items", "total", "page", "page_size", "pages", "total_amount_try"} <= set(d.keys())
        assert d["total"] >= 1
        ours = next(it for it in d["items"] if it["description"] == "fazb test")
        assert ours["amount_try"] == -1000.0
        assert ours["expected_try"] == 50000.0 and ours["realized_try"] == 51000.0
        assert ours["source"] == "match"

    def test_fx_differences_requires_view(self, client, no_perm_user_headers):
        assert client.get(f"{MUTABAKAT_API}/fx-differences",
                          headers=no_perm_user_headers).status_code == 403

    def test_fx_revaluation_endpoint_sedna_bekliyor(self, client, auth_headers, db, monkeypatch):
        """Type=4 fişi yok (valuation_tl None) → 'sedna_bekliyor'; rate/expected_try dolu."""
        import app.utils.sedna_client as sedna_client_module

        acc = _mk_fx_account(db, currency="EUR")
        db.add(BankTransaction(account_id=acc.id, date=date(2026, 6, 15),
                               description="fazb", amount=1000, type="income",
                               balance=1000, tx_hash="fazb-{}".format(uuid4().hex)))
        db.flush()
        _clear_rates(db, "EUR", date(2026, 6, 20), date(2026, 7, 2))
        _seed_rate(db, date(2026, 6, 30), "EUR", 47.0)   # ay sonu günü kuru (01.07 − 1)
        db.commit()

        monkeypatch.setattr(sedna_client_module, "fetch_bank_fx_valuation",
                            lambda codes, year, month: {})
        r = client.get(f"{MUTABAKAT_API}/fx-revaluation?year=2026&month=6", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["year"] == 2026 and d["month"] == 6
        item = next(it for it in d["items"] if it["account_id"] == acc.id)
        assert item["status"] == "sedna_bekliyor"
        assert item["our_fx_balance"] == 1000.0
        assert item["rate"] == pytest.approx(47.0)
        assert item["expected_try"] == pytest.approx(47000.0)
        assert item["sedna_valuation_tl"] is None

    def test_fx_revaluation_sedna_unavailable_503(self, client, auth_headers, db, monkeypatch):
        import app.utils.sedna_client as sedna_client_module

        _mk_fx_account(db, currency="EUR")
        db.commit()

        def _boom(codes, year, month):
            raise SednaUnavailable("tünel kapalı (test)")

        monkeypatch.setattr(sedna_client_module, "fetch_bank_fx_valuation", _boom)
        r = client.get(f"{MUTABAKAT_API}/fx-revaluation?year=2026&month=6", headers=auth_headers)
        assert r.status_code == 503

    def test_fx_revaluation_statuses_service_level(self, db):
        """Enjekte fetch_valuation ile mutabik/sapma durumları (tolerans: %0.5 veya 100 TL)."""
        acc = _mk_fx_account(db, currency="EUR")
        db.add(BankTransaction(account_id=acc.id, date=date(2026, 6, 10),
                               description="fazb", amount=1000, type="income",
                               balance=1000, tx_hash="fazb-{}".format(uuid4().hex)))
        db.flush()
        _clear_rates(db, "EUR", date(2026, 6, 20), date(2026, 7, 2))
        _seed_rate(db, date(2026, 6, 30), "EUR", 47.0)

        def _fetch(sedna_map):
            return lambda codes, year, month: {acc.sedna_account_code: sedna_map}

        ok = fx_service.compute_monthly_revaluation(
            db, 2026, 6,
            fetch_valuation=_fetch({"tl_balance": 47050.0, "fx_balance": 1000.0,
                                    "valuation_tl": 123.0}))
        assert ok["items"][0]["status"] == "mutabik"    # fark 50 ≤ max(235, 100)

        bad = fx_service.compute_monthly_revaluation(
            db, 2026, 6,
            fetch_valuation=_fetch({"tl_balance": 60000.0, "fx_balance": 1000.0,
                                    "valuation_tl": 123.0}))
        assert bad["items"][0]["status"] == "sapma"

    def test_items_entity_type_filter(self, client, auth_headers, db):
        eid_check, eid_vtx = _eid(), _eid()
        report_entity_diff(db, "check", eid_check, amount=10, currency="TRY",
                           event_date=TODAY, description="çek sapması",
                           sedna_description="s", sedna_rec_id=None)
        report_entity_diff(db, "vendor_tx", eid_vtx, amount=20, currency="TRY",
                           event_date=TODAY, description="cari sapması",
                           sedna_description="s", sedna_rec_id=None)
        db.flush()

        r = client.get(f"{MUTABAKAT_API}/items?entity_type=check", headers=auth_headers)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert all(it["entity_type"] == "check" for it in items)
        assert any(it["entity_id"] == eid_check for it in items)
        assert not any(it["entity_id"] == eid_vtx for it in items)

        # whitelist dışı entity_type → 422
        assert client.get(f"{MUTABAKAT_API}/items?entity_type=evil",
                          headers=auth_headers).status_code == 422
