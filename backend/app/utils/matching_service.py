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

from sqlalchemy.orm import Session

from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.check import Check
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_product import CreditPayment, CreditProduct
from app.models.transaction_category import TransactionCategory
from app.utils.finance_event_service import finance_event_svc

logger = logging.getLogger(__name__)


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

    # Zaten etiketlenmiş banka işlemlerini atla
    kk_cat = db.query(TransactionCategory).filter(TransactionCategory.name == "Kredi Kartı Borç Ödeme").first()

    # Etiketlenmemiş banka gider işlemleri
    bank_expenses = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.type == "expense",
            BankTransaction.category_id.is_(None),
        )
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

        if best_match and best_score >= 20:
            check.bank_transaction_id = best_match.id
            check.status = "paid"
            used_btx_ids.add(best_match.id)
            matched_count += 1
            db.flush()
            # finance_events: çek is_matched=True, banka is_realized=True
            finance_event_svc.match(db, "bank", best_match.id, "check", check.id)
            # FE'nin event_status/bank_name'ini de tazele — match() yalnız is_matched
            # set eder; durum 'pending' kalırsa ödenen çek nakit akımda "Ödendi"
            # rozetiyle GÖRÜNMEZ (2026-07-04 denetim bulgusu: prod'da 41 çek)
            finance_event_svc.upsert_check(db, check, best_match)

    return {
        "matched": matched_count,
        "total_pending": len(pending_checks),
    }


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

        if best_match and best_score >= 40:
            payment.is_paid = True
            payment.paid_date = best_match.date
            payment.bank_transaction_id = best_match.id
            used_btx_ids.add(best_match.id)
            matched_count += 1
            # Anapara varsa kalan borcu düşür
            if payment.principal and product:
                product.remaining_amount = max(0, float(product.remaining_amount) - float(payment.principal))
            db.flush()
            finance_event_svc.match(db, "bank", best_match.id, "credit", payment.id)
            continue

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
                    # Eşleşti! İlk işlemi ana eşleşme olarak kullan
                    first_tx = None
                    for tx, acc in group["txs"]:
                        if tx.id not in used_btx_ids:
                            if first_tx is None:
                                first_tx = tx
                            used_btx_ids.add(tx.id)

                    if first_tx:
                        payment.is_paid = True
                        payment.paid_date = check_date
                        payment.bank_transaction_id = first_tx.id
                        matched_count += 1
                        # Anapara varsa kalan borcu düşür
                        if payment.principal and product:
                            product.remaining_amount = max(0, float(product.remaining_amount) - float(payment.principal))
                        db.flush()
                        finance_event_svc.match(db, "bank", first_tx.id, "credit", payment.id)
                    break
            else:
                continue
            break

    if matched_count > 0:
        db.flush()

    return {"matched": matched_count, "total_unpaid": len(unpaid)}
