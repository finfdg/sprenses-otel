"""Otomatik etiketleme kuralları — Döviz Satışı + Acenta tahsilatı tespiti (2026-07-13).

Kapsam:
- "Döviz Satışı" kuralı "Kredi/Leasing"den ÖNCE çalışır ("YapiKrediFX+ Dvz Satis" açıklaması
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
        kredi = db.query(TransactionCategory).filter(TransactionCategory.name == "Kredi/Leasing").first()
        if kredi is None:
            db.add(TransactionCategory(name="Kredi/Leasing", color="orange"))
            db.flush()
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-50000, desc="KREDİ TAKSİT ÖDEMESİ 3/12")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == "Kredi/Leasing"

    def test_managed_categories_created_idempotent(self, client, db):
        c1 = _get_or_create_category(db, "Döviz Satışı")
        c2 = _get_or_create_category(db, "Döviz Satışı")
        assert c1.id == c2.id


def _ensure_category(db, name, color="gray"):
    cat = db.query(TransactionCategory).filter(TransactionCategory.name == name).first()
    if cat is None:
        cat = TransactionCategory(name=name, color=color)
        db.add(cat)
        db.flush()
    return cat


class TestBankNameNoise:
    """Karşı-taraf banka adındaki 'kredi' kelimesi kural tetiklememeli (2026-07-18).

    Canlı bug: "Yapı ve Kredi Bankası A.Ş. ... hesabına giden FAST" açıklamalı
    personel avansları Kredi başlığına düşüyordu (18 kayıt).
    """

    YK_SUFFIX = (
        " (17/07/2026 tarihli 2787824369 sorgu no'lu MURAT-A TURİZM TİCARET SANAYİ VE "
        "İNŞAAT ANONİM ŞİRKETİ hesabından Yapı ve Kredi Bankası A.Ş. YALÇIN YAVUZ "
        "hesabına giden FAST ödemesi)"
    )

    def test_fast_avans_to_yapikredi_tagged_personel_not_kredi(self, client, db):
        _ensure_category(db, "Personel", "pink")
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-20000, desc="FAST Anlık Ödeme TEMMUZ AVANS" + self.YK_SUFFIX)
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == "Personel"

    def test_izin_ucreti_to_yapikredi_tagged_personel(self, client, db):
        _ensure_category(db, "Personel", "pink")
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-24800, desc="FAST Anlık Ödeme YILLIK İZİN ÖDEMESİ" + self.YK_SUFFIX)
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == "Personel"

    def test_bank_name_alone_not_tagged_kredi(self, client, db):
        """Başka anahtar kelime yoksa banka adı tek başına hiçbir kural tetiklemez."""
        _ensure_category(db, "Kredi/Leasing", "orange")
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-30000, desc="FAST Anlık Ödeme ARALIK KİRA ÖDEMESİ" + self.YK_SUFFIX)
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) is None

    def test_real_credit_from_yapikredi_account_still_kredi(self, client, db):
        """Gerçek kredi kelimesi banka adı dışında geçiyorsa Kredi kalır."""
        _ensure_category(db, "Kredi/Leasing", "orange")
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-50000, desc="İHTİYAÇ KREDİSİ TAKSİT ÖDEMESİ 3/12" + self.YK_SUFFIX)
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == "Kredi/Leasing"

    def test_payment_method_stays_fast(self, client, db):
        from app.utils.auto_tagger import detect_payment_method

        assert detect_payment_method("FAST Anlık Ödeme TEMMUZ AVANS" + self.YK_SUFFIX) == "fast"

    def test_payment_method_bank_name_not_kredi(self, client, db):
        from app.utils.auto_tagger import detect_payment_method

        assert (
            detect_payment_method("Para Gönder Yapı ve Kredi Bankası A.Ş. hesabına gönderilen tutar")
            != "kredi"
        )

    def test_truncated_bank_name_not_tagged_kredi(self, client, db):
        """Banka adın başını kırpabiliyor: '...VE KREDİ BANKASI A.Ş.' de Kredi tetiklememeli."""
        _ensure_category(db, "Kredi/Leasing", "orange")
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=4863, desc="Para Gönder Diğer VE KREDİ BANKASI A.Ş. AHMET DEMİR")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) != "Kredi/Leasing"


class TestVergiTaksitRule:
    """'Vergi Tahsilatı … Taksit:1' banka formatı Kredi'ye düşmemeli (Sedna denetimi 2026-07-18).

    Canlıda 35 vergi ödemesi (KDV/stopaj/konaklama vergisi/MTV, ₺8,6M) 'taksit'
    kelimesiyle Kredi etiketlenmişti.
    """

    def test_vergi_tahsilati_with_taksit_tagged_vergi(self, client, db):
        _ensure_category(db, "Vergi/SGK", "red")
        _ensure_category(db, "Kredi/Leasing", "orange")
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-1663355, desc=(
            "Vergi Tahsilatı 0015/0015/KDV GERÇEK Tahsilatı Dönem :11/2025/11/2025 Taksit:1 Vkn/Tc"
        ))
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == "Vergi/SGK"

    def test_real_kredi_taksit_tahsilati_stays_kredi(self, client, db):
        """'KREDİ TAKSİT TAHSİLATI' gerçek kredi hareketidir — Kredi kalır (regresyon)."""
        _ensure_category(db, "Vergi/SGK", "red")
        _ensure_category(db, "Kredi/Leasing", "orange")
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-50000, desc="KREDİ TAKSİT TAHSİLATI 4101728829 3/12")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == "Kredi/Leasing"


class TestLeasingRule:
    """Leasing ödemeleri 'Kredi/Leasing' başlığına düşer (2026-07-18 kullanıcı isteği).

    Canlıda 24 leasing ödemesi 'havale' (Virman) / 'tahsilat' (Vergi/SGK) kelimeleri
    ve cari eşleşmesiyle yanlış başlıklara (çoğu 'Cari') dağılmıştı.
    """

    def test_qnb_leasing_tahsilat_not_vergi(self, client, db):
        _ensure_category(db, "Vergi/SGK", "red")
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-955.88, desc=(
            "Ödeme İşlemleri - 2500515201 - QNB Leasing Türkiye TAHSİLATI OTOMATIK"
        ))
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == "Kredi/Leasing"

    def test_vakif_leasing_havale_not_virman(self, client, db):
        _ensure_category(db, "Virman", "purple")
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-6145, desc=(
            "Gönderilen havale VAKIF LEASİNG 11. TAKSİT / TR54 0001 5001"
        ))
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == "Kredi/Leasing"

    def test_finansal_kiralama_tagged(self, client, db):
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-5517, desc=(
            "Gönderilen havale VAKIF FİNANSAL KİRALAMA A.O. sözleşme ödemesi"
        ))
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == "Kredi/Leasing"

    def test_halkbank_odeme_plani_tagged(self, client, db):
        """'HAVALE ... NOLU ÖDEME PLANI' (Halk Leasing formatı — leasing kelimesi yok)
        de Kredi/Leasing'e düşer (2026-07-18 ikinci kullanıcı bulgusu)."""
        _ensure_category(db, "Virman", "purple")
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-1887.19, desc="HAVALE 2600046701 NOLU ÖDEME PLANI")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == "Kredi/Leasing"

    def test_plain_havale_still_virman(self, client, db):
        """Leasing geçmeyen havale Virman kalır (kural sırası regresyonu)."""
        _ensure_category(db, "Virman", "purple")
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-1000, desc="Gönderilen havale AHMET DEMİR")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == "Virman"


