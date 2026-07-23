"""Sedna karşı-hesap köprüsü testleri (services/sedna_tag_bridge).

Mutabakatta eşleşen ETİKETSİZ banka hareketlerinin fiş karşı-hesabından kategorize
edilmesi (2026-07-23): 335/196→Personel, 320→Cari (+vendor_id/tag_note yalnız exact),
360→Vergi/SGK; 102-yalnız fişte Virman / Döviz Satışı; haritasız (770) ve karışık k↔k
gruplar ATLANIR; manuel etiket ve "pos bloke" açıklaması DOKUNULMAZ; Sedna kopuksa
köprü hatası mutabakat koşusunu düşürmez.
"""

from datetime import date, datetime, timedelta
from uuid import uuid4

import pytz

from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.finance_event import FinanceEvent
from app.models.transaction_category import TransactionCategory
from app.models.vendor import Vendor
from app.services.sedna_recon_service import _match_account, run_reconciliation
from app.services.sedna_tag_bridge import apply_sedna_tag_bridge, decide_category
from app.utils.finance_event_service import finance_event_svc
from app.utils.sedna_client import SednaUnavailable

tz_istanbul = pytz.timezone("Europe/Istanbul")
TODAY = datetime.now(tz_istanbul).date()


# ─────────────────────────── Yardımcılar ───────────────────────────

def _b(i, d, a):
    return {"id": i, "date": d, "amount": float(a), "description": f"banka {i}"}


def _s(i, d, a, owner_id=None):
    return {"rec_id": i, "owner_id": owner_id if owner_id is not None else i * 10,
            "voucher": i, "fiche_date": d, "amount": float(a), "remark": f"sedna {i}",
            "record_user": "sednauser", "change_date": None}


def _leg(owner_id, code, debit=0.0, credit=0.0, name=""):
    return {"owner_id": owner_id, "code": code, "debit": debit, "credit": credit,
            "account_name": name}


def _unmap_all(db):
    db.query(BankAccount).update(
        {"sedna_account_code": None, "sedna_code_confirmed": False},
        synchronize_session=False,
    )
    db.flush()


def _mk_account(db, *, currency="TRY", sedna_code=None, confirmed=True):
    acc = BankAccount(
        bank_name="Köprü Test Bankası",
        iban="TR{:024d}".format(uuid4().int % 10**24),
        currency=currency, is_active=True,
        sedna_account_code=sedna_code, sedna_code_confirmed=confirmed,
    )
    db.add(acc)
    db.flush()
    return acc


def _mapped_account(db, currency="TRY"):
    _unmap_all(db)
    code = "102.90.{}.{}".format(uuid4().hex[:2], uuid4().hex[:4])
    return _mk_account(db, currency=currency, sedna_code=code, confirmed=True)


def _mk_btx(db, acc, d, amount, description="Para Gönder Diğer TEST KİŞİ",
            category_id=None, tag_source=None):
    btx = BankTransaction(
        account_id=acc.id, date=d, amount=amount,
        type="income" if amount >= 0 else "expense",
        description=description, source="statement",
        tx_hash=f"bridge-{uuid4().hex}",
        category_id=category_id, tag_source=tag_source,
    )
    db.add(btx)
    db.flush()
    return btx


def _sedna_ledger_row(code, fiche_date, amount, rec_id):
    """run_reconciliation fetch_rows satırı (TRY hesap: Debit/Credit taşır)."""
    return {
        "rec_id": rec_id, "owner_id": rec_id * 10, "voucher": rec_id,
        "fiche_date": fiche_date, "record_date": fiche_date, "change_date": None,
        "record_user": "sednauser", "owner_type": 0, "code": code,
        "debit": amount if amount > 0 else 0, "credit": -amount if amount < 0 else 0,
        "curr": "TL", "rate": 1, "curr_debit": 0, "curr_credit": 0,
        "remark": "Sedna test fişi",
    }


def _run(db, rows, legs, **kw):
    """Sedna'ya dokunmadan koşu (fetch'ler enjekte, bildirim kapalı)."""
    return run_reconciliation(
        db,
        fetch_rows=lambda codes, start: rows,
        fetch_max_dates=lambda codes: {},
        fetch_legs=(legs if callable(legs) else (lambda owner_ids: legs)),
        notify=False,
        **kw,
    )


