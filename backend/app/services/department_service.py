"""Departman domain servis katmanı — CRUD (HTTP'siz).

D1-2 (2026-06-22): Router (departmanlar.py) ve onay executor (_handle_finance_departmanlar) ORTAK
çağırır. Kapatılan drift: executor delete'i guard'sız SOFT (is_active=False) idi; router HARD +
cari-işlem/bütçe guard'lı. Service router'ı birebir yapar (guard'lı HARD).
"""
from sqlalchemy.orm import Session

from app.models.budget import Budget
from app.models.department import Department
from app.models.vendor_transaction import VendorTransaction


def create_department(db: Session, data: dict) -> Department:
    dept = Department(
        name=data.get("name", ""),
        code=data.get("code", ""),
        manager_id=data.get("manager_id"),
        is_active=data.get("is_active", True),
        sort_order=data.get("sort_order", 0),
    )
    db.add(dept)
    return dept


def apply_department_update(db: Session, dept: Department, update_data: dict) -> None:
    for key, value in update_data.items():
        if key.startswith("_"):
            continue
        if hasattr(dept, key):
            setattr(dept, key, value)


def delete_department(db: Session, dept: Department) -> None:
    """HARD delete — bağlı cari işlem/bütçe varsa ValueError (router 400'e çevirir)."""
    vtx_count = db.query(VendorTransaction).filter(VendorTransaction.department_id == dept.id).count()
    if vtx_count > 0:
        raise ValueError(f"Bu departmana ait {vtx_count} cari işlem bulunduğu için silinemez")
    budget_count = db.query(Budget).filter(Budget.department_id == dept.id).count()
    if budget_count > 0:
        raise ValueError(f"Bu departmana ait {budget_count} bütçe kaydı bulunduğu için silinemez")
    db.delete(dept)
