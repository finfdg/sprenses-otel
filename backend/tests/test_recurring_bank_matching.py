"""Düzenli Ödeme (recurring) ↔ banka eşleştirmesi + para birimi kapısı (2026-07-28).

Canlı bulgu: `_match_scheduled_to_bank` yalnız salary/sgk/withholding tiplerini
kapsıyordu → her Düzenli Ödeme kaleminin banka bacağı ELLE bağlanmak zorundaydı ve
bağlanmayınca planlı bacak + banka bacağı ÇİFT sayılıyordu (Temmuz 2026 Leasing All
Risk Sigortası, €684,38: planlı 28.07 + banka 27.07).

Bu dosya iki şeyi sabitler:
1. `recurring` kapsama alındı — anahtar kelime TANIM ADINDAN türetilir; kelimesiz
   ("kör") toplu-transfer yolu bu tipe KAPALIDIR.
2. Para birimi kapısı — aday banka hareketinin HESAP para birimi girişinkiyle aynı
   olmalı; aksi halde |btx|/tutar oranı bir oran değil kur çarpanıdır.
"""
from datetime import date, timedelta
from uuid import uuid4

from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.event_match import MATCH_METHOD_SUGGESTION, EventMatch
from app.models.finance_event import FinanceEvent
from app.models.scheduled import ScheduledDefinition, ScheduledEntry
from app.models.transaction_category import TransactionCategory
from app.utils.finance_event_service import finance_event_svc
from app.utils.matching_service import _match_scheduled_to_bank, _recurring_keyword_re

API = "/api/finance/cash-flow"
TODAY = date.today()

# Canlı vakanın açıklaması (VakıfBank, btx#6430) — kısaltılmış
LEASING_DESC = ("Gönderilen havale FİNANSAL KİRALAMA SİGORTA ÖDEMESİ / "
                "TR54 0001 5001 58** **** **07 65 nolu MURAT-A TURİZM hesabından "
                "VAKIF FİNANSAL KİRALAMA ANONİM ŞİRKETİ hesabına havale yapılmıştır.")


# ─── yardımcılar ─────────────────────────────────────────────────────────────

def _mk_account(db, *, currency="TRY", bank_name="Düzenli Test Bankası"):
    acc = BankAccount(bank_name=bank_name, iban=f"TR{uuid4().hex}"[:34],
                      currency=currency, is_active=True)
    db.add(acc)
    db.flush()
    return acc


def _mk_btx(db, acc, *, amount, tx_date=None, desc="DÜZENLİ TEST HAREKETİ"):
    btx = BankTransaction(
        account_id=acc.id, date=tx_date or TODAY, description=desc,
        amount=amount, balance=0,
        type="expense" if amount < 0 else "income",
        tx_hash=f"recurring-{uuid4().hex}",
    )
    db.add(btx)
    db.flush()
    return btx


def _mk_entry(db, *, name, amount, entry_date=None, currency="EUR",
              source_type="recurring", category=None, is_paid=False, paid_date=None,
              synced_from_cari=False):
    entry_date = entry_date or TODAY
    defn = ScheduledDefinition(
        source_type=source_type, name=name, category=category,
        amount=amount, year=entry_date.year, frequency="monthly",
        payment_day=min(entry_date.day, 28), start_month=1, currency=currency,
    )
    db.add(defn)
    db.flush()
    entry = ScheduledEntry(
        definition_id=defn.id, source_type=source_type, entry_date=entry_date,
        period_year=entry_date.year, period_month=entry_date.month, amount=amount,
        currency=currency, description=f"[Düzenli Ödeme] {name}",
        is_paid=is_paid, paid_date=paid_date, synced_from_cari=synced_from_cari,
    )
    db.add(entry)
    db.flush()
    finance_event_svc.upsert_scheduled_entry(db, entry, direction=-1)
    db.flush()
    return defn, entry


def _fe(db, source_type, source_id):
    return db.query(FinanceEvent).filter(
        FinanceEvent.source_type == source_type,
        FinanceEvent.source_id == source_id,
    ).first()


def _suggestions(db, *, target_type=None, target_id=None):
    q = db.query(EventMatch).filter(EventMatch.method == MATCH_METHOD_SUGGESTION)
    if target_type:
        q = q.filter(EventMatch.target_source_type == target_type)
    if target_id:
        q = q.filter(EventMatch.target_source_id == target_id)
    return q.all()


