"""Cari FIFO hesaplama — net borç bazlı fatura kırpma.

Ödeme planı ve finance_events sync için ortak mantık.
Her carinin net borcu hesaplanır, faturalar en eskiden yeniye sıralanır,
ödemeler en eski faturalardan düşülür.

Returns: dict[vtx_id, fifo_amount] — her faturanın FIFO sonrası ödenmemiş tutarı.
Tam ödenmiş faturalar dict'te yer almaz.
"""
from collections import defaultdict
from datetime import date as date_type
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.vendor import STATUS_PAYMENT_BANNED, Vendor
from app.models.vendor_transaction import VendorTransaction


def _next_friday(d: date_type) -> date_type:
    """Verilen tarihten SONRAKİ Cuma'ya hizala (vade GÜNÜ hizalaması).

    NOT: Bu, fatura tarihinden vade hesaplarken (fatura + payment_days) hesaplanan
    HAM vade gününü Cuma'ya yuvarlar — "ödeme günü Cuma"dır kuralı. Bu KORUNUR.
    Vadesi GEÇEN faturayı ileri aktarmakla (kaldırıldı) KARIŞTIRILMAMALIDIR.
    """
    days_ahead = 4 - d.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return d + timedelta(days=days_ahead)


def coming_friday(d: date_type) -> date_type:
    """Bugünden itibaren en yakın Cuma (bugün Cuma ise bugün)."""
    days_ahead = 4 - d.weekday()
    if days_ahead < 0:
        days_ahead += 7
    return d + timedelta(days=days_ahead)


def effective_due_date(payment_due_date, vtx_id=None, deferral_map=None):
    """Faturanın EFEKTİF ödeme tarihi.

    2026-07-04 (kullanıcı kararı): **Vadesi geçen faturanın sonraki Cuma'ya AKTARILMASI
    GLOBAL KALDIRILDI.** Ödenmemiş fatura artık ORİJİNAL vade tarihinde kalır (geçmişte
    görünür — gerçek durum). Yalnızca KALICI ÖTELEME (payment_deferrals) uygulanır:
    kullanıcı bir kalemi bilinçli ileri çekmişse o tarih döner.

    Cuma'ya yuvarlama (`_next_friday`) fatura tarihinden vade hesabında (fatura +
    payment_days) HÂLÂ geçerli — o AYRI bir kural ("vade günü Cuma"). Burada YOK.

    deferral_map: (source_type, source_id) → deferred_to (opsiyonel; verilirse SELECT'siz).
    """
    if vtx_id is not None:
        if deferral_map is not None:
            deferred = deferral_map.get(("vendor_payment", vtx_id))
        else:
            deferred = None
        if deferred is not None:
            return deferred
    return payment_due_date


