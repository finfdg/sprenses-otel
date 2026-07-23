"""Banka ekstresi ↔ çek / kredi / kredi kartı otomatik eşleştirme (reconciliation) servisi.

Banka ekstresi yüklenince banks.py bu üç saf fonksiyonu çağırır. Eskiden domain router
modüllerinde (checks.py, krediler/payments.py, banks_cc_match.py) private duruyorlardı;
katman temizliği için tek servis modülünde toplandı (2026-06-19). Saf (db)->dict fonksiyonları,
FastAPI bağımlılığı yok, yalnız model + finance_event_svc kullanır.
"""
import json
import logging
import re
from collections import defaultdict
from datetime import timedelta
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.advance import Advance
from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.check import Check
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_product import CreditPayment, CreditProduct
from app.models.transaction_category import TransactionCategory
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.utils.finance_event_service import finance_event_svc
from app.utils.text_match import _norm_tokens

logger = logging.getLogger(__name__)

# ─── İki-eşikli bantlar (Faz 1 #9, 2026-07-11) ──────────────────────────────
# Otomatik eşiğin ALTINDA ama öneri-tabanının ÜSTÜNDE kalan en iyi aday otomatik
# UYGULANMAZ; event_matches'e method='suggestion' kaydı düşer (Eşleşme Önerileri
# paneli). Mevcut otomatik davranış DEĞİŞMEZ (geçmiş yanlış-pozitif vakalarının
# panzehiri: KK 13→2, avans yanlış-taksit).
CHECK_AUTO_MIN = 20
CHECK_SUGGEST_MIN = 8
CREDIT_AUTO_MIN = 40
CREDIT_SUGGEST_MIN = 20
ADVANCE_AUTO_MIN = 20
ADVANCE_SUGGEST_MIN = 8
VENDOR_AUTO_MIN = 80          # cari kapatma FIFO'yu değiştirir → en temkinli alan
VENDOR_SUGGEST_MIN = 50
VENDOR_AUTO_WINDOW_DAYS = 7   # otomatik cari eşleşme vade penceresi
VENDOR_SUGGEST_WINDOW_DAYS = 14
FX_SUGGEST_TOLERANCE = 0.01   # çapraz-para beklenen-TL bandı ±%1 (yalnız ÖNERİ üretir)
FX_SUGGEST_WINDOW_DAYS = 10


# ─── Kredi Kartı ↔ Banka Eşleştirme ──────────────────────

# CC ödemesi ekstre toplamını hafifçe aşabilir (faiz/gecikme/masraf/kur farkı) — bu oran
# içinde kalan fazla ödeme yine "tam ödeme" sayılır (fazlası zaten banka hareketinde görünür).
CC_OVERPAY_TOLERANCE = 0.02  # %2

# Kelime-yok yolunda ödeme tarihi ekstre penceresinde olmalı: kesim tarihinden önce
# (ekstre daha oluşmamış) veya son ödemeden bu kadar gün SONRAsına kadar (geç ödeme payı).
CC_PAY_GRACE_DAYS = 25


def _get_card_last4(product: CreditProduct) -> Optional[str]:
    """Kredi kartı ürününden son 4 haneyi çıkar."""
    if not product.details:
        return None
    try:
        details = json.loads(product.details)
        return details.get("kart_no_son4")
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_last4_from_desc(description: str) -> Optional[str]:
    """Banka işlem açıklamasından kart son 4 hanesini çıkar.

    Örnek açıklamalar:
    - '[Kart Ödemesi] K.Kartı Ödeme 5400 **** **** 1028'
    - 'VISA KART ODEME *1234'
    - 'KK BORC ODEME ...5678'
    - 'Diğer Internet - Mobil INT 650837******7261 3006'  (maskeli PAN, sonda referans)
    - 'Kart İşlemleri - 6075 ile biten QNB Corporate ödemesi - Virman'  (yazılı son-4, yıldızsız)
    """
    if not description:
        return None

    # "1028" gibi — son 4 rakam bloğu
    # İlk kalıplar kart no'yu açıklamanın SONUNDA arar; sonraki kalıp maskeli PAN'ı
    # (yıldız bloğu + son 4) açıklamanın herhangi bir yerinde yakalar — mobil/internet
    # havalesi açıklamalarında son 4'ten sonra referans no gelebilir (ör. "...7261 3006").
    # Son kalıp yazıyla verilen "…{son4} ile biten…" desenini (yıldızsız) yakalar (ör. QNB Corporate).
    patterns = [
        r'\*{3,4}\s*(\d{4})\s*$',          # **** 1028 veya ***1028
        r'\*(\d{4})\s*$',                    # *1028
        r'\.{3}(\d{4})\s*$',                # ...1028
        r'(\d{4})\s*\*{4}\s*\*{4}\s*(\d{4})',  # 5400 **** **** 1028
        r'\*{2,}\s*(\d{4})(?!\d)',          # 650837******7261 — maskeli PAN (2+ yıldız + son 4)
        r'(\d{4})\s+ile\s+biten',           # "6075 ile biten …" — yazılı kart son-4 (yıldızsız)
    ]
    for pattern in patterns:
        m = re.search(pattern, description)
        if m:
            return m.group(m.lastindex)

    return None


def _cc_payment_in_window(pay_date, stmt) -> bool:
    """Ödeme tarihi ekstrenin makul ödeme penceresinde mi?

    Kesim tarihinden ÖNCE (ekstre henüz oluşmamış) veya son ödemeden CC_PAY_GRACE_DAYS
    gün SONRAsından ileri olan bir ödeme, o ekstrenin ödemesi olamaz → başka aya aittir.
    Kelime-yok yolunda farklı-ayın ödemesinin açık ekstreye yanlış atanmasını engeller.
    """
    if pay_date is None:
        return False
    if stmt.kesim_tarihi and pay_date < stmt.kesim_tarihi:
        return False
    if stmt.son_odeme_tarihi and pay_date > stmt.son_odeme_tarihi + timedelta(days=CC_PAY_GRACE_DAYS):
        return False
    return True


def _is_cc_payment_desc(description: str) -> bool:
    """Açıklamanın kredi kartı ödemesi olup olmadığını kontrol et."""
    if not description:
        return False
    desc_lower = description.lower()
    keywords = ["kart öd", "kart od", "k.kartı", "k.karti", "kk borc", "kk borç",
                "kredi kartı", "kredi karti", "credit card", "visa kart", "mastercard"]
    if any(kw in desc_lower for kw in keywords):
        return True
    # Bankanın yazıyla kart-no verdiği ödeme deseni: "…{son4} ile biten … ödeme(si)"
    # (ör. QNB Corporate "Virman" ödemeleri — yıldızlı PAN yok). Kısmi ödemelerin de
    # eşleşebilmesi için (kelime yolu partial'a izin verir) bu güvenilir imzayı tanı;
    # son-4 kapısı + tutar eşleşmesi yanlış-pozitifi engeller. "öde" şartı kart aidatı/
    # ücretini dışarıda bırakır (kısmi tutarla yanlış ekstre düşülmesin).
    if "ile biten" in desc_lower and "öde" in desc_lower:
        return True
    return False


