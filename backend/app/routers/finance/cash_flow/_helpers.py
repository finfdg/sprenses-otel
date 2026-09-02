"""Nakit akım modülü paylaşılan yanıt oluşturucular ve yardımcı fonksiyonlar."""

from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.check import Check
from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_product import CREDIT_TYPE_LABELS, CreditPayment, CreditProduct
from app.models.exchange_rate import ExchangeRate
from app.models.finance_event import DIRECTION_INCOME, FinanceEvent
from app.models.transaction_category import TransactionCategory
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.schemas.cash_flow import CashFlowResponse
from app.services.fx_rates import CROSS_EUR_CURRENCIES  # noqa: F401 — re-export (tek kaynak utils/fx_rates)


def _build_bank_response(
    tx: BankTransaction,
    acc: BankAccount,
    cat: Optional[TransactionCategory],
    vendor: Optional[Vendor] = None,
) -> dict:
    """Banka işleminden yanıt oluştur."""
    return CashFlowResponse(
        id=tx.id,
        date=tx.date,
        description=tx.description,
        amount=abs(float(tx.amount)),
        type=tx.type,
        source="bank",
        balance=float(tx.balance) if tx.balance is not None else None,
        receipt_no=tx.receipt_no,
        bank_name=acc.bank_name,
        currency=acc.currency,
        iban=acc.iban,
        account_id=tx.account_id,
        category_id=tx.category_id,
        category_name=cat.name if cat else None,
        category_color=cat.color if cat else None,
        tag_note=tx.tag_note,
        tag_source=tx.tag_source,
        vendor_id=tx.vendor_id,
        vendor_name=vendor.hesap_adi if vendor else None,
        payment_method=tx.payment_method,
        match_number=tx.match_number,
    ).model_dump()


def _build_check_response(c: Check, bank_tx: Optional[BankTransaction] = None) -> dict:
    """Çek kaydından yanıt oluştur."""
    display_date = bank_tx.date if bank_tx else c.due_date

    return CashFlowResponse(
        id=c.id,
        date=display_date,
        description=c.vendor_name,
        amount=float(c.amount_currency),
        type="expense",
        source="check",
        currency="TRY" if c.currency == "TL" else c.currency,
        payment_method="cek",
        check_no=c.check_no,
        check_status=c.status,
        vendor_code=c.vendor_code,
        vendor_name=c.vendor_name,
        tag_note=c.description,
        bank_name=bank_tx.account.bank_name if bank_tx and bank_tx.account else None,
    ).model_dump()


def _build_credit_response(payment: CreditPayment, product: CreditProduct) -> dict:
    """Kredi taksitinden yanıt oluştur."""
    type_label = CREDIT_TYPE_LABELS.get(product.type, product.type)
    desc = f"[{type_label}] {product.name}"
    if payment.installment_no:
        desc += f" — Taksit #{payment.installment_no}"

    return CashFlowResponse(
        id=payment.id,
        date=payment.due_date,
        description=desc,
        amount=float(payment.amount),
        type="expense",
        source="credit",
        currency=product.currency or "TRY",
        bank_name=product.bank_name,
        payment_method=product.type,
        tag_note=f"Anapara: {float(payment.principal):,.2f}" if payment.principal else None,
        check_status="paid" if payment.is_paid else "pending",
    ).model_dump()


def _build_cc_payment_response(stmt: CreditCardStatement, product: CreditProduct) -> dict:
    """Kredi kartı ekstre ödemesinden yanıt oluştur."""
    kalan = float(stmt.toplam_borc) - float(stmt.paid_amount or 0)
    desc = f"[Kredi Kartı] {product.name} — {stmt.kesim_tarihi.strftime('%d.%m.%Y')} Ekstresi"
    if kalan < float(stmt.toplam_borc):
        desc += f" (Kalan: ₺{kalan:,.2f})"

    return CashFlowResponse(
        id=stmt.id,
        date=stmt.son_odeme_tarihi,
        description=desc,
        amount=float(stmt.toplam_borc),
        type="expense",
        source="cc_payment",
        currency="TRY",
        bank_name=product.bank_name,
        payment_method="kredi_karti",
        check_status="paid" if stmt.is_paid else "pending",
        tag_note=f"Asgari: ₺{float(stmt.asgari_odeme):,.2f}",
    ).model_dump()


def _build_advance_response(adv) -> dict:
    """Avans kaydından nakit akım yanıtı oluştur."""
    return CashFlowResponse(
        id=adv.id,
        date=adv.received_date or adv.advance_date,
        description=f"[Avans] {adv.agency_name}",
        amount=float(adv.received_amount or adv.amount),
        type="income",
        source="advance",
        currency=adv.currency,
        check_status=adv.status,
        tag_note=adv.notes,
    ).model_dump()


