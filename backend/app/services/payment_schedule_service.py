"""Haftalık cari ödeme planı hesaplayıcı — `cariler/payment_schedule.py`'den BİREBİR çıkarım (2026-09-02).

Yeniden yapılandırma (katman yönü: router → service → model). `get_payment_schedule` endpoint'inin
GÖVDESİ (`compute_payment_schedule`) `app/routers/finance/cariler/payment_schedule.py`'den satırı
satırına, DEĞİŞTİRİLMEDEN taşındı (finansal parmak izi kapısı: eski-kod/yeni-kod 41 değişmez sıfır
fark vermelidir — hiçbir varsayılan, yuvarlama, guard, sıralama anahtarı ya da sorgu sırası
değiştirilmedi; `vendor_fifo.get_payment_schedule` ikiziyle BİRLEŞTİRİLMEDİ — bu kopya ödeme
yasaklısı carileri HARİÇ TUTMAZ ve net borç fazlasını son faturaya 'leftover' satırı olarak ekler).
Tek farklılık: gövdedeki `sync_vendor_finance_events(db)` çağrısı `sync_fn(db)` oldu; `sync_fn`
None ise bu modülün `sync_vendor_finance_events` import'una düşer. Router endpoint'i MODÜL
niteliğini (`sync_fn=sync_vendor_finance_events`) çağrı anında geçirir → `audit_finance_invariants.
_inv_odeme_plani_haftalik` router modülü üzerindeki monkeypatch'i (`ps.sync_vendor_finance_events`)
korumaya devam eder (API-003: okuma sırasında yazma + commit davranışı değişmedi). Fonksiyon içi
lazy import'lar (deferral_service / vendor_fifo.effective_due_date) monkeypatch hedefi + döngü
kırıcı olduğundan lazy bırakıldı. `payment_schedule.py` router'ı `compute_payment_schedule` +
`_next_friday` adlarını geriye uyumluluk için yeniden dışa verir; endpoint ince sarmalayıcıdır.
"""

from collections import defaultdict
from datetime import date as date_type
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.schemas.vendor import PaymentScheduleItem, WeeklyPaymentGroup
from app.services.sync_vendor_fifo import sync_vendor_finance_events
from app.services.vendor_fifo import _next_friday


def compute_payment_schedule(
    db: Session,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    sync_fn=None,
):
    """Haftalık ödeme planını getir — net borç bazlı, FIFO kırpmalı.

    Vadesi geçmiş faturalar otomatik olarak sonraki Cuma'ya kaydırılır.
    Her çağrıda finance_events tablosu da senkronize edilir.

    `sync_fn`: finance_events senkron fonksiyonu (varsayılan `sync_vendor_finance_events`);
    router modül niteliğini geçirir ki parmak izi ölçümündeki monkeypatch etkili kalsın.
    """
    if sync_fn is None:
        sync_fn = sync_vendor_finance_events
    sync_result = sync_fn(db)
    if (sync_result.get("updated") or sync_result.get("created") or sync_result.get("removed")
            or sync_result.get("recurring_synced")):
        db.commit()

    # 1) Her carinin net borcunu ve vade gün sayısını çek
    vendor_balance_rows = (
        db.query(
            VendorTransaction.vendor_id,
            sa_func.coalesce(sa_func.sum(VendorTransaction.borc), 0).label("total_borc"),
            sa_func.coalesce(sa_func.sum(VendorTransaction.alacak), 0).label("total_alacak"),
        )
        .group_by(VendorTransaction.vendor_id)
        .all()
    )

    vendor_net_debt: dict = {}
    for row in vendor_balance_rows:
        bakiye = float(row.total_borc) - float(row.total_alacak)
        if bakiye < 0:
            vendor_net_debt[row.vendor_id] = abs(bakiye)

    if not vendor_net_debt:
        return []

    vendor_info = {
        v.id: v.payment_days
        for v in db.query(Vendor.id, Vendor.payment_days)
        .filter(Vendor.id.in_(list(vendor_net_debt.keys())))
        .all()
    }

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
    class InvoiceRow:
        """Fatura satırını temsil eden yardımcı sınıf."""
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

    invoice_rows = []
    for row in rows:
        if row.payment_due_date:
            invoice_rows.append(InvoiceRow(row))
        else:
            pay_days = vendor_info.get(row.vendor_id, 90)
            if row.date:
                raw_due = row.date + timedelta(days=pay_days)
                due = _next_friday(raw_due)
                invoice_rows.append(InvoiceRow(row, due))

    # 4) FIFO: Her cari için en eski faturadan başla, ödemeleri düş
    vendor_invoices: dict = defaultdict(list)
    for inv in invoice_rows:
        if inv.payment_due_date:
            vendor_invoices[inv.vendor_id].append(inv)

    schedule_items = []
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
    from app.services.vendor_fifo import effective_due_date
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
    groups: dict = defaultdict(list)
    for inv, amount in schedule_items:
        groups[inv.payment_due_date].append(PaymentScheduleItem(
            vendor_id=inv.vendor_id,
            hesap_kodu=inv.hesap_kodu,
            hesap_adi=inv.hesap_adi,
            evrak_no=inv.evrak_no,
            transaction_type=inv.transaction_type,
            invoice_date=inv.date,
            payment_due_date=inv.payment_due_date,
            amount=round(amount, 2),
        ))

    result = []
    for friday_date in sorted(groups.keys()):
        items = groups[friday_date]
        result.append(WeeklyPaymentGroup(
            friday_date=friday_date,
            total_amount=round(sum(item.amount for item in items), 2),
            items=[item.model_dump() for item in items],
        ).model_dump())

    return result
