"""Nakit Koruma / Runway — içinde bulunulan ay için nakit projeksiyonu (EUR).

Ay-içi runway görünümü: BUGÜNKÜ toplam banka nakdi (`start_eur`) başlangıç
noktası; bugünden ay sonuna kadar GERÇEKLEŞMEMİŞ + EŞLEŞMEMİŞ planlı hareketler
(`FinanceEvent`) gelir (`inflows`) ve gider (`outs`) kalemleri olarak listelenir.
Gerçekleşen hareketler (bankada zaten var) ve eşleşmiş/çift-sayım kayıtları
dışarıda kalır. Transfer kategorileri (Virman / Döviz Satım / İade) tamamen
hariçtir — bunlar hesaplar arası iç hareket, gerçek nakit giriş/çıkışı değil.

Tüm tutarlar EUR'a çevrilir:
- `start_eur`: her hesabın son bakiyesi (blocked_amount düşülmüş) o günün EN SON
  TCMB EUR/USD alış kuruyla EUR'a çevrilir (mobile_dashboard_summary "son bakiye"
  deseni + eur_balances `to_eur` çevrim mantığı).
- kalem tutarları: olayın kendi `event_date`'indeki EUR alış kuru (`_get_eur_rate`);
  USD kalemler USD/EUR çaprazıyla (amount × USD alış / EUR alış, `_get_usd_rate`).
Kur yoksa kalem 1 TL = 1 EUR gibi çevrilmez → ATLANIR + `skipped_no_rate` sayılır.
"""

import calendar
from datetime import date as date_cls
from typing import Dict, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import runway_limiter
from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.exchange_rate import ExchangeRate
from app.models.finance_event import (
    DIRECTION_EXPENSE,
    DIRECTION_INCOME,
    SOURCE_BANK,
    FinanceEvent,
)
from app.models.payment_deferral import PaymentDeferral
from app.models.user import User
from app.utils.finance_helpers import MIN_DATE

from ._helpers import _get_eur_rate, _get_usd_rate

# Transfer kategorileri — t_account / groupByMonth ile birebir aynı (iç hareket)
TRANSFER_CATEGORIES = ("Virman", "Döviz Satım", "İade")

# Türkçe ay adları — sunucu locale'ine güvenilmez, sabit liste (report.py ile aynı)
TR_MONTHS = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]

# Kaynak bazlı Türkçe kalem etiketleri (ad üretilemezse son çare)
SOURCE_LABELS = {
    "check": "Verilen Çek",
    "credit": "Kredi/Leasing Taksiti",
    "vendor_payment": "Cari Ödeme",
    "cc_payment": "KK Borç Ödeme",
    "tax": "Vergi",
    "salary": "Maaş",
    "recurring": "Düzenli Ödeme",
    "sgk": "SGK",
    "withholding": "Stopaj",
    "dividend": "Temettü",
    "dividend_stopaj": "Temettü Stopajı",
    "rent_expense": "Verilen Kira",
    "rent_income": "Alınan Kira",
    "advance": "Avans",
    "bank": "Banka",
    "contract_installment": "Kontrat Taksiti",  # okuma-anında projeksiyon (FE'siz, #26-iii)
}

router = APIRouter()


def _latest_buying(db: Session, currency_code: str) -> Optional[float]:
    """Verilen döviz için EN SON (birim başına) TCMB alış kuru; yoksa None."""
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


def _compute_start_eur(db: Session) -> float:
    """BUGÜNKÜ toplam banka nakdi (EUR) — her hesabın son bakiyesi, blocked düşülmüş.

    mobile_dashboard_summary'deki tek-sorgu "son bakiye" desenini kopyalar:
    her hesabın max(id) işleminin bakiyesi → effective = last_balance - blocked.
    EUR çevrim: TRY → /eurRate, EUR → aynen, USD → (usd*usdRate)/eurRate,
    diğer para birimleri → /eurRate (en son alış kurları). Kur yoksa 0 varsayılır
    (banka nakdi başlangıç değeri — kalem atlama mantığı yalnız planlı hareketlerde).
    """
    accounts = db.query(BankAccount).all()

    last_tx_sub = (
        db.query(
            BankTransaction.account_id,
            func.max(BankTransaction.id).label("max_id"),
        )
        .filter(BankTransaction.balance.isnot(None))
        .group_by(BankTransaction.account_id)
        .subquery()
    )
    last_balance_rows = (
        db.query(BankTransaction.account_id, BankTransaction.balance)
        .join(
            last_tx_sub,
            (BankTransaction.account_id == last_tx_sub.c.account_id)
            & (BankTransaction.id == last_tx_sub.c.max_id),
        )
        .all()
    )
    last_bal = {row.account_id: float(row.balance) for row in last_balance_rows}
    acc_blocked = {
        a.id: float(a.blocked_amount) if a.blocked_amount else 0.0 for a in accounts
    }
    acc_currency = {a.id: (a.currency or "TRY").upper() for a in accounts}

    eur_rate = _latest_buying(db, "EUR")
    usd_rate = _latest_buying(db, "USD")

    total_eur = 0.0
    for acc_id, bal in last_bal.items():
        effective = bal - acc_blocked.get(acc_id, 0.0)
        currency = acc_currency.get(acc_id, "TRY")
        if currency == "EUR":
            total_eur += effective
        elif currency == "USD":
            if usd_rate and eur_rate:
                total_eur += (effective * usd_rate) / eur_rate
        else:  # TRY ve diğer para birimleri → EUR kuruna böl
            if eur_rate:
                total_eur += effective / eur_rate
    return round(total_eur, 2)


