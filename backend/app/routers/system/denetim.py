"""Sistem — Denetim Takip: kurumsal denetim bulgularının yaşayan takibi.

Rapor (`docs/denetim/*.md`) statik metindir; bu modül onu veriye çevirir — her bulgu
bir satır, her boyut bir skor taşıyıcı. Bulgu kapandığında genel not YENİDEN HESAPLANIR
(saklanmaz), böylece "hangi madde düzeldi, not kaça çıktı" sorusu ölçülebilir olur.

İzin: `system.denetim` (view = görüntüle, use = durum değiştir / otomasyon yönet).
Mutasyon uçları onay akışından (`check_approval`) ve audit'ten geçer.
"""
import json
import os
import re
import subprocess
import sys
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.approval.approval_check import check_approval
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.audit_tracker import AuditFinding, AuditFindingRun
from app.models.user import User
from app.paths import BACKEND_DIR, CRON_DENETIM_SCRIPT
from app.schemas.audit_tracker import (
    AutomationConfigUpdate,
    FindingCreate,
    FindingUpdate,
)
from app.services import audit_tracker_service as svc
from app.utils.audit import log_action
from app.utils.pagination import page_meta
from app.utils.sql_search import like_pattern

router = APIRouter()

MODULE_CODE = "system.denetim"

# Otomasyon cron'unun mutlak yolu — "şimdi çalıştır" ucu bunu alt süreç olarak başlatır
_BACKEND_DIR = str(BACKEND_DIR)
_CRON_SCRIPT = str(CRON_DENETIM_SCRIPT)


# ─── Yardımcılar ─────────────────────────────────────────────

def _run_dict(run: Optional[AuditFindingRun]) -> Optional[dict]:
    if not run:
        return None
    return {
        "id": run.id,
        "trigger": run.trigger,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration_sec": run.duration_sec,
        "branch": run.branch,
        "commit_sha": run.commit_sha,
        "files_changed": run.files_changed,
        "tests_passed": run.tests_passed,
        "tests_failed": run.tests_failed,
        "deployed": run.deployed,
        "rolled_back": run.rolled_back,
        "model": run.model,
        "cost_usd": float(run.cost_usd) if run.cost_usd is not None else None,
        "summary": run.summary,
        "log_excerpt": run.log_excerpt,
        "error": run.error,
    }


def _build_finding(db: Session, f: AuditFinding, report, dim_names: dict,
                   with_prompt: bool = True) -> dict:
    points = svc.finding_points(db, report, f)
    last_run = (
        db.query(AuditFindingRun)
        .filter(AuditFindingRun.finding_id == f.id)
        .order_by(desc(AuditFindingRun.started_at))
        .first()
    )
    run_count = (
        db.query(AuditFindingRun).filter(AuditFindingRun.finding_id == f.id).count()
    )
    return {
        "id": f.id,
        "code": f.code,
        "title": f.title,
        "dimension_no": f.dimension_no,
        "dimension_name": dim_names.get(f.dimension_no, f"Boyut {f.dimension_no}"),
        "risk": f.risk,
        "effort": f.effort,
        "category": f.category,
        "status": f.status,
        "evidence": f.evidence,
        "solution": f.solution,
        "closure_criteria": f.closure_criteria,
        "source_section": f.source_section,
        "score_impact": float(f.score_impact),
        "applied_points": points["applied"],
        "potential_points": points["potential"],
        "automatable": f.automatable,
        "auto_enabled": f.auto_enabled,
        "auto_attempts": f.auto_attempts or 0,
        "last_run_at": f.last_run_at,
        "last_run_status": f.last_run_status,
        "branch_name": f.branch_name,
        "closed_at": f.closed_at,
        "closed_by_name": f.closer.full_name if f.closer else None,
        "closure_note": f.closure_note,
        "verification_output": f.verification_output,
        "prompt": svc.build_prompt(db, f, report) if with_prompt else "",
        "has_prompt_override": bool(f.prompt_override),
        "run_count": run_count,
        "last_run": _run_dict(last_run),
    }


def _active_report_or_404(db: Session):
    report = svc.get_active_report(db)
    if not report:
        raise HTTPException(status_code=404, detail="Aktif denetim raporu bulunamadı")
    return report