def _build_vendor_payment_response(
    vtx: VendorTransaction, vendor: Vendor, amount: float
) -> dict:
    """Cari ödeme planından nakit akım yanıtı oluştur."""
    return CashFlowResponse(
        id=vtx.id,
        date=vtx.payment_due_date,
        description=vendor.hesap_adi,
        amount=amount,
        type="expense",
        source="vendor_payment",
        currency="TRY",
        payment_method="cari",
        vendor_id=vtx.vendor_id,
        vendor_name=vendor.hesap_adi,
        vendor_code=vendor.hesap_kodu,
        tag_note=vtx.evrak_no,
    ).model_dump()


def _get_vendor_net_debts(db: Session) -> dict:
    """Her carinin net borcunu hesapla. Sadece borçlu olanları döndür."""
    rows = (
        db.query(
            VendorTransaction.vendor_id,
            func.coalesce(func.sum(VendorTransaction.alacak), 0).label("total_alacak"),
            func.coalesce(func.sum(VendorTransaction.borc), 0).label("total_borc"),
        )
        .group_by(VendorTransaction.vendor_id)
        .all()
    )
    debts = {}
    for row in rows:
        net = float(row.total_alacak) - float(row.total_borc)
        if net > 0.01:
            debts[row.vendor_id] = net
    return debts


def _fe_to_response(fe: FinanceEvent) -> dict:
    """FinanceEvent → CashFlowResponse dict."""
    return CashFlowResponse(
        id=fe.source_id,
        date=fe.event_date,
        description=fe.description or "",
        amount=float(fe.amount),
        type="income" if fe.direction == DIRECTION_INCOME else "expense",
        source=fe.source_type,
        balance=float(fe.balance) if fe.balance is not None else None,
        receipt_no=fe.receipt_no,
        bank_name=fe.bank_name,
        currency=fe.currency,
        iban=fe.iban,
        account_id=fe.account_id,
        category_id=fe.category_id,
        category_name=fe.category_name,
        category_color=fe.category_color,
        tag_note=fe.tag_note,
        tag_source=fe.tag_source,
        vendor_id=fe.vendor_id,
        vendor_name=fe.vendor.hesap_adi if fe.vendor_id and fe.vendor else None,
        payment_method=fe.payment_method,
        match_number=fe.match_number,
        check_no=fe.check_no,
        check_status=fe.event_status,
        vendor_code=fe.vendor_code,
        amount_try=float(fe.amount_try) if fe.amount_try else (float(fe.amount) if fe.currency == "TRY" else None),
        is_matched=bool(fe.is_matched),
    ).model_dump()


def _get_eur_rate(db: Session, target_date) -> float:
    """Belirli tarih için EUR/TRY alış kuru."""
    rate = (
        db.query(ExchangeRate.forex_buying)
        .filter(ExchangeRate.currency_code == "EUR", ExchangeRate.date <= target_date)
        .order_by(ExchangeRate.date.desc())
        .first()
    )
    return float(rate[0]) if rate and rate[0] else 1.0


# EUR'a çapraz kurla çevrilen dövizler (amount × {code} alış / EUR alış) — TCMB üçü
# için de günlük kur çeker; amount_try'a BAKILMAZ. USD 2026-07-19 kararı; GBP
# 2026-08-14'te ilk GBP hesabı (Halkbank 2A000897) canlıya girince aynı yola alındı.
# t_account._event_eur + runway._event_eur/_compute_start_eur + eur_balances.to_eur
# dördü de bu kümeyi kullanır (tek sayı kuralı).
# Tanım `utils/fx_rates.py`'de (2026-09-01): HTTP'siz servisler (agency_finance) router paketinden
# import edemez (katman yönü kuralı) → tek kaynak utils'e taşındı, buradan yeniden dışa verilir;
# t_account / runway / eur_balances / chart `from ._helpers import CROSS_EUR_CURRENCIES` değişmez.


def _get_fx_buying(db: Session, code: str, target_date) -> float:
    """Belirli tarih için {code}/TRY alış kuru (<= en yakın gün); yoksa 1.0.

    Çağıran 1.0'ı "kur yok" sinyali olarak ele almalı (1:1 varsayımı yapılmaz).
    """
    rate = (
        db.query(ExchangeRate.forex_buying)
        .filter(ExchangeRate.currency_code == code, ExchangeRate.date <= target_date)
        .order_by(ExchangeRate.date.desc())
        .first()
    )
    return float(rate[0]) if rate and rate[0] else 1.0


def _get_usd_rate(db: Session, target_date) -> float:
    """Belirli tarih için USD/TRY alış kuru."""
    return _get_fx_buying(db, "USD", target_date)


