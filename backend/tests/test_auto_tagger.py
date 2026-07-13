"""Otomatik etiketleme kuralları — Döviz Satışı + Acenta tahsilatı tespiti (2026-07-13).

Kapsam:
- "Döviz Satışı" kuralı "Kredi"den ÖNCE çalışır ("YapiKrediFX+ Dvz Satis" açıklaması
  "kredi" desenini de içerdiğinden yanlışlıkla Kredi etiketleniyordu).
- Acenta tahsilatı tespiti: Sedna tahsilat (tutar+para birimi+tarih) eşleşmesi,
  acente adı token'ı, açıklama ipucu; yalnız GELİR; virman/hesaplar-arası hariç.
- Yönetilen kategoriler (Döviz Satışı / Acenta) yoksa otomatik oluşturulur.
"""

from datetime import date, timedelta
from uuid import uuid4

from app.models.agency_group import AgencyGroup
from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.sales_invoice import SalesCollection
from app.models.transaction_category import TransactionCategory
from app.utils.auto_tagger import (
    AGENCY_CATEGORY,
    _get_or_create_category,
    auto_tag_transactions,
)

TODAY = date.today()


def _mk_account(db, *, bank_name="Etiket Test Bankası", currency="TRY"):
    acc = BankAccount(
        bank_name=bank_name, iban=f"TR{uuid4().hex}"[:34], currency=currency,
        is_active=True,
    )
    db.add(acc)
    db.flush()
    return acc


def _mk_btx(db, acc, *, amount, desc, tx_date=None):
    btx = BankTransaction(
        account_id=acc.id, date=tx_date or TODAY, description=desc,
        amount=amount, balance=0,
        type="expense" if amount < 0 else "income",
        tx_hash=f"atag-{uuid4().hex}",
    )
    db.add(btx)
    db.flush()
    return btx


def _mk_collection(db, *, code, name, col_date, amount_tl, currency="TL", amount_currency=None):
    col = SalesCollection(
        customer_code=code, customer_name=name, collection_date=col_date,
        amount=amount_tl, currency=currency,
        amount_currency=amount_currency if amount_currency is not None else amount_tl,
        tx_hash=f"col-{uuid4().hex}",
    )
    db.add(col)
    db.flush()
    return col


def _cat_of(db, btx):
    if btx.category_id is None:
        return None
    return db.query(TransactionCategory).get(btx.category_id).name


class TestFxSaleRule:
    def test_fx_sale_income_tagged_doviz_satisi_not_kredi(self, client, db):
        """'YapiKrediFX+ Dvz Satis' geliri Döviz Satışı olur — Kredi DEĞİL (canlı bug)."""
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=741222.25, desc="Döviz Internet - Mobil YapiKrediFX+ Dvz Satis")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == "Döviz Satışı"
        assert btx.tag_source == "auto"

    def test_fx_sale_expense_leg_also_doviz_satisi(self, client, db):
        """EUR hesabındaki satış bacağı (gider) da aynı başlık altında toplanır."""
        acc = _mk_account(db, currency="EUR")
        btx = _mk_btx(db, acc, amount=-13852.55, desc="Döviz Internet - Mobil YapiKrediFX+ Dvz Satis")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == "Döviz Satışı"

    def test_tcmb_doviz_satis_matches(self, client, db):
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=1939941.82, desc="Döviz Diğer TCMB DÖVİZ SATIŞ kur:53.253")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == "Döviz Satışı"

    def test_real_credit_still_tagged_kredi(self, client, db):
        """Gerçek kredi hareketi Kredi kalır (regresyon)."""
        _get_or_create_category(db, "Döviz Satışı")  # yönetilen kategori varken bile
        kredi = db.query(TransactionCategory).filter(TransactionCategory.name == "Kredi").first()
        if kredi is None:
            db.add(TransactionCategory(name="Kredi", color="orange"))
            db.flush()
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-50000, desc="KREDİ TAKSİT ÖDEMESİ 3/12")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == "Kredi"

    def test_managed_categories_created_idempotent(self, client, db):
        c1 = _get_or_create_category(db, "Döviz Satışı")
        c2 = _get_or_create_category(db, "Döviz Satışı")
        assert c1.id == c2.id