class TestTemettuRule:
    """Temettü/ortak ödemeleri havale/EFT kelimesiyle Virman'a düşmemeli (2026-07-18)."""

    def test_temettu_havale_tagged_temettu_not_virman(self, client, db):
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-170000, desc="HAVALE Temettü avans ödemesi")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == "Temettü"

    def test_ortaklara_odenen_eft_tagged_temettu(self, client, db):
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-304583, desc=(
            "Hesaba giden EFT 04.11.2025 TARİHLİ GENEL KURUL KARARINA İSTİNADEN ORTAKLARA ÖDENEN 1. TAKSİT"
        ))
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == "Temettü"

    def test_plain_havale_still_virman(self, client, db):
        _ensure_category(db, "Virman", "purple")
        acc = _mk_account(db)
        btx = _mk_btx(db, acc, amount=-25000, desc="HAVALE Kendi hesabına gönderim")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == "Virman"


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


class TestBankFeeTagging:
    """Banka havale/EFT komisyon tespiti — 'Havale Komisyonları' (2026-07-13)."""

    def test_yk_fee_leg_small_amount_tagged(self, client, db):
        """YK ücret bacağı ('Diğer Internet - Mobil X', küçük tutar) → Havale Komisyonları."""
        acc = _mk_account(db, currency="TRY")
        fee = _mk_btx(db, acc, amount=-15.96, desc="Diğer Internet - Mobil FARUK SEVİK")
        bsmv = _mk_btx(db, acc, amount=-0.80, desc="Diğer Internet - Mobil FARUK SEVİK")
        auto_tag_transactions(db, [fee.id, bsmv.id])
        assert _cat_of(db, fee) == "Havale Komisyonları"
        assert _cat_of(db, bsmv) == "Havale Komisyonları"

    def test_masked_pan_cc_payment_not_tagged_as_fee(self, client, db):
        """Aynı önekli BÜYÜK tutar (maskeli PAN kart borcu, canlı ₺15.000) ücret DEĞİLDİR."""
        acc = _mk_account(db, currency="TRY")
        btx = _mk_btx(db, acc, amount=-15000.00, desc="Diğer Internet - Mobil INT 650837******7261 0707")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) != "Havale Komisyonları"

    def test_fee_keyword_tagged(self, client, db):
        """Ücret anahtar kelimeli küçük giderler (ücr/kom) → Havale Komisyonları."""
        acc = _mk_account(db, currency="TRY")
        pos_fee = _mk_btx(db, acc, amount=-590.00, desc="000742062-06.AyFiz.POSYaz.Donm.Bkm.Ücr")
        kom = _mk_btx(db, acc, amount=-143.64, desc="Diğer Diğer KOM")
        auto_tag_transactions(db, [pos_fee.id, kom.id])
        assert _cat_of(db, pos_fee) == "Havale Komisyonları"
        assert _cat_of(db, kom) == "Havale Komisyonları"

    def test_big_amount_with_fee_keyword_not_fee(self, client, db):
        """Tavan üstü 'komisyon' içeren gerçek ödeme bu başlığa girmez (eski kurala düşer)."""
        acc = _mk_account(db, currency="TRY")
        btx = _mk_btx(db, acc, amount=-50000.00, desc="KREDİ KULLANDIRIM KOMİSYONU ÖDEMESİ")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) != "Havale Komisyonları"

    def test_income_with_fee_keyword_not_tagged(self, client, db):
        """Ücret iadesi (GELİR) ücret olarak etiketlenmez."""
        acc = _mk_account(db, currency="TRY")
        btx = _mk_btx(db, acc, amount=25.00, desc="MASRAF İADESİ")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) != "Havale Komisyonları"

    def test_fx_account_fee_cap(self, client, db):
        """Döviz hesabında ücret tavanı daha dar: €30 ücret bacağı etiketlenmez, €5 masraf etiketlenir."""
        acc = _mk_account(db, currency="EUR")
        big_leg = _mk_btx(db, acc, amount=-30.00, desc="Diğer Internet - Mobil ODEME X")
        small_fee = _mk_btx(db, acc, amount=-5.00, desc="HVL.MASRAFI")
        auto_tag_transactions(db, [big_leg.id, small_fee.id])
        assert _cat_of(db, big_leg) != "Havale Komisyonları"
        assert _cat_of(db, small_fee) == "Havale Komisyonları"