def calculate_fifo_amounts(db: Session) -> Dict[int, float]:
    """FIFO ile her faturanın ödenmemiş tutarını hesapla.

    Returns:
        dict[vtx_id → fifo_amount]: Ödenmemiş faturalar ve tutarları.
        Tam ödenmiş faturalar dahil edilmez.
    """
    # 1) Her carinin net borcunu hesapla
    vendor_net_debt = _get_vendor_net_debts(db)
    if not vendor_net_debt:
        return {}

    # Vendor vade günleri
    vendor_info = _get_vendor_payment_days(db, list(vendor_net_debt.keys()))

    # 2) Borçlu carilerin alacak faturalarını çek
    rows = (
        db.query(
            VendorTransaction.id,
            VendorTransaction.vendor_id,
            VendorTransaction.date,
            VendorTransaction.alacak,
            VendorTransaction.payment_due_date,
        )
        .filter(
            VendorTransaction.alacak > 0,
            VendorTransaction.vendor_id.in_(list(vendor_net_debt.keys())),
        )
        .all()
    )

    # 3) Vade tarihi hesapla (boş olanlar için)
    class InvRow:
        __slots__ = ("vtx_id", "vendor_id", "date", "alacak", "payment_due_date")

        def __init__(self, row, calc_due: Optional[date_type] = None):
            self.vtx_id = row.id
            self.vendor_id = row.vendor_id
            self.date = row.date
            self.alacak = row.alacak
            self.payment_due_date = row.payment_due_date or calc_due

    invoice_rows = []
    for row in rows:
        if row.payment_due_date:
            invoice_rows.append(InvRow(row))
        else:
            pay_days = vendor_info.get(row.vendor_id, 90)
            if row.date:
                raw_due = row.date + timedelta(days=pay_days)
                due = _next_friday(raw_due)
                invoice_rows.append(InvRow(row, due))

    # 4) FIFO: her cari için en eski faturadan başla, ödemeleri düş
    vendor_invoices: Dict[int, list] = defaultdict(list)
    for inv in invoice_rows:
        if inv.payment_due_date:
            vendor_invoices[inv.vendor_id].append(inv)

    # Minimum tutar eşiği (1 kuruş) — float aritmetiğinden kalan
    # kırıntıları (ör. 8.37e-11) filtrelemek için
    MIN_AMOUNT = 0.01

    result: Dict[int, float] = {}
    for vid, invoices in vendor_invoices.items():
        remaining_debt = vendor_net_debt.get(vid, 0)
        if remaining_debt <= 0:
            continue

        # Vade tarihine göre sırala (en eski önce)
        invoices.sort(key=lambda r: (r.payment_due_date, r.date or r.payment_due_date))

        total_invoices = sum(float(r.alacak) for r in invoices)

        if total_invoices <= remaining_debt:
            # Tüm faturalar ödenmemiş
            for inv in invoices:
                result[inv.vtx_id] = float(inv.alacak)
        else:
            # FIFO: en eski faturalar "ödenmiş" kabul et
            paid_amount = total_invoices - remaining_debt

            for inv in invoices:
                inv_amount = float(inv.alacak)
                if paid_amount >= inv_amount:
                    paid_amount -= inv_amount
                    # Tam ödenmiş — result'a eklenmez
                    continue
                elif paid_amount > 0:
                    show_amount = inv_amount - paid_amount
                    paid_amount = 0
                    if show_amount >= MIN_AMOUNT:
                        result[inv.vtx_id] = show_amount
                else:
                    result[inv.vtx_id] = inv_amount

    return result


def calculate_overdue_by_vendor(
    db: Session,
    today: Optional[date_type] = None,
    vendor_ids: Optional[List[int]] = None,
) -> Dict[int, Tuple[float, int]]:
    """Her cari için NET vadesi geçmiş tutarı + fatura sayısı.

    `calculate_fifo_amounts` (Ödeme Planı + nakit akım ile AYNI kaynak) ile hesaplanan
    ödenmemiş fatura paylarından, efektif vadesi BUGÜNDEN ÖNCE olanları toplar. Böylece
    cari detayındaki "Vadesi Geçmiş" kartı, brüt eşleşmemiş-fatura toplamı yerine gerçek
    ödenmemiş-ve-gecikmiş tutarı gösterir — Ödeme Planı'nın geçmiş-vadeli kısmıyla birebir
    tutarlı. (Ödemeler en eski faturalardan düşüldüğü için gecikmiş kısım net borçla sınırlı
    kalır; yasaklı/borçsuz cariler FIFO kaynağında zaten yer almaz.)

    vendor_ids verilirse yalnız o carilere ait sonuç döner (detay sayfası tek cariyi okur).

    Returns:
        dict[vendor_id → (overdue_amount, overdue_count)]  — yalnız overdue > 0 olan cariler.
    """
    from app.services.deferral_service import get_deferral_map

    if today is None:
        today = date_type.today()

    fifo = calculate_fifo_amounts(db)  # {vtx_id: ödenmemiş tutar}
    if not fifo:
        return {}

    rows = (
        db.query(
            VendorTransaction.id,
            VendorTransaction.vendor_id,
            VendorTransaction.date,
            VendorTransaction.payment_due_date,
        )
        .filter(VendorTransaction.id.in_(list(fifo.keys())))
        .all()
    )
    if vendor_ids is not None:
        vid_set = set(vendor_ids)
        rows = [r for r in rows if r.vendor_id in vid_set]
    if not rows:
        return {}

    # payment_due_date boş faturalar için vade günü (FIFO ile aynı: date + payment_days → Cuma)
    need_days = {r.vendor_id for r in rows if not r.payment_due_date and r.date}
    pay_days_map = _get_vendor_payment_days(db, list(need_days)) if need_days else {}

    deferral_map = get_deferral_map(db)

    MIN_AMOUNT = 0.01
    acc: Dict[int, Tuple[float, int]] = {}
    for r in rows:
        amount = fifo.get(r.id, 0.0)
        if amount < MIN_AMOUNT:
            continue
        if r.payment_due_date:
            due = r.payment_due_date
        elif r.date:
            pay_days = pay_days_map.get(r.vendor_id, 90)
            due = _next_friday(r.date + timedelta(days=pay_days))
        else:
            continue
        due = effective_due_date(due, vtx_id=r.id, deferral_map=deferral_map)
        if due < today:
            amt, cnt = acc.get(r.vendor_id, (0.0, 0))
            acc[r.vendor_id] = (amt + float(amount), cnt + 1)

    return {vid: (round(a, 2), c) for vid, (a, c) in acc.items()}