class TestAgencyTagging:
    def test_collection_amount_date_currency_match(self, client, db):
        """Sedna acente tahsilatıyla tutar+para birimi birebir, tarih ±4 gün → Acenta.

        Kırpık banka açıklaması ('TRAVE/020726/278982') kelimeyle yakalanamaz —
        tutar eşleşmesi tek güvenilir sinyal (canlı örnek: NLTG 36.781,33 EUR).
        """
        acc = _mk_account(db, currency="EUR")
        _mk_collection(
            db, code="120.01.02.0016", name="NORDİC LEİSURE TRAVEL GROUP AB ( NLTG )",
            col_date=TODAY - timedelta(days=1), amount_tl=1952684.03,
            currency="EUR", amount_currency=36781.33,
        )
        btx = _mk_btx(db, acc, amount=36781.33, desc="Diğer Diğer TRAVE/020726/278982")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == AGENCY_CATEGORY

    def test_collection_tl_leg_matches_try_account(self, client, db):
        """EUR tahsilatın TL karşılığı TRY hesabına düşmüşse TL tutar üzerinden eşleşir."""
        acc = _mk_account(db, currency="TRY")
        _mk_collection(
            db, code="120.01.01.F005", name="FUN AND SUN HOTELS OTEL İŞLETMECİLİĞİ TURİZM",
            col_date=TODAY, amount_tl=1860925.50, currency="EUR", amount_currency=35000.00,
        )
        btx = _mk_btx(db, acc, amount=1860925.50, desc="Diğer Diğer carı hesap ödeme / TR13 0001")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == AGENCY_CATEGORY

    def test_transferish_desc_needs_co_signal_amount_alone_insufficient(self, client, db):
        """Havale/EFT/FAST/transfer görünümlü açıklamada SALT-TUTAR eşleşmesi yetmez.

        Canlı bulgu (inceleme 2026-07-13): kendi bankalar-arası transferin gelen bacağı
        acente tahsilatıyla kuruş+tarih çakışıp 'Acenta'ya düşüyordu — eski 'Virman'
        kelime kuralı devre dışı kalıyordu. Eş-sinyalsiz transferish → Virman'a düşmeli.
        """
        acc = _mk_account(db, currency="TRY")
        _mk_collection(
            db, code="120.25.01.0001", name="MAYTATİL TURİZM LTD. ŞTİ.",
            col_date=TODAY, amount_tl=100000.00,
        )
        btx = _mk_btx(db, acc, amount=100000.00,
                      desc="ŞİRKETİMİZ HESABINDAN HALK BANK'A YAPILAN TRANSFER")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) != AGENCY_CATEGORY

    def test_collection_consumed_once(self, client, db):
        """Tek tahsilat EN ÇOK BİR işlemi etiketler (devam-transferi ikinci kez almaz)."""
        acc = _mk_account(db, currency="EUR")
        _mk_collection(
            db, code="120.01.01.P003", name="PGST ANTALYA TURİZM SEYAHAT ACENTASI",
            col_date=TODAY, amount_tl=717785.55, currency="EUR", amount_currency=13500.00,
        )
        first = _mk_btx(db, acc, amount=13500.00, desc="Diğer Diğer GELEN ODEME A")
        second = _mk_btx(db, acc, amount=13500.00, desc="Diğer Diğer GELEN ODEME B")
        auto_tag_transactions(db, [first.id, second.id])
        tags = [_cat_of(db, first), _cat_of(db, second)]
        assert tags.count(AGENCY_CATEGORY) == 1

    def test_guest_fast_with_bank_name_not_tagged(self, client, db):
        """Misafir FAST ödemesi, açıklamadaki gönderen banka adı ('Türkiye Garanti
        Bankası') yüzünden Acenta OLMAMALI — banka token'ları havuza girmez + FAST
        transferish olduğundan tutar eş-sinyal ister (canlı yanlış-pozitif sınıfı)."""
        acc = _mk_account(db, currency="TRY")
        _mk_collection(
            db, code="120.01.01.0143", name="TÜRKİYE GARANTİ BANKASI A.Ş.(ATM KİRA)",
            col_date=TODAY, amount_tl=5000.00,
        )
        btx = _mk_btx(db, acc, amount=5000.00,
                      desc="ZEYNEP CANSU GEÇGEL 'DAN GELEN FAST ODEMESİ , Türkiye Garanti Bankası A.Ş.")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) != AGENCY_CATEGORY

    def test_blocked_collection_customers_produce_no_amount_signal(self, client, db):
        """120.01.* içindeki banka/telekom/kiracı kayıtları (canlıda mevcut) tutar
        sinyali üretmez — ATM kirası geliri Acenta'ya düşmez."""
        acc = _mk_account(db, currency="TRY")
        _mk_collection(
            db, code="120.01.01.0002", name="VODAFONE TELEKOMÜNİKASYON A.Ş.",
            col_date=TODAY, amount_tl=7500.00,
        )
        btx = _mk_btx(db, acc, amount=7500.00, desc="Diğer Diğer AYLIK ODEME REF 42")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) != AGENCY_CATEGORY

    def test_desc_hint_seyahat_acent(self, client, db):
        acc = _mk_account(db, currency="EUR")
        btx = _mk_btx(db, acc, amount=15000, desc="Diğer Diğer SEYAHAT ACENT/100726/950767")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == AGENCY_CATEGORY

    def test_agency_name_token_match(self, client, db):
        """Acente adının ayırt edici token çifti (AYNI acenteden ≥2) açıklamada → Acenta."""
        acc = _mk_account(db, currency="EUR")
        _mk_collection(
            db, code="120.01.02.0016", name="NORDİC LEİSURE TRAVEL GROUP AB ( NLTG )",
            col_date=TODAY - timedelta(days=200), amount_tl=1, currency="EUR", amount_currency=1,
        )
        btx = _mk_btx(db, acc, amount=99999, desc="Diğer Diğer NORDIC LEISURE GELEN ODEME")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == AGENCY_CATEGORY

    def test_generic_single_token_not_sufficient(self, client, db):
        """'İşletmeciliği/otel/hotels' gibi jenerik kelimeler tek başına eşleşme sayılmaz
        (inceleme bulgusu: herhangi bir '... İŞLETMECİLİĞİ ...' göndericisi Acenta oluyordu)."""
        acc = _mk_account(db, currency="EUR")
        _mk_collection(
            db, code="120.01.01.F005", name="FUN AND SUN HOTELS OTEL İŞLETMECİLİĞİ TURİZM",
            col_date=TODAY - timedelta(days=200), amount_tl=1, currency="EUR", amount_currency=1,
        )
        btx = _mk_btx(db, acc, amount=88888, desc="Diğer Diğer BAŞKA OTEL ISLETMECILIGI A.S. ODEME")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) != AGENCY_CATEGORY

    def test_cross_agency_token_pair_not_sufficient(self, client, db):
        """İki FARKLI acentenin tek'er token'ı birleşip eşleşme sayılmaz (acente-bazlı kümeler)."""
        acc = _mk_account(db, currency="EUR")
        _mk_collection(
            db, code="120.01.02.0016", name="NORDİC LEİSURE TRAVEL GROUP",
            col_date=TODAY - timedelta(days=200), amount_tl=1, currency="EUR", amount_currency=1,
        )
        _mk_collection(
            db, code="120.01.01.P003", name="PEGAS TOURISTIK ANTALYA TURİZM",
            col_date=TODAY - timedelta(days=200), amount_tl=1, currency="EUR", amount_currency=1,
        )
        # "nordic" (Nordic'ten) + "pegas" (Pegas'tan) — aynı acenteden 2 token DEĞİL,
        # ikisi de <8 karakter → eşleşme yok
        btx = _mk_btx(db, acc, amount=77777, desc="Diğer Diğer NORDIC PEGAS ORTAK ODEME")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) != AGENCY_CATEGORY

    def test_agency_group_member_token_match(self, client, db):
        """agency_groups üye adları da token kaynağıdır (ALLTOURS)."""
        db.add(AgencyGroup(name=f"ALLTOURS-{uuid4().hex[:6]}", members=["ALLTOURS D", "ALLTOURS NV"]))
        db.flush()
        acc = _mk_account(db, currency="EUR")
        btx = _mk_btx(db, acc, amount=99999, desc="Diğer Diğer ALLTOURS FLUGREISEN GMBH ODEME")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == AGENCY_CATEGORY

    def test_guest_collection_not_tagged(self, client, db):
        """Bireysel misafir ön ödemesi (120.26.*) acenta DEĞİLDİR — Etiketsiz kalır."""
        acc = _mk_account(db, currency="TRY")
        _mk_collection(
            db, code="120.26.01.0015", name="CİHAN AY",
            col_date=TODAY, amount_tl=33800.00,
        )
        btx = _mk_btx(db, acc, amount=33800.00, desc="Para Gönder Diğer mesutbey 9.8 - 13.8 ön ödeme")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) is None

    def test_expense_never_tagged_agency(self, client, db):
        """Acenta tespiti yalnız GELİR işlemlerine bakar (gider tutarı çakışsa bile)."""
        acc = _mk_account(db, currency="EUR")
        _mk_collection(
            db, code="120.01.01.P003", name="PGST ANTALYA TURİZM SEYAHAT ACENTASI",
            col_date=TODAY, amount_tl=717785.55, currency="EUR", amount_currency=13500.00,
        )
        btx = _mk_btx(db, acc, amount=-13500.00, desc="Diğer Diğer GIDEN ODEME 13500")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) is None

    def test_internal_move_not_tagged_agency(self, client, db):
        """Virman/hesaplar arası açıklama acenta adayı olamaz — Virman kuralına düşer."""
        acc = _mk_account(db, currency="TRY")
        _mk_collection(
            db, code="120.01.01.P003", name="PGST ANTALYA TURİZM SEYAHAT ACENTASI",
            col_date=TODAY, amount_tl=50000.00,
        )
        btx = _mk_btx(db, acc, amount=50000.00, desc="Virman gelen ödeme 50000")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) != AGENCY_CATEGORY

    def test_collection_outside_date_window_not_tagged(self, client, db):
        """Tutar aynı ama tarih ±4 gün dışında → tutar sinyali eşleşmez."""
        acc = _mk_account(db, currency="EUR")
        _mk_collection(
            db, code="120.01.02.O001", name="OTS Open",  # kısa ad → token sinyali yok
            col_date=TODAY - timedelta(days=30), amount_tl=1165976.79,
            currency="EUR", amount_currency=21846.39,
        )
        btx = _mk_btx(db, acc, amount=21846.39, desc="Diğer Diğer 0260958PO348414 GELEN")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) is None

    def test_finance_event_syncs_category(self, client, db):
        """Acenta etiketi finance_events'e de yansır (Panel T-Hesap bu koldan okur)."""
        from app.models.finance_event import FinanceEvent
        from app.utils.finance_event_service import finance_event_svc

        acc = _mk_account(db, currency="EUR")
        btx = _mk_btx(db, acc, amount=13500, desc="Diğer Diğer SEYAHAT ACENT/030726/352484")
        finance_event_svc.upsert_bank_tx(db, btx, acc)
        auto_tag_transactions(db, [btx.id])
        fe = (
            db.query(FinanceEvent)
            .filter(FinanceEvent.source_type == "bank", FinanceEvent.source_id == btx.id)
            .first()
        )
        assert fe is not None
        assert fe.category_name == AGENCY_CATEGORY
