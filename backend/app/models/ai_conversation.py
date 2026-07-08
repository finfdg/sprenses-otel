"""AI asistan konuşma kalıcılığı — kullanıcı sohbetleri + mesajları.

Her kullanıcının geçmiş sohbetleri saklanır ve tekrar açılabilir. Konuşma silinince
mesajları CASCADE ile silinir.
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AiConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True,
    )
    title: Mapped[str] = mapped_column(String(200), server_default="Yeni sohbet")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    messages: Mapped[List["AiMessage"]] = relationship(
        "AiMessage", back_populates="conversation",
        cascade="all, delete-orphan", order_by="AiMessage.id",
    )


class AiMessage(Base):
    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True,
    )
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    conversation: Mapped["AiConversation"] = relationship(
        "AiConversation", back_populates="messages",
    )
