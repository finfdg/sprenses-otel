"""Kullanıcı şemaları — giriş, kayıt, CRUD ve yanıt modelleri."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserLogin(BaseModel):
    username: str = Field(max_length=150)
    password: str = Field(max_length=128)


# NOT: UserRegister şeması, public /api/auth/register endpoint'i ile birlikte
# güvenlik nedeniyle kaldırıldı (2026-06-19). Kullanıcı oluşturma için
# UserCreate (admin, system.users:use) kullanılır.


class RoleBrief(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class ModulePermission(BaseModel):
    module_code: str
    module_name: str
    can_view: bool
    can_use: bool


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    first_name: str
    last_name: str
    role_id: int
    role: Optional[RoleBrief] = None
    is_active: bool
    email_verified: bool = False
    email_verified_at: Optional[datetime] = None
    created_at: datetime
    last_online_at: Optional[datetime] = None
    permissions: List[ModulePermission] = []

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    # Token artık HttpOnly cookie ile gönderiliyor, body'de döndürülmüyor
    access_token: str = ""
    token_type: str = "bearer"
    user: UserResponse


class UserCreate(BaseModel):
    username: str = Field(max_length=150)
    email: Optional[str] = Field(default=None, max_length=254)
    password: str = Field(max_length=128)
    first_name: str = Field(max_length=100)
    last_name: str = Field(max_length=100)
    role_id: int
    is_active: bool = True

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Şifre en az 8 karakter olmalıdır")
        return v


class UserUpdate(BaseModel):
    username: Optional[str] = Field(default=None, max_length=150)
    email: Optional[str] = Field(default=None, max_length=254)
    password: Optional[str] = Field(default=None, max_length=128)
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    role_id: Optional[int] = None
    is_active: Optional[bool] = None


class EmailVerifyRequest(BaseModel):
    token: str = Field(max_length=2048)


class PasswordReset(BaseModel):
    new_password: str = Field(max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Şifre en az 8 karakter olmalıdır")
        return v


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Şifre en az 8 karakter olmalıdır")
        return v
