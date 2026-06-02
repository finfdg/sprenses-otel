from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class ModuleCreate(BaseModel):
    name: str
    code: str
    description: Optional[str] = None
    icon: Optional[str] = None
    parent_id: Optional[int] = None
    sort_order: int = 0


class ModuleUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    parent_id: Optional[int] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class ModuleResponse(BaseModel):
    id: int
    name: str
    code: str
    description: Optional[str] = None
    icon: Optional[str] = None
    parent_id: Optional[int] = None
    sort_order: int
    is_active: bool
    created_at: datetime
    children: List["ModuleResponse"] = []

    class Config:
        from_attributes = True


ModuleResponse.model_rebuild()
