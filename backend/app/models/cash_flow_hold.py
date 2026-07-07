"""CashFlowHold — bir bekleyen nakit akım kaleminin "beklemeye alınmış" durumu.

Kullanıcı, Panel Nakit Akım kartında bir BEKLEYEN (gerçekleşmemiş, vadesi gelmemiş) hareketi
"beklemeye alabilir": kalem nakit akım projeksiyonundan DIŞLANIR ve ayrı "Bekleme Listesi"nde
sarı gösterilir. Öteleme (payment_deferrals) tarihi değiştirir; bekletme ise kalemi tamamen
akım-dışı park eder. TEK tablo — `source_type` + `source_id` doğal anahtarıyla ayrışır (öteleme
deseniyle aynı). ORTAK durum (kullanıcıya özel değil): tüm finans kullanıcıları aynı bekletmeleri görür.

Bekletme YALNIZ future-pending kalemi dışlar (event_date >= bugün ve is_realized=False):
- Vade geçince (event_date < bugün) → dışlama biter, kalem "Vadesi Geçenler"e düşer (doğal filtre).
- Ödenince (is_realized=True) → kalem "Gerçekleşen"e düşer (doğal filtre).
Böylece "vadesi geçince overdue'ya / ödenince realized'a taşınsın" kuralı ekstra kod olmadan sağlanır.
"""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.database import Base


class CashFlowHold(Base):
    """Beklemeye alınmış nakit akım kalemi (doğal anahtar: source_type+source_id)."""

    __tablename__ = "cash_flow_holds"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    source_type = Column(String(30), nullable=False)
    source_id   = Column(BigInteger, nullable=False)

    created_by  = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    note        = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_cash_flow_holds_source"),
        Index("idx_cash_flow_holds_source", "source_type", "source_id"),
    )

    def __repr__(self) -> str:
        return f"<CashFlowHold id={self.id} {self.source_type}/{self.source_id}>"
