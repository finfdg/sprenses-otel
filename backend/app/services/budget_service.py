"""Bütçe domain servis katmanı — kategori + bütçe kaydı CRUD (HTTP'siz).

D1-2 (2026-06-22): Router (butce.py) ve onay executor (_handle_finance_butce) ORTAK çağırır →
router↔executor sapması (sessiz bug) yapısal olarak engellenir.

Kapatılan DRIFT: Router budget create endpoint'i (`upsert_budget`) KOMPOZİT ANAHTAR upsert yapar
(aynı department+category+year+month varsa GÜNCELLE, yoksa EKLE). Executor ise budget'i ENTITY_ID
bazlı insert/update yapıyordu → onaylı budget create AYNI dönem için ÇİFT bütçe oluşturuyor (ya da
UniqueConstraint `uq_budget_dept_cat_year_month` ihlali → IntegrityError). Artık her iki yol da
`upsert_budget()` kompozit-anahtar mantığını kullanır.

Bütçe kayıtları finance_events'e YAZMAZ (planlama verisi, gerçekleşen para hareketi değil) →
service yalnız saf DB mutasyonu yapar; commit ETMEZ (çağıran commit eder).
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.budget import Budget, BudgetCategory


# ── Kategori CRUD ──────────────────────────────────────

def create_category(db: Session, data: dict) -> BudgetCategory:
    """Yeni bütçe kategorisi oluştur (çağıran benzersizlik doğrulamasını yapar)."""
    name = (data.get("name") or "").strip()
    category = BudgetCategory(
        name=name,
        type=data.get("type", "expense"),
        is_active=data.get("is_active", True),
        sort_order=data.get("sort_order", 0),
    )
    db.add(category)
    return category


def apply_category_update(db: Session, category: BudgetCategory, update_data: dict) -> dict:
    """Alanları kategoriye uygula. Döner: uygulanan changes (router audit/validation için)."""
    changes: dict = {}
    if update_data.get("name") is not None:
        name = update_data["name"].strip()
        changes["name"] = name
        category.name = name
    if update_data.get("type") is not None:
        changes["type"] = update_data["type"]
        category.type = update_data["type"]
    if update_data.get("is_active") is not None:
        changes["is_active"] = update_data["is_active"]
        category.is_active = update_data["is_active"]
    if update_data.get("sort_order") is not None:
        changes["sort_order"] = update_data["sort_order"]
        category.sort_order = update_data["sort_order"]
    return changes


def delete_category(db: Session, category: BudgetCategory) -> None:
    """Kategoriyi sil (çağıran kullanım guard'larını — bütçe/cari işlem — önceden kontrol eder)."""
    db.delete(category)


# ── Bütçe kaydı CRUD ───────────────────────────────────

def upsert_budget(
    db: Session,
    department_id: int,
    category_id: int,
    year: int,
    month: int,
    planned_amount: float,
    currency: str,
    notes: Optional[str],
    created_by: Optional[int],
) -> Budget:
    """Bütçe kaydı upsert: aynı dept+kategori+yıl+ay varsa planned_amount güncelle, yoksa oluştur.

    KOMPOZİT ANAHTAR (department_id, category_id, year, month) → çift bütçe oluşmaz
    (`uq_budget_dept_cat_year_month` ile uyumlu). entity_id'ye bakılmaz; kayıt doğal anahtarla bulunur.
    """
    existing = db.query(Budget).filter(
        Budget.department_id == department_id,
        Budget.category_id == category_id,
        Budget.year == year,
        Budget.month == month,
    ).first()
    if existing:
        existing.planned_amount = planned_amount
        if notes is not None:
            existing.notes = notes
        return existing

    new_budget = Budget(
        department_id=department_id,
        category_id=category_id,
        year=year,
        month=month,
        planned_amount=planned_amount,
        actual_amount=0,
        currency=currency,
        notes=notes,
        created_by=created_by,
    )
    db.add(new_budget)
    return new_budget


def delete_budget(db: Session, budget: Budget) -> None:
    db.delete(budget)