def _event_eur(
    db: Session, fe: FinanceEvent, cache: Dict[date_cls, float],
    usd_cache: Dict[date_cls, float],
) -> Optional[float]:
    """Kalemi EUR'a çevir; çevrilemiyorsa None (çağıran skipped_no_rate sayar).

    EUR kalem → amount aynen; USD kalem → USD/EUR çaprazı (amount × USD alış /
    EUR alış — t_account/eur_balances ile aynı formül; amount_try'a BAKILMAZ,
    USD satırlarında dolmuyordu → USD kalemler atlanıyordu, 2026-07-19).
    Diğerleri → TRY değeri / o tarihteki EUR alış kuru. TRY değeri: amount_try,
    yoksa currency TRY ise amount. Kur yoksa/0 ise 1'e bölünmez — kalem
    dışarıda bırakılır.
    """
    currency = (fe.currency or "TRY").upper()
    if currency == "EUR":
        return float(fe.amount)

    if fe.event_date not in cache:
        cache[fe.event_date] = _get_eur_rate(db, fe.event_date)
    eur_rate = cache[fe.event_date]

    if currency == "USD":
        if fe.event_date not in usd_cache:
            usd_cache[fe.event_date] = _get_usd_rate(db, fe.event_date)
        usd_rate = usd_cache[fe.event_date]
        # _get_*_rate kur yoksa 1.0 döner → 1:1 saçmalığını engelle (iki kur da gerekli)
        if not usd_rate or usd_rate <= 1.0 or not eur_rate or eur_rate <= 1.0:
            return None
        return float(fe.amount) * usd_rate / eur_rate

    if fe.amount_try is not None:
        try_value = float(fe.amount_try)
    elif currency in ("TRY", "TL"):
        try_value = float(fe.amount)
    else:
        return None  # döviz kalem, TRY karşılığı bilinmiyor

    # _get_eur_rate kur yoksa 1.0 döner → 1 TL = 1 EUR saçmalığını engelle
    if not eur_rate or eur_rate <= 1.0:
        return None
    return try_value / eur_rate


def _item_name(fe: FinanceEvent) -> str:
    """Kalem adı: açıklama → banka adı → çek no → kaynak Türkçe etiketi."""
    return (
        (fe.description or "").strip()
        or (fe.bank_name or "").strip()
        or (fe.check_no or "").strip()
        or SOURCE_LABELS.get(fe.source_type, fe.source_type)
    )


def _natural_date(db: Session, source_type: str, source_id: int):
    """Kaynağın öteleme ÖNCESİ doğal vade tarihi (yalnız ötelenmiş kalemler için sorgulanır).

    Cuma roll-over kaldırıldığı için ötelemeden başka hiçbir şey FE'yi doğal tarihinden
    kaydırmaz → ötelenmemiş kalemde event_date zaten doğal tarihtir (bu fn çağrılmaz).
    """
    if source_type == "check":
        from app.models.check import Check
        c = db.query(Check.due_date).filter(Check.id == source_id).first()
        return c[0] if c else None
    if source_type == "credit":
        from app.models.credit_product import CreditPayment
        p = db.query(CreditPayment.due_date).filter(CreditPayment.id == source_id).first()
        return p[0] if p else None
    if source_type == "cc_payment":
        from app.models.credit_card_statement import CreditCardStatement
        s = db.query(CreditCardStatement.son_odeme_tarihi).filter(
            CreditCardStatement.id == source_id).first()
        return s[0] if s else None
    if source_type == "vendor_payment":
        from app.models.vendor_transaction import VendorTransaction
        v = db.query(VendorTransaction.payment_due_date).filter(
            VendorTransaction.id == source_id).first()
        return v[0] if v else None
    if source_type in ("dividend", "dividend_stopaj"):
        # source_id = dividend_payments.id → doğal tarih = taksit vadesi (net) / muhtasar (stopaj)
        from app.models.dividend import DividendInstallment, DividendPayment
        pay = db.query(DividendPayment.installment_id).filter(DividendPayment.id == source_id).first()
        if not pay:
            return None
        i = db.query(DividendInstallment.due_date).filter(DividendInstallment.id == pay[0]).first()
        if not i:
            return None
        if source_type == "dividend_stopaj":
            from app.services.dividend_service import _derive_stopaj_date
            return _derive_stopaj_date(i[0])
        return i[0]
    # scheduled türleri: entry_date (paid_date ödeme tarihi olurdu ama öteleme = planlı)
    from app.models.scheduled import ScheduledEntry
    e = db.query(ScheduledEntry.entry_date).filter(ScheduledEntry.id == source_id).first()
    return e[0] if e else None


