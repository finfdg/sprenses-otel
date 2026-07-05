"""KMH (Kredili Mevduat Hesabı) faiz hesaplama servisi.

KMH taksitli kredi gibi sabit ödeme planı tutmaz. Bağlı banka hesabının bakiyesi
negatife düştüğünde "adat" (gün × bakiye) üzerinden faiz birikir; banka bunu
**ÇEYREKLİK** (üç ayda bir, çeyrek sonunda: 31 Mart / 30 Haziran / 30 Eylül / 31 Aralık)
biriken faiz + BSMV + komisyon olarak hesaptan tahsil eder (kullanıcı kararı 2026-07-04;
canlı QNB KMH faizi 30 Haziran'da ₺9.910 + BSMV olarak tek seferde çekildi).

Algoritma:
  Adat        = SUM_over_each_day(|negatif_bakiye_o_gün|)
  Faiz        = Adat × (yıllık_oran / 36000)   ← Türk bankacılığı standardı (360 günlük ticari yıl)
  BSMV        = Faiz × bsmv_rate / 100
  Komisyon    = Faiz × commission_rate / 100
  Toplam Borç = Faiz + BSMV + Komisyon

Çoklu çeyrek desteği: KMH başlangıcından bugüne kadar her ÇEYREK için ayrı tahakkuk
hesaplanır. Geçmiş çeyrekler kapalı (gerçekleşen adat), mevcut çeyrek projeksiyonlu
(bugünkü borç çeyrek sonuna kadar sürerse). Periods listesi çeyrek çeyrek döner.

**Nakit akım (sync_kmh_to_finance_events):** yalnız MEVCUT çeyreğin projeksiyonu yansıtılır.
Geçmiş çeyrekler bankaca zaten tahsil edildi (gerçek "Faiz Tahakkuku" banka hareketi asıl
kaynak) → sistem projeksiyonu eklenirse ÇİFT SAYIM olur; bu yüzden geçmiş çeyrekler
nakit akıma girmez. Gelecek çeyrekler yalnız KMH detay sayfasında tahmin olarak kalır.
"""

import logging
from calendar import monthrange
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.credit_product import CreditPayment, CreditProduct

logger = logging.getLogger(__name__)


def _last_day_of_month(d: date) -> date:
    """Verilen tarihin ait olduğu ayın son günü."""
    last = monthrange(d.year, d.month)[1]
    return date(d.year, d.month, last)


def _next_month_first(d: date) -> date:
    """Verilen tarihin sonraki ayın 1. günü."""
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _quarter_num(d: date) -> int:
    """Verilen tarihin çeyreği (1-4)."""
    return (d.month - 1) // 3 + 1


def _quarter_first(d: date) -> date:
    """Verilen tarihin ait olduğu çeyreğin ilk günü (1 Oca/1 Nis/1 Tem/1 Eki)."""
    q = (d.month - 1) // 3
    return date(d.year, q * 3 + 1, 1)


def _quarter_last(d: date) -> date:
    """Verilen tarihin ait olduğu çeyreğin son günü (31 Mar/30 Haz/30 Eyl/31 Ara)."""
    q = (d.month - 1) // 3
    return _last_day_of_month(date(d.year, q * 3 + 3, 1))


def _next_quarter_first(d: date) -> date:
    """Verilen tarihin ait olduğu çeyreğin SONRAKİ çeyreğinin ilk günü."""
    qf = _quarter_first(d)
    if qf.month == 10:  # Q4 → sonraki yıl Q1
        return date(qf.year + 1, 1, 1)
    return date(qf.year, qf.month + 3, 1)


def _build_daily_balance_series(
    txs: list, start: date, end: date, initial_balance: float = 0.0
) -> dict:
    """Tarih aralığındaki her gün için 'o günün son bakiyesi'ni döndürür.

    İşlem olmayan günler önceki günün bakiyesini taşır (forward fill).
    initial_balance: period başlamadan önceki son bakiye (önceki tx'ten).
    """
    balance_at_date: dict = {}
    for tx in txs:
        if tx.balance is not None:
            balance_at_date[tx.date] = float(tx.balance)

    sorted_dates = sorted(balance_at_date.keys())
    series: dict = {}
    last_balance = initial_balance
    di = 0

    current = start
    while current <= end:
        while di < len(sorted_dates) and sorted_dates[di] <= current:
            last_balance = balance_at_date[sorted_dates[di]]
            di += 1
        series[current] = last_balance
        current += timedelta(days=1)

    return series


