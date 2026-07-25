"""Denetim Takip modelleri — kurumsal kod denetimi bulgularının yaşayan takibi.

Amaç: `docs/denetim/*.md` altındaki denetim raporları statik metindir; bir bulgu kapandığında
rapor elle güncellenir ve skorun ne olduğu insan hesabına kalır. Bu modeller raporu
**veriye** çevirir: her bulgu bir satır, her boyut bir skor taşıyıcı, her otomasyon koşusu
bir kayıt. Böylece "hangi madde düzeldi, genel not kaça çıktı" sorusu hesaplanabilir olur.

Skor modeli — TÜRETİLMİŞ, saklanmaz:
    boyut_güncel = score_baseline + Σ(kapanan bulguların score_impact'i)   [kısmen = %50]
    üst sınır    = score_target (rapordaki 90 gün hedefi) ve 10
    genel not    = ortalama(boyut_güncel) × 10
Saklamak yerine türetmek bilinçli: durum değişince skorun bayatlaması (FIN-001'in
`amount_try` sınıfı hatası) yapısal olarak imkânsız olur.

DB'de saklanan sabit değerler (`status`, `risk`, `effort`, `category`) sonradan
DEĞİŞTİRİLEMEZ — `app/constants.py`'deki sabitlerle birebir tutulur.
"""
from datetime import date as date_type
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class AuditReport(Base):
    """Bir denetim raporu (ör. 2026-07-25 v4). Bulgular ve boyutlar buna asılır."""

    __tablename__ = "audit_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True, index=True)  # 2026-07-25-v4
    title: Mapped[str] = mapped_column(String(200))
    report_date: Mapped[date_type] = mapped_column(Date)
    doc_path: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)  # docs/denetim/...
    # Rapordaki ilan edilmiş notlar — türetilen skorla karşılaştırma için referans
    baseline_score: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)  # 55.0
    target_score: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)  # 72.0
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # panoda gösterilen rapor

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    dimensions: Mapped[list["AuditDimension"]] = relationship(
        "AuditDimension", back_populates="report", cascade="all, delete-orphan",
    )
    findings: Mapped[list["AuditFinding"]] = relationship(
        "AuditFinding", back_populates="report", cascade="all, delete-orphan",
    )


