"""Onay Akışı modelleri — modül bazlı, rol tabanlı iş akışı onay sistemi."""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base

# --- Sabitler ---
APPROVER_TYPE_USER = "user"
APPROVER_TYPE_ROLE = "role"
APPROVER_TYPE_DEPT_MANAGER = "department_manager"
APPROVER_TYPES = [APPROVER_TYPE_USER, APPROVER_TYPE_ROLE, APPROVER_TYPE_DEPT_MANAGER]

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_RETURNED = "returned"
STATUS_CANCELLED = "cancelled"
ALL_STATUSES = [STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED, STATUS_RETURNED, STATUS_CANCELLED]

ACTION_APPROVE = "approve"
ACTION_REJECT = "reject"
ACTION_RETURN = "return"
ACTION_CANCEL = "cancel"
ACTION_RESUBMIT = "resubmit"
ACTION_SUBMIT = "submit"
ALL_ACTIONS = [ACTION_APPROVE, ACTION_REJECT, ACTION_RETURN, ACTION_CANCEL, ACTION_RESUBMIT, ACTION_SUBMIT]

# İşlem türleri
ACTION_TYPE_CREATE = "create"
ACTION_TYPE_UPDATE = "update"
ACTION_TYPE_DELETE = "delete"
ALL_ACTION_TYPES = [ACTION_TYPE_CREATE, ACTION_TYPE_UPDATE, ACTION_TYPE_DELETE]


class ApprovalWorkflow(Base):
    """Onay iş akışı tanımı — hangi modülde, hangi roller için onay gerektiğini belirler."""
    __tablename__ = "approval_workflows"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, unique=True)
    entity_type = Column(String(50), nullable=True)  # Geriye uyumluluk — yeni kayıtlarda kullanılmaz
    module_id = Column(Integer, ForeignKey("modules.id", ondelete="SET NULL"), nullable=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    conditions_json = Column(Text, nullable=True)

    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # İlişkiler
    module = relationship("Module", foreign_keys=[module_id])
    steps = relationship("ApprovalWorkflowStep", back_populates="workflow", cascade="all, delete-orphan",
                         order_by="ApprovalWorkflowStep.step_number")
    requestor_roles = relationship("ApprovalWorkflowRequestorRole", back_populates="workflow",
                                   cascade="all, delete-orphan")
    approver_roles = relationship("ApprovalWorkflowApproverRole", back_populates="workflow",
                                  cascade="all, delete-orphan")
    requests = relationship("ApprovalRequest", back_populates="workflow")
    creator = relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        Index("ix_aw_entity_type", "entity_type"),
        Index("ix_aw_active", "is_active"),
        Index("ix_aw_module", "module_id"),
    )


class ApprovalWorkflowRequestorRole(Base):
    """Onay akışında talep eden roller — bu rollerdeki kullanıcıların işlemleri onaya tabi."""
    __tablename__ = "approval_workflow_requestor_roles"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("approval_workflows.id", ondelete="CASCADE"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)

    workflow = relationship("ApprovalWorkflow", back_populates="requestor_roles")
    role = relationship("Role", foreign_keys=[role_id])

    __table_args__ = (
        UniqueConstraint("workflow_id", "role_id", name="uq_awrr_workflow_role"),
        Index("ix_awrr_workflow", "workflow_id"),
    )


class ApprovalWorkflowApproverRole(Base):
    """Onay akışında onay veren roller — bu rollerdeki kullanıcılar onay/red verebilir."""
    __tablename__ = "approval_workflow_approver_roles"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("approval_workflows.id", ondelete="CASCADE"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)

    workflow = relationship("ApprovalWorkflow", back_populates="approver_roles")
    role = relationship("Role", foreign_keys=[role_id])

    __table_args__ = (
        UniqueConstraint("workflow_id", "role_id", name="uq_awar_workflow_role"),
        Index("ix_awar_workflow", "workflow_id"),
    )


class ApprovalWorkflowStep(Base):
    """Onay iş akışı adımı — sıralı onaycı tanımı."""
    __tablename__ = "approval_workflow_steps"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("approval_workflows.id", ondelete="CASCADE"), nullable=False)
    step_number = Column(SmallInteger, nullable=False)

    approver_type = Column(String(20), nullable=False)
    approver_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approver_role_id = Column(Integer, ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    approver_dept_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # İlişkiler
    workflow = relationship("ApprovalWorkflow", back_populates="steps")
    approver_user = relationship("User", foreign_keys=[approver_user_id])
    approver_role = relationship("Role", foreign_keys=[approver_role_id])
    approver_dept = relationship("Department", foreign_keys=[approver_dept_id])

    __table_args__ = (
        UniqueConstraint("workflow_id", "step_number", name="uq_aws_workflow_step"),
        Index("ix_aws_workflow", "workflow_id"),
    )


class ApprovalRequest(Base):
    """Onay talebi — belirli bir kayıt için oluşturulan onay süreci."""
    __tablename__ = "approval_requests"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("approval_workflows.id", ondelete="SET NULL"), nullable=True)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=False)
    module_code = Column(String(50), nullable=True)
    action_type = Column(String(10), nullable=True)  # create, update, delete
    payload_json = Column(Text, nullable=True)  # Bekletilen değişiklik verisi

    status = Column(String(20), nullable=False, default=STATUS_PENDING)
    current_step = Column(SmallInteger, nullable=False, default=1)
    total_steps = Column(SmallInteger, nullable=False, default=1)

    requested_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    requested_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    completed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # İlişkiler
    workflow = relationship("ApprovalWorkflow", back_populates="requests")
    requester = relationship("User", foreign_keys=[requested_by])
    completer = relationship("User", foreign_keys=[completed_by])
    logs = relationship("ApprovalRequestLog", back_populates="request", cascade="all, delete-orphan",
                        order_by="ApprovalRequestLog.created_at")

    __table_args__ = (
        Index("ix_ar_entity", "entity_type", "entity_id"),
        Index("ix_ar_status", "status"),
        Index("ix_ar_requested_by", "requested_by"),
        Index("ix_ar_workflow", "workflow_id"),
    )


class ApprovalRequestLog(Base):
    """Onay talebi geçmişi — her adım ve aksiyonun kaydı."""
    __tablename__ = "approval_request_logs"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False)
    step_number = Column(SmallInteger, nullable=False)
    action = Column(String(20), nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # İlişkiler
    request = relationship("ApprovalRequest", back_populates="logs")
    actor = relationship("User", foreign_keys=[actor_id])

    __table_args__ = (
        Index("ix_arl_request", "request_id"),
        Index("ix_arl_actor", "actor_id"),
    )
