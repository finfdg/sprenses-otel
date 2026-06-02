from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class PermissionItem(BaseModel):
    module_id: int
    can_view: bool = False
    can_use: bool = False


class RoleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: List[PermissionItem] = []


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    permissions: Optional[List[PermissionItem]] = None


class PermissionResponse(BaseModel):
    module_id: int
    module_code: str = ""
    module_name: str = ""
    can_view: bool
    can_use: bool

    class Config:
        from_attributes = True


class RoleResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime
    permissions: List[PermissionResponse] = []

    class Config:
        from_attributes = True
