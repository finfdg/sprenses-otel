"""Otomatik işlem etiketleme utility'si."""
import logging
import re
from collections import defaultdict
from datetime import timedelta
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.models.agency_group import AgencyGroup
from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.reservation import Reservation
from app.models.sales_invoice import SalesCollection
from app.models.transaction_category import TransactionCategory
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction

logger = logging.getLogger(__name__)

# Türkçe karakter normalize haritası
_TR_MAP = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


# ─── Ödeme Yöntemi Tespiti ─────────────────────────────────────────────
# Sıralama önemli: FAST "havale" içerebilir, kredi_karti "kredi" içerebilir
# Bu yüzden spesifik kurallar önce gelmeli.

PAYMENT_METHOD_RULES: List[Tuple[str, str]] = [
    ("fast", r"fast|anlik odeme|anlik havale"),
    ("cek", r"\bcek\b|takas|cek ile"),
    ("kredi_karti", r"pos[ /y.]|kkiv|kart bor|kredi karti|kk ode"),
    ("otomatik_odeme", r"otomatik odeme|duzenli odeme|fatura tahsilat|abone tahsilat|asat |tedas |elektrik tahsilat|su tahsilat|dogalgaz tahsilat"),
    ("virman", r"virman|transfer islemleri|hesaplar arasi"),
    ("havale_eft", r"havale|eft |hesaba giden|gonderilen|gelen havale|giden eft"),
    ("kredi", r"kredi|taksit |kmh|taksitli"),
    ("nakit", r"nakit|atm |kasa "),
]

# Ödeme yöntemi Türkçe etiketleri
PAYMENT_METHOD_LABELS: Dict[str, str] = {
    "havale_eft": "Havale/EFT",
    "fast": "FAST",
    "virman": "Virman",
    "cek": "Çek",
    "kredi_karti": "Kredi Kartı",
    "otomatik_odeme": "Otomatik Ödeme",
    "nakit": "Nakit",
    "kredi": "Kredi",
    "diger": "Diğer",
}


def detect_payment_method(description: str) -> str:
    """Banka açıklamasından ödeme yöntemini tespit et.

    Normalize edilmiş metin üzerinde regex ile eşleşme yapar.
    Eşleşme bulunamazsa 'diger' döndürür.
    """
    norm = _normalize(description)
    for method, pattern in PAYMENT_METHOD_RULES:
        if re.search(pattern, norm):
            return method
    return "diger"


def _sync_finance_events(db: Session, txs) -> None:
    """Otomatik atanan etiket/cari/ödeme yöntemini finance_events'e yansıt.

    Manuel yol (transaction_tags.tag_transaction) sync_tag kullanır — otomatik yol
    kullanmıyordu; nakit akım FE'nin denormalize kolonlarından okuduğu için otomatik
    etiketler ekranda görünmüyordu (2026-07-11 denetim A4). is_matched'a DOKUNMAZ.
    """
    if not txs:
        return
    from app.utils.finance_event_service import finance_event_svc

    cat_ids = {t.category_id for t in txs if t.category_id}
    cats = {}
    if cat_ids:
        for c in db.query(TransactionCategory).filter(TransactionCategory.id.in_(list(cat_ids))).all():
            cats[c.id] = c
    for t in txs:
        c = cats.get(t.category_id)
        finance_event_svc.sync_tag(
            db, t.id,
            category_id=t.category_id,
            category_name=c.name if c else None,
            category_color=c.color if c else None,
            tag_note=t.tag_note, tag_source=t.tag_source,
            payment_method=t.payment_method, match_number=t.match_number,
            vendor_id=t.vendor_id,
        )


def auto_detect_payment_methods(db: Session, overwrite: bool = False) -> Dict[str, int]:
    """Tüm işlemlerin ödeme yöntemini otomatik tespit et.

    overwrite=True: mevcut değerlerin üzerine yaz
    overwrite=False: sadece boş olanları doldur
    """
    from app.utils.finance_helpers import MIN_DATE

    query = db.query(BankTransaction).filter(BankTransaction.date >= MIN_DATE)
    if not overwrite:
        query = query.filter(BankTransaction.payment_method.is_(None))

    txs = query.all()
    counts: Dict[str, int] = defaultdict(int)

    for tx in txs:
        method = detect_payment_method(tx.description)
        tx.payment_method = method
        counts[method] += 1

    db.flush()
    _sync_finance_events(db, txs)  # ödeme yöntemi FE'ye yansısın (manuel yolla tutarlı)
    return dict(counts)


