"""Personel birleştirmesi (2026-07-18) — üç parçanın regresyon ağı:

1. T-Hesap başlık birleştirme: salary/sgk/withholding planlı kalemleri banka
   "Personel" kategorisiyle TEK "Personel" grubunda toplanır (t_account.SOURCE_LABELS).
2. Maaş tahmini ↔ Sedna bordro senkronu (salary_sync_service): ödenmemiş + ayı
   bitmiş dönemin tutarı 335 tahakkukuna çekilir; gelecek dönem / ödenmiş giriş /
   işlenmemiş bordro (tahakkuk < %40) korunur.
3. Planlı personel ↔ banka eşleştirici (_match_scheduled_to_bank): çift sayım
   dedup'u — anahtar kelimeli otomatik kapama, elle-ödendi attach, kelimesiz toplu
   transfer önerisi, banka kanıtının tutarı gerçeğe çekmesi, öneri kalıcılığı.
"""
from datetime import date, timedelta
from uuid import uuid4

from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.event_match import MATCH_METHOD_SUGGESTION, EventMatch
from app.models.exchange_rate import ExchangeRate
from app.models.finance_event import FinanceEvent
from app.models.scheduled import ScheduledDefinition, ScheduledEntry
from app.models.transaction_category import TransactionCategory
from app.services.salary_sync_service import sync_salary_from_sedna
from app.services.scheduled_service import close_entry_via_bank, link_entry_to_bank
from app.utils.finance_event_service import finance_event_svc
from app.utils.matching_service import (
    _match_scheduled_to_bank,
    cleanup_stale_suggestions,
    run_all_matchers,
)

TODAY = date.today()


# ─── yardımcılar ─────────────────────────────────────────────────────────────

def _mk_account(db, *, currency="TRY", bank_name="Personel Test Bankası"):
    acc = BankAccount(bank_name=bank_name, iban=f"TR{uuid4().hex}"[:34],
                      currency=currency, is_active=True)
    db.add(acc)
    db.flush()
    return acc


def _mk_btx(db, acc, *, amount, tx_date=None, desc="PERSONEL TEST HAREKETİ"):
    btx = BankTransaction(
        account_id=acc.id, date=tx_date or TODAY, description=desc,
        amount=amount, balance=0,
        type="expense" if amount < 0 else "income",
        tx_hash=f"personel-{uuid4().hex}",
    )
    db.add(btx)
    db.flush()
    return btx


def _mk_entry(db, *, source_type, amount, entry_date, period=None,
              is_paid=False, paid_date=None, with_fe=True):
    period = period or (entry_date.year, entry_date.month)
    defn = ScheduledDefinition(
        source_type=source_type, name=f"PERSONEL TEST {uuid4().hex[:6]}",
        amount=amount, year=period[0], frequency="monthly",
        payment_day=min(entry_date.day, 28), start_month=1,
    )
    db.add(defn)
    db.flush()
    entry = ScheduledEntry(
        definition_id=defn.id, source_type=source_type, entry_date=entry_date,
        period_year=period[0], period_month=period[1], amount=amount,
        currency="TRY", description=f"[Test] {source_type} girişi",
        is_paid=is_paid, paid_date=paid_date,
    )
    db.add(entry)
    db.flush()
    if with_fe:
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


def _ensure_category(db, name, color="pink"):
    cat = db.query(TransactionCategory).filter(TransactionCategory.name == name).first()
    if cat is None:
        cat = TransactionCategory(name=name, color=color)
        db.add(cat)
        db.flush()
    return cat


def _mk_eur_rate(db, dt, value=48.0):
    db.query(ExchangeRate).filter(
        ExchangeRate.date == dt, ExchangeRate.currency_code == "EUR"
    ).delete(synchronize_session=False)
    db.add(ExchangeRate(date=dt, currency_code="EUR", unit=1,
                        forex_buying=value, forex_selling=value))
    db.flush()


# ─── 1) T-Hesap başlık birleştirme ───────────────────────────────────────────