# ─── Ödeme Planı ────────────────────────────────────────


def _get_vendor_net_debts(db: Session) -> Dict[int, float]:
    """Her carinin net borcunu hesapla. Sadece borçlu cariler döner.

    Ödeme yasaklısı cariler hariç tutulur.
    """
    # Ödeme yasaklısı carileri bul
    banned_ids = {
        v.id for v in db.query(Vendor.id)
        .filter(Vendor.status == STATUS_PAYMENT_BANNED)
        .all()
    }

    rows = (
        db.query(
            VendorTransaction.vendor_id,
            sa_func.coalesce(sa_func.sum(VendorTransaction.borc), 0).label("total_borc"),
            sa_func.coalesce(sa_func.sum(VendorTransaction.alacak), 0).label("total_alacak"),
        )
        .group_by(VendorTransaction.vendor_id)
        .all()
    )
    result: Dict[int, float] = {}
    for row in rows:
        if row.vendor_id in banned_ids:
            continue
        bakiye = float(row.total_borc) - float(row.total_alacak)
        if bakiye < 0:
            result[row.vendor_id] = abs(bakiye)
    return result


def _get_vendor_payment_days(db: Session, vendor_ids: List[int]) -> Dict[int, int]:
    """Vendor'ların payment_days bilgisini toplu çek."""
    return {
        v.id: v.payment_days
        for v in db.query(Vendor.id, Vendor.payment_days)
        .filter(Vendor.id.in_(vendor_ids))
        .all()
    }


class ScheduleInvoice:
    """Ödeme planı fatura satırı."""
    __slots__ = ("vtx_id", "vendor_id", "date", "evrak_no", "transaction_type",
                 "alacak", "hesap_kodu", "hesap_adi", "payment_due_date")

    def __init__(self, row, calc_due: Optional[date_type] = None):
        self.vtx_id = row.id
        self.vendor_id = row.vendor_id
        self.date = row.date
        self.evrak_no = row.evrak_no
        self.transaction_type = row.transaction_type
        self.alacak = row.alacak
        self.hesap_kodu = row.hesap_kodu
        self.hesap_adi = row.hesap_adi
        self.payment_due_date = row.payment_due_date or calc_due