def _normalize(text: str) -> str:
    """Türkçe karakterleri ASCII'ye çevir ve küçült."""
    return text.translate(_TR_MAP).lower()


# Kategori adı → regex pattern (normalize edilmiş metin üzerinde çalışır)
# "Döviz Satışı" kuralı "Kredi"den ÖNCE gelmeli: "YapiKrediFX+ Dvz Satis" açıklaması
# "kredi" desenini de içerir — döviz satışı kredi kullanımı DEĞİLDİR (2026-07-13).
AUTO_TAG_RULES: List[Tuple[str, str]] = [
    ("Virman", r"virman|havale|eft |transfer"),
    ("Döviz Satışı", r"dvz sat|doviz sat"),
    ("POS", r"pos |kkiv|kart "),
    ("Kredi", r"kredi|taksit|kmh"),
    ("Personel", r"maas|personel|ucret"),
    ("Vergi/SGK", r"vergi|sgk|sgdp|tahsilat"),
    ("Komisyon", r"komisyon|masraf"),
]

# Kural motoru tarafından yönetilen (yoksa otomatik oluşturulan) kategoriler → renk
# (renkler frontend colorMap.ts paletinden — bilinmeyen renk gray'e düşer)
MANAGED_CATEGORY_COLORS: Dict[str, str] = {
    "Döviz Satışı": "cyan",
    "Acenta": "teal",
}


def _get_or_create_category(db: Session, name: str) -> TransactionCategory:
    """Yönetilen kategoriyi getir; yoksa oluştur (idempotent, commit ETMEZ).

    İlk-koşu yarışı: eşzamanlı iki işlem (ekstre yüklemesi + Sedna sync) aynı anda
    oluşturmaya çalışırsa unique(name) ihlali SAVEPOINT ile yutulur ve kayıt yeniden
    okunur — çağıranın transaction'ı bozulmaz (inceleme bulgusu 2026-07-13).
    """
    cat = db.query(TransactionCategory).filter(TransactionCategory.name == name).first()
    if cat is None:
        from sqlalchemy.exc import IntegrityError

        try:
            with db.begin_nested():
                cat = TransactionCategory(name=name, color=MANAGED_CATEGORY_COLORS.get(name, "gray"))
                db.add(cat)
        except IntegrityError:
            cat = db.query(TransactionCategory).filter(TransactionCategory.name == name).first()
        db.flush()
    return cat


def auto_tag_transactions(
    db: Session,
    transaction_ids: Optional[List[int]] = None,
) -> Tuple[int, int]:
    """Etiketlenmemiş işlemlere otomatik kural uygula.

    Sıra: önce veri-temelli acenta tahsilatı tespiti (Sedna tahsilat/acente adları —
    genel kelime kurallarından daha yüksek sinyal), sonra kelime kuralları.

    Returns:
        (etiketlenen_sayı, toplam_etiketsiz_sayı)
    """
    # Kategori adı → id eşlemesi (yönetilen kural kategorileri yoksa oluşturulur)
    categories = db.query(TransactionCategory).all()
    cat_map = {c.name: c.id for c in categories}
    for managed in MANAGED_CATEGORY_COLORS:
        if managed not in cat_map:
            cat_map[managed] = _get_or_create_category(db, managed).id

    # Etiketlenmemiş işlemleri al
    query = db.query(BankTransaction).filter(
        BankTransaction.category_id.is_(None),
    )
    if transaction_ids:
        query = query.filter(BankTransaction.id.in_(transaction_ids))

    untagged = query.all()
    tagged = _tag_agency_collections(db, untagged, cat_map[AGENCY_CATEGORY])

    for tx in untagged:
        if tx.category_id is not None:  # acenta geçişinde etiketlendi
            continue
        normalized = _normalize(tx.description)
        for cat_name, pattern in AUTO_TAG_RULES:
            if re.search(pattern, normalized):
                cat_id = cat_map.get(cat_name)
                if cat_id:
                    tx.category_id = cat_id
                    tx.tag_source = "auto"
                    tagged.append(tx)
                break  # İlk eşleşen kural kazanır

    if tagged:
        db.flush()
        _sync_finance_events(db, tagged)  # otomatik kategori FE'ye yansısın

    return len(tagged), len(untagged)