def _get_initial_balance(db: Session, account_id: int, before: date) -> tuple:
    """Verilen tarihten önceki son tx ve bakiyesi (forward fill için)."""
    prev_tx = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.account_id == account_id,
            BankTransaction.date < before,
            BankTransaction.balance.isnot(None),
        )
        .order_by(BankTransaction.date.desc(), BankTransaction.id.desc())
        .first()
    )
    if prev_tx and prev_tx.balance is not None:
        return float(prev_tx.balance), prev_tx
    return 0.0, None


def _calculate_for_period(
    credit: CreditProduct,
    db: Session,
    period_start: date,
    period_end: date,
    today: date,
    blocked_amount: float = 0.0,
) -> dict:
    """Belirli bir ay için adat, faiz, BSMV, komisyon hesabı + hareketler.

    blocked_amount: hesabın bloke tutarı. KMH adat hesabı için her bakiyeden
    düşülür (kullanılabilir bakiye = bakiye - bloke). Bloke tutarı kullanıcının
    KMH'den çekemediği para olduğu için faiz hesabına dahil edilmez.

    period_end > today ise: bugüne kadar 'past_adat', bugünden period_end'e kadar
    'future_adat' (mevcut bakiyenin devam ettiği varsayılır) hesaplanır.
    period_end <= today ise: tüm period kapalı (sadece past_adat).
    """
    is_current = period_start <= today <= period_end
    is_future = period_start > today

    # Period başına devir bakiye (raw bakiye, bloke düşülmemiş)
    raw_initial, prev_tx = _get_initial_balance(db, credit.linked_account_id, period_start)
    # KMH için kullanılabilir bakiye = raw - bloke
    initial_balance = raw_initial - blocked_amount

    # Period içindeki işlemler
    actual_end = min(period_end, today) if not is_future else period_start
    txs = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.account_id == credit.linked_account_id,
            BankTransaction.date >= period_start,
            BankTransaction.date <= actual_end,
        )
        .order_by(BankTransaction.date, BankTransaction.id)
        .all()
    )

    # Geçmiş kısım için günlük bakiye serisi (raw, sonra bloke düşülecek)
    if not is_future:
        raw_daily = _build_daily_balance_series(txs, period_start, actual_end, raw_initial)
        # KMH için her bakiyeden bloke tutarı düş
        daily = {d: b - blocked_amount for d, b in raw_daily.items()}
        past_adat = sum(abs(b) for b in daily.values() if b < 0)
        ending_balance = daily.get(actual_end, initial_balance)
    else:
        past_adat = 0.0
        ending_balance = initial_balance

    # Projeksiyon
    future_adat = 0.0
    if is_current and ending_balance < 0:
        # Mevcut ay: bugünden ay sonuna kadar
        days_remaining = (period_end - today).days
        future_adat = abs(ending_balance) * days_remaining
    elif is_future and initial_balance < 0:
        # Gelecek ay: tüm period için projeksiyon (devir bakiye negatif kalmaya devam eder)
        days_in_period = (period_end - period_start).days + 1
        future_adat = abs(initial_balance) * days_in_period
        ending_balance = initial_balance  # değişmez

    total_adat = past_adat + future_adat

    rate = float(credit.interest_rate or 0)
    bsmv_rate = float(credit.bsmv_rate or 0)
    commission_rate = float(credit.commission_rate or 0)

    interest = total_adat * rate / 36000
    bsmv = interest * bsmv_rate / 100
    commission = interest * commission_rate / 100
    total_due = interest + bsmv + commission

    accrued_interest = past_adat * rate / 36000
    accrued_bsmv = accrued_interest * bsmv_rate / 100
    accrued_commission = accrued_interest * commission_rate / 100
    accrued_total = accrued_interest + accrued_bsmv + accrued_commission

    movements = []
    for tx in txs:
        raw_balance_after = float(tx.balance) if tx.balance is not None else None
        # KMH state için bloke düşülmüş net bakiye kullan
        net_balance = (raw_balance_after - blocked_amount) if raw_balance_after is not None else None
        movements.append({
            "id": tx.id,
            "date": tx.date.isoformat(),
            "amount": float(tx.amount),
            "balance_after": raw_balance_after,  # ekstreye uyumlu ham bakiye
            "net_balance": net_balance,  # bloke düşülmüş — KMH bağlamı
            "description": tx.description or "",
            "kmh_state": (
                "negatif" if net_balance is not None and net_balance < 0
                else "pozitif" if net_balance is not None
                else "bilinmiyor"
            ),
        })

    return {
        "year": period_start.year,
        "month": period_start.month,
        "quarter": _quarter_num(period_start),
        # "month_label" adı korundu (frontend tüketimi) ama artık ÇEYREK etiketi: "2026-Ç3"
        "month_label": f"{period_start.year}-Ç{_quarter_num(period_start)}",
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "is_current": is_current,
        "is_future": is_future,
        "days_in_period": (period_end - period_start).days + 1,
        "days_passed": (min(today, period_end) - period_start).days + 1 if not is_future else 0,
        "carry_balance": round(initial_balance, 2),
        "carry_date": prev_tx.date.isoformat() if prev_tx else None,
        "carry_description": (prev_tx.description or "")[:120] if prev_tx else None,
        "ending_balance": round(ending_balance, 2),
        "past_adat": round(past_adat, 2),
        "future_adat": round(future_adat, 2),
        "total_adat": round(total_adat, 2),
        "accrued_interest": round(accrued_interest, 2),
        "accrued_bsmv": round(accrued_bsmv, 2),
        "accrued_commission": round(accrued_commission, 2),
        "accrued_total": round(accrued_total, 2),
        "projected_interest": round(interest, 2),
        "projected_bsmv": round(bsmv, 2),
        "projected_commission": round(commission, 2),
        "projected_total_due": round(total_due, 2),
        "movements": movements,
    }


