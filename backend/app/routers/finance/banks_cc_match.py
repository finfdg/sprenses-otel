"""Banka ekstresi yüklendiğinde kredi kartı borç ödemelerini otomatik eşleştir.

Eşleştirme mantığı:
1. Ödenmemiş CC ekstrelerini al
2. Banka gider işlemlerinde "kart" veya son 4 hane içeren açıklamaları tara
3. Tutar tam eşleşirse → eşleştir (kısmi ödeme de desteklenir)
"""
import json
import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models.bank_transaction import BankTransaction
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_product import CreditProduct
from app.models.transaction_category import TransactionCategory
from app.utils.finance_event_service import finance_event_svc

logger = logging.getLogger(__name__)


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
    """
    if not description:
        return None

    # "1028" gibi — son 4 rakam bloğu
    # Kart ödemesi açıklamalarında son 4 hane genellikle en sondadır
    patterns = [
        r'\*{3,4}\s*(\d{4})\s*$',          # **** 1028 veya ***1028
        r'\*(\d{4})\s*$',                    # *1028
        r'\.{3}(\d{4})\s*$',                # ...1028
        r'(\d{4})\s*\*{4}\s*\*{4}\s*(\d{4})',  # 5400 **** **** 1028
    ]
    for pattern in patterns:
        m = re.search(pattern, description)
        if m:
            return m.group(m.lastindex)

    return None


def _is_cc_payment_desc(description: str) -> bool:
    """Açıklamanın kredi kartı ödemesi olup olmadığını kontrol et."""
    if not description:
        return False
    desc_lower = description.lower()
    keywords = ["kart öd", "kart od", "k.kartı", "k.karti", "kk borc", "kk borç",
                "kredi kartı", "kredi karti", "credit card", "visa kart", "mastercard"]
    return any(kw in desc_lower for kw in keywords)


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
        if not _is_cc_payment_desc(btx.description):
            continue

        btx_last4 = _extract_last4_from_desc(btx.description)
        if not btx_last4 or btx_last4 not in last4_to_stmts:
            continue

        payment_amount = abs(float(btx.amount))

        # En uygun ekstre bul: son_odeme_tarihi'ne en yakın + tutar eşleşen
        best_stmt = None
        best_prod = None
        best_remaining = None

        for stmt, prod in last4_to_stmts[btx_last4]:
            remaining = float(stmt.toplam_borc) - float(stmt.paid_amount or 0)
            if remaining <= 0.01:
                continue

            # Tutar kontrolü: tam eşleşme veya kısmi (banka tutarı <= kalan borç)
            if abs(payment_amount - remaining) < 0.01:
                # Tam eşleşme — en iyi
                best_stmt = stmt
                best_prod = prod
                best_remaining = remaining
                break
            elif abs(payment_amount - float(stmt.toplam_borc)) < 0.01:
                # Toplam borç ile eşleşme
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

        # CC ekstre tamamen ödendiyse, cc_payment finance_event'i gizle
        if best_stmt.is_paid:
            from app.models.finance_event import FinanceEvent
            cc_fe = db.query(FinanceEvent).filter(
                FinanceEvent.source_type == "cc_payment",
                FinanceEvent.source_id == best_stmt.id,
            ).first()
            if cc_fe:
                cc_fe.is_matched = True

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
