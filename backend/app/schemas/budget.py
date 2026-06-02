"""Bütçe şemaları — departman, kategori ve bütçe kaydı CRUD."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ─── Department ─────────────────────────────────────────
class DepartmentCreate(BaseModel):
    name: str
    code: str
    manager_id: Optional[int] = None
    is_active: bool = True
    sort_order: int = 0


class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    manager_id: Optional[int] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class DepartmentResponse(BaseModel):
    id: int
    name: str
    code: str
    manager_id: Optional[int]
    manager_name: Optional[str] = None
    is_active: bool
    sort_order: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ─── Budget Category ───────────────────────────────────
class BudgetCategoryCreate(BaseModel):
    name: str
    type: str = Field(..., pattern="^(income|expense)$")
    is_active: bool = True
    sort_order: int = 0


class BudgetCategoryUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class BudgetCategoryResponse(BaseModel):
    id: int
    name: str
    type: str
    is_active: bool
    sort_order: int

    class Config:
        from_attributes = True


# ─── Budget ────────────────────────────────────────────
class BudgetCreate(BaseModel):
    department_id: int
    category_id: int
    year: int
    month: int = Field(..., ge=1, le=12)
    planned_amount: float = 0
    currency: str = "TRY"
    notes: Optional[str] = None


class BudgetBulkItem(BaseModel):
    department_id: int
    category_id: int
    year: int
    month: int = Field(..., ge=1, le=12)
    planned_amount: float = 0
    currency: str = "TRY"


class BudgetBulkCreate(BaseModel):
    items: List[BudgetBulkItem]


class BudgetResponse(BaseModel):
    id: int
    department_id: int
    department_name: Optional[str] = None
    category_id: int
    category_name: Optional[str] = None
    category_type: Optional[str] = None
    year: int
    month: int
    planned_amount: float
    actual_amount: float
    currency: str
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BudgetSummaryItem(BaseModel):
    department_id: int
    department_name: str
    total_planned_income: float = 0
    total_actual_income: float = 0
    total_planned_expense: float = 0
    total_actual_expense: float = 0


class BudgetMonthlySummary(BaseModel):
    month: int
    planned_income: float = 0
    actual_income: float = 0
    planned_expense: float = 0
    actual_expense: float = 0