def calculate_kmh_status(credit: CreditProduct, db: Session) -> Optional[dict]:
    """KMH'nin tüm aylar için ayrı tahakkukları + güncel durum.

    None döner: KMH değilse veya linked_account_id yoksa.
    """
    if credit.type != "kmh" or not credit.linked_account_id:
        return None

    today = date.today()
    kmh_start = credit.start_date or today.replace(day=1)

    # Bağlı hesabın bloke tutarını al (kullanılabilir bakiye = bakiye - bloke)
    bank_acc = db.query(BankAccount).filter(BankAccount.id == credit.linked_account_id).first()
    blocked_amount = float(bank_acc.blocked_amount) if bank_acc and bank_acc.blocked_amount else 0.0

    # Bugünkü bakiye (raw, sonra bloke düşülecek)
    raw_today, _ = _get_initial_balance(db, credit.linked_account_id, today + timedelta(days=1))
    initial_balance_today = raw_today - blocked_amount

    # KMH start çeyreğinden bugünün çeyreğine kadar her ÇEYREK için ayrı period hesapla
    periods = []
    cursor_q_first = _quarter_first(kmh_start)
    today_q_first = _quarter_first(today)

    while cursor_q_first <= today_q_first:
        # Bu çeyrek için period: KMH start sonrası ya da çeyrek başı (hangisi sonraysa)
        period_start = max(kmh_start, cursor_q_first)
        period_end = _quarter_last(cursor_q_first)
        period_data = _calculate_for_period(credit, db, period_start, period_end, today, blocked_amount)
        periods.append(period_data)
        cursor_q_first = _next_quarter_first(cursor_q_first)

    # Bu çeyrekten sonraki 4 çeyrek (≈1 yıl) projeksiyon (mevcut bakiyenin devam ettiği varsayılır)
    for _ in range(4):
        period_start = cursor_q_first
        period_end = _quarter_last(cursor_q_first)
        # Future çeyrek için bitiş tarihi KMH end_date'i geçmemeli
        if credit.end_date and period_start > credit.end_date:
            break
        period_data = _calculate_for_period(credit, db, period_start, period_end, today, blocked_amount)
        periods.append(period_data)
        cursor_q_first = _next_quarter_first(cursor_q_first)

    # Genel toplamlar
    total_accrued = sum(p["accrued_total"] for p in periods)
    total_projected = sum(p["projected_total_due"] for p in periods)

    # Mevcut ay (görüntülemenin merkezinde)
    current_period = next((p for p in periods if p["is_current"]), periods[-1] if periods else None)

    today_balance = initial_balance_today
    current_debt = abs(today_balance) if today_balance < 0 else 0.0

    return {
        "credit_id": credit.id,
        "credit_name": credit.name,
        "linked_account_id": credit.linked_account_id,
        "limit": float(credit.total_amount or 0),
        "interest_rate": float(credit.interest_rate or 0),
        "bsmv_rate": float(credit.bsmv_rate or 0),
        "commission_rate": float(credit.commission_rate or 0),
        "today": today.isoformat(),
        "today_balance": round(today_balance, 2),  # net (bloke düşülmüş)
        "today_raw_balance": round(raw_today, 2),  # ekstre bakiyesi (bloke dahil)
        "blocked_amount": round(blocked_amount, 2),
        "current_debt": round(current_debt, 2),
        "available_limit": round(float(credit.total_amount or 0) - current_debt, 2),
        # Mevcut ay özeti (üst stat kartlar için)
        "current_period": current_period,
        # Tüm aylar (geçmiş + mevcut + 12 gelecek projeksiyonu)
        "periods": periods,
        # Genel toplamlar
        "total_accrued": round(total_accrued, 2),  # tüm ayların gerçekleşmiş tahakkuku
        "total_projected": round(total_projected, 2),  # mevcut ay projeksiyon dahil tüm aylar
    }