class TestTAccountPersonelMerge:
    def test_source_labels_merged(self):
        # 2026-07-18 revizyonu (kullanıcı): stopaj/SGK vergisel yükümlülük →
        # banka "Vergi/SGK" kategorisiyle birleşir; yalnız maaş "Personel"de kalır.
        from app.routers.finance.cash_flow.t_account import SOURCE_LABELS
        assert SOURCE_LABELS["salary"] == "Personel"
        assert SOURCE_LABELS["sgk"] == "Vergi/SGK"
        assert SOURCE_LABELS["withholding"] == "Vergi/SGK"

    def test_taccount_groups_planned_and_bank_under_personel(self, client, auth_headers, db):
        """Maaş planlısı + 'Personel' etiketli banka gideri TEK 'Personel' grubunda;
        SGK planlısı 'Vergi/SGK' grubuna düşer (ayrı Maaş/SGK başlığı kalmaz)."""
        _mk_eur_rate(db, TODAY - timedelta(days=1))
        cat = _ensure_category(db, "Personel")
        acc = _mk_account(db)
        future = TODAY + timedelta(days=3)
        _mk_entry(db, source_type="salary", amount=120000.0, entry_date=future)
        _mk_entry(db, source_type="sgk", amount=30000.0, entry_date=future)
        btx = _mk_btx(db, acc, amount=-5000.0, tx_date=TODAY, desc="PERSONEL ÖDEMESİ")
        finance_event_svc.upsert_bank_tx(db, btx, acc)
        finance_event_svc.sync_tag(db, btx.id, cat.id, cat.name, cat.color,
                                   None, "manual", None, None, None)
        db.commit()

        resp = client.get("/api/finance/cash-flow/t-account?period=monthly&offset=0",
                          headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        labels = [g["label"] for g in body["cikis"]]
        assert "Personel" in labels
        for eski in ("Maaş", "SGK", "Stopaj"):
            assert eski not in labels
        grp = next(g for g in body["cikis"] if g["label"] == "Personel")
        assert grp["item_count"] >= 2  # maaş planlısı + banka bacağı aynı grupta
        vergi = next(g for g in body["cikis"] if g["label"] == "Vergi/SGK")
        assert vergi["item_count"] >= 1  # SGK planlısı vergisel grupta


# ─── 2) Maaş ↔ Sedna bordro senkronu ─────────────────────────────────────────

class TestSalarySedaSync:
    def test_completed_period_updated_to_accrual(self, db):
        today = date(2026, 7, 18)
        defn, entry = _mk_entry(db, source_type="salary", amount=12_000_000.0,
                                entry_date=date(2026, 7, 10), period=(2026, 6))
        payroll = [{"ay": "2026-06", "tahakkuk": 13_523_065.40, "odenen": 14_889_027.67}]
        result = sync_salary_from_sedna(db, payroll=payroll, today=today)
        assert result["entries_updated"] == 1
        db.expire_all()
        e = db.get(ScheduledEntry, entry.id)
        assert float(e.amount) == 13_523_065.40
        fe = _fe(db, "salary", entry.id)
        assert float(fe.amount) == 13_523_065.40

    def test_incomplete_period_untouched(self, db):
        """Dönem ayı bitmeden elle tahmine dokunulmaz (mevsimsel tahmin korunur)."""
        today = date(2026, 7, 18)
        defn, entry = _mk_entry(db, source_type="salary", amount=13_000_000.0,
                                entry_date=date(2026, 8, 10), period=(2026, 7))
        payroll = [{"ay": "2026-07", "tahakkuk": 12_500_000.0, "odenen": 0}]
        result = sync_salary_from_sedna(db, payroll=payroll, today=today)
        assert result["entries_updated"] == 0
        db.expire_all()
        assert float(db.get(ScheduledEntry, entry.id).amount) == 13_000_000.0

    def test_partial_accrual_skipped(self, db):
        """Tahakkuk mevcut tahminin %40'ının altındaysa bordro işlenmemiştir → atla."""
        today = date(2026, 8, 3)
        defn, entry = _mk_entry(db, source_type="salary", amount=13_000_000.0,
                                entry_date=date(2026, 8, 10), period=(2026, 7))
        payroll = [{"ay": "2026-07", "tahakkuk": 224_686.0, "odenen": 0}]
        result = sync_salary_from_sedna(db, payroll=payroll, today=today)
        assert result["entries_updated"] == 0
        assert result["entries_skipped_no_accrual"] == 1
        db.expire_all()
        assert float(db.get(ScheduledEntry, entry.id).amount) == 13_000_000.0

    def test_paid_entry_untouched(self, db):
        today = date(2026, 7, 18)
        defn, entry = _mk_entry(db, source_type="salary", amount=11_500_000.0,
                                entry_date=date(2026, 6, 10), period=(2026, 5),
                                is_paid=True, paid_date=date(2026, 6, 10))
        payroll = [{"ay": "2026-05", "tahakkuk": 15_198_014.50, "odenen": 0}]
        result = sync_salary_from_sedna(db, payroll=payroll, today=today)
        assert result["entries_updated"] == 0
        db.expire_all()
        assert float(db.get(ScheduledEntry, entry.id).amount) == 11_500_000.0


# ─── 3) Planlı personel ↔ banka eşleştirici (dedup) ──────────────────────────

class TestScheduledBankMatcher:
    def test_sgk_keyword_auto_close_updates_amount(self, db):
        """SGK MOSİP açıklamalı gider + tek açık SGK girişi (±%30 içinde) → otomatik
        kapanır; giriş tutarı banka GERÇEĞİNE çekilir; FE gizlenir (çift sayım biter)."""
        _ensure_category(db, "Vergi/SGK", color="red")
        acc = _mk_account(db)
        on = TODAY - timedelta(days=3)
        defn, entry = _mk_entry(db, source_type="sgk", amount=3_000_000.0, entry_date=on)
        btx = _mk_btx(db, acc, amount=-3_516_007.34, tx_date=on,
                      desc="SGK MOSİP Tahsilatı Sicil No: 2551001011")
        db.commit()

        r = _match_scheduled_to_bank(db)
        assert r["matched"] == 1
        db.expire_all()
        e = db.get(ScheduledEntry, entry.id)
        assert e.is_paid is True
        assert float(e.amount) == 3_516_007.34  # banka kanıtı tahmini ezdi
        fe = _fe(db, "sgk", entry.id)
        assert fe.is_matched is True and fe.is_realized is True
        # Banka bacağı kanonik kategorisini aldı → T-Hesap başlığı doğru
        db.refresh(btx)
        cat = db.query(TransactionCategory).filter(TransactionCategory.id == btx.category_id).first()
        assert cat is not None and cat.name == "Vergi/SGK"

    def test_paid_unmatched_salary_attached_to_bank(self, db):
        """Elle 'ödendi' işaretlenmiş maaş girişi + aynı gün etiketsiz büyük transfer
        (kelimesiz, ±%15) → attach: FE eşlenir, tutar gerçeğe çekilir."""
        _ensure_category(db, "Personel")
        acc = _mk_account(db)
        pay_day = TODAY - timedelta(days=8)
        defn, entry = _mk_entry(db, source_type="salary", amount=12_000_000.0,
                                entry_date=pay_day, is_paid=True, paid_date=pay_day)
        btx = _mk_btx(db, acc, amount=-11_409_775.06, tx_date=pay_day,
                      desc="Para Gönder Internet - Mobil TİCARET SANAYİ")
        db.commit()

        r = _match_scheduled_to_bank(db)
        assert r["matched"] == 1
        db.expire_all()
        e = db.get(ScheduledEntry, entry.id)
        assert float(e.amount) == 11_409_775.06
        fe = _fe(db, "salary", entry.id)
        assert fe.is_matched is True
        db.refresh(btx)
        cat = db.query(TransactionCategory).filter(TransactionCategory.id == btx.category_id).first()
        assert cat is not None and cat.name == "Personel"

    def test_open_salary_blind_transfer_only_suggested(self, db):
        """AÇIK maaş girişi + kelimesiz toplu transfer → OTOMATİK KAPANMAZ (aynı gün
        benzer tutarlı cari EFT riski); öneri yazılır, giriş açık kalır."""
        acc = _mk_account(db)
        defn, entry = _mk_entry(db, source_type="salary", amount=12_000_000.0,
                                entry_date=TODAY)
        btx = _mk_btx(db, acc, amount=-11_400_000.0, tx_date=TODAY,
                      desc="Para Gönder Internet - Mobil TİCARET SANAYİ")
        db.commit()

        r = _match_scheduled_to_bank(db)
        assert r["matched"] == 0 and r["suggested"] == 1
        db.expire_all()
        assert db.get(ScheduledEntry, entry.id).is_paid is False
        sugs = _suggestions(db, target_type="salary", target_id=entry.id)
        assert len(sugs) == 1 and sugs[0].bank_source_id == btx.id

    def test_manual_other_category_not_candidate(self, db):
        """Kullanıcının farklı manuel etiketi (ör. Virman) aday olamaz."""
        virman = _ensure_category(db, "Virman", color="purple")
        acc = _mk_account(db)
        defn, entry = _mk_entry(db, source_type="salary", amount=12_000_000.0,
                                entry_date=TODAY, is_paid=True, paid_date=TODAY)
        btx = _mk_btx(db, acc, amount=-12_200_000.0, tx_date=TODAY,
                      desc="Hesaba Giden EFT MURAT-A")
        btx.category_id = virman.id
        btx.tag_source = "manual"
        db.commit()

        r = _match_scheduled_to_bank(db)
        assert r["matched"] == 0 and r["suggested"] == 0

    def test_currency_mismatch_keeps_estimate(self, db):
        """Döviz hesabından kapanan giriş: eşleşir ama TRY tahmini EZİLMEZ."""
        acc = _mk_account(db, currency="EUR")
        defn, entry = _mk_entry(db, source_type="withholding", amount=20_000.0,
                                entry_date=TODAY)
        btx = _mk_btx(db, acc, amount=-21_000.0, tx_date=TODAY, desc="STOPAJ ÖDEMESİ")
        db.commit()

        assert close_entry_via_bank(db, entry, btx) is True
        db.expire_all()
        e = db.get(ScheduledEntry, entry.id)
        assert e.is_paid is True
        assert float(e.amount) == 20_000.0  # kur çevirisi yok → tahmin korunur

    def test_suggestion_persists_via_orchestrator(self, db):
        """run_all_matchers yalnız-öneri koşusunda da commit eder (2026-07-18 düzeltme:
        eskiden matched==0 → SAVEPOINT rollback öneriyi sessizce siliyordu)."""
        acc = _mk_account(db)
        defn, entry = _mk_entry(db, source_type="salary", amount=12_000_000.0,
                                entry_date=TODAY)
        _mk_btx(db, acc, amount=-11_400_000.0, tx_date=TODAY,
                desc="Para Gönder Internet - Mobil TİCARET")
        db.commit()

        run_all_matchers(db)
        assert len(_suggestions(db, target_type="salary", target_id=entry.id)) == 1

    def test_stale_cleanup_keeps_paid_unmatched_suggestion(self, db):
        """Elle-ödendi ama eşleşmemiş girişin önerisi bayat SAYILMAZ; eşleşince silinir."""
        acc = _mk_account(db)
        defn, entry = _mk_entry(db, source_type="salary", amount=12_000_000.0,
                                entry_date=TODAY, is_paid=True, paid_date=TODAY)
        btx = _mk_btx(db, acc, amount=-11_400_000.0, tx_date=TODAY, desc="TRANSFER")
        db.add(EventMatch(
            bank_source_type="bank", bank_source_id=btx.id,
            target_source_type="salary", target_source_id=entry.id,
            amount=11_400_000.0, currency="TRY",
            method=MATCH_METHOD_SUGGESTION, score=50,
        ))
        db.flush()

        cleanup_stale_suggestions(db)
        assert len(_suggestions(db, target_type="salary", target_id=entry.id)) == 1

        assert link_entry_to_bank(db, entry, btx) is True
        cleanup_stale_suggestions(db)
        assert _suggestions(db, target_type="salary", target_id=entry.id) == []


# ─── 4) Eşleşme bayrağı bütünlüğü (2026-07-19 canlı denetim regresyonu) ──────
# Canlı bulgu: banka↔planlı eşleşme izi event_matches'te dururken hedef FE
# is_matched=False kalabiliyordu → t_account iki bacağı da toplayıp geçmiş ay
# giderlerini ÇİFT sayıyordu (Haziran ~€94K). İki kök: (a) upsert_scheduled_entry
# sabit False yazıp eşleşme SONRASI re-upsert'te bayrağı sıfırlıyordu; (b) kısmi
# (r<0.75) banka bacağı öneri-Onayla'da planlı toplamı eziyordu.

class TestMatchFlagIntegrity:
    def test_partial_suggestion_accept_marks_target_matched(self, client, auth_headers, db):
        """KISMİ (r=0.5) öneri Onayla → hedef planlı FE is_matched=True + is_realized=True,
        banka bacağı görünür kalır, planlı TUTAR kısmi banka tutarıyla EZİLMEZ."""
        acc = _mk_account(db)
        pay_day = TODAY - timedelta(days=3)
        defn, entry = _mk_entry(db, source_type="withholding", amount=2_000_000.0,
                                entry_date=pay_day, is_paid=True, paid_date=pay_day)
        btx = _mk_btx(db, acc, amount=-1_000_000.0, tx_date=pay_day,
                      desc="Vergi Tahsilatı G.STOPAJ Tahsilatı Taksit:1")
        finance_event_svc.upsert_bank_tx(db, btx, acc)
        sug = EventMatch(
            bank_source_type="bank", bank_source_id=btx.id,
            target_source_type="withholding", target_source_id=entry.id,
            amount=1_000_000.0, currency="TRY",
            method=MATCH_METHOD_SUGGESTION, score=60,
        )
        db.add(sug)
        db.commit()

        resp = client.post(f"/api/finance/cash-flow/match-suggestions/{sug.id}/accept",
                           headers=auth_headers)
        assert resp.status_code == 200, resp.text

        db.expire_all()
        fe = _fe(db, "withholding", entry.id)
        assert fe.is_matched is True
        assert fe.is_realized is True
        bank_fe = _fe(db, "bank", btx.id)
        assert bank_fe.is_matched is False  # banka bacağı tek gerçek olarak görünür kalır
        e = db.get(ScheduledEntry, entry.id)
        assert float(e.amount) == 2_000_000.0  # kısmi ₺1M planlı ₺2M'yi ezmedi
        # Kalıcı iz gerçek eşleşme oldu (öneri düştü)
        assert _suggestions(db, target_type="withholding", target_id=entry.id) == []
        real = db.query(EventMatch).filter(
            EventMatch.target_source_type == "withholding",
            EventMatch.target_source_id == entry.id,
            EventMatch.method != MATCH_METHOD_SUGGESTION).all()
        assert len(real) == 1

    def test_reupsert_after_match_preserves_is_matched(self, db):
        """Eşleşme SONRASI girişe dokunan re-upsert (PATCH/tutar düzeltmesi) bayrağı
        SIFIRLAMAMALI — eski davranış sabit False yazıp çift sayımı geri getiriyordu."""
        from app.services.scheduled_service import apply_entry_update

        acc = _mk_account(db)
        pay_day = TODAY - timedelta(days=2)
        defn, entry = _mk_entry(db, source_type="sgk", amount=3_000_000.0,
                                entry_date=pay_day, is_paid=True, paid_date=pay_day)
        btx = _mk_btx(db, acc, amount=-3_000_000.0, tx_date=pay_day,
                      desc="SGK MOSİP Tahsilatı PRİM ÖDEMESİ")
        assert link_entry_to_bank(db, entry, btx) is True
        assert _fe(db, "sgk", entry.id).is_matched is True

        # Kullanıcı girişin tutarını düzeltir → FE yeniden yazılır
        apply_entry_update(db, entry, {"amount": 3_516_007.34}, direction=-1)
        db.flush()

        fe = _fe(db, "sgk", entry.id)
        assert fe.is_matched is True, "re-upsert eşleşme bayrağını sıfırladı (çift sayım geri döner)"
        assert float(fe.amount) == 3_516_007.34

    def test_unmatch_then_reupsert_stays_unmatched(self, db):
        """unmatch izi de sildiğinden sonraki re-upsert bayrağı yeniden AÇMAMALI."""
        acc = _mk_account(db)
        pay_day = TODAY - timedelta(days=2)
        defn, entry = _mk_entry(db, source_type="withholding", amount=1_500_000.0,
                                entry_date=pay_day, is_paid=True, paid_date=pay_day)
        btx = _mk_btx(db, acc, amount=-1_500_000.0, tx_date=pay_day,
                      desc="Vergi Tahsilatı G.STOPAJ Tahsilatı")
        assert link_entry_to_bank(db, entry, btx) is True

        finance_event_svc.unmatch(db, "withholding", entry.id)
        finance_event_svc.upsert_scheduled_entry(db, entry, direction=-1)
        db.flush()

        assert _fe(db, "withholding", entry.id).is_matched is False

    def test_partial_bank_close_keeps_planned_amount(self, db):
        """AÇIK girişi kısmi banka kanıtıyla kapatmak (close_entry_via_bank) planlı
        tutarı korur; tam-ödeme bandındaki kanıt ise tutarı gerçeğe çeker."""
        acc = _mk_account(db)
        pay_day = TODAY - timedelta(days=1)

        defn1, partial_entry = _mk_entry(db, source_type="withholding", amount=2_000_000.0,
                                         entry_date=pay_day)
        btx_partial = _mk_btx(db, acc, amount=-1_000_000.0, tx_date=pay_day,
                              desc="Vergi Tahsilatı G.STOPAJ Taksit:1")
        assert close_entry_via_bank(db, partial_entry, btx_partial) is True
        db.expire_all()
        e1 = db.get(ScheduledEntry, partial_entry.id)
        assert float(e1.amount) == 2_000_000.0  # r=0.5 → planlı toplam korunur
        assert e1.is_paid is True
        assert _fe(db, "withholding", partial_entry.id).is_matched is True

        defn2, full_entry = _mk_entry(db, source_type="withholding", amount=2_000_000.0,
                                      entry_date=pay_day)
        btx_full = _mk_btx(db, acc, amount=-1_900_000.0, tx_date=pay_day,
                           desc="Vergi Tahsilatı G.STOPAJ Tahsilatı")
        assert close_entry_via_bank(db, full_entry, btx_full) is True
        db.expire_all()
        e2 = db.get(ScheduledEntry, full_entry.id)
        assert float(e2.amount) == 1_900_000.0  # r=0.95 → gerçeğe çekilir