def _ensure_category(db, name, color="amber"):
    cat = db.query(TransactionCategory).filter(TransactionCategory.name == name).first()
    if cat is None:
        cat = TransactionCategory(name=name, color=color)
        db.add(cat)
        db.flush()
    return cat


# ─── 1) Tanım adından anahtar kelime üretimi ─────────────────────────────────

class TestRecurringKeywordRegex:
    def test_turkish_suffix_tolerated_via_stem(self):
        """"Sigortası" → "sigort" kökü; banka açıklamasındaki "SİGORTA" ile eşleşir."""
        from app.utils.auto_tagger import _normalize

        re_ = _recurring_keyword_re("2026 Leasing All Risk Sigortası (Trafo)", "Sigorta")
        assert re_ is not None
        assert re_.search(_normalize(LEASING_DESC)) is not None

    def test_generic_only_name_yields_none(self):
        """Yalnız genel sözcük/sayı içeren ad ayırt edici kelime üretmez → None."""
        assert _recurring_keyword_re("Temmuz 2026 Ödeme", None) is None
        assert _recurring_keyword_re("", "") is None

    def test_short_tokens_dropped(self):
        """5 karakterden kısa kök elenir ("risk" gibi kolay eşleşen tokenlar)."""
        re_ = _recurring_keyword_re("Risk KDV Su", None)
        assert re_ is None


# ─── 2) Otomatik eşleşme + çift sayım kapanması ──────────────────────────────

class TestRecurringAutoMatch:
    def test_leasing_insurance_auto_closed_by_definition_name(self, db):
        """Canlı vaka: EUR düzenli ödeme + aynı tutarlı EUR banka çıkışı (bir gün önce)
        → otomatik kapanır, paid_date banka tarihini alır, FE eşleşir (çift sayım biter)."""
        acc = _mk_account(db, currency="EUR", bank_name="VakıfBank")
        paid_on = TODAY - timedelta(days=1)
        defn, entry = _mk_entry(db, name="2026 Leasing All Risk Sigortası (Trafo)",
                                category="Sigorta", amount=684.38, currency="EUR")
        btx = _mk_btx(db, acc, amount=-684.38, tx_date=paid_on, desc=LEASING_DESC)
        db.commit()

        r = _match_scheduled_to_bank(db)
        assert r["matched"] == 1

        db.expire_all()
        e = db.get(ScheduledEntry, entry.id)
        assert e.is_paid is True
        assert e.paid_date == paid_on
        fe = _fe(db, "recurring", entry.id)
        assert fe.is_matched is True and fe.is_realized is True
        # Kalıcı iz kuruldu → tekrar koşuda aday olmaz
        assert db.query(EventMatch).filter(
            EventMatch.target_source_type == "recurring",
            EventMatch.target_source_id == entry.id,
            EventMatch.method != MATCH_METHOD_SUGGESTION,
        ).count() == 1

    def test_bank_leg_tagged_with_definition_category(self, db):
        """recurring'in kanonik kategorisi tanımın `category` alanıdır → banka bacağı
        o kategoriyi alır (salary→Personel eşleniği)."""
        _ensure_category(db, "Sigorta")
        acc = _mk_account(db, currency="EUR")
        defn, entry = _mk_entry(db, name="Leasing All Risk Sigortası", category="Sigorta",
                                amount=684.38, currency="EUR")
        btx = _mk_btx(db, acc, amount=-684.38, tx_date=TODAY, desc=LEASING_DESC)
        db.commit()

        assert _match_scheduled_to_bank(db)["matched"] == 1
        db.refresh(btx)
        cat = db.query(TransactionCategory).filter(
            TransactionCategory.id == btx.category_id).first()
        assert cat is not None and cat.name == "Sigorta"

    def test_two_candidates_only_suggestion(self, db):
        """İki uygun aday → otomatik kapanmaz, en iyi aday öneriye düşer."""
        acc = _mk_account(db, currency="EUR")
        defn, entry = _mk_entry(db, name="Leasing All Risk Sigortası", amount=684.38,
                                currency="EUR")
        _mk_btx(db, acc, amount=-684.38, tx_date=TODAY, desc=LEASING_DESC)
        _mk_btx(db, acc, amount=-684.38, tx_date=TODAY - timedelta(days=2),
                desc=LEASING_DESC)
        db.commit()

        r = _match_scheduled_to_bank(db)
        assert r["matched"] == 0 and r["suggested"] == 1
        db.expire_all()
        assert db.get(ScheduledEntry, entry.id).is_paid is False
        assert len(_suggestions(db, target_type="recurring", target_id=entry.id)) == 1