def sync_kmh_to_finance_events(credit: CreditProduct, db: Session) -> int:
    """KMH'nin YALNIZ MEVCUT ÇEYREK tahakkukunu credit_payment + finance_event olarak yansıtır.

    **Geçmiş çeyrekler nakit akıma GİRMEZ** (kullanıcı kararı 2026-07-04): banka KMH faizini
    çeyrek sonunda gerçek bir "Faiz Tahakkuku" banka hareketi olarak tahsil eder — o asıl
    kaynaktır; sistem geçmiş çeyrek projeksiyonu da eklerse aynı faiz İKİ KEZ sayılır (canlı
    QNB'de olan buydu). Gelecek çeyrekler henüz tahakkuk etmedi (yalnız KMH detay sayfasında
    tahmin). Böylece mevcut çeyreğin çeyrek-sonu tahmini nakit akımda görünür; geçmiş çeyrekler
    yalnız bankanın gerçek çekimiyle sayılır.

    Strateji: KMH için tüm credit_payment'ları sil ve yeniden oluştur (idempotent).
    finance_events otomatik upsert_credit_payment ile güncellenir.

    Returns: oluşturulan payment sayısı (0 veya 1 — mevcut çeyrek).
    """
    if credit.type != "kmh" or not credit.linked_account_id:
        return 0

    from app.utils.finance_event_service import finance_event_svc

    status = calculate_kmh_status(credit, db)
    if not status:
        return 0

    # Mevcut KMH credit_payment'larını ve finance_events'i temizle
    existing = db.query(CreditPayment).filter(
        CreditPayment.credit_product_id == credit.id
    ).all()
    for old in existing:
        try:
            finance_event_svc.invalidate(db, "credit", old.id)
        except Exception:
            logger.debug("KMH eski finance_event temizlenemedi pay_id=%s", old.id, exc_info=True)
        db.delete(old)
    db.flush()

    # YALNIZ MEVCUT çeyreğin projeksiyonunu oluştur (geçmiş = bankaca tahsil edildi → çift
    # sayım; gelecek = henüz tahakkuk yok). Böylece nakit akım geçmiş KMH faizini iki kez saymaz.
    created = 0
    for p in status["periods"]:
        if not p["is_current"]:
            continue
        # Sıfır tahakkuk için kayıt oluşturma (boş satır olur)
        if p["projected_total_due"] <= 0.01:
            continue

        new_pay = CreditPayment(
            credit_product_id=credit.id,
            installment_no=None,
            due_date=date.fromisoformat(p["period_end"]),
            amount=p["projected_total_due"],
            principal=None,
            interest=p["projected_interest"],
            bsmv=p["projected_bsmv"],
            commission=p["projected_commission"],
            is_paid=False,
            notes=f"KMH çeyrek sonu tahakkuku (tahmini) — {p['month_label']}",
        )
        db.add(new_pay)
        db.flush()

        try:
            finance_event_svc.upsert_credit_payment(db, new_pay, credit)
        except Exception:
            logger.warning("KMH finance_event yansıtılamadı pay_id=%s", new_pay.id, exc_info=True)

        created += 1

    db.commit()
    return created