def _latest_buying(db: Session, currency_code: str) -> Optional[float]:
    """EN SON yayınlanan (birim başına) TCMB alış kuru; hiç yoksa None.

    `_get_fx_buying`'den farkı TARİH FİLTRESİ YOKLUĞUDUR: "bugünkü bakiye"
    değerlemesi ileri tarihli bir gün için de en son yayınlanan kuru kullanır
    (hafta sonu/tatilde dünkü kur). 1.0 fallback YOK — çağıran None'ı
    "kur bilinmiyor" olarak ele alır (1 TL = 1 EUR saçmalığı engellenir).
    """
    row = (
        db.query(ExchangeRate.forex_buying, ExchangeRate.unit)
        .filter(
            ExchangeRate.currency_code == currency_code,
            ExchangeRate.forex_buying.isnot(None),
        )
        .order_by(ExchangeRate.date.desc())
        .first()
    )
    if row and row.forex_buying:
        return float(row.forex_buying) / float(row.unit or 1)
    return None


def bank_snapshot(db: Session) -> dict:
    """ANLIK banka nakdi — hesap bazında son bakiye + toplam EUR karşılığı.

    `runway._compute_start_eur`'ün TEK KAYNAĞIdır (o fonksiyon buraya delege eder,
    2026-08-19): "Bankadaki Nakit" başlığı, runway `start_eur` ve Nakit Akım
    grafiğinin hesap şeridi aynı sayıyı gösterir. Daha önce yalnız TOPLAM
    hesaplanıyordu; grafik hesap KIRILIMI istediğinden hesaplama buraya taşındı
    ve satır satır döner (matematik birebir aynı — `total_eur` değişmedi).

    "Son bakiye" = (date, id) sırasına göre son satır — max(id) DEĞİL: sonradan
    eklenen (backfill/devir) ESKİ tarihli satır tabloda en yüksek id'yi alır ve
    bayat bakiyeyi "güncel" sanırdı (2026-07-19 bulgusu; canlı hesap 9/10'da 57
    çelişkili satır). DISTINCT ON (PostgreSQL).

    EUR çevrimi: TRY → /eurRate, EUR → aynen, USD/GBP → (bakiye × fxRate)/eurRate
    (çapraz kur, `CROSS_EUR_CURRENCIES`), diğer para birimleri → /eurRate.
    Kur yoksa hesap toplama KATILMAZ (`balance_eur=None`) — 1:1 varsayılmaz.

    HAREKETSİZ hesaplar (hiç banka işlemi yok) listede `last_balance=None` ile
    görünür ama toplama girmez — eski `_compute_start_eur` davranışıyla birebir
    (o da yalnız son-bakiyesi olan hesaplar üzerinde döngü kurardı).
    """
    accounts = db.query(BankAccount).order_by(BankAccount.bank_name, BankAccount.id).all()

    last_rows = (
        db.query(
            BankTransaction.account_id,
            BankTransaction.balance,
            BankTransaction.date,
        )
        .filter(BankTransaction.balance.isnot(None))
        .distinct(BankTransaction.account_id)
        .order_by(
            BankTransaction.account_id,
            BankTransaction.date.desc(),
            BankTransaction.id.desc(),
        )
        .all()
    )
    last_bal = {r.account_id: float(r.balance) for r in last_rows}
    last_date = {r.account_id: r.date for r in last_rows}

    eur_rate = _latest_buying(db, "EUR")
    cross_rates = {code: _latest_buying(db, code) for code in CROSS_EUR_CURRENCIES}

    items = []
    total_eur = 0.0
    for acc in accounts:
        currency = (acc.currency or "TRY").upper()
        blocked = float(acc.blocked_amount) if acc.blocked_amount else 0.0
        raw = last_bal.get(acc.id)
        effective = None if raw is None else raw - blocked

        balance_eur = None
        if effective is not None:
            if currency == "EUR":
                balance_eur = effective
            elif currency in CROSS_EUR_CURRENCIES:
                fx_rate = cross_rates.get(currency)
                if fx_rate and eur_rate:
                    balance_eur = (effective * fx_rate) / eur_rate
            elif eur_rate:
                balance_eur = effective / eur_rate
        if balance_eur is not None:
            total_eur += balance_eur

        items.append({
            "id": acc.id,
            "bank_name": acc.bank_name,
            "account_no": acc.account_no,
            # IBAN'ın yalnız son 4 hanesi (tam IBAN grafik şeridinde gerekmez)
            "iban_tail": (acc.iban or "")[-4:] or None,
            "currency": currency,
            "is_active": bool(acc.is_active),
            "last_balance": None if raw is None else round(raw, 2),
            "blocked_amount": round(blocked, 2),
            "effective_balance": None if effective is None else round(effective, 2),
            "balance_eur": None if balance_eur is None else round(balance_eur, 2),
            "last_movement_date": last_date[acc.id].isoformat() if acc.id in last_date else None,
        })

    return {
        "accounts": items,
        "total_eur": round(total_eur, 2),
        "eur_rate": eur_rate,
    }
