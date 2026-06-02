"""Cari modülü paylaşılan yardımcı fonksiyonlar ve sabitler."""

import logging
import os

from sqlalchemy.orm import Session

from app.models.budget import BudgetCategory
from app.models.department import Department
from app.models.user import User
from app.schemas.vendor import VendorTransactionResponse

logger = logging.getLogger(__name__)

UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))),
    "uploads", "vendor_statements",
)


def _ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def _build_tx_response(tx, dept_map, cat_map, user_map):
    """VendorTransaction → dict (departman bilgileriyle)."""
    return VendorTransactionResponse(
        id=tx.id,
        vendor_id=tx.vendor_id,
        date=tx.date,
        evrak_no=tx.evrak_no,
        transaction_type=tx.transaction_type,
        fis_no=tx.fis_no,
        description=tx.description,
        borc=float(tx.borc),
        alacak=float(tx.alacak),
        bakiye=float(tx.bakiye) if tx.bakiye is not None else None,
        payment_due_date=tx.payment_due_date,
        match_number=tx.match_number,
        payment_method=tx.payment_method,
        department_id=tx.department_id,
        department_name=dept_map.get(tx.department_id) if tx.department_id else None,
        budget_category_id=tx.budget_category_id,
        budget_category_name=cat_map.get(tx.budget_category_id) if tx.budget_category_id else None,
        dept_status=tx.dept_status,
        dept_assigned_by_name=user_map.get(tx.dept_assigned_by) if tx.dept_assigned_by else None,
        dept_assigned_at=str(tx.dept_assigned_at) if tx.dept_assigned_at else None,
        dept_rejection_note=tx.dept_rejection_note,
    ).model_dump()


def _build_dept_cat_user_maps(db: Session, transactions):
    """İşlem listesi için departman, kategori ve kullanıcı adı map'lerini oluştur."""
    dept_ids = list(set(tx.department_id for tx in transactions if tx.department_id))
    dept_map = {}
    if dept_ids:
        depts = db.query(Department).filter(Department.id.in_(dept_ids)).all()
        dept_map = {d.id: d.name for d in depts}

    cat_ids = list(set(tx.budget_category_id for tx in transactions if tx.budget_category_id))
    cat_map = {}
    if cat_ids:
        cats = db.query(BudgetCategory).filter(BudgetCategory.id.in_(cat_ids)).all()
        cat_map = {c.id: c.name for c in cats}

    assigned_ids = list(set(tx.dept_assigned_by for tx in transactions if tx.dept_assigned_by))
    user_map = {}
    if assigned_ids:
        users = db.query(User).filter(User.id.in_(assigned_ids)).all()
        user_map = {u.id: u.full_name for u in users}

    return dept_map, cat_map, user_map
