from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

# --- Request schemas ---

class ConversationCreate(BaseModel):
    user_id: int
    message: Optional[str] = Field(None, max_length=5000)


class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    member_ids: List[int] = Field(..., max_length=256)
    message: Optional[str] = Field(None, max_length=5000)


class GroupMemberAdd(BaseModel):
    user_ids: List[int] = Field(..., max_length=256)


class GroupNameUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class GroupAdminUpdate(BaseModel):
    is_admin: bool


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)


class MessageEdit(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)


# --- Response schemas ---

class UserBrief(BaseModel):
    id: int
    username: str
    first_name: str
    last_name: str

    class Config:
        from_attributes = True


class GroupMemberBrief(BaseModel):
    id: int
    first_name: str
    last_name: str
    username: str
    is_admin: bool

    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    sender_id: int
    content: str
    message_type: str
    created_at: datetime
    is_edited: bool = False
    edited_at: Optional[datetime] = None
    is_deleted: bool = False
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    sender_name: Optional[str] = None

    class Config:
        from_attributes = True


class MuteUpdate(BaseModel):
    is_muted: bool


class ConversationResponse(BaseModel):
    id: int
    type: str
    name: Optional[str] = None
    other_user: Optional[UserBrief] = None
    members: Optional[List[GroupMemberBrief]] = None
    last_message: Optional[MessageResponse] = None
    unread_count: int = 0
    is_muted: bool = False
    updated_at: datetime

    class Config:
        from_attributes = True


class ConversationDetailResponse(BaseModel):
    id: int
    type: str
    name: Optional[str] = None
    other_user: Optional[UserBrief] = None
    members: Optional[List[GroupMemberBrief]] = None
    messages: List[MessageResponse] = []
    has_more: bool = False
    other_user_last_read_at: Optional[datetime] = None
    created_by: Optional[int] = None

    class Config:
        from_attributes = True


class UnreadCountResponse(BaseModel):
    total_unread: int


class ChatUserResponse(BaseModel):
    id: int
    username: str
    first_name: str
    last_name: str
    role_name: Optional[str] = None
    has_existing_conversation: bool = False
    conversation_id: Optional[int] = None

    class Config:
        from_attributes = True
