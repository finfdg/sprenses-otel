"""Otomatik işlem etiketleme utility'si."""
import logging
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.bank_transaction import BankTransaction
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
    return dict(counts)


def _normalize(text: str) -> str:
    """Türkçe karakterleri ASCII'ye çevir ve küçült."""
    return text.translate(_TR_MAP).lower()


# Kategori adı → regex pattern (normalize edilmiş metin üzerinde çalışır)
AUTO_TAG_RULES: List[Tuple[str, str]] = [
    ("Virman", r"virman|havale|eft |transfer"),
    ("POS", r"pos |kkiv|kart "),
    ("Kredi", r"kredi|taksit|kmh"),
    ("Personel", r"maas|personel|ucret"),
    ("Vergi/SGK", r"vergi|sgk|sgdp|tahsilat"),
    ("Komisyon", r"komisyon|masraf"),
]


def auto_tag_transactions(
    db: Session,
    transaction_ids: Optional[List[int]] = None,
) -> Tuple[int, int]:
    """Etiketlenmemiş işlemlere otomatik kural uygula.

    Returns:
        (etiketlenen_sayı, toplam_etiketsiz_sayı)
    """
    # Kategori adı → id eşlemesi
    categories = db.query(TransactionCategory).all()
    cat_map = {c.name: c.id for c in categories}

    # Etiketlenmemiş işlemleri al
    query = db.query(BankTransaction).filter(
        BankTransaction.category_id.is_(None),
    )
    if transaction_ids:
        query = query.filter(BankTransaction.id.in_(transaction_ids))

    untagged = query.all()
    tagged_count = 0

    for tx in untagged:
        normalized = _normalize(tx.description)
        for cat_name, pattern in AUTO_TAG_RULES:
            if re.search(pattern, normalized):
                cat_id = cat_map.get(cat_name)
                if cat_id:
                    tx.category_id = cat_id
                    tx.tag_source = "auto"
                    tagged_count += 1
                break  # İlk eşleşen kural kazanır

    if tagged_count > 0:
        db.flush()

    return tagged_count, len(untagged)


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
            matched_count += 1
            vendors_used.add(matched_vendor_id)

    if matched_count > 0 and not dry_run:
        db.flush()

    return {
        "matched": matched_count,
        "total_untagged": len(untagged),
        "vendors_used": len(vendors_used),
    }