# ─── Acenta Tahsilatı Tespiti (2026-07-13; hassasiyet sertleştirmesi aynı gün) ──
# Panel/Nakit Akım'da acente ödemeleri "Etiketsiz" kalıyordu (banka açıklaması
# kırpık: "TRAVE/020726/278982", "SEYAHAT ACENT/030726/..."). Üç sinyalle
# "Acenta" kategorisine etiketlenir (yalnız GELİR işlemleri):
#   1) Sedna tahsilat eşleşmesi — sales_collections'taki acente tahsilatıyla
#      tutar+para birimi birebir, tarih ±4 gün; her tahsilat EN ÇOK BİR işlemi
#      etiketler (tüketilir — aynı paranın devam-transferi ikinci kez etiketlenmesin).
#   2) Acente adı token'ı — agency_groups (ad+üyeler), rezervasyon acenteleri ve
#      isim-ipucu-doğrulanmış tahsilat müşteri adlarından; ≥2 token AYNI acenteden
#      veya tek token ≥8 karakter (jenerik kelimeler ayrıca elenir).
#   3) Açıklama ipucu — "seyahat acent", "travel", "acente/acenta" gibi kalıplar.
# Guard'lar (çok-ajanlı inceleme bulguları, canlı dry-run'la doğrulandı 2026-07-13):
#   - Virman/hesaplar-arası açıklamalar aday olamaz.
#   - havale/EFT/FAST/transfer görünümlü açıklamada SALT-TUTAR eşleşmesi YETMEZ
#     (kendi bankalar-arası transferler + misafir FAST ödemeleri tutar çakışmasıyla
#     Acenta'ya düşüyordu) — isim token'ı veya açıklama ipucu eş-sinyali şart.
#   - 120.01.* segmenti saf acente DEĞİL (canlıda Vodafone/TT Mobil/banka ATM-kira/
#     gerçek kişi var) → banka/telekom/kira adlı tahsilatlar blok listesiyle elenir;
#     token havuzuna yalnız isim-ipucu-doğrulanmış acenteler girer.
#   - Jenerik kelimeler (işletmeciliği/otel/hotels/group/turkiye/bankasi…) token olamaz.

AGENCY_CATEGORY = "Acenta"
_AGENCY_CODE_PREFIX = "120.01."  # Sedna acente ağırlıklı cari segmenti (saf değil!)
_AGENCY_NAME_HINT = re.compile(r"turizm|travel|seyahat|acent|touristik|reisen|holiday|tour")
# Acente OLMADIĞI kesin tahsilat müşterileri (120.01.* içinde banka ATM-kira,
# telekom, market/kuyum kiracıları görüldü — canlı bulgu)
_AGENCY_NAME_BLOCK = re.compile(
    r"banka|bankasi|vodafone|telekom|tt mobil|iletisim|sigorta|\batm\b|kira|elektrik|"
    r"enerji|belediye|market|kuyum|restaurant|restoran"
)
_AGENCY_DESC_HINT = re.compile(r"seyahat acent|travel|acente|acenta|touristik|reisen")
# Transfer görünümlü açıklama: salt-tutar eşleşmesine güvenilmez (eş-sinyal şart)
_TRANSFERISH = re.compile(r"havale|\beft\b|transfer|\bfast\b|para gonder")
_AGENCY_DATE_WINDOW_DAYS = 4
_AGENCY_MIN_SINGLE_TOKEN = 8  # tek token eşleşmesinde asgari uzunluk
# Acente adlarında ayırt edici SAYILMAYACAK jenerik kelimeler (_SKIP_WORDS'e ek):
# otelcilik/kurumsal/banka/telekom/coğrafya kelimeleri tek başına veya çapraz-acente
# kombinasyonla eşleşme üretmesin (canlı yanlış-pozitif sınıfı).
_AGENCY_TOKEN_SKIP = {
    "isletmeciligi", "isletmecilik", "isletme", "otel", "otelcilik", "oteli",
    "hotel", "hotels", "holding", "group", "grup", "gmbh", "services", "service",
    "online", "global", "turkiye", "bankasi", "banka", "garanti", "vodafone",
    "telekom", "telekomuni", "iletisim", "mobil", "distance", "frankfurt",
    "turkey", "kongre", "organizasyon", "yatirim", "yatirimlari",
}


