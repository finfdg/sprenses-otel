"""PMS acente adı → muhasebe 120 cari kodu köprüsü.

Kaynak: Sedna PMS `Agency.Name` + `AgencyAccCode.AccCode` (sales import'unda tazelenir).
Kullanım: hak ediş gruplaması — agency_groups.members (PMS adları) → 120 kodları.
"""
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgencyCodeMap(Base):
    __tablename__ = "agency_code_map"
    __table_args__ = (Index("ix_agency_code_map_acc", "acc_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pms_name: Mapped[str] = mapped_column(String(200), unique=True)
    acc_code: Mapped[str] = mapped_column(String(50))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