def _cat_name(db, btx):
    db.expire_all()
    fresh = db.get(BankTransaction, btx.id)
    if fresh.category_id is None:
        return None
    return db.get(TransactionCategory, fresh.category_id).name


# ─────────────── A) decide_category (saf) ───────────────

class TestDecideCategory:
    def test_personel_avans_fisi(self):
        legs = [
            _leg(10, "102.01.01.0001", credit=15000.0),
            _leg(10, "335.01.05.0026", debit=15000.0, name="HÜSEYİN YILDIZ"),
            _leg(10, "196.01.03.0008", debit=100.0, name="PERSONEL AVANS"),
        ]
        cat, dec = decide_category(legs, "102.01.01.0001", "TRY", {})
        assert cat == "Personel"
        assert dec["code"].startswith("335")  # en büyük |tutar|lı 102-dışı bacak

    def test_unmapped_prefix_skipped(self):
        legs = [_leg(10, "102.01.01.0001", credit=500.0),
                _leg(10, "770.07.01.0002", debit=500.0, name="BANKA MASRAFLARI")]
        assert decide_category(legs, "102.01.01.0001", "TRY", {}) == (None, None)

    def test_bank_only_same_currency_virman(self):
        legs = [_leg(10, "102.01.01.0001", credit=9000.0),
                _leg(10, "102.02.01.0005", debit=9000.0)]
        cat, _ = decide_category(legs, "102.01.01.0001", "TRY",
                                 {"102.02.01.0005": "TRY"})
        assert cat == "Virman"

    def test_bank_only_cross_currency_doviz_satisi(self):
        legs = [_leg(10, "102.03.01.0002", credit=36000.0),
                _leg(10, "102.01.01.0001", debit=1500000.0)]
        cat, _ = decide_category(legs, "102.03.01.0002", "EUR",
                                 {"102.01.01.0001": "TRY"})
        assert cat == "Döviz Satışı"

    def test_own_leg_excluded_empty_fise_none(self):
        legs = [_leg(10, "102.01.01.0001", credit=100.0)]
        assert decide_category(legs, "102.01.01.0001", "TRY", {}) == (None, None)


# ─────────────── B) _match_account match_groups_out ───────────────

class TestMatchGroupsOut:
    def test_exact_pair(self):
        d = TODAY - timedelta(days=2)
        out = []
        _match_account([_b(1, d, -15000.0)], [_s(1, d, -15000.0)],
                       sedna_max_date=TODAY, match_groups_out=out)
        assert len(out) == 1
        assert out[0]["exact"] is True
        assert [x["id"] for x in out[0]["btxs"]] == [1]
        assert [x["rec_id"] for x in out[0]["sednas"]] == [1]

    def test_k_by_k_group_not_exact(self):
        d = TODAY - timedelta(days=2)
        out = []
        _match_account([_b(1, d, -15000.0), _b(2, d, -15000.0)],
                       [_s(1, d, -15000.0), _s(2, d, -15000.0)],
                       sedna_max_date=TODAY, match_groups_out=out)
        assert len(out) == 1
        assert out[0]["exact"] is False
        assert len(out[0]["btxs"]) == 2 and len(out[0]["sednas"]) == 2

    def test_window_pair_not_exact(self):
        out = []
        _match_account([_b(1, TODAY - timedelta(days=3), -777.0)],
                       [_s(1, TODAY - timedelta(days=1), -777.0)],
                       sedna_max_date=TODAY, match_groups_out=out)
        assert len(out) == 1
        assert out[0]["exact"] is False

    def test_no_out_param_backwards_compatible(self):
        d = TODAY - timedelta(days=2)
        assert _match_account([_b(1, d, 100.0)], [_s(1, d, 100.0)],
                              sedna_max_date=TODAY) == []


# ─────────────── C) Köprü uçtan uca (run_reconciliation) ───────────────