def _match_cc_to_bank(db: Session) -> dict:
    """Ödenmemiş CC ekstrelerini banka işlemleriyle otomatik eşleştir.

    Ekstre yüklendiğinde çağrılır.
    Eşleşme kriterleri:
    - Banka işlemi gider olmalı
    - Açıklamada kart ödemesi ifadesi + son 4 hane eşleşmeli
    - Tutar eşleşmeli (tam veya kısmi)

    Returns:
        {"matched": int, "details": list}
    """
    # Ödenmemiş CC ekstreleri
    unpaid = (
        db.query(CreditCardStatement)
        .filter(CreditCardStatement.is_paid == False)
        .all()
    )
    if not unpaid:
        return {"matched": 0}

    # Ürün bilgileri + son 4 hane cache
    product_cache = {}
    last4_to_stmts = {}  # son4 → [stmt, ...]
    for stmt in unpaid:
        if stmt.credit_product_id not in product_cache:
            prod = db.query(CreditProduct).filter(CreditProduct.id == stmt.credit_product_id).first()
            product_cache[stmt.credit_product_id] = prod
        prod = product_cache[stmt.credit_product_id]
        if not prod:
            continue
        last4 = _get_card_last4(prod)
        if last4:
            last4_to_stmts.setdefault(last4, []).append((stmt, prod))

    if not last4_to_stmts:
        return {"matched": 0}

    kk_cat = db.query(TransactionCategory).filter(TransactionCategory.name == "Kredi Kartı Borç Ödeme").first()

    # Etiketsiz VE otomatik-etiketli gider işlemleri taranır. Auto-tag orkestratörde
    # matcher'lardan ÖNCE koşar (run_post_ingest_processing) → "kart ödemesi" açıklamalı
    # gider POS gibi genel bir kelime kuralına düşünce salt-NULL filtre onu bu matcher'dan
    # kalıcı saklıyordu (canlı: ₺1,9M QNB kart ödemesi POS etiketiyle eşleşemedi,
    # 2026-07-14). Manuel etiket kullanıcı kararıdır → dokunulmaz; KK kategorisindeki
    # otomatik etiket zaten eşleşmiş ödemedir → yeniden taranıp paid_amount mükerrer
    # artmasın. 'sedna' (karşı-hesap köprüsü, 2026-07-23) da makine etiketidir — 'auto'
    # ile aynı muamele (köprü bir KK ödemesini yanlış sınıflarsa matcher düzeltebilsin).
    if kk_cat:
        tag_filter = or_(
            BankTransaction.category_id.is_(None),
            and_(BankTransaction.tag_source.in_(("auto", "sedna")),
                 BankTransaction.category_id != kk_cat.id),
        )
    else:
        tag_filter = BankTransaction.category_id.is_(None)
    bank_expenses = (
        db.query(BankTransaction)
        .filter(BankTransaction.type == "expense", tag_filter)
        .all()
    )

    matched_count = 0
    details = []

    for btx in bank_expenses:
        btx_last4 = _extract_last4_from_desc(btx.description)
        # Kredi kartı ödemesi sinyali: açıklamada bilinen (ödenmemiş) bir kartın maskeli
        # son-4 hanesi geçiyor. Kelime kapısı ("kart öd" vb.) KALDIRILDI (2026-07-04) —
        # mobil/internet havalesiyle yapılan kart ödemelerinin açıklamasında kart ifadesi
        # yoktur ama maskeli PAN vardır (ör. "Diğer Internet - Mobil INT 650837******7261").
        # Yanlış-pozitifi aşağıdaki tutar eşleşmesi engeller (bilinen kart + tutar uyumu).
        if not btx_last4 or btx_last4 not in last4_to_stmts:
            continue

        payment_amount = abs(float(btx.amount))
        has_keyword = _is_cc_payment_desc(btx.description)

        # En uygun ekstre bul: son_odeme_tarihi'ne en yakın + tutar eşleşen
        best_stmt = None
        best_prod = None
        best_remaining = None

        for stmt, prod in last4_to_stmts[btx_last4]:
            remaining = float(stmt.toplam_borc) - float(stmt.paid_amount or 0)
            if remaining <= 0.01:
                continue
            total_borc = float(stmt.toplam_borc)

            if has_keyword:
                # Açıklamada kart ifadesi VAR — güvenilir sinyal; mevcut mantık (değişmedi):
                # tam eşleşme (kalan/toplam) veya kısmi (tarih yakınlığıyla en uygun ekstre).
                if abs(payment_amount - remaining) < 0.01:
                    best_stmt = stmt
                    best_prod = prod
                    best_remaining = remaining
                    break
                elif abs(payment_amount - total_borc) < 0.01:
                    best_stmt = stmt
                    best_prod = prod
                    best_remaining = remaining
                    break
                elif payment_amount <= remaining + 0.01:
                    # Kısmi ödeme — tarih yakınlığına bak
                    if best_stmt is None:
                        best_stmt = stmt
                        best_prod = prod
                        best_remaining = remaining
                    elif stmt.son_odeme_tarihi and btx.date:
                        # Son ödeme tarihine en yakın ekstre
                        if best_stmt.son_odeme_tarihi is None or \
                           abs((btx.date - stmt.son_odeme_tarihi).days) < abs((btx.date - best_stmt.son_odeme_tarihi).days):
                            best_stmt = stmt
                            best_prod = prod
            else:
                # Kelime YOK ama bilinen kart son-4'ü (ör. "Diğer Internet - Mobil INT
                # ...7261"). Aşırı eşleşmeyi önlemek için YÜKSEK GÜVEN şartı: yalnız TAM
                # ödeme (≈ ekstre toplamı; hafif fazla dahil) + ödeme tarihi ekstre
                # penceresinde. Kısmi/farklı-ay ödemeleri (oto-ödeme kartlarında bol)
                # elenir — bunlar açık ekstrelere yanlış atanıyordu.
                if not _cc_payment_in_window(btx.date, stmt):
                    continue
                if total_borc - 1.0 <= payment_amount <= total_borc * (1 + CC_OVERPAY_TOLERANCE):
                    best_stmt = stmt
                    best_prod = prod
                    best_remaining = remaining
                    break

        if not best_stmt or not best_prod:
            continue

        # Yarış koruması: ekstre hâlâ açık mı (tetikler çoğaldı — Faz 1)
        locked_stmt = (db.query(CreditCardStatement)
                       .filter(CreditCardStatement.id == best_stmt.id,
                               CreditCardStatement.is_paid == False)  # noqa: E712
                       .with_for_update(skip_locked=True).first())
        if locked_stmt is None:
            continue
        best_stmt = locked_stmt

        # Eşleştir
        current_paid = float(best_stmt.paid_amount or 0)
        new_paid = current_paid + payment_amount
        total_borc = float(best_stmt.toplam_borc)

        best_stmt.paid_amount = min(new_paid, total_borc)
        if new_paid >= total_borc - 0.01:
            best_stmt.is_paid = True
            best_stmt.paid_date = btx.date

        # Banka işlemini etiketle
        btx.category_id = kk_cat.id if kk_cat else None
        btx.tag_source = "auto"
        btx.tag_note = best_prod.name
        btx.payment_method = "kredi_karti"

        # finance_events güncelle
        finance_event_svc.sync_tag(
            db, btx.id,
            category_id=btx.category_id,
            category_name=kk_cat.name if kk_cat else None,
            category_color=kk_cat.color if kk_cat else None,
            tag_note=btx.tag_note,
            tag_source=btx.tag_source,
            payment_method=btx.payment_method,
            match_number=None,
            vendor_id=None,
        )

        # CC ekstre FE'sini yeniden hesapla (tek-kaynak upsert — çek düzeltmesiyle aynı
        # desen): tam ödemede gizlenir (is_matched + event_status='paid'), kısmi ödemede
        # kalan borç düşer. Elle is_matched set etmek event_status'ü bayat bırakıyordu.
        finance_event_svc.upsert_cc_statement(db, best_stmt, best_prod)

        matched_count += 1
        card_name = best_prod.name
        logger.info(
            "CC otomatik eşleşme: btx=%d → stmt=%d (%s) | ₺%s",
            btx.id, best_stmt.id, card_name, f"{payment_amount:,.2f}",
        )
        details.append({
            "bank_tx_id": btx.id,
            "statement_id": best_stmt.id,
            "card_name": card_name,
            "amount": payment_amount,
        })

    return {"matched": matched_count, "details": details}


# ─── Çek ↔ Banka Eşleştirme ──────────────────────────────