class TestAgencyDisplayName:
    """Acenta kaleminde görünen ad = çözülen acente adı (tag_note; 2026-07-13)."""

    def test_short_agency_name(self, client):
        from app.utils.auto_tagger import _short_agency_name
        assert _short_agency_name("PGST ANTALYA TURİZM SEYAHAT ACENTASI TAŞ. VE TİC.") == "PGST"
        assert _short_agency_name("OTS Open Travel Services AG") == "OTS Open Travel"
        assert _short_agency_name("NORDİC LEİSURE TRAVEL GROUP AB ( NLTG )") == "NORDİC LEİSURE TRAVEL"
        assert _short_agency_name("FUN AND SUN HOTELS OTEL İŞLETMECİLİĞİ TURİZM") == "FUN AND SUN"
        assert _short_agency_name("MAYTATİL TURİZM LİMİTED ŞİRKETİ") == "MAYTATİL"
        assert _short_agency_name("W2M S.L.U VAT:B62880992") == "W2M"

    def test_amount_match_sets_tag_note(self, client, db):
        acc = _mk_account(db, currency="EUR")
        _mk_collection(
            db, code="120.01.02.0016", name="NORDİC LEİSURE TRAVEL GROUP AB ( NLTG )",
            col_date=TODAY, amount_tl=1952684.03, currency="EUR", amount_currency=36781.33,
        )
        btx = _mk_btx(db, acc, amount=36781.33, desc="Diğer Diğer TRAVE/020726/278982")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == AGENCY_CATEGORY
        assert btx.tag_note == "NORDİC LEİSURE TRAVEL"

    def test_hint_match_resolves_name_from_collection(self, client, db):
        """Açıklama ipucuyla eşleşen kalem bile adını tutar-eş tahsilattan çözer."""
        acc = _mk_account(db, currency="EUR")
        _mk_collection(
            db, code="120.01.01.P003", name="PGST ANTALYA TURİZM SEYAHAT ACENTASI TAŞ.",
            col_date=TODAY, amount_tl=717785.55, currency="EUR", amount_currency=13500.00,
        )
        btx = _mk_btx(db, acc, amount=13500.00, desc="Diğer Diğer SEYAHAT ACENT/030726/352484")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == AGENCY_CATEGORY
        assert btx.tag_note == "PGST"

    def test_unresolvable_hint_keeps_tag_note_empty(self, client, db):
        """Çözülemeyen (tahsilatsız/token'sız) ipucu kalemi tag_note almaz → açıklama görünür."""
        acc = _mk_account(db, currency="EUR")
        btx = _mk_btx(db, acc, amount=4321.00, desc="Diğer Diğer SEYAHAT ACENT/999999/1")
        auto_tag_transactions(db, [btx.id])
        assert _cat_of(db, btx) == AGENCY_CATEGORY
        assert btx.tag_note is None