@router.get("/cash-flow/runway")
def runway(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cash_flow", "view")),
):
    """Nakit koruma / runway — içinde bulunulan ay için EUR nakit projeksiyonu."""
    runway_limiter.check(f"cashflow-runway-{current_user.id}")

    today = date_cls.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    month_start = date_cls(today.year, today.month, 1)
    month_end = date_cls(today.year, today.month, last_day)

    start_eur = _compute_start_eur(db)

    # Planlı/ödenmemiş hareketler: gerçekleşmemiş + eşleşmemiş. Transfer hariç.
    # İKİ pencere: (1) bugün..ay sonu → inflows/outs; (2) VADESİ GEÇEN (< bugün, MIN_DATE
    # üstü) ödenmemiş → overdue. Cuma roll-over kaldırıldığından vadesi geçen kalemler
    # artık orijinal (geçmiş) tarihlerinde durur → ayrı "Vadesi Geçenler" başlığı.
    events = (
        db.query(FinanceEvent)
        .filter(
            FinanceEvent.is_matched == False,
            FinanceEvent.is_realized == False,
            FinanceEvent.event_date >= MIN_DATE,
            FinanceEvent.event_date <= month_end,
            # NULL kategori NOT IN'de UNKNOWN döner → or_ ile açıkça korunur
            or_(
                FinanceEvent.category_name.is_(None),
                ~FinanceEvent.category_name.in_(TRANSFER_CATEGORIES),
            ),
        )
        .order_by(FinanceEvent.event_date.asc(), FinanceEvent.id.asc())
        .all()
    )

    # Ötelenmiş kalemler kümesi — kalemlere `deferred` bayrağı + `original_date` için
    deferred_set = {
        (st, sid)
        for st, sid in db.query(PaymentDeferral.source_type, PaymentDeferral.source_id).all()
    }

    # Beklemeye alınmış (hold) future-pending kalemler akımdan dışlanır → ayrı "held" listesi
    from app.services.hold_service import get_hold_set
    hold_set = get_hold_set(db)

    inflows: list = []
    outs: list = []
    overdue: list = []
    overdue_income: list = []
    held: list = []
    skipped_no_rate = 0
    rate_cache: Dict[date_cls, float] = {}
    usd_rate_cache: Dict[date_cls, float] = {}

    for fe in events:
        eur = _event_eur(db, fe, rate_cache, usd_rate_cache)
        if eur is None:
            skipped_no_rate += 1
            continue
        key = (fe.source_type, fe.source_id)
        is_deferred = key in deferred_set
        original_date = (
            _natural_date(db, fe.source_type, fe.source_id) if is_deferred else fe.event_date
        )
        item = {
            "id": f"{fe.source_type}:{fe.source_id}",
            "date": fe.event_date.isoformat(),
            "name": _item_name(fe),
            "amount_eur": round(eur, 2),
            # Kalem kendi para biriminde de dönülür (detay satırı native; grup/toplam EUR)
            "amount_native": round(float(fe.amount), 2),
            "currency": (fe.currency or "TRY").upper(),
            "source_type": fe.source_type,
            "deferred": is_deferred,
            "original_date": original_date.isoformat() if original_date else None,
        }
        if fe.event_date <= today:
            # Vadesi geçmiş VEYA BUGÜN vadeli ödenmemiş: GİDER → "Vadesi Geçenler"; GELİR → "Vadesi
            # Geçen Tahsilatlar". BUGÜN dahil (`<= today`, kullanıcı isteği 2026-07-16): bugün vadeli
            # ama ödenmemiş kalem (ör. su faturası) bekleyen çıkışta değil, hemen Vadesi Geçenler'de
            # gösterilir. `t_account.py` de aynı sınırı kullanır → kalem ya akışta ya overdue'da olur
            # (çift gösterim yok). (beklenen ama gelmemiş avans/kira/tahsilat; kullanıcı isteği
            # 2026-07-07 — eskiden düşürülüp hiçbir yerde gösterilmiyordu, T-Hesap'ta bekleyen sayılıyordu.)
            if fe.direction == DIRECTION_EXPENSE:
                overdue.append(item)
            elif fe.direction == DIRECTION_INCOME:
                overdue_income.append(item)
        elif (fe.source_type, fe.source_id) in hold_set:
            # Beklemeye alınmış (future-pending) → akımdan dışlanır, Bekleme Listesi'nde gösterilir.
            # Vade geçince yukarıdaki overdue dalına, ödenince realized'a doğal olarak geçer.
            held.append(item)
        elif fe.direction == DIRECTION_INCOME:
            item.pop("source_type")  # inflow'da source_type gösterilmiyordu (geriye uyum)
            inflows.append(item)
        else:
            outs.append(item)

    # Tahmini kredi kartı ekstresi rezervi (yüklenmemiş cari ay = kart limiti) — runway'e
    # cari-ay OUT kalemi olarak eklenir → nakit akım tablosuyla aynı rezerv (kullanıcı isteği
    # 2026-07-04). Kesim hatırlatıcıları (tutar 0) hariç (due_reserve_projections yalnız tutarlı).
    from app.services.cc_projection_service import due_reserve_projections
    for proj in due_reserve_projections(db, today=today):
        due = date_cls.fromisoformat(proj["date"])
        if due < today or due > month_end:
            continue  # yalnız bu ay penceresi (bugün..ay sonu)
        if due not in rate_cache:
            rate_cache[due] = _get_eur_rate(db, due)
        rate = rate_cache[due]
        if not rate or rate <= 1.0:
            skipped_no_rate += 1
            continue
        proj_card_id = proj.get("card_id")
        proj_item = {
            "id": f"cc_projection:{proj_card_id}",
            "date": proj["date"],
            "name": f"{proj['description']} (Tahmini)",
            "amount_eur": round(float(proj["amount"]) / rate, 2),
            "amount_native": round(float(proj["amount"]), 2),
            "currency": "TRY",
            "source_type": "cc_payment",  # Bekleme Listesi'nde "KK Borç Ödemeleri" altında grupla
            "deferred": False,
            "original_date": proj["date"],
            "projected": True,
        }
        # Kart bazında beklemeye alınmış projeksiyon rezervi → Bekleme Listesi (outs'tan çıkar)
        if proj_card_id is not None and ("cc_projection", proj_card_id) in hold_set:
            held.append(proj_item)
        else:
            outs.append(proj_item)
    # Kontrat taksitleri (advances'a netlenmiş) + TAM CİRO tahsilat projeksiyonu (#26-iii,
    # 2026-07-17 — okuma-anında servis, FE yazılmaz). Vadesi geçen taksitler "Vadesi Geçen
    # Tahsilatlar"a kalem kalem düşer (alacak takibi); cari ay vadeliler girişlere.
    from app.services.contract_projection_service import contract_inflow_projections
    _cproj = contract_inflow_projections(db, today=today)
    for _ci in _cproj["installments"]:
        _cdt = date_cls.fromisoformat(_ci["date"])
        if _cdt > month_end:
            continue  # runway yalnız cari ay penceresi
        _name = _ci["label"] + (" — KOŞULLU" if _ci.get("conditional") else "")
        _item = {
            "id": f"contract_installment:{_ci['installment_id']}",
            "date": _ci["date"],
            "name": _name,
            "amount_eur": round(float(_ci["amount_eur"]), 2),
            "amount_native": round(float(_ci["amount_eur"]), 2),
            "currency": "EUR",
            "source_type": "contract_installment",
            "deferred": False,
            "original_date": _ci["date"],
            "projected": True,
        }
        if _cdt <= today:
            overdue_income.append(_item)
        else:
            _inf = dict(_item)
            _inf.pop("source_type")
            inflows.append(_inf)
    for _ci in _cproj["ciro_monthly"]:
        _cdt = date_cls.fromisoformat(_ci["date"])
        if _cdt <= today or _cdt > month_end:
            continue
        inflows.append({
            "id": f"contract_ciro:{_ci['month']}",
            "date": _ci["date"],
            "name": _ci["label"],
            "amount_eur": round(float(_ci["amount_eur"]), 2),
            "amount_native": round(float(_ci["amount_eur"]), 2),
            "currency": "EUR",
            "deferred": False,
            "original_date": _ci["date"],
            "projected": True,
        })
    inflows.sort(key=lambda x: x["date"])
    overdue_income.sort(key=lambda x: x["date"])

    outs.sort(key=lambda x: x["date"])  # projeksiyonlar sona eklendi → tarih sırasına çek

    return {
        "month_label": f"{TR_MONTHS[today.month - 1]} {today.year}",
        "month_start": month_start.isoformat(),
        "month_end": month_end.isoformat(),
        "today": today.isoformat(),
        "start_eur": start_eur,
        "inflows": inflows,
        "outs": outs,
        "overdue": overdue,
        "overdue_income": overdue_income,
        "held": held,
        "skipped_no_rate": skipped_no_rate,
    }
