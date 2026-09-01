"""AgencyGroup modeli — acente gruplama tanımları."""

import re

from sqlalchemy import JSON, Column, DateTime, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped

from app.database import Base

# Acente Mahsup & Nakit Akım projeksiyonu için varsayılan vade (gün)
DEFAULT_AGENCY_TERM_DAYS = 30

# Ödeme günü hizalaması: vade (çıkış + term_days) sonrası ödeme hangi güne oturur
PAYMENT_ALIGN_FRIDAY = "friday"        # sonraki ilk Cuma (varsayılan — cariler konvansiyonu)
PAYMENT_ALIGN_MONTH_END = "month_end"  # vadenin düştüğü ayın son günü
PAYMENT_ALIGN_DAY_PREFIX = "day_"      # "day_27" = ayın 27'si (vade günü 27'yi geçtiyse
                                       # ertesi ayın 27'si — ör. Nordic, 2026-08-13)
PAYMENT_ALIGN_CHECKIN = "checkin"      # GİRİŞTE öder (POS/havale — ör. Expedia, Münferit;
                                       # 2026-08-14): kalem GÜNLÜK, giriş tarihine yazılır

# Geçerli değer deseni (2026-09-01) — router şeması (pydantic `pattern`) ve
# `agency_group_service.validate_payment_alignment` AYNI kaynağı kullanır. Tek yazım:
# day_1..day_31, öncü sıfır YOK ("day_07" geçersiz) → `_align_due` int() ile tek biçim okur.
PAYMENT_ALIGNMENT_PATTERN = r"^(friday|month_end|checkin|day_([1-9]|[12][0-9]|3[01]))$"
_PAYMENT_ALIGNMENT_RE = re.compile(PAYMENT_ALIGNMENT_PATTERN)


def is_valid_payment_alignment(value) -> bool:
    """`payment_alignment` kabul edilen dört konvansiyondan biri mi (friday | month_end |
    checkin | day_N)? Onay executor yolu pydantic şemasından geçmediği için service de
    bununla doğrular."""
    return isinstance(value, str) and _PAYMENT_ALIGNMENT_RE.match(value) is not None


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
    # Ciro projeksiyonunda ödeme günü hizalaması (2026-08-13): friday | month_end | day_N |
    # checkin — 2026-09-01'den beri API/UI'dan düzenlenir (PATCH /sales/agency-groups/{id},
    # Acente Ayarları modalı); daha önce yalnız SQL ile set edilebiliyordu.
    payment_alignment: Mapped[str] = Column(String(10), nullable=False,
                                            server_default=PAYMENT_ALIGN_FRIDAY)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"),
                        onupdate=text("now()"), nullable=False)
