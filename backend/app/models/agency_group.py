"""AgencyGroup modeli — acente gruplama tanımları."""

from sqlalchemy import Column, Integer, String, DateTime, JSON, text
from sqlalchemy.orm import Mapped

from app.database import Base


class AgencyGroup(Base):
    """Rezervasyon acentelerini gruplayan tanım tablosu."""

    __tablename__ = "agency_groups"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    name: Mapped[str] = Column(String(100), nullable=False, unique=True)
    members: Mapped[list] = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"),
                        onupdate=text("now()"), nullable=False)