def _match_checks_to_bank(db: Session) -> dict:
    """Bekleyen çekleri banka işlemleriyle eşleştir.

    Eşleştirme önceliği:
    1. Çek numarası banka açıklamasında geçiyor + tutar eşleşiyor (kesin)
    2. Tutar + tarih (±3 gün) eşleşiyor (yüksek güvenilirlik)

    Eşleşen çekler 'paid' olarak işaretlenir.
    """
    from collections import defaultdict

    # Eşleşmemiş bekleyen çekler
    pending_checks = (
        db.query(Check)
        .filter(Check.status == "pending", Check.bank_transaction_id.is_(None))
        .all()
    )
    if not pending_checks:
        return {"matched": 0, "total_pending": 0}

    # Eşleşmemiş banka gider işlemleri (çekle eşleşmemiş olanlar)
    already_matched_ids = set(
        r[0] for r in
        db.query(Check.bank_transaction_id)
        .filter(Check.bank_transaction_id.isnot(None))
        .all()
    )

    bank_expenses = (
        db.query(BankTransaction)
        .filter(BankTransaction.type == "expense")
        .all()
    )

    # Tutar bazlı index
    btx_by_amount = defaultdict(list)
    for tx in bank_expenses:
        if tx.id not in already_matched_ids:
            btx_by_amount[round(abs(float(tx.amount)), 2)].append(tx)

    matched_count = 0
    used_btx_ids = set()

    for check in pending_checks:
        # Hem TL hem döviz tutarıyla aday ara
        amt_tl = round(float(check.amount_tl), 2)
        amt_cur = round(float(check.amount_currency), 2)
        candidates = btx_by_amount.get(amt_tl, [])
        if amt_cur != amt_tl:
            candidates = candidates + btx_by_amount.get(amt_cur, [])

        best_match = None
        best_score = 0

        # Çek numarasını normalize et (baştaki sıfırları kaldır)
        check_no_stripped = check.check_no.lstrip("0")

        for tx in candidates:
            if tx.id in used_btx_ids:
                continue

            date_diff = abs((tx.date - check.due_date).days)
            if date_diff > 10:
                continue

            score = 0
            desc_upper = tx.description.upper()

            # Çek numarası açıklamada geçiyor → kesin eşleşme
            # Hem orijinal hem sıfırsız versiyonunu kontrol et
            if check.check_no in desc_upper or (check_no_stripped and check_no_stripped in desc_upper):
                score = 100 - date_diff

            # Çek numarası yok ama çek ödeme ifadesi + tutar+tarih
            elif date_diff <= 5 and ("TAKAS" in desc_upper or "ÇEKLE" in desc_upper or "CEKLE" in desc_upper or "ÇEK NO" in desc_upper or "CEK NO" in desc_upper or "TAKAS CEKI" in desc_upper or "ÇEK" in desc_upper and "ÖDEME" in desc_upper):
                score = 60 - date_diff * 5

            if score > best_score:
                best_score = score
                best_match = tx

        if best_match and best_score >= CHECK_AUTO_MIN:
            # apply_* yarış-korumalı: koşul commit anına kadar değişmiş olabilir
            if apply_check_bank_match(db, check, best_match, method="auto", score=best_score):
                used_btx_ids.add(best_match.id)
                matched_count += 1
            continue
        if best_match and best_score >= CHECK_SUGGEST_MIN:
            # İki-eşikli bant (Faz 1 #9): otomatik eşik altı → öneri
            _upsert_suggestion(db, best_match.id, "check", check.id,
                               amt_cur if check.currency != "TL" else amt_tl,
                               "TRY" if check.currency == "TL" else check.currency, best_score)
            continue

        # Çapraz-para önerisi (Faz 1 #13): döviz çek TL hesaptan GÜNCEL kurla ödenmiş
        # olabilir — birebir tutar anahtarı bunu asla yakalayamaz. Beklenen TL bandı
        # (±%1, defter kuru) içindeki TL gideri YALNIZ ÖNERİ olarak sunulur.
        if check.currency != "TL" and amt_cur > 0:
            from app.services.fx_service import ledger_rate
            fx_best, fx_diff = None, None
            for tx in bank_expenses:
                if tx.id in used_btx_ids or tx.id in already_matched_ids:
                    continue
                ddiff = abs((tx.date - check.due_date).days)
                if ddiff > FX_SUGGEST_WINDOW_DAYS:
                    continue
                rate = ledger_rate(db, tx.date, check.currency)
                if not rate:
                    continue
                expected_tl = amt_cur * rate
                delta = abs(abs(float(tx.amount)) - expected_tl)
                if delta <= expected_tl * FX_SUGGEST_TOLERANCE and (fx_diff is None or delta < fx_diff):
                    fx_best, fx_diff = tx, delta
            if fx_best is not None:
                _upsert_suggestion(db, fx_best.id, "check", check.id, amt_cur, check.currency, 40)

    # 1-N otomatik grup (Faz 1 #12): tek EFT ile birden çok çek ödenmesi — aynı cariye
    # ait, vadesi ±2 gün içindeki bekleyen çeklerin TOPLAMI bir banka giderine ±0.02
    # eşitse hepsi kapatılır (kredi faiz+vergi grup deseninin çeke uyarlanması).
    still_pending = [c for c in pending_checks
                     if c.status == "pending" and c.bank_transaction_id is None and c.vendor_code]
    by_vendor = defaultdict(list)
    for c in still_pending:
        if c.currency == "TL":  # grup yalnız TL (döviz çekleri çapraz-para önerisine kaldı)
            by_vendor[c.vendor_code].append(c)
    for vendor_code, checks_group in by_vendor.items():
        if len(checks_group) < 2:
            continue
        checks_group.sort(key=lambda c: c.due_date)
        # ±2 gün vade kümeleri
        i = 0
        while i < len(checks_group):
            cluster = [checks_group[i]]
            j = i + 1
            while j < len(checks_group) and (checks_group[j].due_date - cluster[0].due_date).days <= 2:
                cluster.append(checks_group[j])
                j += 1
            i = j
            if len(cluster) < 2:
                continue
            total = round(sum(float(c.amount_tl) for c in cluster), 2)
            cand = None
            for tx in btx_by_amount.get(total, []):
                if tx.id in used_btx_ids:
                    continue
                if abs((tx.date - cluster[0].due_date).days) <= 5:
                    cand = tx
                    break
            if cand is None:
                continue
            applied = 0
            for c in cluster:
                if apply_check_bank_match(db, c, cand, method="auto", score=90):
                    applied += 1
            if applied:
                used_btx_ids.add(cand.id)
                matched_count += applied
                logger.info("Çek 1-N grup eşleşmesi: btx=%d → %d çek (%s, toplam %s)",
                            cand.id, applied, vendor_code, f"{total:,.2f}")

    return {
        "matched": matched_count,
        "total_pending": len(pending_checks),
    }


# ─── Avans ↔ Banka Eşleştirme ────────────────────────────

# Acente adı banka açıklamasında geçiyorsa (güçlü sinyal) beklenen tarihten bu kadar
# gün GECİKMEYE izin verilir — avansın beklenen tarihi kabaca girilebilir.
ADVANCE_NAMED_WINDOW_DAYS = 60
# İsim eşleşmesi YOKSA yalnız tutar+para birimi+tarih ile eşleşilir (kör yol) —
# yanlış-pozitif riski nedeniyle dar pencere.
ADVANCE_BLIND_WINDOW_DAYS = 10
# Para beklenen tarihten en çok bu kadar gün ÖNCE gelebilir (erken ödeme sınırı).
# Daha erken gelen para büyük olasılıkla ÖNCEKİ taksitin tahsilatıdır (canlı vaka:
# 10.06 Swift'i, elle 'alındı' işaretlenmiş 10.06 taksiti yerine 20.07 taksitine
# bağlanıyordu — isimli yolun geniş penceresi geriye doğru da açıktı).
ADVANCE_EARLY_DAYS = 10