def get_payment_schedule(
    db: Session,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> List[dict]:
    """Haftalık ödeme planını getir — net borç bazlı, FIFO kırpmalı.

    Vadesi geçmiş faturalar otomatik olarak sonraki Cuma'ya kaydırılır.

    Returns:
        List[dict]: WeeklyPaymentGroup formatında haftalık gruplar.
    """
    from app.utils.sync_vendor_fifo import sync_vendor_finance_events

    # Vadesi geçmiş faturaların finance_events tarihlerini güncelle
    sync_result = sync_vendor_finance_events(db)
    if sync_result.get("updated") or sync_result.get("created") or sync_result.get("removed"):
        db.commit()

    # 1) Her carinin net borcunu çek
    vendor_net_debt = _get_vendor_net_debts(db)
    if not vendor_net_debt:
        return []

    vendor_info = _get_vendor_payment_days(db, list(vendor_net_debt.keys()))

    # 2) Borçlu carilerin TÜM alacak faturalarını çek
    rows = (
        db.query(
            VendorTransaction.id,
            VendorTransaction.vendor_id,
            VendorTransaction.date,
            VendorTransaction.evrak_no,
            VendorTransaction.transaction_type,
            VendorTransaction.alacak,
            VendorTransaction.payment_due_date,
            Vendor.hesap_kodu,
            Vendor.hesap_adi,
        )
        .join(Vendor, VendorTransaction.vendor_id == Vendor.id)
        .filter(
            VendorTransaction.alacak > 0,
            VendorTransaction.vendor_id.in_(list(vendor_net_debt.keys())),
        )
        .all()
    )

    # 3) payment_due_date boş olanlar için hesapla
    invoice_rows: List[ScheduleInvoice] = []
    for row in rows:
        if row.payment_due_date:
            invoice_rows.append(ScheduleInvoice(row))
        else:
            pay_days = vendor_info.get(row.vendor_id, 90)
            if row.date:
                raw_due = row.date + timedelta(days=pay_days)
                due = _next_friday(raw_due)
                invoice_rows.append(ScheduleInvoice(row, due))

    # 4) FIFO: Her cari için en eski faturadan başla, ödemeleri düş
    vendor_invoices: Dict[int, list] = defaultdict(list)
    for inv in invoice_rows:
        if inv.payment_due_date:
            vendor_invoices[inv.vendor_id].append(inv)

    schedule_items: List[Tuple[ScheduleInvoice, float]] = []
    for vid, invoices in vendor_invoices.items():
        remaining_debt = vendor_net_debt.get(vid, 0)
        if remaining_debt <= 0:
            continue

        invoices.sort(key=lambda r: (r.payment_due_date, r.date or r.payment_due_date))
        total_invoices = sum(float(r.alacak) for r in invoices)

        if total_invoices <= remaining_debt:
            for inv in invoices:
                schedule_items.append((inv, float(inv.alacak)))
            leftover = remaining_debt - total_invoices
            if leftover > 0.01 and invoices:
                last_inv = invoices[-1]
                schedule_items.append((last_inv, leftover))
        else:
            paid_amount = total_invoices - remaining_debt
            for inv in invoices:
                inv_amount = float(inv.alacak)
                if paid_amount >= inv_amount:
                    paid_amount -= inv_amount
                    continue
                elif paid_amount > 0:
                    show_amount = inv_amount - paid_amount
                    paid_amount = 0
                    schedule_items.append((inv, show_amount))
                else:
                    schedule_items.append((inv, inv_amount))

    # 5) KALICI ÖTELEME uygula (Cuma roll-over KALDIRILDI 2026-07-04 — vadesi geçen
    #    fatura orijinal tarihinde kalır; yalnız kullanıcı ötelediyse ileri çekilir).
    from app.services.deferral_service import get_deferral_map
    deferral_map = get_deferral_map(db)
    for inv, _amt in schedule_items:
        inv.payment_due_date = effective_due_date(
            inv.payment_due_date, vtx_id=inv.vtx_id, deferral_map=deferral_map
        )

    # 6) Tarih filtresi
    if from_date:
        try:
            fd = datetime.strptime(from_date, "%Y-%m-%d").date()
            schedule_items = [(inv, amt) for inv, amt in schedule_items if inv.payment_due_date >= fd]
        except ValueError:
            pass

    if to_date:
        try:
            td = datetime.strptime(to_date, "%Y-%m-%d").date()
            schedule_items = [(inv, amt) for inv, amt in schedule_items if inv.payment_due_date <= td]
        except ValueError:
            pass

    # 7) Haftalık gruplama
    groups: Dict[date_type, list] = defaultdict(list)
    for inv, amount in schedule_items:
        groups[inv.payment_due_date].append({
            "vendor_id": inv.vendor_id,
            "hesap_kodu": inv.hesap_kodu,
            "hesap_adi": inv.hesap_adi,
            "evrak_no": inv.evrak_no,
            "transaction_type": inv.transaction_type,
            "invoice_date": inv.date,
            "payment_due_date": inv.payment_due_date,
            "amount": round(amount, 2),
        })

    result = []
    for friday_date in sorted(groups.keys()):
        items = groups[friday_date]
        result.append({
            "friday_date": friday_date,
            "total_amount": round(sum(item["amount"] for item in items), 2),
            "items": items,
        })

    return result