# ─── 3) Para birimi kapısı ───────────────────────────────────────────────────

class TestCurrencyGate:
    def test_try_transaction_not_candidate_for_eur_entry(self, db):
        """€684,38 giriş ile ₺684,38 hareket r=1.0 verir ama AYNI PARA DEĞİL →
        ne otomatik ne öneri. Kapı olmadan bu yanlış eşleşirdi."""
        acc = _mk_account(db, currency="TRY")
        defn, entry = _mk_entry(db, name="Leasing All Risk Sigortası", amount=684.38,
                                currency="EUR")
        _mk_btx(db, acc, amount=-684.38, tx_date=TODAY, desc=LEASING_DESC)
        db.commit()

        r = _match_scheduled_to_bank(db)
        assert r["matched"] == 0 and r["suggested"] == 0
        db.expire_all()
        assert db.get(ScheduledEntry, entry.id).is_paid is False
        assert _suggestions(db, target_type="recurring", target_id=entry.id) == []

    def test_tl_alias_treated_as_try(self, db):
        """'TL' kodu 'TRY' ile aynı sayılır (normalize) → eşleşme kurulur."""
        acc = _mk_account(db, currency="TL")
        defn, entry = _mk_entry(db, name="Leasing All Risk Sigortası", amount=25_000.0,
                                currency="TRY")
        _mk_btx(db, acc, amount=-25_000.0, tx_date=TODAY, desc=LEASING_DESC)
        db.commit()

        assert _match_scheduled_to_bank(db)["matched"] == 1

    def test_suggestion_records_entry_currency_not_hardcoded_try(self, db):
        """Öneri kaydı girişin para birimini taşır (eskiden sabit 'TRY' yazılıyordu)."""
        acc = _mk_account(db, currency="EUR")
        defn, entry = _mk_entry(db, name="Leasing All Risk Sigortası", amount=684.38,
                                currency="EUR")
        _mk_btx(db, acc, amount=-684.38, tx_date=TODAY, desc=LEASING_DESC)
        _mk_btx(db, acc, amount=-684.38, tx_date=TODAY - timedelta(days=2),
                desc=LEASING_DESC)
        db.commit()

        assert _match_scheduled_to_bank(db)["suggested"] == 1
        sug = _suggestions(db, target_type="recurring", target_id=entry.id)[0]
        assert sug.currency == "EUR"

    def test_salary_try_path_unaffected(self, db):
        """Regresyon: personel kör yolu TRY↔TRY'de eskisi gibi çalışır (kapı bozmadı)."""
        acc = _mk_account(db, currency="TRY")
        pay_day = TODAY - timedelta(days=1)
        defn, entry = _mk_entry(db, name="MAAŞ TEST", source_type="salary",
                                amount=12_000_000.0, currency="TRY",
                                entry_date=pay_day, is_paid=True, paid_date=pay_day)
        _mk_btx(db, acc, amount=-11_409_775.06, tx_date=pay_day,
                desc="Para Gönder Internet - Mobil TİCARET SANAYİ")
        db.commit()

        assert _match_scheduled_to_bank(db)["matched"] == 1
        db.expire_all()
        assert _fe(db, "salary", entry.id).is_matched is True


# ─── 4) Kör yol recurring'e kapalı ───────────────────────────────────────────

class TestRecurringBlindPathClosed:
    def test_no_keyword_large_transfer_not_matched_or_suggested(self, db):
        """Kelimesiz etiketsiz büyük transfer düzenli ödemeye BAĞLANMAZ — kör bant
        yalnız personel tiplerinde geçerli (küçük+çok sayıda kalemde yanlış-pozitif)."""
        acc = _mk_account(db, currency="TRY")
        defn, entry = _mk_entry(db, name="Leasing All Risk Sigortası",
                                amount=12_000_000.0, currency="TRY",
                                is_paid=True, paid_date=TODAY)
        _mk_btx(db, acc, amount=-12_000_000.0, tx_date=TODAY,
                desc="Para Gönder Internet - Mobil TİCARET SANAYİ")
        db.commit()

        r = _match_scheduled_to_bank(db)
        assert r["matched"] == 0 and r["suggested"] == 0

    def test_generic_named_definition_produces_no_candidates(self, db):
        """Ayırt edici kelimesi olmayan tanım (yalnız genel sözcük) hiç aday üretmez."""
        acc = _mk_account(db, currency="TRY")
        defn, entry = _mk_entry(db, name="Aylık Ödeme", amount=5_000.0, currency="TRY")
        _mk_btx(db, acc, amount=-5_000.0, tx_date=TODAY, desc="AYLIK ÖDEME")
        db.commit()

        r = _match_scheduled_to_bank(db)
        assert r["matched"] == 0 and r["suggested"] == 0