def _match_advances_to_bank(db: Session) -> dict:
    """Bekleyen avansları banka gelir işlemleriyle otomatik eşleştir.

    Ekstre yüklendiğinde çağrılır. Eşleşme kriterleri:
    - Banka işlemi GELİR ve hesabın para birimi avansın para birimiyle aynı
    - Tutar birebir eşleşmeli (±0.01)
    - Acente adı tokenları açıklamada geçiyorsa geniş tarih penceresi
      (±ADVANCE_NAMED_WINDOW_DAYS); geçmiyorsa beklenen tarihe yakınlık şartı
      (skorlu, en çok ±ADVANCE_BLIND_WINDOW_DAYS)
    - "virman" içeren açıklamalar atlanır (hesaplar arası aktarım avans tahsilatı değildir)

    Eşleşen avanslar 'received' yapılır; FE tarafında avans is_matched=True olur,
    banka bacağı görünür kalır (çift sayım kapanır).
    """
    pending = (
        db.query(Advance)
        .filter(Advance.status == "pending", Advance.bank_transaction_id.is_(None))
        .all()
    )
    if not pending:
        return {"matched": 0, "total_pending": 0}

    # Başka avansla zaten eşleşmiş banka işlemleri aday olamaz
    already_matched = set(
        r[0] for r in
        db.query(Advance.bank_transaction_id)
        .filter(Advance.bank_transaction_id.isnot(None))
        .all()
    )

    # ELLE 'alındı' işaretlenmiş avanslar banka işlemine bağlanmaz (btx_id=NULL) —
    # onların karşılığı olan banka hareketi 'boşta' görünür. Aynı (para birimi,
    # tutar, tarih) imzalı hareketleri aday havuzundan düş (canlı vaka: id=217
    # elle alındı → 10.06 Swift'i başka taksite eşleşiyordu).
    manual_receipts = set(
        (a.currency, round(float(a.received_amount or a.amount), 2), a.received_date)
        for a in db.query(Advance)
        .filter(Advance.status == "received", Advance.bank_transaction_id.is_(None),
                Advance.received_date.isnot(None))
        .all()
    )

    bank_incomes = (
        db.query(BankTransaction, BankAccount)
        .join(BankAccount, BankTransaction.account_id == BankAccount.id)
        .filter(BankTransaction.type == "income")
        .all()
    )

    # (para birimi, tutar) bazlı aday index'i
    btx_index = defaultdict(list)
    for tx, acc in bank_incomes:
        if tx.id in already_matched:
            continue
        if "virman" in (tx.description or "").lower():
            continue
        key_amount = round(abs(float(tx.amount)), 2)
        if (acc.currency, key_amount, tx.date) in manual_receipts:
            continue
        btx_index[(acc.currency, key_amount)].append(tx)

    if not btx_index:
        return {"matched": 0, "total_pending": len(pending)}

    matched_count = 0
    used_btx_ids = set()

    # Beklenen tarihi eski olan önce eşleşsin (aynı tutarlı iki avansta determinizm)
    for adv in sorted(pending, key=lambda a: a.advance_date):
        candidates = btx_index.get((adv.currency, round(float(adv.amount), 2)), [])
        if not candidates:
            continue

        adv_tokens = _norm_tokens(adv.agency_name)
        best_match = None
        best_score = 0

        for tx in candidates:
            if tx.id in used_btx_ids:
                continue

            # delta > 0: para beklenenden GEÇ geldi; delta < 0: ERKEN geldi.
            # Erken geliş her iki yolda da ADVANCE_EARLY_DAYS ile sınırlı —
            # daha erken para önceki taksite aittir.
            delta = (tx.date - adv.advance_date).days
            if delta < -ADVANCE_EARLY_DAYS:
                continue
            date_diff = abs(delta)
            name_hit = bool(adv_tokens and adv_tokens & _norm_tokens(tx.description))

            if name_hit:
                if delta > ADVANCE_NAMED_WINDOW_DAYS:
                    continue
                score = 100 - date_diff
            else:
                if delta > ADVANCE_BLIND_WINDOW_DAYS:
                    continue
                score = 60 - date_diff * 5

            if score > best_score:
                best_score = score
                best_match = tx

        if not best_match or best_score < ADVANCE_SUGGEST_MIN:
            continue
        if best_score < ADVANCE_AUTO_MIN:
            _upsert_suggestion(db, best_match.id, "advance", adv.id,
                               float(adv.amount), adv.currency, best_score)
            continue

        if not apply_advance_bank_match(db, adv, best_match, method="auto", score=best_score):
            continue
        used_btx_ids.add(best_match.id)
        matched_count += 1
        logger.info(
            "Avans otomatik eşleşme: btx=%d → adv=%d (%s) | %s %s",
            best_match.id, adv.id, adv.agency_name,
            f"{abs(float(best_match.amount)):,.2f}", adv.currency,
        )

    return {"matched": matched_count, "total_pending": len(pending)}


# ─── Kredi ↔ Banka Eşleştirme ────────────────────────────


def _match_credits_to_bank(db: Session) -> dict:
    """Ödenmemiş kredi taksitlerini banka işlemleriyle otomatik eşleştir.

    Ekstre yüklendiğinde çağrılır. Banka işlemi ile kredi taksiti arasında
    tutar + tarih (±3 gün) + banka adı eşleşmesi yapılır.

    Eşleşen taksitler is_paid=True + bank_transaction_id set edilir.
    """
    from app.models.bank_account import BankAccount
    from app.models.bank_transaction import BankTransaction

    # Ödenmemiş ve banka eşleşmesi olmayan taksitler
    unpaid = (
        db.query(CreditPayment)
        .filter(
            CreditPayment.is_paid == False,
            CreditPayment.bank_transaction_id.is_(None),
        )
        .all()
    )
    if not unpaid:
        return {"matched": 0, "total_unpaid": 0}

    # Kredi ürün bilgilerini cache'le
    product_cache = {}
    for p in unpaid:
        if p.credit_product_id not in product_cache:
            prod = db.query(CreditProduct).filter(CreditProduct.id == p.credit_product_id).first()
            product_cache[p.credit_product_id] = prod

    # Zaten eşleşmiş banka işlem ID'leri
    already_matched = set(
        r[0] for r in
        db.query(CreditPayment.bank_transaction_id)
        .filter(CreditPayment.bank_transaction_id.isnot(None))
        .all()
    )

    # Banka gider işlemleri (hesap bilgisiyle)
    bank_expenses = (
        db.query(BankTransaction, BankAccount)
        .join(BankAccount, BankTransaction.account_id == BankAccount.id)
        .filter(BankTransaction.type == "expense")
        .all()
    )

    # Tutar bazlı index (tek işlem)
    btx_by_amount = defaultdict(list)
    for tx, acc in bank_expenses:
        if tx.id not in already_matched:
            btx_by_amount[round(abs(float(tx.amount)), 2)].append((tx, acc))

    # Aynı gün + aynı banka + aynı para birimi toplamları (faiz+vergi ayrı satır durumu)
    # (tarih, banka_adı, para_birimi) → (toplam_tutar, [tx_listesi])
    daily_bank_totals = defaultdict(lambda: {"total": 0.0, "txs": []})
    for tx, acc in bank_expenses:
        if tx.id not in already_matched:
            key = (tx.date, acc.bank_name, acc.currency)
            daily_bank_totals[key]["total"] += abs(float(tx.amount))
            daily_bank_totals[key]["txs"].append((tx, acc))

    matched_count = 0
    used_btx_ids = set()

    for payment in unpaid:
        product = product_cache.get(payment.credit_product_id)
        if not product:
            continue

        amt = round(float(payment.amount), 2)

        # 1. Önce tek işlem eşleşmesi dene
        candidates = btx_by_amount.get(amt, [])
        best_match = None
        best_score = 0

        for tx, acc in candidates:
            if tx.id in used_btx_ids:
                continue

            score = 0
            date_diff = abs((tx.date - payment.due_date).days)

            if date_diff > 3:
                continue
            if date_diff == 0:
                score += 50
            elif date_diff <= 1:
                score += 40
            else:
                score += 20

            if product.bank_name and acc.bank_name:
                if product.bank_name.lower() in acc.bank_name.lower() or acc.bank_name.lower() in product.bank_name.lower():
                    score += 30

            prod_currency = product.currency or "TRY"
            if prod_currency == acc.currency:
                score += 20

            if score > best_score:
                best_score = score
                best_match = tx

        if best_match and best_score >= CREDIT_AUTO_MIN:
            if apply_credit_bank_match(db, payment, product, best_match, method="auto", score=best_score):
                used_btx_ids.add(best_match.id)
                matched_count += 1
            continue
        if best_match and best_score >= CREDIT_SUGGEST_MIN:
            _upsert_suggestion(db, best_match.id, "credit", payment.id, amt,
                               product.currency or "TRY", best_score)
            # öneri sonrası grup denemesi de yapılır (aşağıda) — birebir aday zayıftı

        # 2. Tek işlem eşleşmedi → aynı gün toplamıyla dene (faiz+vergi ayrı satır)
        prod_currency = product.currency or "TRY"
        for date_offset in range(4):  # ±3 gün
            for sign in [0, 1, -1]:
                check_date = payment.due_date + timedelta(days=date_offset * sign) if sign else payment.due_date
                if date_offset == 0 and sign != 0:
                    continue

                key = (check_date, product.bank_name, prod_currency)
                group = daily_bank_totals.get(key)
                if not group:
                    continue

                # Kullanılmış işlemleri çıkar
                available_total = round(sum(
                    abs(float(tx.amount)) for tx, acc in group["txs"] if tx.id not in used_btx_ids
                ), 2)

                if abs(available_total - amt) < 0.02:  # Kuruş toleransı
                    # Eşleşti! Grubun TÜM banka satırlarına iz bırak (Faz 1 #10):
                    # ortak match_number + her satır için match() → event_matches izi.
                    # Eskiden yalnız first_tx bağ alıyordu, diğer satırlar işaretsiz
                    # kalıyordu (mutabakat denetiminde kanıtsız satır + yarım unmatch).
                    group_txs = [tx for tx, acc in group["txs"] if tx.id not in used_btx_ids]
                    first_tx = group_txs[0] if group_txs else None

                    if first_tx:
                        # Yarış koruması: taksit hâlâ açık mı?
                        locked_pay = (db.query(CreditPayment)
                                      .filter(CreditPayment.id == payment.id,
                                              CreditPayment.is_paid == False,  # noqa: E712
                                              CreditPayment.bank_transaction_id.is_(None))
                                      .with_for_update(skip_locked=True).first())
                        if locked_pay is None:
                            break
                        from sqlalchemy import text as _sa_text
                        group_mn = db.execute(_sa_text("SELECT nextval('match_number_seq')")).scalar()
                        locked_pay.is_paid = True
                        locked_pay.paid_date = check_date
                        locked_pay.bank_transaction_id = first_tx.id
                        matched_count += 1
                        if locked_pay.principal and product:
                            product.remaining_amount = max(0, float(product.remaining_amount) - float(locked_pay.principal))
                        for tx in group_txs:
                            used_btx_ids.add(tx.id)
                            if tx.match_number is None:
                                tx.match_number = group_mn
                        db.flush()
                        for tx in group_txs:
                            finance_event_svc.match(db, "bank", tx.id, "credit", locked_pay.id,
                                                    method="auto", score=90)
                        # Grubun tüm banka bacakları "Kredi/Leasing" etiketi alır
                        # (tekil eşleşme yoluyla aynı kural; manuel etiket korunur)
                        from app.utils.auto_tagger import (LEASING_CATEGORY,
                                                           _get_or_create_category)
                        _get_or_create_category(db, LEASING_CATEGORY)
                        for tx in group_txs:
                            _tag_scheduled_bank_leg(db, tx, LEASING_CATEGORY)
                        logger.info("Kredi N-1 grup eşleşmesi: %d banka satırı → taksit=%d (grup #%s)",
                                    len(group_txs), locked_pay.id, group_mn)
                    break
            else:
                continue
            break

    if matched_count > 0:
        db.flush()

    return {"matched": matched_count, "total_unpaid": len(unpaid)}