class AuditDimension(Base):
    """Skor panosunun bir boyutu (23 boyut). `score_current` saklanmaz — türetilir."""

    __tablename__ = "audit_dimensions"
    __table_args__ = (
        UniqueConstraint("report_id", "no", name="uq_audit_dimension_report_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("audit_reports.id", ondelete="CASCADE"), index=True,
    )
    no: Mapped[int] = mapped_column(Integer)  # 1..23
    name: Mapped[str] = mapped_column(String(120))
    score_prev: Mapped[Optional[float]] = mapped_column(Numeric(4, 2), nullable=True)  # v3
    score_baseline: Mapped[float] = mapped_column(Numeric(4, 2))  # denetim anındaki v4 skoru
    score_target: Mapped[float] = mapped_column(Numeric(4, 2))  # 90 gün hedefi
    layer: Mapped[str] = mapped_column(String(20))  # cekirdek | operasyon
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    report: Mapped["AuditReport"] = relationship("AuditReport", back_populates="dimensions")


class AuditFinding(Base):
    """Tek bir denetim bulgusu — tablonun satırı, otomasyonun iş kalemi."""

    __tablename__ = "audit_findings"
    __table_args__ = (
        UniqueConstraint("report_id", "code", name="uq_audit_finding_report_code"),
        Index("ix_audit_findings_status", "status"),
        Index("ix_audit_findings_risk", "risk"),
        Index("ix_audit_findings_dimension", "report_id", "dimension_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("audit_reports.id", ondelete="CASCADE"), index=True,
    )
    code: Mapped[str] = mapped_column(String(30))  # FIN-001, DR-002, PERF-03
    title: Mapped[str] = mapped_column(Text)
    dimension_no: Mapped[int] = mapped_column(Integer)  # 1..23 → AuditDimension.no
    risk: Mapped[str] = mapped_column(String(10))  # kritik | yuksek | orta | dusuk
    effort: Mapped[str] = mapped_column(String(2))  # S | M | L
    category: Mapped[str] = mapped_column(String(20))  # kod | altyapi | surec | ...
    status: Mapped[str] = mapped_column(String(12), default="acik")

    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    solution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    closure_criteria: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_section: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    # Kapanınca ilgili boyutun skoruna eklenecek puan (kısmen → yarısı)
    score_impact: Mapped[float] = mapped_column(Numeric(4, 2), default=0.2)

    # ── Otomasyon ──
    # automatable: bir kod ajanı repo içinde yapabilir mi (GitHub ayarı/AWS provizyonu → false)
    automatable: Mapped[bool] = mapped_column(Boolean, default=False)
    # auto_enabled: kullanıcı bu maddeyi otomasyon kuyruğuna soktu mu
    auto_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    prompt_override: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auto_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_run_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    branch_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    # ── Kapanış ──
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    closed_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    closure_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Kapanış kriterinin ÖLÇÜLEN çıktısı — "kapandı" iddiasının kanıtı
    verification_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    report: Mapped["AuditReport"] = relationship("AuditReport", back_populates="findings")
    closer: Mapped[Optional["User"]] = relationship("User")
    runs: Mapped[list["AuditFindingRun"]] = relationship(
        "AuditFindingRun", back_populates="finding",
        cascade="all, delete-orphan", order_by="desc(AuditFindingRun.started_at)",
    )


class AuditFindingRun(Base):
    """Bir bulgu üzerinde yapılan tek otomasyon (veya elle) koşusunun kaydı.

    Otomasyonun ne yaptığının denetlenebilir izi: hangi branch, hangi commit, testler
    geçti mi, canlıya çıktı mı, ne kadara mal oldu.
    """

    __tablename__ = "audit_finding_runs"
    __table_args__ = (
        Index("ix_audit_runs_finding_started", "finding_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("audit_findings.id", ondelete="CASCADE"), index=True,
    )
    trigger: Mapped[str] = mapped_column(String(12), default="otomatik")  # otomatik | elle
    status: Mapped[str] = mapped_column(String(16), default="calisiyor")
    # calisiyor | basarili | basarisiz | atlandi | geri_alindi

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    branch: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    commit_sha: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    files_changed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    tests_passed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tests_failed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    deployed: Mapped[bool] = mapped_column(Boolean, default=False)
    rolled_back: Mapped[bool] = mapped_column(Boolean, default=False)

    model: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(8, 4), nullable=True)

    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    log_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    finding: Mapped["AuditFinding"] = relationship("AuditFinding", back_populates="runs")


class AuditAutomationConfig(Base):
    """Otomasyonun tek-satırlık yapılandırması (id=1). UI'dan yönetilir.

    `enabled` acil durdurma anahtarıdır — cron her koşuda ÖNCE buna bakar, kapalıysa
    hiçbir şey yapmadan çıkar (systemd timer'ı durdurmaya gerek kalmaz).
    """

    __tablename__ = "audit_automation_config"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    interval_hours: Mapped[int] = mapped_column(Integer, default=5)
    model: Mapped[str] = mapped_column(String(40), default="opus")
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    max_budget_usd: Mapped[float] = mapped_column(Numeric(6, 2), default=8.00)
    timeout_min: Mapped[int] = mapped_column(Integer, default=45)
    # Test yeşilse master'a merge + deploy (kullanıcı kararı 2026-07-25)
    auto_deploy: Mapped[bool] = mapped_column(Boolean, default=True)
    # Deploy sonrası /api/health başarısızsa otomatik geri al
    auto_rollback: Mapped[bool] = mapped_column(Boolean, default=True)
    # Bellek bekçisi: MemAvailable + SwapFree bu değerin altındaysa koşu atlanır
    min_free_mb: Mapped[int] = mapped_column(Integer, default=2500)
    notify_inapp: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True)

    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
