"""AgencyGroup modeli — acente gruplama tanımları."""

from sqlalchemy import Column, Integer, Numeric, String, DateTime, JSON, text
from sqlalchemy.orm import Mapped

from app.database import Base

# Acente Mahsup & Nakit Akım projeksiyonu için varsayılan vade (gün)
DEFAULT_AGENCY_TERM_DAYS = 30

# Ödeme günü hizalaması: vade (çıkış + term_days) sonrası ödeme hangi güne oturur
PAYMENT_ALIGN_FRIDAY = "friday"        # sonraki ilk Cuma (varsayılan — cariler konvansiyonu)
PAYMENT_ALIGN_MONTH_END = "month_end"  # vadenin düştüğü ayın son günü
PAYMENT_ALIGN_DAY_PREFIX = "day_"      # "day_27" = ayın 27'si (vade günü 27'yi geçtiyse
                                       # ertesi ayın 27'si — ör. Nordic, 2026-08-13)


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
    # Sedna 340.01.* avans hesap kodları (Faz C — acente başına PARA BİRİMİ AYRI hesap
    # olabildiğinden liste: ör. ANEX EUR + ANEX USD; avans mutabakatı kod-öncelikli eşleşir)
    sedna_account_codes: Mapped[list] = Column(JSON, nullable=True)
    # Ciro projeksiyonunda ödeme günü hizalaması (2026-08-13): friday | month_end
    payment_alignment: Mapped[str] = Column(String(10), nullable=False,
                                            server_default=PAYMENT_ALIGN_FRIDAY)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"),
                        onupdate=text("now()"), nullable=False)