# ─── Öneri kuyruğu (Faz 1 #9 — event_matches method='suggestion') ───────────

def _upsert_suggestion(db: Session, bank_tx_id: int, target_type: str, target_id: int,
                       amount, currency: str, score: int) -> None:
    """Otomatik eşiğin altında kalan en iyi adayı öneri olarak kaydet (idempotent).

    Öneri bir EŞLEŞME DEĞİLDİR — finance_events'e dokunulmaz; kullanıcı panelden
    Onayla deyince ilgili apply_* fonksiyonu gerçek eşleşmeyi kurar.
    """
    from app.models.event_match import MATCH_METHOD_SUGGESTION, EventMatch

    ex = (db.query(EventMatch)
          .filter(EventMatch.method == MATCH_METHOD_SUGGESTION,
                  EventMatch.bank_source_type == "bank",
                  EventMatch.bank_source_id == bank_tx_id,
                  EventMatch.target_source_type == target_type,
                  EventMatch.target_source_id == target_id)
          .first())
    if ex is not None:
        ex.score = int(score)
        return
    db.add(EventMatch(
        bank_source_type="bank", bank_source_id=bank_tx_id,
        target_source_type=target_type, target_source_id=target_id,
        amount=round(float(amount or 0), 2), currency=(currency or "TRY")[:3],
        method=MATCH_METHOD_SUGGESTION, score=int(score),
    ))
    db.flush()


def cleanup_stale_suggestions(db: Session) -> int:
    """Hedefi artık açık olmayan önerileri sil (her orkestratör koşusu sonunda).

    Hedef eşleşmiş/kapanmışsa öneri bayattır — panelde gürültü üretmesin.
    """
    from app.models.event_match import MATCH_METHOD_SUGGESTION, EventMatch

    removed = 0
    for sug in db.query(EventMatch).filter(EventMatch.method == MATCH_METHOD_SUGGESTION).all():
        stale = False
        t, tid = sug.target_source_type, sug.target_source_id
        if t == "check":
            row = db.query(Check).filter(Check.id == tid).first()
            stale = row is None or row.status != "pending" or row.bank_transaction_id is not None
        elif t == "credit":
            row = db.query(CreditPayment).filter(CreditPayment.id == tid).first()
            stale = row is None or row.is_paid or row.bank_transaction_id is not None
        elif t == "advance":
            row = db.query(Advance).filter(Advance.id == tid).first()
            stale = row is None or row.status != "pending"
        elif t == "vendor_payment":
            row = db.query(VendorTransaction).filter(VendorTransaction.id == tid).first()
            stale = row is None or row.match_number is not None
        elif t in ("tax", "sgk", "withholding", "salary", "rent_expense"):
            from app.models.finance_event import FinanceEvent
            from app.models.scheduled import ScheduledEntry
            row = db.query(ScheduledEntry).filter(ScheduledEntry.id == tid).first()
            if row is None:
                stale = True
            elif row.is_paid:
                # Elle-ödendi ama bankaya bağlanmamış giriş için öneri CANLI kalır
                # (attach yolu — çift sayım ancak eşleşince biter, 2026-07-18)
                fe = (db.query(FinanceEvent)
                      .filter(FinanceEvent.source_type == t, FinanceEvent.source_id == tid)
                      .first())
                stale = fe is not None and fe.is_matched
        # Banka bacağı başka kayda bağlandıysa da bayat
        if not stale:
            b = db.query(BankTransaction).filter(BankTransaction.id == sug.bank_source_id).first()
            if b is None:
                stale = True
        if stale:
            db.delete(sug)
            removed += 1
    if removed:
        db.flush()
    return removed


# ─── Uygulayıcılar (matcher + öneri-Onayla ORTAK; hafif yarış koruması) ──────
# Her uygulayıcı hedefi FOR UPDATE SKIP LOCKED ile yeniden doğrular (Faz 1 yarış
# koruması: tetikler çoğaldı — ekstre + API + rematch + öneri onayı; koşullar
# commit anına kadar değişebilir). Koşul bozulmuşsa False/None döner, eşleşme kurulmaz.

def apply_check_bank_match(db: Session, check: Check, btx: BankTransaction,
                           method: str = "auto", score=None, actor_id=None) -> bool:
    """Çeki banka hareketiyle eşle (status='paid'). Yarış-korumalı."""
    locked = (db.query(Check)
              .filter(Check.id == check.id, Check.status == "pending",
                      Check.bank_transaction_id.is_(None))
              .with_for_update(skip_locked=True).first())
    if locked is None:
        return False
    locked.bank_transaction_id = btx.id
    locked.status = "paid"
    db.flush()
    finance_event_svc.match(db, "bank", btx.id, "check", locked.id,
                            method=method, score=score, created_by=actor_id)
    finance_event_svc.upsert_check(db, locked, btx)
    return True


def apply_credit_bank_match(db: Session, payment: CreditPayment, product: CreditProduct,
                            btx: BankTransaction, method: str = "auto",
                            score=None, actor_id=None) -> bool:
    """Kredi taksitini banka hareketiyle eşle (is_paid=True + anapara düşümü). Yarış-korumalı."""
    locked = (db.query(CreditPayment)
              .filter(CreditPayment.id == payment.id, CreditPayment.is_paid == False,  # noqa: E712
                      CreditPayment.bank_transaction_id.is_(None))
              .with_for_update(skip_locked=True).first())
    if locked is None:
        return False
    locked.is_paid = True
    locked.paid_date = btx.date
    locked.bank_transaction_id = btx.id
    if locked.principal and product:
        product.remaining_amount = max(0, float(product.remaining_amount) - float(locked.principal))
    db.flush()
    finance_event_svc.match(db, "bank", btx.id, "credit", locked.id,
                            method=method, score=score, created_by=actor_id)
    # Banka bacağı kanonik "Kredi/Leasing" etiketi alır (2026-07-18): kredi/leasing
    # taksit havaleleri kelime kurallarıyla Virman/Cari'ye düşebiliyordu (canlı:
    # "HAVALE ... NOLU ÖDEME PLANI" Halk Leasing taksitleri "Cari"de görünüyordu).
    # Manuel etiket _tag_scheduled_bank_leg içinde korunur.
    from app.utils.auto_tagger import LEASING_CATEGORY, _get_or_create_category
    _get_or_create_category(db, LEASING_CATEGORY)
    _tag_scheduled_bank_leg(db, btx, LEASING_CATEGORY)
    return True