class TestPosBlokeTransfers:
    """POS bloke çözüm çiftleri 'Pos Bloke Çözme' olur (2026-07-18): parayı bloke
    hesaptan ana hesaba taşıyan İKİ bacak (aynı gün, zıt işaretli aynı tutar, farklı
    hesap) iç virmandır. Karşı bacaksız (ücret/aidat) kalemler kelime kurallarına düşer;
    manuel etiket asla ezilmez."""

    DESC = "UBLK/1376/000000003787614             /POS BLOKE ÇÖZÜM"

    def test_paired_legs_both_tagged(self, client, db):
        acc_bloke = _mk_account(db, currency="EUR")
        acc_main = _mk_account(db, currency="EUR")
        out_leg = _mk_btx(db, acc_bloke, amount=-5100, desc=self.DESC)
        in_leg = _mk_btx(db, acc_main, amount=5100, desc=self.DESC)
        auto_tag_transactions(db, [out_leg.id, in_leg.id])
        assert _cat_of(db, out_leg) == "Pos Bloke Çözme"
        assert _cat_of(db, in_leg) == "Pos Bloke Çözme"
        assert out_leg.tag_source == "auto" and in_leg.tag_source == "auto"

    def test_unpaired_fee_leg_falls_to_word_rules(self, client, db):
        """Aynı açıklamalı ama EŞSİZ gider (banka kesintisi) transfer sayılmaz."""
        acc = _mk_account(db)
        fee = _mk_btx(db, acc, amount=-3871.78, desc=self.DESC)
        auto_tag_transactions(db, [fee.id])
        assert _cat_of(db, fee) == "POS"  # "pos " kelime kuralı — Pos Bloke Çözme DEĞİL

    def test_same_account_pair_not_matched(self, client, db):
        """Karşı bacak FARKLI hesapta olmalı — aynı hesapta zıt tutar çift sayılmaz."""
        acc = _mk_account(db)
        out_leg = _mk_btx(db, acc, amount=-1500, desc=self.DESC)
        in_leg = _mk_btx(db, acc, amount=1500, desc=self.DESC)
        auto_tag_transactions(db, [out_leg.id, in_leg.id])
        assert _cat_of(db, out_leg) != "Pos Bloke Çözme"
        assert _cat_of(db, in_leg) != "Pos Bloke Çözme"

    def test_late_counterpart_retags_auto_leg(self, client, db):
        """Karşı bacak sonraki ekstreyle gelirse önceden OTOMATİK etiketlenen bacak hizalanır."""
        acc_bloke = _mk_account(db)
        acc_main = _mk_account(db)
        out_leg = _mk_btx(db, acc_bloke, amount=-170000, desc=self.DESC)
        auto_tag_transactions(db, [out_leg.id])
        assert _cat_of(db, out_leg) == "POS"  # eşi henüz yok → kelime kuralı
        in_leg = _mk_btx(db, acc_main, amount=170000, desc=self.DESC)
        auto_tag_transactions(db, [in_leg.id])
        assert _cat_of(db, in_leg) == "Pos Bloke Çözme"
        assert _cat_of(db, out_leg) == "Pos Bloke Çözme"
        assert out_leg.tag_source == "auto"

    def test_manual_counterpart_not_overridden(self, client, db):
        """Manuel etiketli karşı bacak kullanıcı kararıdır — dokunulmaz."""
        acc_bloke = _mk_account(db)
        acc_main = _mk_account(db)
        out_leg = _mk_btx(db, acc_bloke, amount=-2000, desc=self.DESC)
        virman = _get_or_create_category(db, "Virman")
        out_leg.category_id = virman.id
        out_leg.tag_source = "manual"
        db.flush()
        in_leg = _mk_btx(db, acc_main, amount=2000, desc=self.DESC)
        auto_tag_transactions(db, [in_leg.id])
        assert _cat_of(db, in_leg) == "Pos Bloke Çözme"
        assert _cat_of(db, out_leg) == "Virman"
        assert out_leg.tag_source == "manual"
