"""Sedna karşı-hesap köprüsü — mutabakatta eşleşen ETİKETSİZ banka hareketlerini kategorize eder.

Banka↔Sedna mutabakatı (`sedna_recon_service.run_reconciliation`) bir banka hareketini
Sedna fişiyle eşlediğinde, fişin KARŞI-HESAP bacakları (102 banka bacağı dışındaki
AccountingTrans satırları) hareketin niteliğini söyler: 335/196 = personel, 320 = cari,
360/368 = vergi... Kelime kural motoru (`auto_tagger`) "Para Gönder Diğer <kişi adı>"
gibi sinyalsiz açıklamaları etiketleyemediğinden bu sınıf kalemler Panel T-Hesap'ta
"Etiketsiz"te kalıyordu (2026-07-23 kullanıcı bulgusu — 20 Tem'de 28 personel avansı).
Bu köprü, 2026-07-18'de ELLE yapılan karşı-hesap denetiminin kalıcı otomasyonudur ve
2 saatlik cron'un bank_recon adımıyla birlikte koşar.

Temkinlilik kuralları (yalnız kanıtlı sınıflar — 2026-07-18 denetim dersleri):
- Karar bacağı = fişin 102-dışı bacaklarından |tutar|ı en büyük olanı. Prefix haritada
  yoksa kalem ETİKETLENMEZ (770 gibi karışık gider hesapları bilinçli dışarıda —
  denetimde de o sınıfın kategori kararı kullanıcıya bırakılmıştı).
- Fişte 102-dışı bacak hiç yoksa (banka↔banka fişi): karşı 102 hesabı bizim eşlenmiş
  hesaplarımızdan FARKLI para birimindeyse "Döviz Satışı", değilse "Virman".
- Aynı (tarih, tutar) anahtarında k↔k eşleşme banka↔fiş eşlemesini ÇAPRAZLAYABİLİR
  (aynı gün iki ₺15.000 avans) → grup yalnız TÜM fişler AYNI kategoriye çıkıyorsa
  etiketlenir; cari (vendor_id) ve tag_note ataması yalnız birebir (exact) eşleşmede.
- Manuel/mevcut etiket ASLA ezilmez (yalnız `category_id IS NULL` taranır); "pos bloke"
  açıklamaları atlanır (çift-bacak POS tagger'ının alanı — `_tag_pos_bloke_transfers`).
- `tag_source='sedna'` yazılır; CC matcher yeniden-tarama filtresi bu değeri 'auto'
  gibi sayar (`matching_service._match_cc_to_bank`).
"""
import logging
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.vendor import Vendor
from app.utils import sedna_client
from app.utils.auto_tagger import LEASING_CATEGORY, _get_or_create_category, _sync_finance_events

logger = logging.getLogger(__name__)

# Karşı-hesap prefix'i → kategori adı. YALNIZ kanıtlı sınıflar — yeni prefix eklerken
# önce Sedna fiş örnekleriyle doğrula (2026-07-18 dersi: sabit kelime/format niteliği
# değil biçimi anlatır; burada da hesap planı anlamı esas alınır).
PREFIX_CATEGORY: Dict[str, str] = {
    "335": "Personel",       # Personele Borçlar
    "196": "Personel",       # Personel Avansları
    "320": "Cari",           # Satıcılar
    "360": "Vergi/SGK",      # Ödenecek Vergi ve Fonlar
    "361": "Vergi/SGK",      # Ödenecek SGK Kesintileri
    "368": "Vergi/SGK",      # Taksitlendirilmiş Vergi
    "369": "Vergi/SGK",      # Ödenecek Diğer Yükümlülükler
    "300": LEASING_CATEGORY,  # Banka Kredileri
    "303": LEASING_CATEGORY,  # Uzun Vadeli Kredi Anapara Taksitleri
    "340": "Acenta",         # Alınan Sipariş Avansları (tur operatörü avansları)
    "331": "Temettü",        # Ortaklara Borçlar
}

TAG_SOURCE_SEDNA = "sedna"