def _agency_name_tokens(name: str) -> Set[str]:
    """TEK acente adından ayırt edici (normalize) token kümesi çıkar."""
    tokens: Set[str] = set()
    if not name:
        return tokens
    cleaned = re.sub(r"\([^)]*\)", "", name)
    cleaned = re.sub(r"[.\-/,;:]+", " ", cleaned)
    for w in cleaned.split():
        norm = _normalize(w.strip())
        if (
            len(norm) < _MIN_WORD_LEN
            or norm in _SKIP_WORDS
            or norm in _AGENCY_TOKEN_SKIP
            or norm.isdigit()
        ):
            continue
        tokens.add(norm)
    return tokens


def _agency_collection_signals(db: Session) -> Tuple[Dict[Tuple[int, str], List[dict]], List[Set[str]]]:
    """Acente tahsilat sinyalleri.

    Döner: (amount_index, token_sets)
    - amount_index: (kuruş, para birimi) → [{"date", "col_id"}] — kuruş hassasiyetinde
      int anahtar (float sapması olmasın). Döviz tahsilatın TL karşılığı (amount) ayrıca
      TRY anahtarıyla eklenir (EUR faturalı acente TL EFT'yle ödeyebilir); col_id ortak →
      tek tahsilat toplamda EN ÇOK BİR işlemi etiketler.
    - token_sets: ACENTE BAZINDA token kümeleri (çapraz-acente 2'li kombinasyon
      eşleşme sayılmasın — auto_match_vendors'daki cari-bazlı keyword deseni).
    """
    amount_index: Dict[Tuple[int, str], List[dict]] = defaultdict(list)
    token_sets: List[Set[str]] = []

    collections = (
        db.query(SalesCollection)
        .filter(SalesCollection.customer_code.like("120.%"))
        .all()
    )
    for col in collections:
        norm_name = _normalize(col.customer_name or "")
        if _AGENCY_NAME_BLOCK.search(norm_name):
            continue  # banka/telekom/kiracı — acente değil (120.01.* içinde de olabilir)
        has_hint = bool(_AGENCY_NAME_HINT.search(norm_name))
        is_agency = (col.customer_code or "").startswith(_AGENCY_CODE_PREFIX) or has_hint
        if not is_agency:
            continue
        # Token havuzuna yalnız isim-ipucu-doğrulanmış acenteler girer (segment saf
        # değil: kişi/karışık kayıtların adları token üretmesin); tutar sinyali için
        # segment yeterli (kuruş+para birimi+tarih birebir eşleşme zaten güçlü kanıt).
        if has_hint:
            tokens = _agency_name_tokens(col.customer_name or "")
            if tokens:
                token_sets.append(tokens)
        cur = (col.currency or "TL").upper()
        cur = "TRY" if cur == "TL" else cur
        native = float(col.amount_currency or 0) or float(col.amount or 0)
        if native:
            amount_index[(int(round(native * 100)), cur)].append(
                {"date": col.collection_date, "col_id": col.id}
            )
        if cur != "TRY" and col.amount:
            amount_index[(int(round(float(col.amount) * 100)), "TRY")].append(
                {"date": col.collection_date, "col_id": col.id}
            )

    for grp in db.query(AgencyGroup).all():
        for name in [grp.name or ""] + list(grp.members or []):
            tokens = _agency_name_tokens(name)
            if tokens:
                token_sets.append(tokens)
    for (agency,) in db.query(Reservation.agency).distinct().all():
        tokens = _agency_name_tokens(agency or "")
        if tokens:
            token_sets.append(tokens)

    return amount_index, token_sets