def _dim_names(db: Session, report) -> dict:
    return {
        d["no"]: d["name"] for d in svc.dimension_scores(db, report)
    }


# ─── Skor panosu ─────────────────────────────────────────────

@router.get("/scoreboard")
def get_scoreboard(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(MODULE_CODE, "view")),
):
    """23 boyutun canlı skoru + genel not + bulgu sayıları."""
    report = _active_report_or_404(db)
    return svc.scoreboard(db, report)


# ─── Bulgu listesi ───────────────────────────────────────────

@router.get("/findings")
def list_findings(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(MODULE_CODE, "view")),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status_filter: Optional[str] = Query(
        None, alias="status", pattern="^(acik|devam|inceleme|kismen|kapali|iptal)$",
    ),
    risk: Optional[str] = Query(None, pattern="^(kritik|yuksek|orta|dusuk)$"),
    category: Optional[str] = Query(
        None, pattern="^(kod|altyapi|surec|dokuman|test|guvenlik|veri)$",
    ),
    dimension_no: Optional[int] = Query(None, ge=1, le=23),
    automatable: Optional[bool] = Query(None),
    open_only: bool = Query(False),
    search: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(
        None, pattern="^(code|title|risk|effort|status|score_impact|dimension_no|last_run_at)$",
    ),
    sort_dir: Optional[str] = Query("asc", pattern="^(asc|desc)$"),
):
    """Bulgu listesi — sayfalı, filtreli, sıralanabilir."""
    report = _active_report_or_404(db)
    q = db.query(AuditFinding).filter(AuditFinding.report_id == report.id)

    if status_filter:
        q = q.filter(AuditFinding.status == status_filter)
    if open_only:
        q = q.filter(AuditFinding.status.in_(("acik", "devam", "inceleme")))
    if risk:
        q = q.filter(AuditFinding.risk == risk)
    if category:
        q = q.filter(AuditFinding.category == category)
    if dimension_no:
        q = q.filter(AuditFinding.dimension_no == dimension_no)
    if automatable is not None:
        q = q.filter(AuditFinding.automatable.is_(automatable))
    if search:
        pattern = like_pattern(search)
        q = q.filter(
            AuditFinding.title.ilike(pattern, escape="\\")
            | AuditFinding.code.ilike(pattern, escape="\\")
            | AuditFinding.evidence.ilike(pattern, escape="\\"),
        )

    sort_map = {
        "code": AuditFinding.code,
        "title": AuditFinding.title,
        "risk": AuditFinding.risk,
        "effort": AuditFinding.effort,
        "status": AuditFinding.status,
        "score_impact": AuditFinding.score_impact,
        "dimension_no": AuditFinding.dimension_no,
        "last_run_at": AuditFinding.last_run_at,
    }
    if sort_by and sort_by in sort_map:
        col = sort_map[sort_by]
        order_expr = desc(col) if sort_dir == "desc" else col
        rows = q.order_by(order_expr, AuditFinding.id).all()
    else:
        # Varsayılan: açık maddeler önce, sonra risk, sonra efor (Hızlı Kazanımlar mantığı)
        rows = q.all()
        rows.sort(key=lambda f: (
            0 if f.status in ("acik", "devam", "inceleme") else 1,
            svc.RISK_RANK.get(f.risk, 9),
            svc.EFFORT_RANK.get(f.effort, 9),
            -float(f.score_impact),
            f.code,
        ))

    total = len(rows)
    start = (page - 1) * page_size
    window = rows[start:start + page_size]

    dim_names = _dim_names(db, report)
    items = [_build_finding(db, f, report, dim_names) for f in window]
    return page_meta(items, total, page, page_size)


