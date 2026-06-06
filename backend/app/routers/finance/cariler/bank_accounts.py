"""Cari banka hesapları (IBAN) — ödeme talimatında kullanılır.

IBAN'lar büyük ölçüde Sedna'nın `dbo.Bank` tablosundan otomatik çekilir (`/sedna-import-ibans`,
bkz. sedna_import.py); bu CRUD elle ekleme/düzenleme (Sedna'da olmayan cariler veya düzeltmeler)
ve varsayılan seçimi içindir. Bir cari → 0..N banka hesabı; biri **varsayılan** (ödeme talimatına
otomatik gelir). Master veri — onaydan muaf (vade günü güncelleme gibi), audit'li, finance.cariler use.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.user import User
from app.models.vendor import Vendor
from app.models.vendor_bank_account import VendorBankAccount
from app.schemas.vendor import (
    VendorBankAccountCreate,
    VendorBankAccountResponse,
    VendorBankAccountUpdate,
)
from app.utils.audit import log_action

logger = logging.getLogger(__name__)
router = APIRouter()


def _norm_iban(s) -> Optional[str]:
    if not s:
        return None
    return "".join(str(s).split()).upper() or None


def _resp(ba: VendorBankAccount) -> dict:
    return VendorBankAccountResponse(
        id=ba.id, vendor_id=ba.vendor_id, bank_name=ba.bank_name, iban=ba.iban,
        account_holder=ba.account_holder, is_default=ba.is_default, sort_order=ba.sort_order,
    ).model_dump()


def _vendor_or_404(db: Session, vendor_id: int) -> Vendor:
    v = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Cari bulunamadı")
    return v


@router.get("/vendors/{vendor_id}/bank-accounts")
def list_bank_accounts(
    vendor_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cariler", "view")),
):
    _vendor_or_404(db, vendor_id)
    rows = (
        db.query(VendorBankAccount)
        .filter(VendorBankAccount.vendor_id == vendor_id)
        .order_by(VendorBankAccount.is_default.desc(), VendorBankAccount.sort_order)
        .all()
    )
    return [_resp(b) for b in rows]


@router.post("/vendors/{vendor_id}/bank-accounts", status_code=status.HTTP_201_CREATED)
def add_bank_account(
    vendor_id: int,
    data: VendorBankAccountCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "use")),
):
    _vendor_or_404(db, vendor_id)
    iban = _norm_iban(data.iban)
    if not iban:
        raise HTTPException(status_code=400, detail="IBAN zorunlu")
    existing = db.query(VendorBankAccount).filter(VendorBankAccount.vendor_id == vendor_id).all()
    if any((e.iban or "").upper() == iban for e in existing):
        raise HTTPException(status_code=409, detail="Bu IBAN bu caride zaten kayıtlı")

    make_default = data.is_default or len(existing) == 0  # ilk hesap otomatik varsayılan
    if make_default:
        for e in existing:
            e.is_default = False
    so = max((e.sort_order for e in existing), default=-1) + 1

    ba = VendorBankAccount(
        vendor_id=vendor_id,
        bank_name=(data.bank_name or "").strip() or None,
        iban=iban,
        account_holder=(data.account_holder or "").strip() or None,
        is_default=make_default,
        sort_order=so,
    )
    db.add(ba)
    db.flush()
    log_action(db, current_user.id, "create", "vendor_bank_account", ba.id,
               f"Cari IBAN eklendi: {iban} (cari #{vendor_id})", get_client_ip(request))
    db.commit()
    db.refresh(ba)
    return _resp(ba)


@router.patch("/vendors/{vendor_id}/bank-accounts/{ba_id}")
def update_bank_account(
    vendor_id: int,
    ba_id: int,
    data: VendorBankAccountUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "use")),
):
    ba = (
        db.query(VendorBankAccount)
        .filter(VendorBankAccount.id == ba_id, VendorBankAccount.vendor_id == vendor_id)
        .first()
    )
    if not ba:
        raise HTTPException(status_code=404, detail="Banka hesabı bulunamadı")

    upd = data.model_dump(exclude_unset=True)
    if "iban" in upd:
        ni = _norm_iban(upd.pop("iban"))
        if not ni:
            raise HTTPException(status_code=400, detail="IBAN zorunlu")
        dup = (
            db.query(VendorBankAccount)
            .filter(
                VendorBankAccount.vendor_id == vendor_id,
                VendorBankAccount.id != ba_id,
                func.upper(VendorBankAccount.iban) == ni,
            )
            .first()
        )
        if dup:
            raise HTTPException(status_code=409, detail="Bu IBAN bu caride zaten kayıtlı")
        ba.iban = ni
    if upd.get("is_default") is True:
        for e in (
            db.query(VendorBankAccount)
            .filter(VendorBankAccount.vendor_id == vendor_id, VendorBankAccount.id != ba_id)
            .all()
        ):
            e.is_default = False
    for k in ("bank_name", "account_holder"):
        if k in upd:
            upd[k] = (upd[k] or "").strip() or None
    for k, v in upd.items():
        setattr(ba, k, v)
    log_action(db, current_user.id, "update", "vendor_bank_account", ba.id,
               f"Cari IBAN güncellendi (cari #{vendor_id})", get_client_ip(request))
    db.commit()
    db.refresh(ba)
    return _resp(ba)


@router.delete("/vendors/{vendor_id}/bank-accounts/{ba_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bank_account(
    vendor_id: int,
    ba_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.cariler", "use")),
):
    ba = (
        db.query(VendorBankAccount)
        .filter(VendorBankAccount.id == ba_id, VendorBankAccount.vendor_id == vendor_id)
        .first()
    )
    if not ba:
        raise HTTPException(status_code=404, detail="Banka hesabı bulunamadı")
    was_default = ba.is_default
    db.delete(ba)
    db.flush()
    if was_default:  # varsayılan silindiyse kalanlardan ilkini varsayılan yap
        nxt = (
            db.query(VendorBankAccount)
            .filter(VendorBankAccount.vendor_id == vendor_id)
            .order_by(VendorBankAccount.sort_order)
            .first()
        )
        if nxt:
            nxt.is_default = True
    log_action(db, current_user.id, "delete", "vendor_bank_account", ba_id,
               f"Cari IBAN silindi (cari #{vendor_id})", get_client_ip(request))
    db.commit()
