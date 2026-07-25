"""Denetim Takip şemaları — bulgu, boyut, otomasyon koşusu ve yapılandırma."""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field

# DB'de saklanan sabit değerler — değiştirilmez (bkz. models/audit_tracker.py docstring)
RISK_PATTERN = "^(kritik|yuksek|orta|dusuk)$"
EFFORT_PATTERN = "^(S|M|L)$"
STATUS_PATTERN = "^(acik|devam|inceleme|kismen|kapali|iptal)$"
CATEGORY_PATTERN = "^(kod|altyapi|surec|dokuman|test|guvenlik|veri)$"


class FindingCreate(BaseModel):
    """Elle yeni bulgu ekleme (rapor dışı madde de takip edilebilsin)."""

    code: str = Field(..., min_length=2, max_length=30)
    title: str = Field(..., min_length=3)
    dimension_no: int = Field(..., ge=1, le=23)
    risk: str = Field(..., pattern=RISK_PATTERN)
    effort: str = Field("M", pattern=EFFORT_PATTERN)
    category: str = Field("kod", pattern=CATEGORY_PATTERN)
    status: str = Field("acik", pattern=STATUS_PATTERN)
    evidence: Optional[str] = None
    solution: Optional[str] = None
    closure_criteria: Optional[str] = None
    source_section: Optional[str] = None
    score_impact: float = Field(0.2, ge=0, le=3)
    automatable: bool = False
    auto_enabled: bool = False
    prompt_override: Optional[str] = None


class FindingUpdate(BaseModel):
    """Bulgu güncelleme — tüm alanlar opsiyonel."""

    title: Optional[str] = None
    dimension_no: Optional[int] = Field(None, ge=1, le=23)
    risk: Optional[str] = Field(None, pattern=RISK_PATTERN)
    effort: Optional[str] = Field(None, pattern=EFFORT_PATTERN)
    category: Optional[str] = Field(None, pattern=CATEGORY_PATTERN)
    status: Optional[str] = Field(None, pattern=STATUS_PATTERN)
    evidence: Optional[str] = None
    solution: Optional[str] = None
    closure_criteria: Optional[str] = None
    score_impact: Optional[float] = Field(None, ge=0, le=3)
    automatable: Optional[bool] = None
    auto_enabled: Optional[bool] = None
    prompt_override: Optional[str] = None
    closure_note: Optional[str] = None
    verification_output: Optional[str] = None


class AutomationConfigUpdate(BaseModel):
    """Otomasyon ayarları — 5 saatlik koşunun davranışı."""

    enabled: Optional[bool] = None
    interval_hours: Optional[int] = Field(None, ge=1, le=24)
    model: Optional[str] = Field(None, pattern="^(opus|sonnet|haiku|fable)$")
    max_attempts: Optional[int] = Field(None, ge=1, le=5)
    max_chain_runs: Optional[int] = Field(None, ge=1, le=10)
    max_budget_usd: Optional[float] = Field(None, ge=0.5, le=50)
    timeout_min: Optional[int] = Field(None, ge=5, le=180)
    auto_deploy: Optional[bool] = None
    auto_rollback: Optional[bool] = None
    min_free_mb: Optional[int] = Field(None, ge=500, le=8000)
    notify_inapp: Optional[bool] = None
    notify_email: Optional[bool] = None


class RunResponse(BaseModel):
    """Bir otomasyon koşusunun özeti."""

    id: int
    trigger: str
    status: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    duration_sec: Optional[int] = None
    branch: Optional[str] = None
    commit_sha: Optional[str] = None
    files_changed: Optional[int] = None
    tests_passed: Optional[int] = None
    tests_failed: Optional[int] = None
    deployed: bool = False
    rolled_back: bool = False
    model: Optional[str] = None
    cost_usd: Optional[float] = None
    summary: Optional[str] = None
    log_excerpt: Optional[str] = None
    error: Optional[str] = None


class FindingResponse(BaseModel):
    """Tablo satırı — bulgu + türetilmiş alanlar (prompt, skor etkisi)."""

    id: int
    code: str
    title: str
    dimension_no: int
    dimension_name: str
    risk: str
    effort: str
    category: str
    status: str
    evidence: Optional[str] = None
    solution: Optional[str] = None
    closure_criteria: Optional[str] = None
    source_section: Optional[str] = None
    score_impact: float
    # Bu bulgunun genel nota (100'lük) hâlihazırda kattığı / katacağı puan
    applied_points: float
    potential_points: float
    automatable: bool
    auto_enabled: bool
    auto_attempts: int
    last_run_at: Optional[datetime] = None
    last_run_status: Optional[str] = None
    branch_name: Optional[str] = None
    closed_at: Optional[datetime] = None
    closed_by_name: Optional[str] = None
    closure_note: Optional[str] = None
    verification_output: Optional[str] = None
    # Kullanıcının Claude Code'a kopyalayacağı hazır komut
    prompt: str
    has_prompt_override: bool
    run_count: int
    last_run: Optional[RunResponse] = None


class DimensionResponse(BaseModel):
    """Skor panosu satırı — güncel skor TÜRETİLİR, saklanmaz."""

    no: int
    name: str
    layer: str
    score_prev: Optional[float] = None
    score_baseline: float
    score_current: float
    score_target: float
    reason: Optional[str] = None
    open_count: int
    closed_count: int
    total_count: int
    # Bu boyuttaki açık maddelerin tamamı kapanırsa ulaşılacak skor
    score_potential: float


class ScoreboardResponse(BaseModel):
    """Genel not paneli — raporun ilan ettiği nota karşı canlı hesap."""

    report_key: str
    report_title: str
    report_date: date
    doc_path: Optional[str] = None
    baseline_score: float
    current_score: float
    potential_score: float
    target_score: float
    declared_baseline: Optional[float] = None
    declared_target: Optional[float] = None
    core_avg: float
    ops_avg: float
    counts: dict
    dimensions: List[DimensionResponse]
