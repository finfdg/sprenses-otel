from typing import List, Optional

from pydantic import BaseModel, Field


class TransactionCategoryResponse(BaseModel):
    id: int
    name: str
    color: str
    sort_order: int
    is_active: bool

    class Config:
        from_attributes = True


class TagAssignment(BaseModel):
    category_id: Optional[int] = None
    tag_note: Optional[str] = Field(None, max_length=300)
    vendor_id: Optional[int] = None
    payment_method: Optional[str] = Field(None, max_length=20)


class BulkTagAssignment(BaseModel):
    transaction_ids: List[int]
    category_id: Optional[int] = None
    tag_note: Optional[str] = Field(None, max_length=300)
    vendor_id: Optional[int] = None


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    color: str = Field("gray", max_length=20)