# ─── 5) Cari-senkronlu aylar kapsam dışı ─────────────────────────────────────

class TestSyncedFromCariExcluded:
    def test_cari_synced_entry_never_matched(self, db):
        """`synced_from_cari` ayın otoritesi `recurring_vendor_sync`'tir: o akış ödenen ayın
        finance_event'ini BİLEREK siler (nakit akımı cari/banka bacağı temsil eder). Buradan
        bağlamak FE'yi geri yaratır + tutarı banka bacağına çeker, sonraki senkron ikisini de
        geri alır → her koşuda ping-pong. Canlı kuru çalışmada yakalandı (CK Akdeniz elektrik)."""
        acc = _mk_account(db, currency="TRY")
        defn, entry = _mk_entry(db, name="2026 Elektrik", category="Fatura",
                                amount=1_404_820.40, currency="TRY",
                                is_paid=True, paid_date=TODAY, synced_from_cari=True)
        # Cari senkronunun yaptığı gibi FE'yi kaldır (ödenen ay)
        finance_event_svc.invalidate(db, "recurring", entry.id)
        _mk_btx(db, acc, amount=-1_378_310.00, tx_date=TODAY,
                desc="CLK Akdeniz Elektrik Tahsilatı Hesap Numarası:9126051491")
        db.commit()

        r = _match_scheduled_to_bank(db)
        assert r["matched"] == 0 and r["suggested"] == 0
        db.expire_all()
        e = db.get(ScheduledEntry, entry.id)
        assert float(e.amount) == 1_404_820.40  # cari faturasının tutarı korundu
        assert _fe(db, "recurring", entry.id) is None  # FE geri yaratılmadı


# ─── 6) Öneri "Onayla" yolu recurring'i tanır ────────────────────────────────

class TestAcceptRecurringSuggestion:
    def test_accept_closes_recurring_entry(self, client, auth_headers, db):
        """Öneri paneli "Onayla" → link_entry_to_bank koşar (tip listesi recurring'i
        kapsamasaydı 409 "hedef kapanmış" dönerdi)."""
        acc = _mk_account(db, currency="EUR")
        defn, entry = _mk_entry(db, name="Leasing All Risk Sigortası", amount=684.38,
                                currency="EUR")
        btx = _mk_btx(db, acc, amount=-684.38, tx_date=TODAY, desc=LEASING_DESC)
        _mk_btx(db, acc, amount=-684.38, tx_date=TODAY - timedelta(days=2),
                desc=LEASING_DESC)
        db.commit()

        assert _match_scheduled_to_bank(db)["suggested"] == 1
        db.commit()
        sug = _suggestions(db, target_type="recurring", target_id=entry.id)[0]

        resp = client.post(f"{API}/match-suggestions/{sug.id}/accept", headers=auth_headers)
        assert resp.status_code == 200, resp.text

        db.expire_all()
        assert db.get(ScheduledEntry, entry.id).is_paid is True
        assert _fe(db, "recurring", entry.id).is_matched is True
        assert _suggestions(db, target_type="recurring", target_id=entry.id) == []

    def test_suggestion_list_enriches_recurring_target(self, client, auth_headers, db):
        """Öneri listesi recurring hedefini açıklama/tarihle zenginleştirir."""
        acc = _mk_account(db, currency="EUR")
        defn, entry = _mk_entry(db, name="Leasing All Risk Sigortası", amount=684.38,
                                currency="EUR")
        _mk_btx(db, acc, amount=-684.38, tx_date=TODAY, desc=LEASING_DESC)
        _mk_btx(db, acc, amount=-684.38, tx_date=TODAY - timedelta(days=2),
                desc=LEASING_DESC)
        db.commit()
        assert _match_scheduled_to_bank(db)["suggested"] == 1
        db.commit()

        resp = client.get(f"{API}/match-suggestions", headers=auth_headers)
        assert resp.status_code == 200
        row = next(i for i in resp.json()["items"]
                   if i["target_source_type"] == "recurring"
                   and i["target_source_id"] == entry.id)
        assert "Leasing" in (row["target_description"] or "")
        assert row["target_date"] == entry.entry_date.isoformat()
