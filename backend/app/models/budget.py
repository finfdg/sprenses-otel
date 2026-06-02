"""Bütçe modelleri — kategori tanımları ve departman bazlı aylık bütçe kayıtları."""

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BudgetCategory(Base):
    __tablename__ = "budget_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)  # "income" or "expense"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__: tuple = (
        UniqueConstraint("name", "type", name="uq_budget_category_name_type"),
    )


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    department_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("budget_categories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_amount: Mapped[float] = mapped_column(Numeric(15, 2), default=0, nullable=False)
    actual_amount: Mapped[float] = mapped_column(Numeric(15, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(5), default="TRY")
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    department = relationship("Department", foreign_keys=[department_id])
    category = relationship("BudgetCategory", foreign_keys=[category_id])

    __table_args__ = (
        UniqueConstraint(
            "department_id", "category_id", "year", "month",
            name="uq_budget_dept_cat_year_month"
        ),
        Index("ix_budgets_year_month", "year", "month"),
    )