def apply_advance_bank_match(db: Session, adv: Advance, btx: BankTransaction,
                             method: str = "auto", score=None, actor_id=None) -> bool:
    """Avansı banka gelir hareketiyle eşle (status='received'). Yarış-korumalı."""
    locked = (db.query(Advance)
              .filter(Advance.id == adv.id, Advance.status == "pending",
                      Advance.bank_transaction_id.is_(None))
              .with_for_update(skip_locked=True).first())
    if locked is None:
        return False
    locked.status = "received"
    locked.received_date = btx.date
    locked.received_amount = abs(float(btx.amount))
    locked.bank_transaction_id = btx.id
    db.flush()
    finance_event_svc.match(db, "bank", btx.id, "advance", locked.id,
                            method=method, score=score, created_by=actor_id)
    finance_event_svc.upsert_advance(db, locked)
    return True


def apply_vendor_bank_match(db: Session, vtx: VendorTransaction, btx: BankTransaction,
                            method: str = "auto", score=None, actor_id=None):
    """Cari işlemini banka hareketiyle eşle (match_number bağı) — matcher + manuel
    endpoint + öneri-Onayla ORTAK (D1-2). is_matched'a DOKUNMAZ (cari kuralı).

    Dönüş: match_number (başarı) | None (yarış/koşul bozuldu).
    """
    from sqlalchemy import text as sa_text

    from app.models.event_match import EventMatch

    locked_v = (db.query(VendorTransaction)
                .filter(VendorTransaction.id == vtx.id, VendorTransaction.match_number.is_(None))
                .with_for_update(skip_locked=True).first())
    locked_b = (db.query(BankTransaction)
                .filter(BankTransaction.id == btx.id, BankTransaction.match_number.is_(None))
                .with_for_update(skip_locked=True).first())
    if locked_v is None or locked_b is None:
        return None

    match_number = db.execute(sa_text("SELECT nextval('match_number_seq')")).scalar()
    # Leasing ödemesinin banka bacağı "Cari" değil "Kredi/Leasing" etiketi alır
    # (2026-07-18 kullanıcı isteği): leasing şirketi Sedna'da 320'li cari olduğundan
    # cari eşleşmesi bacağı "Cari" başlığına çekiyordu — eşleşme bağı yine kurulur.
    from app.utils.auto_tagger import (LEASING_CATEGORY, _get_or_create_category,
                                       is_leasing_description)
    if is_leasing_description(locked_b.description):
        cari_cat = _get_or_create_category(db, LEASING_CATEGORY)
    else:
        cari_cat = db.query(TransactionCategory).filter(TransactionCategory.name == "Cari").first()
    vendor = db.query(Vendor).filter(Vendor.id == locked_v.vendor_id).first()

    locked_b.vendor_id = locked_v.vendor_id
    locked_b.match_number = match_number
    locked_b.payment_method = locked_b.payment_method or "havale_eft"
    locked_b.tag_source = "auto" if method == "auto" else "manual"
    if cari_cat:
        locked_b.category_id = cari_cat.id
    if not locked_b.tag_note:
        locked_b.tag_note = vendor.hesap_adi if vendor else None

    locked_v.match_number = match_number
    locked_v.payment_method = locked_b.payment_method
    db.flush()

    finance_event_svc.sync_tag(
        db, locked_b.id,
        category_id=locked_b.category_id,
        category_name=cari_cat.name if cari_cat else None,
        category_color=cari_cat.color if cari_cat else None,
        tag_note=locked_b.tag_note, tag_source=locked_b.tag_source,
        payment_method=locked_b.payment_method, match_number=match_number,
        vendor_id=locked_b.vendor_id,
    )
    db.add(EventMatch(
        bank_source_type="bank", bank_source_id=locked_b.id,
        target_source_type="vendor_payment", target_source_id=locked_v.id,
        amount=float(locked_v.alacak or 0) or abs(float(locked_b.amount)), currency="TRY",
        match_number=match_number, method=method, score=score, created_by=actor_id,
    ))
    db.flush()
    return match_number


# ─── Cari ↔ Banka Eşleştirme (Faz 1 #8 — hacimce en büyük kalem) ─────────────

def _match_vendors_to_bank(db: Session) -> dict:
    """Açık cari ödeme tahminlerini (vendor_payment FE) banka gider hareketleriyle eşle.

    En temkinli matcher: cari kapatma FIFO'yu değiştirir. OTOMATİK eşleşme yalnız
    [tutar birebir ±0.01] + [isim/vendor sinyali ZORUNLU] + [vade ±7 gün] üçlüsüyle
    (skor ≥ VENDOR_AUTO_MIN); isimsiz veya geniş-pencere adaylar ÖNERİ olur.
    İsim sinyali: cari adı token'ı açıklamada geçiyor VEYA auto_tagger btx'e aynı
    vendor_id'yi atamış.
    """
    from app.models.finance_event import FinanceEvent

    open_fes = (
        db.query(FinanceEvent)
        .filter(FinanceEvent.source_type == "vendor_payment",
                FinanceEvent.is_matched == False,  # noqa: E712
                FinanceEvent.is_realized == False)  # noqa: E712
        .all()
    )
    if not open_fes:
        return {"matched": 0, "total_open": 0}

    vendor_names = {v.id: v.hesap_adi for v in db.query(Vendor).all()}

    candidates_q = (
        db.query(BankTransaction)
        .filter(BankTransaction.type == "expense",
                BankTransaction.match_number.is_(None))
        .all()
    )
    btx_by_amount = defaultdict(list)
    for tx in candidates_q:
        btx_by_amount[round(abs(float(tx.amount)), 2)].append(tx)

    matched_count = 0
    suggested = 0
    used_btx_ids = set()

    for fe in sorted(open_fes, key=lambda f: f.event_date):
        amt = round(float(fe.amount or 0), 2)
        if amt <= 0:
            continue
        cands = btx_by_amount.get(amt, [])
        if not cands:
            continue
        v_tokens = _norm_tokens(vendor_names.get(fe.vendor_id, "") or (fe.vendor_code or ""))

        best, best_score, best_diff = None, 0, None
        for tx in cands:
            if tx.id in used_btx_ids:
                continue
            date_diff = abs((tx.date - fe.event_date).days)
            if date_diff > VENDOR_SUGGEST_WINDOW_DAYS:
                continue
            name_hit = bool(v_tokens and v_tokens & _norm_tokens(tx.description or ""))
            vendor_hit = tx.vendor_id is not None and tx.vendor_id == fe.vendor_id
            score = 50  # tutar birebir
            if name_hit or vendor_hit:
                score += 30
            if date_diff == 0:
                score += 20
            elif date_diff <= 3:
                score += 15
            elif date_diff <= VENDOR_AUTO_WINDOW_DAYS:
                score += 10
            if score > best_score:
                best_score, best, best_diff = score, tx, date_diff

        if best is None or best_score < VENDOR_SUGGEST_MIN:
            continue
        vtx = db.query(VendorTransaction).filter(VendorTransaction.id == fe.source_id).first()
        if vtx is None or vtx.match_number is not None:
            continue
        # Otomatik yol yalnız DAR pencerede (±VENDOR_AUTO_WINDOW_DAYS): isimli aday
        # 8-14 gün bandında skor tam 80'e ulaşabiliyordu (50 tutar + 30 isim) → geniş
        # pencere adayı otomatik kapanıyordu. Docstring kuralı ("vade ±7 gün ZORUNLU")
        # burada açıkça zorlanır; geniş-pencere adaylar öneriye düşer.
        if best_score >= VENDOR_AUTO_MIN and best_diff is not None and best_diff <= VENDOR_AUTO_WINDOW_DAYS:
            mn = apply_vendor_bank_match(db, vtx, best, method="auto", score=best_score)
            if mn is not None:
                used_btx_ids.add(best.id)
                matched_count += 1
                logger.info("Cari otomatik eşleşme: btx=%d → vtx=%d (%s) #%s skor=%d",
                            best.id, vtx.id, vendor_names.get(fe.vendor_id, ""), mn, best_score)
        else:
            _upsert_suggestion(db, best.id, "vendor_payment", vtx.id, amt, "TRY", best_score)
            suggested += 1

    if matched_count:
        # Eşleşme FIFO kalanını değiştirir → vendor_payment FE'leri yeniden yazılır
        from app.utils.sync_vendor_fifo import sync_vendor_finance_events
        sync_vendor_finance_events(db)

    return {"matched": matched_count, "suggested": suggested, "total_open": len(open_fes)}