def _f(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def decide_category(
    legs: List[dict],
    own_code: Optional[str],
    account_currency: Optional[str],
    mapped_currencies: Dict[str, str],
) -> Tuple[Optional[str], Optional[dict]]:
    """Fiş bacaklarından (kategori adı, karar bacağı) türet — saf, test edilebilir.

    legs: fetch_fiche_counter_legs satırları (tek fiş). own_code: banka hesabımızın
    Sedna 102 kodu (kendi bacağımız karar dışı). mapped_currencies: bizim eşlenmiş
    hesaplarımız {sedna_code: currency} (banka↔banka fişinde döviz satışı ayrımı).
    Haritalanamayan fiş → (None, None): kalem etiketlenmez.
    """
    others = [l for l in legs if (l.get("code") or "") != (own_code or "")]
    non_bank = [l for l in others if not (l.get("code") or "").startswith("102")]
    if non_bank:
        decisive = max(non_bank, key=lambda l: abs(_f(l.get("debit")) - _f(l.get("credit"))))
        prefix = (decisive.get("code") or "").split(".")[0]
        cat = PREFIX_CATEGORY.get(prefix)
        return (cat, decisive) if cat else (None, None)
    bank_others = [l for l in others if (l.get("code") or "").startswith("102")]
    if not bank_others:
        return None, None
    for l in bank_others:
        cur = mapped_currencies.get(l.get("code") or "")
        if cur and cur != (account_currency or "TRY"):
            return "Döviz Satışı", l
    return "Virman", bank_others[0]


def apply_sedna_tag_bridge(
    db: Session,
    bridge_groups: List[dict],
    fetch_legs: Optional[Callable[[List[int]], List[dict]]] = None,
) -> dict:
    """Mutabakat eşleşmelerinden etiketsiz banka hareketlerini kategorize et.

    bridge_groups: [{"account": BankAccount, "groups": [{"btxs", "sednas", "exact"}]}]
    (`_match_account`'ın match_groups_out çıktısı). Commit'i KENDİSİ yapar (mutabakat
    koşusunun ana commit'inden sonra, izole). Sedna erişilemezse exception yükselir —
    çağıran (run_reconciliation) yutar, mutabakat sonucu etkilenmez.
    """
    fetch_legs = fetch_legs or sedna_client.fetch_fiche_counter_legs

    # Aday = etiketsiz + "pos bloke" olmayan banka hareketleri (manuel etiket ezilmez)
    all_ids = [b["id"] for entry in bridge_groups for g in entry["groups"] for b in g["btxs"]]
    if not all_ids:
        return {"sedna_tagged": 0}
    candidates = {
        t.id: t
        for t in db.query(BankTransaction)
        .filter(BankTransaction.id.in_(all_ids), BankTransaction.category_id.is_(None))
        .all()
        if "pos bloke" not in (t.description or "").lower()
    }
    if not candidates:
        return {"sedna_tagged": 0}

    owner_ids = {
        s.get("owner_id")
        for entry in bridge_groups
        for g in entry["groups"]
        if any(b["id"] in candidates for b in g["btxs"])
        for s in g["sednas"]
        if s.get("owner_id")
    }
    legs_by_owner: Dict[int, List[dict]] = {}
    for leg in fetch_legs(sorted(owner_ids)):
        legs_by_owner.setdefault(leg["owner_id"], []).append(leg)

    mapped_currencies = {
        a.sedna_account_code: (a.currency or "TRY")
        for a in db.query(BankAccount).filter(BankAccount.sedna_account_code.isnot(None)).all()
    }

    tagged: List[BankTransaction] = []
    skipped_unmapped = 0
    skipped_ambiguous = 0
    for entry in bridge_groups:
        acc = entry["account"]
        for g in entry["groups"]:
            cand_btxs = [candidates[b["id"]] for b in g["btxs"] if b["id"] in candidates]
            if not cand_btxs:
                continue
            decisions = [
                decide_category(legs_by_owner.get(s.get("owner_id"), []),
                                acc.sedna_account_code, acc.currency, mapped_currencies)
                for s in g["sednas"]
            ]
            cats = {c for c, _ in decisions}
            if None in cats:
                skipped_unmapped += len(cand_btxs)
                continue
            if len(cats) != 1:
                # k↔k çaprazlanma riski: fişler farklı kategorilere çıkıyor → dokunma
                skipped_ambiguous += len(cand_btxs)
                continue
            cat = _get_or_create_category(db, cats.pop())
            for btx in cand_btxs:
                btx.category_id = cat.id
                btx.tag_source = TAG_SOURCE_SEDNA
                tagged.append(btx)
            # Cari/tag_note yalnız birebir eşleşmede (çaprazlanmış kişi/firma yazılmasın)
            if g.get("exact") and len(cand_btxs) == 1 and decisions[0][1]:
                btx, decisive = cand_btxs[0], decisions[0][1]
                code = decisive.get("code") or ""
                name = (decisive.get("account_name") or "").strip()
                if code.startswith("320") and btx.vendor_id is None:
                    vendor = db.query(Vendor).filter(Vendor.hesap_kodu == code).first()
                    if vendor:
                        btx.vendor_id = vendor.id
                if name and not btx.tag_note:
                    btx.tag_note = f"Sedna: {name}"[:300]

    if tagged:
        db.flush()
        _sync_finance_events(db, tagged)  # kategori/cari FE'ye yansısın (T-Hesap başlığı)
        db.commit()
        logger.info(
            "Sedna karşı-hesap köprüsü: %d hareket etiketlendi (%d haritasız, %d belirsiz atlandı)",
            len(tagged), skipped_unmapped, skipped_ambiguous,
        )
    return {
        "sedna_tagged": len(tagged),
        "sedna_tag_skipped_unmapped": skipped_unmapped,
        "sedna_tag_skipped_ambiguous": skipped_ambiguous,
    }
