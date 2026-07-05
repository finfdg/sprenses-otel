"""AgencyGroup modeli — acente gruplama tanımları."""

from sqlalchemy import Column, Integer, Numeric, String, DateTime, JSON, text
from sqlalchemy.orm import Mapped

from app.database import Base

# Acente Mahsup & Nakit Akım projeksiyonu için varsayılan vade (gün)
DEFAULT_AGENCY_TERM_DAYS = 30


class AgencyGroup(Base):
    """Rezervasyon acentelerini gruplayan tanım tablosu.

    `term_days` ve `kickback_percent` "Acente Mahsup & Nakit Akım" projeksiyon
    modülünün (sales.acente_mahsup) konfigürasyonudur:
    - term_days: acentenin tahsilat vadesi (gün) → nakit akım projeksiyonunda
      ciro bu kadar ileriye kaydırılarak tahsilat ayına yazılır.
    - kickback_percent: yıl sonu ciro primi oranı (%) → tutar = ciro × oran.
    Bu vade, Hak Ediş'in `receivable_terms` (muhasebe 120 alacak yaşlandırması)
    tablosundan BAĞIMSIZDIR — ayrı amaç: burası ileri projeksiyon, orası gerçek
    fatura yaşlandırması.
    """

    __tablename__ = "agency_groups"

    id: Mapped[int] = Column(Integer, primary_key=True, index=True)
    name: Mapped[str] = Column(String(100), nullable=False, unique=True)
    members: Mapped[list] = Column(JSON, nullable=False, default=list)
    term_days: Mapped[int] = Column(Integer, nullable=False, server_default="30")
    kickback_percent: Mapped[float] = Column(Numeric(5, 2), nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"),
                        onupdate=text("now()"), nullable=False)
