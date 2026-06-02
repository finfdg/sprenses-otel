"""Kalite modülü Pydantic şemaları."""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field

# ─── Şablon Alan Şemaları ─────────────────────────────────────────────


class TemplateFieldCreate(BaseModel):
    label: str = Field(..., max_length=300)
    field_type: str = Field(...)  # text, number, yes_no, select
    unit: Optional[str] = Field(None, max_length=30)
    is_required: bool = True
    is_resource: bool = False
    is_guest_count: bool = False
    is_meter: bool = False
    is_month_end_only: bool = False
    options: Optional[str] = None  # JSON dizisi (select için)
    sort_order: int = 0


class TemplateFieldResponse(BaseModel):
    id: int
    label: str
    field_type: str
    unit: Optional[str] = None
    is_required: bool
    is_resource: bool
    is_guest_count: bool
    is_meter: bool = False
    is_month_end_only: bool = False
    options: Optional[str] = None
    sort_order: int

    class Config:
        from_attributes = True


# ─── Şablon Bölüm Şemaları ───────────────────────────────────────────


class TemplateSectionCreate(BaseModel):
    name: str = Field(..., max_length=200)
    sort_order: int = 0
    fields: List[TemplateFieldCreate] = []


class TemplateSectionResponse(BaseModel):
    id: int
    name: str
    sort_order: int
    fields: List[TemplateFieldResponse] = []

    class Config:
        from_attributes = True


# ─── Şablon Atama Şemaları ───────────────────────────────────────────


class TemplateAssigneeCreate(BaseModel):
    assignment_type: str  # filler / approver
    user_id: Optional[int] = None
    role_id: Optional[int] = None


class TemplateAssigneeResponse(BaseModel):
    id: int
    assignment_type: str
    user_id: Optional[int] = None
    role_id: Optional[int] = None
    user_name: Optional[str] = None
    role_name: Optional[str] = None

    class Config:
        from_attributes = True


# ─── Şablon Ana Şemaları ─────────────────────────────────────────────


class TemplateCreate(BaseModel):
    name: str = Field(..., max_length=200)
    description: Optional[str] = None
    frequency: str = "daily"
    is_active: bool = True
    footer_text: Optional[str] = None
    increase_threshold: Optional[float] = 10.0
    decrease_threshold: Optional[float] = 10.0
    sections: List[TemplateSectionCreate] = []
    assignees: List[TemplateAssigneeCreate] = []


class TemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    frequency: Optional[str] = None
    is_active: Optional[bool] = None
    footer_text: Optional[str] = None
    increase_threshold: Optional[float] = None
    decrease_threshold: Optional[float] = None
    sections: Optional[List[TemplateSectionCreate]] = None
    assignees: Optional[List[TemplateAssigneeCreate]] = None


class TemplateListResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    frequency: str
    is_active: bool
    section_count: int = 0
    field_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class TemplateDetailResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    frequency: str
    is_active: bool
    footer_text: Optional[str] = None
    increase_threshold: Optional[float] = 10.0
    decrease_threshold: Optional[float] = 10.0
    logo_url: Optional[str] = None
    sections: List[TemplateSectionResponse] = []
    assignees: List[TemplateAssigneeResponse] = []
    created_by: Optional[int] = None
    creator_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ─── Form Değer Şemaları ─────────────────────────────────────────────


class FormValueSubmit(BaseModel):
    field_id: int
    value: Optional[str] = None
    corrective_action: Optional[str] = None
    correction_note: Optional[str] = None


class FormValueResponse(BaseModel):
    id: int
    field_id: int
    value: Optional[str] = None
    corrective_action: Optional[str] = None
    correction_note: Optional[str] = None

    class Config:
        from_attributes = True


# ─── Form Ana Şemaları ───────────────────────────────────────────────


class FormCreate(BaseModel):
    """Manuel form oluşturma."""
    template_id: int
    period_date: date


class FormFill(BaseModel):
    """Form değerlerini kaydet."""
    values: List[FormValueSubmit]
    notes: Optional[str] = None


class FormReview(BaseModel):
    """Onayla veya reddet."""
    action: str  # approve / reject
    comment: Optional[str] = None


class FormListResponse(BaseModel):
    id: int
    template_id: int
    template_name: str
    period_date: date
    status: str
    filled_by_name: Optional[str] = None
    submitted_at: Optional[datetime] = None
    reviewed_by_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class FormDetailResponse(BaseModel):
    id: int
    template_id: int
    template_name: str
    period_date: date
    status: str
    filled_by: Optional[int] = None
    filled_by_name: Optional[str] = None
    submitted_at: Optional[datetime] = None
    reviewed_by: Optional[int] = None
    reviewed_by_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_comment: Optional[str] = None
    notes: Optional[str] = None
    sections: List[TemplateSectionResponse] = []
    values: List[FormValueResponse] = []
    previous_values: Optional[List[FormValueResponse]] = None
    comparisons: Optional[dict] = None
    meter_consumptions: Optional[dict] = None
    increase_threshold: Optional[float] = 10.0
    decrease_threshold: Optional[float] = 10.0
    is_month_end: bool = False
    created_at: datetime

    class Config:
        from_attributes = True
