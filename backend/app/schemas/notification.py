"""Bildirim şemaları — bildirim CRUD ve yanıt modelleri."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: int
    type: str
    title: str
    body: str
    link: Optional[str] = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationUnreadCount(BaseModel):
    count: int


class NotificationMarkRead(BaseModel):
    notification_ids: Optional[List[int]] = None
