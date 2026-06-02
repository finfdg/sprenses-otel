import uuid
from datetime import datetime, timedelta
from typing import Optional

import pytz
from jose import jwt
from passlib.context import CryptContext

from app.config import settings

tz_istanbul = pytz.timezone(settings.timezone)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def generate_session_id() -> str:
    """Yeni oturum kimliği oluştur."""
    return str(uuid.uuid4())


def create_access_token(data: dict, session_id: Optional[str] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(tz_istanbul) + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire})
    if session_id:
        to_encode["session_id"] = session_id
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
