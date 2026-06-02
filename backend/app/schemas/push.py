from typing import Optional

from pydantic import BaseModel


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionCreate(BaseModel):
    endpoint: str
    keys: PushKeys
    user_agent: Optional[str] = None


class PushSubscriptionResponse(BaseModel):
    id: int
    endpoint: str
    is_active: bool

    class Config:
        from_attributes = True


class VapidPublicKeyResponse(BaseModel):
    public_key: str