def _tag_agency_collections(
    db: Session, untagged: List[BankTransaction], agency_cat_id: int
) -> List[BankTransaction]:
    """Etiketsiz GELİR işlemlerinden acenta tahsilatlarını işaretle (commit ETMEZ)."""
    internal_move = re.compile(r"virman|hesaplar[i]? aras[i]|hesaplarim arasi")
    candidates = [
        tx for tx in untagged
        if tx.type == "income" and not internal_move.search(_normalize(tx.description or ""))
    ]
    if not candidates:
        return []

    # Açıklama ipucu sinyalsiz de çalışır — Sedna verisi boşken erken dönme (test bulgusu)
    amount_index, token_sets = _agency_collection_signals(db)
    all_tokens: Set[str] = set().union(*token_sets) if token_sets else set()
    account_currency = {a.id: (a.currency or "TRY").upper() for a in db.query(BankAccount).all()}
    window = timedelta(days=_AGENCY_DATE_WINDOW_DAYS)
    consumed_cols: Set[int] = set()  # tüketilen tahsilatlar (bir tahsilat = en çok bir işlem)
    tagged: List[BankTransaction] = []

    for tx in candidates:
        normalized = _normalize(tx.description or "")
        desc_hit = bool(_AGENCY_DESC_HINT.search(normalized))

        # Acente adı token eşleşmesi: AYNI acenteden ≥2 token veya tek token ≥8 karakter
        token_hit = False
        if all_tokens:
            desc_words = {w for w in re.split(r"[^a-z0-9]+", normalized) if w}
            hits = desc_words & all_tokens
            if hits:
                token_hit = any(len(h) >= _AGENCY_MIN_SINGLE_TOKEN for h in hits) or any(
                    len(desc_words & ts) >= 2 for ts in token_sets
                )

        matched = desc_hit or token_hit

        # Sedna tahsilat tutar eşleşmesi — transfer görünümlü açıklamada (havale/EFT/
        # FAST/transfer) SALT-TUTAR yetmez: isim/ipucu eş-sinyali olmadan etiketleme
        # (kendi transferleri + misafir FAST'leri tutar çakışmasına düşüyordu).
        if not matched and amount_index and not _TRANSFERISH.search(normalized):
            cur = account_currency.get(tx.account_id, "TRY")
            cur = "TRY" if cur == "TL" else cur
            key = (int(round(abs(float(tx.amount)) * 100)), cur)
            for entry in amount_index.get(key, []):
                if entry["col_id"] in consumed_cols:
                    continue
                if abs(tx.date - entry["date"]) <= window:
                    consumed_cols.add(entry["col_id"])
                    matched = True
                    break

        if matched:
            tx.category_id = agency_cat_id
            tx.tag_source = "auto"
            tagged.append(tx)

    return tagged


# ─── Cari Bazlı Otomatik Eşleştirme ──────────────────────────────────


# Kısa/genel kelimeler (false positive üretir)
_SKIP_WORDS = {
    # Kısa genel kelimeler
    "ve", "san", "tic", "ltd", "sti", "as", "dis", "hiz", "paz",
    "nak", "oto", "ith", "ihr", "pet", "mad", "tur", "ins",
    # Uzun ama çok genel ticari kelimeler (çoğu açıklamada geçer)
    "anonim", "sirketi", "sirket", "limited", "ticaret", "ticari",
    "sanayi", "sanayii", "turizm", "insaat", "insa", "gida",
    "hizmet", "hizmetleri", "pazarlama", "nakliyat", "otomotiv",
    "ithalat", "ihracat", "petrol", "madencilik", "enerji",
    "elektrik", "elektronik", "tekstil", "dekorasyon",
    "muhendislik", "mimarlik", "taahut", "taahhut",
    "danismanlik", "lojistik", "bilisim", "yazilim",
    "transfer", "tahsilat", "odeme", "havale", "dekont",
    "ankara", "istanbul", "antalya", "izmir",
}

# Minimum kelime uzunluğu (kısa kelimeler çok fazla false positive üretir)
_MIN_WORD_LEN = 4


def _extract_vendor_keywords(hesap_adi: str) -> List[str]:
    """Cari adından arama kelimeleri çıkar.

    Strateji: ayırt edici kelimeleri seç, genel kelimeleri atla.
    """
    # Parantez içini kaldır, noktalama temizle
    name = re.sub(r"\([^)]*\)", "", hesap_adi)
    name = re.sub(r"[.\-/,;:]+", " ", name)
    words = name.upper().split()

    keywords = []
    for w in words:
        w_clean = w.strip()
        if len(w_clean) < _MIN_WORD_LEN:
            continue
        if _normalize(w_clean) in _SKIP_WORDS:
            continue
        keywords.append(w_clean)
        # En fazla 3 ayırt edici kelime yeterli
        if len(keywords) >= 3:
            break

    return keywords