# ─── Ortak orkestratör (Revize Faz 0 R1, 2026-07-11) ────────────────────────
# Ekstre yüklemesi + banka API senkronları + POST /cash-flow/rematch AYNI yolu
# kullanır: önce otomatik etiketleme (kategori + ödeme yöntemi + cari), sonra
# 4 matcher — her adım SAVEPOINT izolasyonlu (biri patlarsa diğerleri sürer).

def _match_contract_installments_to_bank(db: Session) -> dict:
    """Bekleyen kontrat taksitlerini banka gelir işlemleriyle otomatik eşleştir (Faz 2).

    Avans eşleştiricisinden SONRA koşar — advances BİRİNCİL temsildir (çift-sayım kural
    seti [1]); avansa bağlanmış banka işlemleri burada aday olamaz. guarantee_check
    planları (otelin verdiği teminat) kapsam dışı. Kriterler avans eşleştiricisiyle aynı
    ruhta: tutar birebir + para birimi; grup adı/üye tokenı açıklamada geçiyorsa geniş
    pencere (±60g), geçmiyorsa vadeye yakınlık (±10g). Eşleşen taksit paid + banka bağı.
    """
    from app.models.agency_group import AgencyGroup
    from app.models.contract import (
        INSTALLMENT_PAID, INSTALLMENT_PENDING, PLAN_TYPE_GUARANTEE_CHECK,
        AgencyContract, ContractInstallment, ContractPaymentPlan,
    )

    rows = (
        db.query(ContractInstallment, AgencyContract)
        .join(ContractPaymentPlan, ContractInstallment.plan_id == ContractPaymentPlan.id)
        .join(AgencyContract, ContractPaymentPlan.contract_id == AgencyContract.id)
        .filter(
            ContractPaymentPlan.plan_type != PLAN_TYPE_GUARANTEE_CHECK,
            ContractInstallment.status == INSTALLMENT_PENDING,
            ContractInstallment.bank_transaction_id.is_(None),
            ContractInstallment.amount.isnot(None),
            ContractInstallment.due_date.isnot(None),
        )
        .order_by(ContractInstallment.due_date.asc())
        .all()
    )
    if not rows:
        return {"matched": 0, "total_pending": 0}

    groups = {g.id: g for g in db.query(AgencyGroup).all()}

    # Avans/çek/taksit ile zaten eşleşmiş banka işlemleri aday olamaz
    used = set(r[0] for r in db.query(Advance.bank_transaction_id)
               .filter(Advance.bank_transaction_id.isnot(None)).all())
    used |= set(r[0] for r in db.query(Check.bank_transaction_id)
                .filter(Check.bank_transaction_id.isnot(None)).all())
    used |= set(r[0] for r in db.query(ContractInstallment.bank_transaction_id)
                .filter(ContractInstallment.bank_transaction_id.isnot(None)).all())

    bank_incomes = (
        db.query(BankTransaction, BankAccount)
        .join(BankAccount, BankTransaction.account_id == BankAccount.id)
        .filter(BankTransaction.type == "income")
        .all()
    )
    btx_index = defaultdict(list)
    for tx, acc in bank_incomes:
        if tx.id in used or "virman" in (tx.description or "").lower():
            continue
        btx_index[(acc.currency, round(abs(float(tx.amount)), 2))].append(tx)

    matched = 0
    for inst, contract in rows:
        cands = btx_index.get((inst.currency, round(float(inst.amount), 2)), [])
        if not cands:
            continue
        g = groups.get(contract.agency_group_id)
        name_tokens = set()
        if g:
            name_tokens |= _norm_tokens(g.name)
            for m in (g.members or []):
                name_tokens |= _norm_tokens(m)
        best = None
        for tx in cands:
            if tx.id in used:
                continue
            desc_tokens = _norm_tokens(tx.description or "")
            named = bool(name_tokens & desc_tokens)
            delta = abs((tx.date - inst.due_date).days)
            window = ADVANCE_NAMED_WINDOW_DAYS if named else ADVANCE_BLIND_WINDOW_DAYS
            if delta > window:
                continue
            score = (0 if named else 1, delta)
            if best is None or score < best[0]:
                best = (score, tx)
        if best:
            tx = best[1]
            inst.status = INSTALLMENT_PAID
            inst.paid_date = tx.date
            inst.bank_transaction_id = tx.id
            inst.notes = ((inst.notes or "") +
                          f" | Banka eşleşmesi: btx#{tx.id} {tx.date}")[:300]
            used.add(tx.id)
            matched += 1

    if matched:
        from app.services.contract_projection_service import invalidate_cache
        invalidate_cache()
    return {"matched": matched, "total_pending": len(rows)}


# ─── Planlı personel gideri ↔ banka (maaş / SGK / stopaj) — 2026-07-18 ───────
# Gerçek maaş toplu transferleri ("Para Gönder Internet - Mobil ...") kelime taşımaz
# ve etiketlenmediğinden Faz 1 #11 köprüsü hiç tetiklenmiyordu → planlı bacak açık
# kalıp banka bacağıyla ÇİFT sayılıyordu (canlı: Mayıs–Temmuz maaşları). Bu matcher
# planlı personel girişlerini banka kanıtına bağlar; elle "ödendi" işaretlenmiş ama
# eşleşmemiş girişleri de kapsar (attach yolu — geriye dönük çift-sayım temizliği).
SCHEDULED_MATCH_TYPES = ("salary", "sgk", "withholding")
_SCHEDULED_KEYWORDS = {
    # _normalize sonrası ascii-küçük harf metinde aranır. Genel "vergi" kelimesi
    # BİLEREK yok — KDV/kurumlar ödemeleri stopaj girişine yanlış bağlanmasın
    # (tax source_type'ı bu matcher'ın kapsamı dışında, etiketleme köprüsünde kalır).
    "salary": re.compile(r"maas|personel|ucret|bordro"),
    "sgk": re.compile(r"sgk|mosip|sosyal guv"),
    "withholding": re.compile(r"muhtasar|stopaj"),
}
# Eşleşen banka bacağına atanan kategori → T-Hesap'ta doğru başlık (salary→Personel;
# sgk/stopaj→Vergi/SGK — _SCHEDULED_CATEGORY_MAP köprüsüyle aynı yön eşlemesi)
_SCHEDULED_CANONICAL_CATEGORY = {"salary": "Personel", "sgk": "Vergi/SGK", "withholding": "Vergi/SGK"}
_TRANSFER_CATEGORY_NAMES = ("Virman", "Döviz Satım", "İade", "Döviz Satışı", "Pos Bloke Çözme")
SCHEDULED_LOOKBACK_DAYS = 90       # geriye dönük temizlik penceresi (ref tarihi)
SCHEDULED_CAND_WINDOW_DAYS = 15    # aday banka hareketi ± penceresi
SCHEDULED_MIN_BLIND_AMOUNT = 1_000_000  # kelimesiz (etiketsiz toplu transfer) yolu alt sınırı
SCHEDULED_KW_SUGGEST_SCORE = 60
SCHEDULED_BLIND_SUGGEST_SCORE = 50


def _tag_scheduled_bank_leg(db: Session, tx: BankTransaction, category_name: str) -> None:
    """Eşleşen banka bacağını türün kanonik kategorisine etiketle (best-effort).

    Manuel etiket kullanıcı kararıdır → dokunulmaz. Kategori DB'de yoksa (test
    ortamı) sessiz geçilir — eşleşme kurulmuştur, etiket kozmetiktir.
    """
    if tx.tag_source == "manual" and tx.category_id:
        return
    cat = db.query(TransactionCategory).filter(TransactionCategory.name == category_name).first()
    if cat is None or tx.category_id == cat.id:
        return
    tx.category_id = cat.id
    tx.tag_source = "auto"
    db.flush()
    from app.utils.auto_tagger import _sync_finance_events
    _sync_finance_events(db, [tx])