@router.get("/findings/{finding_id}")
def get_finding(
    finding_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(MODULE_CODE, "view")),
):
    """Tek bulgu + koşu geçmişi."""
    report = _active_report_or_404(db)
    f = db.query(AuditFinding).filter(AuditFinding.id == finding_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Bulgu bulunamadı")

    data = _build_finding(db, f, report, _dim_names(db, report))
    runs = (
        db.query(AuditFindingRun)
        .filter(AuditFindingRun.finding_id == f.id)
        .order_by(desc(AuditFindingRun.started_at))
        .limit(20)
        .all()
    )
    data["runs"] = [_run_dict(r) for r in runs]
    return data


# ─── Bulgu CRUD ──────────────────────────────────────────────

@router.post("/findings", status_code=status.HTTP_201_CREATED)
def create_finding(
    data: FindingCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Rapor dışı bir takip maddesi ekle."""
    report = _active_report_or_404(db)

    approval_resp = check_approval(
        db, MODULE_CODE, 0, current_user.id, "create", data.model_dump(),
    )
    if approval_resp:
        return approval_resp

    exists = (
        db.query(AuditFinding)
        .filter(AuditFinding.report_id == report.id, AuditFinding.code == data.code)
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail=f"'{data.code}' kodu zaten kullanılıyor")

    f = svc.create_finding(db, data.model_dump(), report.id, current_user.id)
    log_action(
        db, current_user.id, "create", "audit_finding", f.id,
        json.dumps({"code": f.code, "risk": f.risk}, ensure_ascii=False),
        get_client_ip(request),
    )
    db.commit()
    db.refresh(f)
    return _build_finding(db, f, report, _dim_names(db, report))


@router.patch("/findings/{finding_id}")
def update_finding(
    finding_id: int,
    data: FindingUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Bulguyu güncelle — durum değişikliği burada skoru da değiştirir."""
    report = _active_report_or_404(db)
    f = db.query(AuditFinding).filter(AuditFinding.id == finding_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Bulgu bulunamadı")

    approval_resp = check_approval(
        db, MODULE_CODE, finding_id, current_user.id, "update",
        data.model_dump(exclude_unset=True),
    )
    if approval_resp:
        return approval_resp

    changes = svc.apply_finding_update(
        db, f, data.model_dump(exclude_unset=True), current_user.id,
    )
    if changes:
        log_action(
            db, current_user.id, "update", "audit_finding", f.id,
            json.dumps({"code": f.code, "degisiklikler": changes}, ensure_ascii=False),
            get_client_ip(request),
        )
        db.commit()
        db.refresh(f)
    return _build_finding(db, f, report, _dim_names(db, report))


@router.delete("/findings/{finding_id}")
def delete_finding(
    finding_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Bulguyu sil (yalnız elle eklenen takip maddeleri için anlamlı)."""
    f = db.query(AuditFinding).filter(AuditFinding.id == finding_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Bulgu bulunamadı")

    approval_resp = check_approval(db, MODULE_CODE, finding_id, current_user.id, "delete", {})
    if approval_resp:
        return approval_resp

    log_action(
        db, current_user.id, "delete", "audit_finding", f.id,
        json.dumps({"code": f.code, "title": f.title[:120]}, ensure_ascii=False),
        get_client_ip(request),
    )
    svc.delete_finding(db, f)
    db.commit()
    return {"detail": "Bulgu silindi"}


# ─── Otomasyon ───────────────────────────────────────────────

@router.get("/config")
def get_config(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(MODULE_CODE, "view")),
):
    """Otomasyon ayarları + sıradaki aday."""
    cfg = svc.get_config(db)
    db.commit()
    report = svc.get_active_report(db)
    nxt = (
        svc.next_automation_candidate(db, report, cfg.max_attempts) if report else None
    )
    return {
        "enabled": cfg.enabled,
        "interval_hours": cfg.interval_hours,
        "model": cfg.model,
        "max_attempts": cfg.max_attempts,
        "max_chain_runs": cfg.max_chain_runs,
        "max_budget_usd": float(cfg.max_budget_usd),
        "timeout_min": cfg.timeout_min,
        "auto_deploy": cfg.auto_deploy,
        "auto_rollback": cfg.auto_rollback,
        "min_free_mb": cfg.min_free_mb,
        "notify_inapp": cfg.notify_inapp,
        "notify_email": cfg.notify_email,
        "last_run_at": cfg.last_run_at,
        "next_candidate": (
            {"id": nxt.id, "code": nxt.code, "title": nxt.title, "risk": nxt.risk}
            if nxt else None
        ),
    }


@router.patch("/config")
def update_config(
    data: AutomationConfigUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Otomasyon ayarlarını güncelle (acil durdurma anahtarı dahil)."""
    payload = data.model_dump(exclude_unset=True)

    approval_resp = check_approval(
        db, MODULE_CODE, 1, current_user.id, "update_config", payload,
    )
    if approval_resp:
        return approval_resp

    cfg = svc.get_config(db)
    changes = svc.apply_config_update(db, cfg, payload)
    if changes:
        log_action(
            db, current_user.id, "update", "audit_automation_config", 1,
            json.dumps(changes, ensure_ascii=False), get_client_ip(request),
        )
    db.commit()
    return {"detail": "Ayarlar güncellendi", "degisiklikler": changes}


@router.post("/findings/{finding_id}/run")
def trigger_run(
    finding_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Bu bulgu için otomasyonu ŞİMDİ başlat (timer'ı beklemeden).

    Cron script'i ayrı bir süreç olarak başlatılır — API isteği beklemez (koşu
    dakikalar sürer, event-loop bloklanmamalı).
    """
    f = db.query(AuditFinding).filter(AuditFinding.id == finding_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Bulgu bulunamadı")
    if not f.automatable:
        raise HTTPException(
            status_code=400,
            detail="Bu bulgu otomasyona uygun değil (repo dışı iş gerektiriyor)",
        )
    if f.status == "devam":
        raise HTTPException(status_code=409, detail="Bu bulgu için bir koşu zaten sürüyor")
    if not os.path.exists(_CRON_SCRIPT):
        raise HTTPException(status_code=503, detail="Otomasyon script'i sunucuda bulunamadı")

    log_action(
        db, current_user.id, "execute", "audit_finding", f.id,
        json.dumps({"code": f.code, "eylem": "elle_otomasyon_baslat"}, ensure_ascii=False),
        get_client_ip(request),
    )
    db.commit()

    # KENDİ cgroup'unda başlat — `subprocess.Popen(start_new_session=True)` YETMEZ:
    # oturumu ayırır ama süreç API'nin cgroup'unda kalır ve systemd'nin varsayılan
    # KillMode=control-group davranışı yüzünden `systemctl restart sprenses-api`
    # koşuyu ortasından öldürür (2026-07-25'te canlıda yaşandı: JOBS-002 koşusu
    # başka bir oturumun API restart'ıyla 37 dakikalık çalışmanın ardından uçtu).
    unit = f"sprenses-denetim-manual-{re.sub(r'[^a-z0-9]+', '-', f.code.lower())}"
    try:
        subprocess.run(  # noqa: S603 — sabit yollar; f.code regex ile temizlendi
            [
                "sudo", "-n", "systemd-run", "--collect", "--unit", unit,
                "--uid=ec2-user",
                "--setenv=TZ=Europe/Istanbul",
                "--setenv=HOME=/home/ec2-user",
                "--working-directory", _BACKEND_DIR,
                sys.executable, _CRON_SCRIPT,
                "--finding", f.code, "--trigger", "elle",
            ],
            check=True, capture_output=True, text=True, timeout=30,
        )
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or "").strip()[:200]
        if "already exists" in detail:
            raise HTTPException(status_code=409, detail="Bu bulgu için bir koşu zaten sürüyor")
        raise HTTPException(status_code=503, detail=f"Otomasyon başlatılamadı: {detail}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=503, detail="Otomasyon başlatılamadı (zaman aşımı)")

    return {"detail": f"{f.code} için otomasyon başlatıldı", "code": f.code, "unit": unit}


@router.get("/runs")
def list_runs(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(MODULE_CODE, "view")),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    """Tüm bulgular üzerindeki otomasyon koşu geçmişi (en yeni önce)."""
    q = (
        db.query(AuditFindingRun, AuditFinding)
        .join(AuditFinding, AuditFinding.id == AuditFindingRun.finding_id)
        .order_by(desc(AuditFindingRun.started_at))
    )
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for run, finding in rows:
        d = _run_dict(run)
        d["finding_code"] = finding.code
        d["finding_title"] = finding.title
        d["finding_id"] = finding.id
        items.append(d)
    return page_meta(items, total, page, page_size)