def auto_match_vendors(
    db: Session,
    mode: str = "name",
    dry_run: bool = False,
) -> Dict[str, int]:
    """Etiketsiz banka işlemlerini cari hesaplarla otomatik eşleştir.

    Eşleştirme stratejileri:
      - "name": Cari adı banka açıklamasında geçiyor
      - "amount": Aynı tarih + aynı tutar (%1 tolerans)
      - "both": Hem isim hem tutar eşleşmeli (en güvenilir)

    Args:
        db: Veritabanı oturumu
        mode: Eşleştirme modu ("name", "amount", "both")
        dry_run: True ise sadece eşleşmeleri say, DB'ye yazma

    Returns:
        {"matched": N, "total_untagged": M, "vendors_used": K, "details": [...]}
    """
    # Tüm carileri al
    vendors = db.query(Vendor).all()
    if not vendors:
        return {"matched": 0, "total_untagged": 0, "vendors_used": 0}

    # Cari isim → keyword haritası
    vendor_keywords: Dict[int, List[str]] = {}
    for v in vendors:
        kws = _extract_vendor_keywords(v.hesap_adi)
        if kws:
            vendor_keywords[v.id] = kws

    # Cari tarih+tutar index'i oluştur (amount modu için)
    # {(date, rounded_amount): vendor_id}
    vendor_amounts: Dict[Tuple, int] = {}
    if mode in ("amount", "both"):
        vtx_rows = (
            db.query(
                VendorTransaction.date,
                VendorTransaction.borc,
                VendorTransaction.vendor_id,
            )
            .filter(VendorTransaction.borc > 0)
            .all()
        )
        for row in vtx_rows:
            key = (row.date, round(float(row.borc), 2))
            vendor_amounts[key] = row.vendor_id

    # Etiketsiz + cariye eşlenmemiş banka işlemleri
    untagged = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.vendor_id.is_(None),
        )
        .all()
    )

    matched_count = 0
    matched_txs = []
    vendors_used = set()
    details = []

    for tx in untagged:
        matched_vendor_id = None
        match_method = None

        tx_desc_upper = tx.description.upper() if tx.description else ""
        tx_amount = round(abs(float(tx.amount)), 2)

        if mode == "both":
            # Her iki koşul da sağlanmalı
            amount_key = (tx.date, tx_amount)
            amount_vendor_id = vendor_amounts.get(amount_key)
            if amount_vendor_id and amount_vendor_id in vendor_keywords:
                kws = vendor_keywords[amount_vendor_id]
                if any(kw in tx_desc_upper for kw in kws):
                    matched_vendor_id = amount_vendor_id
                    match_method = "tarih+tutar+isim"

        elif mode == "amount":
            # Tarih + tutar eşleşmesi
            amount_key = (tx.date, tx_amount)
            if amount_key in vendor_amounts:
                matched_vendor_id = vendor_amounts[amount_key]
                match_method = "tarih+tutar"

        elif mode == "name":
            # İsim eşleşmesi: en çok keyword eşleşen cari kazanır
            best_match_id = None
            best_match_score = 0
            best_match_kw_len = 0
            for vid, kws in vendor_keywords.items():
                matching_kws = [kw for kw in kws if kw in tx_desc_upper]
                score = len(matching_kws)
                max_kw_len = max((len(kw) for kw in matching_kws), default=0)
                if score > best_match_score or (score == best_match_score and max_kw_len > best_match_kw_len):
                    best_match_score = score
                    best_match_id = vid
                    best_match_kw_len = max_kw_len
            # Eşleşme kalite kontrolü:
            # - 2+ keyword eşleşmeli VEYA
            # - Tek keyword ise en az 8 karakter olmalı (kısa/genel isimleri eleme)
            if best_match_id is not None:
                if best_match_score >= 2 or (best_match_score == 1 and best_match_kw_len >= 8):
                    matched_vendor_id = best_match_id
                    match_method = "isim"

        if matched_vendor_id:
            if not dry_run:
                tx.vendor_id = matched_vendor_id
                tx.tag_note = tx.tag_note or next(
                    (v.hesap_adi for v in vendors if v.id == matched_vendor_id), None
                )
                tx.tag_source = "auto"
                matched_txs.append(tx)
            matched_count += 1
            vendors_used.add(matched_vendor_id)

    if matched_count > 0 and not dry_run:
        db.flush()
        _sync_finance_events(db, matched_txs)  # otomatik cari ataması FE'ye yansısın

    return {
        "matched": matched_count,
        "total_untagged": len(untagged),
        "vendors_used": len(vendors_used),
    }
