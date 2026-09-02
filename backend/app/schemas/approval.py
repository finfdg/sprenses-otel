"""Onay Akışı şemaları."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

# --- Yardımcı şemalar ---

class RoleSummary(BaseModel):
    id: int
    name: str



# --- Workflow Step (geriye uyumluluk) ---




# --- Workflow ---

class WorkflowCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    module_id: int
    description: Optional[str] = None
    is_active: bool = True
    conditions_json: Optional[str] = None
    requestor_role_ids: List[int] = Field(..., min_length=1)
    approver_role_ids: List[int] = Field(..., min_length=1)


class WorkflowUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    conditions_json: Optional[str] = None
    requestor_role_ids: Optional[List[int]] = None
    approver_role_ids: Optional[List[int]] = None


class WorkflowResponse(BaseModel):
    id: int
    name: str
    module_id: Optional[int] = None
    module_code: Optional[str] = None
    module_name: Optional[str] = None
    description: Optional[str] = None
    is_active: bool
    conditions_json: Optional[str] = None
    requestor_roles: List[RoleSummary] = []
    approver_roles: List[RoleSummary] = []
    created_by_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# --- Approval Request ---

class ApprovalAction(BaseModel):
    note: Optional[str] = None


class ApprovalRejectAction(BaseModel):
    note: str = Field(..., min_length=1)


class RequestLogResponse(BaseModel):
    id: int
    step_number: int
    action: str
    actor_id: Optional[int] = None
    actor_name: Optional[str] = None
    note: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ApprovalRequestResponse(BaseModel):
    id: int
    workflow_id: Optional[int] = None
    workflow_name: Optional[str] = None
    entity_type: str
    entity_id: int
    entity_summary: Optional[str] = None
    module_code: Optional[str] = None
    action_type: Optional[str] = None
    payload_json: Optional[str] = None
    status: str
    current_step: int
    total_steps: int
    requested_by: Optional[int] = None
    requested_by_name: Optional[str] = None
    requested_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    completed_by_name: Optional[str] = None
    current_step_approver_name: Optional[str] = None
    logs: List[RequestLogResponse] = []

    class Config:
        from_attributes = True


class TriggerApprovalRequest(BaseModel):
    entity_type: str
    entity_id: int
    context_data: Optional[dict] = None