def _match_scheduled_to_bank(db: Session) -> dict:
    """Planlı personel girişlerini (maaş/SGK/stopaj) banka giderleriyle eşleştir.

    Kural tablosu (r = |btx| / giriş tutarı, d = |btx tarihi − referans| gün;
    referans = ödenmişse paid_date, değilse entry_date):
    - Anahtar kelime VAR (tip bazlı regex): d ≤ 5 ve 0.75 ≤ r ≤ 1.30 ve TEK aday
      → OTOMATİK; değilse d ≤ 15 ve 0.5 ≤ r ≤ 1.6 → ÖNERİ (skor 60).
    - Anahtar kelime YOK (tipik maaş toplu transferi — etiketsiz, ≥ 1M): yalnız
      ELLE-ÖDENDİ girişlerde d ≤ 2 ve 0.85 ≤ r ≤ 1.15 ve TEK aday → OTOMATİK;
      diğer durumlar (açık giriş dahil) 0.8 ≤ r ≤ 1.25 → ÖNERİ (skor 50).
      Açık girişte kelimesiz otomatik YOK — aynı gün benzer tutarlı büyük cari
      EFT'si riski (öneri panelinden tek tıkla onaylanır).
    Eşleşen banka bacağı kanonik kategorisini alır → T-Hesap başlığı doğru olur.
    """
    from datetime import date as date_cls

    from app.models.event_match import MATCH_METHOD_SUGGESTION, EventMatch
    from app.models.finance_event import FinanceEvent
    from app.models.scheduled import ScheduledEntry
    from app.services.scheduled_service import link_entry_to_bank
    from app.utils.auto_tagger import _normalize

    today = date_cls.today()
    window_start = today - timedelta(days=SCHEDULED_LOOKBACK_DAYS)

    entries = (db.query(ScheduledEntry)
               .filter(ScheduledEntry.source_type.in_(SCHEDULED_MATCH_TYPES))
               .all())
    fes = {(f.source_type, f.source_id): f
           for f in db.query(FinanceEvent)
           .filter(FinanceEvent.source_type.in_(SCHEDULED_MATCH_TYPES)).all()}

    targets = []  # (entry, ref_tarih)
    for e in entries:
        ref = (e.paid_date or e.entry_date) if e.is_paid else e.entry_date
        if ref is None or ref < window_start or ref > today + timedelta(days=10):
            continue
        fe = fes.get((e.source_type, e.id))
        if e.is_paid and fe is not None and fe.is_matched:
            continue  # zaten banka kanıtına bağlı
        targets.append((e, ref))
    if not targets:
        return {"matched": 0, "suggested": 0, "total_open": 0}

    # Zaten bir planlı girişe bağlanmış banka hareketleri aday olamaz
    used = set(r[0] for r in db.query(EventMatch.bank_source_id)
               .filter(EventMatch.target_source_type.in_(SCHEDULED_MATCH_TYPES),
                       EventMatch.method != MATCH_METHOD_SUGGESTION).all())

    txs = (db.query(BankTransaction)
           .filter(BankTransaction.type == "expense",
                   BankTransaction.date >= window_start - timedelta(days=SCHEDULED_CAND_WINDOW_DAYS))
           .all())
    cat_names = {c.id: c.name for c in db.query(TransactionCategory).all()}

    matched, suggested = 0, 0
    for entry, ref in sorted(targets, key=lambda t: t[1]):
        amt = float(entry.amount or 0)
        if amt <= 0:
            continue
        kwre = _SCHEDULED_KEYWORDS[entry.source_type]
        canonical = _SCHEDULED_CANONICAL_CATEGORY[entry.source_type]
        auto_cands, best = [], None
        for tx in txs:
            if tx.id in used:
                continue
            d = abs((tx.date - ref).days)
            if d > SCHEDULED_CAND_WINDOW_DAYS:
                continue
            cat_name = cat_names.get(tx.category_id)
            if cat_name in _TRANSFER_CATEGORY_NAMES:
                continue  # iç transfer — gerçek gider değil
            if cat_name is not None and cat_name != canonical and tx.tag_source == "manual":
                continue  # kullanıcının farklı manuel etiketi — dokunma
            r = abs(float(tx.amount)) / amt
            kw = bool(kwre.search(_normalize(tx.description or "")))
            if kw:
                if not (0.5 <= r <= 1.6):
                    continue
            else:
                if cat_name is not None:
                    continue  # kelimesiz yol yalnız etiketsiz toplu transfer
                if not (0.8 <= r <= 1.25) or abs(float(tx.amount)) < SCHEDULED_MIN_BLIND_AMOUNT:
                    continue
            if kw and d <= 5 and 0.75 <= r <= 1.30:
                auto_cands.append(tx)
            elif (not kw) and entry.is_paid and d <= 2 and 0.85 <= r <= 1.15:
                auto_cands.append(tx)
            rank = (0 if kw else 1, d, abs(r - 1.0))
            if best is None or rank < best[0]:
                best = (rank, tx, kw)

        if len(auto_cands) == 1 and link_entry_to_bank(db, entry, auto_cands[0]):
            used.add(auto_cands[0].id)
            matched += 1
            _tag_scheduled_bank_leg(db, auto_cands[0], canonical)
            logger.info("Planlı %s girişi banka kanıtına bağlandı: entry=%d ↔ btx=%d",
                        entry.source_type, entry.id, auto_cands[0].id)
            continue
        if best is not None:
            _, tx, kw = best
            _upsert_suggestion(db, tx.id, entry.source_type, entry.id,
                               abs(float(tx.amount)), "TRY",
                               SCHEDULED_KW_SUGGEST_SCORE if kw else SCHEDULED_BLIND_SUGGEST_SCORE)
            suggested += 1

    return {"matched": matched, "suggested": suggested, "total_open": len(targets)}


def run_all_matchers(db) -> dict:
    """4 otomatik eşleştiriciyi SAVEPOINT izolasyonuyla koştur.

    Dönen anahtarlar: checks_matched / credits_matched / cc_matched / advances_matched
    (yalnız eşleşme olan anahtarlar döner — bank_statement_import ile geriye uyumlu).
    """
    results = {}
    for match_fn, label, key in [
        (_match_checks_to_bank, "Çek-banka", "checks_matched"),
        (_match_credits_to_bank, "Kredi-banka", "credits_matched"),
        (_match_cc_to_bank, "Kredi kartı-banka", "cc_matched"),
        (_match_advances_to_bank, "Avans-banka", "advances_matched"),
        (_match_contract_installments_to_bank, "Kontrat taksiti-banka", "contract_installments_matched"),
        (_match_vendors_to_bank, "Cari-banka", "vendor_payments_matched"),
        (_match_scheduled_to_bank, "Planlı personel-banka", "scheduled_matched"),
    ]:
        try:
            nested = db.begin_nested()
            r = match_fn(db)
            # ÖNERİLER de kalıcı olmalı (2026-07-18 düzeltme): eskiden yalnız
            # r["matched"]>0 commit ediliyordu → sadece öneri üreten koşuların
            # _upsert_suggestion kayıtları SAVEPOINT rollback'iyle sessizce kayboluyordu.
            if r["matched"] > 0 or r.get("suggested", 0) > 0:
                nested.commit()
                db.commit()
                if r["matched"] > 0:
                    results[key] = r["matched"]
            else:
                nested.rollback()
        except Exception as e:  # noqa: BLE001 — adım izolasyonu
            db.rollback()
            logger.error("%s otomatik eşleştirme hatası: %s", label, e, exc_info=True)

    # Bayat önerileri süpür (hedefi kapananlar panelde gürültü üretmesin)
    try:
        nested = db.begin_nested()
        removed = cleanup_stale_suggestions(db)
        nested.commit()
        db.commit()
        if removed:
            results["stale_suggestions_removed"] = removed
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error("Öneri temizliği hatası: %s", e)
    return results


def run_post_ingest_processing(db) -> dict:
    """Banka verisi girişi sonrası ortak işlem: otomatik etiketleme + 4 matcher.

    Auto-tag matcher'lardan ÖNCE koşar (atanan vendor_id/kategori eşleştirici
    isabetini artırır ve nakit akımda anında görünür — sync_tag auto_tagger içinde).
    """
    results = {}
    try:
        nested = db.begin_nested()
        from app.utils.auto_tagger import (
            auto_detect_payment_methods,
            auto_match_vendors,
            auto_tag_transactions,
        )
        tagged, _total = auto_tag_transactions(db)
        pm_counts = auto_detect_payment_methods(db)
        vm = auto_match_vendors(db)
        nested.commit()
        db.commit()
        results["auto_tagged"] = tagged
        results["payment_methods_detected"] = sum(pm_counts.values())
        results["vendors_auto_matched"] = vm.get("matched", 0)
    except Exception as e:  # noqa: BLE001 — etiketleme hatası eşleştirmeyi durdurmasın
        db.rollback()
        logger.error("Otomatik etiketleme hatası: %s", e, exc_info=True)
    results.update(run_all_matchers(db))
    return results