class TestBridgeEndToEnd:
    def test_personel_fisi_tags_untagged_btx(self, db):
        acc = _mapped_account(db)
        d = TODAY - timedelta(days=2)
        btx = _mk_btx(db, acc, d, -15000.0, description="Para Gönder Diğer GÜNAL")
        finance_event_svc.upsert_bank_tx(db, btx, acc)
        db.flush()
        rows = [_sedna_ledger_row(acc.sedna_account_code, d, -15000.0, rec_id=1)]
        legs = [_leg(10, acc.sedna_account_code, credit=15000.0),
                _leg(10, "335.01.05.0576", debit=15000.0, name="HALİL GÜNAL"),
                _leg(10, "196.01.03.0008", debit=10.0, name="PERSONEL AVANS")]

        summary = _run(db, rows, legs)

        assert summary["sedna_tagged"] == 1
        assert _cat_name(db, btx) == "Personel"
        fresh = db.get(BankTransaction, btx.id)
        assert fresh.tag_source == "sedna"
        assert fresh.tag_note == "Sedna: HALİL GÜNAL"
        fe = db.query(FinanceEvent).filter(
            FinanceEvent.source_type == "bank", FinanceEvent.source_id == btx.id).first()
        assert fe is not None and fe.category_name == "Personel"

    def test_cari_fisi_exact_assigns_vendor(self, db):
        acc = _mapped_account(db)
        d = TODAY - timedelta(days=2)
        code = "320.01.01.T{}".format(uuid4().hex[:3].upper())
        vendor = Vendor(hesap_kodu=code, hesap_adi="TAÇ KERESTE TEST")
        db.add(vendor)
        db.flush()
        btx = _mk_btx(db, acc, d, -178878.0, description="Para Gönder Diğer TAAH.")
        rows = [_sedna_ledger_row(acc.sedna_account_code, d, -178878.0, rec_id=2)]
        legs = [_leg(20, acc.sedna_account_code, credit=178878.0),
                _leg(20, code, debit=178878.0, name="TAÇ KERESTE TEST")]

        summary = _run(db, rows, legs)

        assert summary["sedna_tagged"] == 1
        assert _cat_name(db, btx) == "Cari"
        fresh = db.get(BankTransaction, btx.id)
        assert fresh.vendor_id == vendor.id
        assert fresh.tag_note == "Sedna: TAÇ KERESTE TEST"

    def test_pre_tagged_btx_untouched(self, db):
        acc = _mapped_account(db)
        d = TODAY - timedelta(days=2)
        manual_cat = db.query(TransactionCategory).first()
        if manual_cat is None:
            manual_cat = TransactionCategory(name=f"Test Kat {uuid4().hex[:6]}", color="gray")
            db.add(manual_cat)
            db.flush()
        btx = _mk_btx(db, acc, d, -5000.0, category_id=manual_cat.id, tag_source="manual")
        rows = [_sedna_ledger_row(acc.sedna_account_code, d, -5000.0, rec_id=3)]
        legs = [_leg(30, acc.sedna_account_code, credit=5000.0),
                _leg(30, "335.01.03.0027", debit=5000.0, name="KİŞİ")]

        summary = _run(db, rows, legs)

        assert summary["sedna_tagged"] == 0
        fresh = db.get(BankTransaction, btx.id)
        assert fresh.category_id == manual_cat.id
        assert fresh.tag_source == "manual"

    def test_ambiguous_mixed_categories_skipped(self, db):
        # Aynı gün aynı tutar: biri personel fişi, biri cari fişi → çaprazlanma
        # riski, İKİSİ DE etiketlenmez
        acc = _mapped_account(db)
        d = TODAY - timedelta(days=2)
        b1 = _mk_btx(db, acc, d, -15000.0, description="Para Gönder Diğer A")
        b2 = _mk_btx(db, acc, d, -15000.0, description="Para Gönder Diğer B")
        rows = [_sedna_ledger_row(acc.sedna_account_code, d, -15000.0, rec_id=4),
                _sedna_ledger_row(acc.sedna_account_code, d, -15000.0, rec_id=5)]
        legs = [_leg(40, acc.sedna_account_code, credit=15000.0),
                _leg(40, "335.01.05.0001", debit=15000.0, name="KİŞİ"),
                _leg(50, acc.sedna_account_code, credit=15000.0),
                _leg(50, "320.01.01.0001", debit=15000.0, name="FİRMA")]

        summary = _run(db, rows, legs)

        assert summary["sedna_tagged"] == 0
        assert summary["sedna_tag_skipped_ambiguous"] == 2
        assert _cat_name(db, b1) is None and _cat_name(db, b2) is None

    def test_ambiguous_same_category_tagged(self, db):
        # k↔k ama İKİ fiş de Personel → çaprazlansa bile kategori doğru, etiketlenir
        acc = _mapped_account(db)
        d = TODAY - timedelta(days=2)
        b1 = _mk_btx(db, acc, d, -15000.0, description="Para Gönder Diğer A")
        b2 = _mk_btx(db, acc, d, -15000.0, description="Para Gönder Diğer B")
        rows = [_sedna_ledger_row(acc.sedna_account_code, d, -15000.0, rec_id=6),
                _sedna_ledger_row(acc.sedna_account_code, d, -15000.0, rec_id=7)]
        legs = [_leg(60, acc.sedna_account_code, credit=15000.0),
                _leg(60, "335.01.05.0001", debit=15000.0, name="KİŞİ A"),
                _leg(70, acc.sedna_account_code, credit=15000.0),
                _leg(70, "335.01.05.0002", debit=15000.0, name="KİŞİ B")]

        summary = _run(db, rows, legs)

        assert summary["sedna_tagged"] == 2
        assert _cat_name(db, b1) == "Personel" and _cat_name(db, b2) == "Personel"
        # Çaprazlanma riski: k↔k grupta kişi adı tag_note'a YAZILMAZ
        db.expire_all()
        assert db.get(BankTransaction, b1.id).tag_note is None

    def test_pos_bloke_description_skipped(self, db):
        acc = _mapped_account(db)
        d = TODAY - timedelta(days=2)
        btx = _mk_btx(db, acc, d, -8000.0, description="UBLK/123 POS BLOKE ÇÖZÜM")
        rows = [_sedna_ledger_row(acc.sedna_account_code, d, -8000.0, rec_id=8)]
        legs = [_leg(80, acc.sedna_account_code, credit=8000.0),
                _leg(80, "335.01.01.0001", debit=8000.0, name="KİŞİ")]

        summary = _run(db, rows, legs)

        assert summary["sedna_tagged"] == 0
        assert _cat_name(db, btx) is None

    def test_fetch_legs_failure_does_not_break_recon(self, db):
        acc = _mapped_account(db)
        d = TODAY - timedelta(days=2)
        btx = _mk_btx(db, acc, d, -1234.0)
        rows = [_sedna_ledger_row(acc.sedna_account_code, d, -1234.0, rec_id=9)]

        def _boom(owner_ids):
            raise SednaUnavailable("tünel kapalı")

        summary = _run(db, rows, _boom)

        # Mutabakat sonucu korunur, köprü sessizce 0 döner
        assert summary["accounts_scanned"] == 1
        assert summary["sedna_tagged"] == 0
        assert _cat_name(db, btx) is None


# ─────────────── D) apply_sedna_tag_bridge (doğrudan) ───────────────

class TestBridgeDirect:
    def test_empty_groups_noop(self, db):
        assert apply_sedna_tag_bridge(db, []) == {"sedna_tagged": 0}

    def test_unmapped_prefix_counted(self, db):
        acc = _mapped_account(db)
        d = TODAY - timedelta(days=2)
        btx = _mk_btx(db, acc, d, -500.0, description="Ücret tahsilatı dışı gider")
        groups = [{"account": acc, "groups": [
            {"btxs": [_b(btx.id, d, -500.0)], "sednas": [_s(1, d, -500.0, owner_id=10)],
             "exact": True},
        ]}]
        legs = [_leg(10, acc.sedna_account_code, credit=500.0),
                _leg(10, "770.07.01.0002", debit=500.0, name="BANKA MASRAFLARI")]

        result = apply_sedna_tag_bridge(db, groups, fetch_legs=lambda ids: legs)

        assert result["sedna_tagged"] == 0
        assert result["sedna_tag_skipped_unmapped"] == 1
        assert _cat_name(db, btx) is None
