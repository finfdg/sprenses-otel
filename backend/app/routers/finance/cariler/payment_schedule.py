"""Haftalık ödeme planı ve Excel export endpoint'leri."""

from collections import defaultdict
from datetime import date as date_type
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.user import User
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction
from app.schemas.vendor import PaymentScheduleItem, WeeklyPaymentGroup
from app.utils.sync_vendor_fifo import sync_vendor_finance_events
from app.utils.vendor_fifo import _next_friday

router = APIRouter()


# ─── Haftalık Ödeme Planı ────────────────────────────────

@router.get("/payment-schedule")
def get_payment_schedule(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cariler", "view")),
):
    """Haftalık ödeme planını getir — net borç bazlı, FIFO kırpmalı.

    Vadesi geçmiş faturalar otomatik olarak sonraki Cuma'ya kaydırılır.
    Her çağrıda finance_events tablosu da senkronize edilir.
    """
    sync_result = sync_vendor_finance_events(db)
    if sync_result.get("updated") or sync_result.get("created") or sync_result.get("removed"):
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
    from app.utils.vendor_fifo import effective_due_date
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


# ─── Excel Export ────────────────────────────────────────


@router.get("/export/vendors")
def export_vendors_excel(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cariler", "view")),
):
    """Cari listesini Excel olarak indir."""
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    vendors = (
        db.query(
            Vendor.hesap_kodu,
            Vendor.hesap_adi,
            Vendor.payment_days,
            sa_func.coalesce(sa_func.sum(VendorTransaction.borc), 0).label("total_borc"),
            sa_func.coalesce(sa_func.sum(VendorTransaction.alacak), 0).label("total_alacak"),
            sa_func.count(VendorTransaction.id).label("tx_count"),
        )
        .outerjoin(VendorTransaction, VendorTransaction.vendor_id == Vendor.id)
        .group_by(Vendor.id, Vendor.hesap_kodu, Vendor.hesap_adi, Vendor.payment_days)
        .order_by(Vendor.hesap_kodu)
        .all()
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Cariler"

    header_font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="0D9488", end_color="0D9488", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    number_fmt = '#,##0.00'
    red_font = Font(name="Calibri", color="DC2626")
    green_font = Font(name="Calibri", color="059669")

    headers = ["Hesap Kodu", "Hesap Adı", "Vade (Gün)", "Toplam Borç", "Toplam Alacak", "Bakiye", "İşlem Sayısı"]
    col_widths = [18, 45, 12, 18, 18, 18, 14]

    for col, (header, width) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border
        ws.column_dimensions[chr(64 + col)].width = width

    for row_idx, v in enumerate(vendors, 2):
        bakiye = float(v.total_borc) - float(v.total_alacak)
        row_data = [
            v.hesap_kodu, v.hesap_adi, v.payment_days,
            float(v.total_borc), float(v.total_alacak), bakiye, v.tx_count,
        ]
        for col, val in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col, value=val)
            cell.border = thin_border
            if col in (4, 5, 6):
                cell.number_format = number_fmt
            if col == 6 and bakiye < 0:
                cell.font = red_font
            elif col == 6 and bakiye > 0:
                cell.font = green_font

    total_row = len(vendors) + 2
    ws.cell(row=total_row, column=1, value="TOPLAM").font = Font(bold=True)
    for col in (4, 5, 6):
        cell = ws.cell(row=total_row, column=col)
        cell.value = f"=SUM({chr(64+col)}2:{chr(64+col)}{total_row-1})"
        cell.number_format = number_fmt
        cell.font = Font(bold=True)
        cell.border = thin_border

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=cariler.xlsx"},
    )


@router.get("/export/payment-schedule")
def export_payment_schedule_excel(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "view")),
):
    """Ödeme planını Excel olarak indir (net borç bazlı, FIFO kırpmalı)."""
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    schedule_data = get_payment_schedule(db=db, _=current_user)

    flat_rows = []
    for group in schedule_data:
        for item in group["items"]:
            flat_rows.append(item)

    wb = Workbook()
    ws = wb.active
    ws.title = "Ödeme Planı"

    header_font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="EA580C", end_color="EA580C", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    number_fmt = '#,##0.00'
    date_fmt = 'DD.MM.YYYY'

    headers = ["Vade Tarihi", "Hesap Kodu", "Hesap Adı", "Evrak No", "İşlem Tipi", "Fatura Tarihi", "Tutar"]
    col_widths = [14, 18, 45, 16, 14, 14, 18]

    for col, (header, width) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border
        ws.column_dimensions[chr(64 + col)].width = width

    for row_idx, r in enumerate(flat_rows, 2):
        due_date = r.get("payment_due_date", "")
        inv_date = r.get("invoice_date", "")
        try:
            due_date = datetime.strptime(str(due_date), "%Y-%m-%d").date() if due_date else ""
        except (ValueError, TypeError):
            pass
        try:
            inv_date = datetime.strptime(str(inv_date), "%Y-%m-%d").date() if inv_date else ""
        except (ValueError, TypeError):
            pass

        row_data = [
            due_date, r.get("hesap_kodu", ""), r.get("hesap_adi", ""),
            r.get("evrak_no", "") or "", r.get("transaction_type", "") or "",
            inv_date, r.get("amount", 0),
        ]
        for col, val in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col, value=val)
            cell.border = thin_border
            if col in (1, 6):
                cell.number_format = date_fmt
            if col == 7:
                cell.number_format = number_fmt

    total_row = len(flat_rows) + 2
    ws.cell(row=total_row, column=1, value="TOPLAM").font = Font(bold=True)
    cell = ws.cell(row=total_row, column=7)
    cell.value = f"=SUM(G2:G{total_row-1})"
    cell.number_format = number_fmt
    cell.font = Font(bold=True)
    cell.border = thin_border

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=odeme-plani.xlsx"},
    )
