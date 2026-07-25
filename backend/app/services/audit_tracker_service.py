"""Denetim Takip domain servisi — skor motoru, prompt üreteci, bulgu CRUD.

HTTP'siz. Router (`app/routers/system_denetim.py`), onay executor handler'ı ve
otomasyon cron'u (`backend/cron_denetim_auto.py`) AYNI fonksiyonları çağırır —
CLAUDE.md D1-2 ortak-service deseni (router ile executor'ın sessizce ayrışmasını
yapısal olarak engeller).

Skor motoru — neden türetilmiş:
    Denetim raporundaki skorlar statik metindi; bir bulgu kapandığında notun ne
    olduğunu insan hesaplıyordu. Burada `score_current` HİÇBİR YERDE SAKLANMAZ,
    her okumada kapanan bulgulardan yeniden hesaplanır. Bu, FIN-001'in
    (`finance_events.amount_try` hiç tazelenmiyor) hata sınıfının bu modülde
    tekrarlamasını imkânsız kılar.
"""
from datetime import datetime
from typing import List, Optional

import pytz
from sqlalchemy.orm import Session

from app.models.audit_tracker import (
    AuditAutomationConfig,
    AuditDimension,
    AuditFinding,
    AuditFindingRun,
    AuditReport,
)

tz_istanbul = pytz.timezone("Europe/Istanbul")

# Kapanmış sayılan durumlar ve skora katkı oranları
STATUS_WEIGHT = {
    "kapali": 1.0,
    "kismen": 0.5,   # DR-001 gibi "büyük ölçüde kapandı" maddeleri
    "inceleme": 0.0,  # kod hazır ama canlıda değil → puan YOK
    "devam": 0.0,
    "acik": 0.0,
    "iptal": 0.0,
}

# Sıralamada kullanılan risk ağırlığı (yüksek önce)
RISK_RANK = {"kritik": 0, "yuksek": 1, "orta": 2, "dusuk": 3}
EFFORT_RANK = {"S": 0, "M": 1, "L": 2}

RISK_LABEL = {"kritik": "Kritik", "yuksek": "Yüksek", "orta": "Orta", "dusuk": "Düşük"}


# ─── Rapor / yapılandırma erişimi ────────────────────────────

def get_active_report(db: Session) -> Optional[AuditReport]:
    """Panoda gösterilen aktif rapor (en yeni aktif)."""
    return (
        db.query(AuditReport)
        .filter(AuditReport.is_active.is_(True))
        .order_by(AuditReport.report_date.desc(), AuditReport.id.desc())
        .first()
    )


def get_config(db: Session) -> AuditAutomationConfig:
    """Tek-satırlık otomasyon yapılandırması; yoksa varsayılanla oluşturur."""
    cfg = db.query(AuditAutomationConfig).filter(AuditAutomationConfig.id == 1).first()
    if not cfg:
        cfg = AuditAutomationConfig(id=1)
        db.add(cfg)
        db.flush()
    return cfg


def apply_config_update(db: Session, cfg: AuditAutomationConfig, data: dict) -> dict:
    """Yapılandırmayı güncelle, değişen alanları döndür (audit detayı için)."""
    changes = {}
    for field, value in data.items():
        if not hasattr(cfg, field):
            continue
        old = getattr(cfg, field)
        if old != value:
            changes[field] = {"eski": _plain(old), "yeni": _plain(value)}
            setattr(cfg, field, value)
    db.flush()
    return changes


# ─── Skor motoru ─────────────────────────────────────────────

def _weight(status: str) -> float:
    return STATUS_WEIGHT.get(status, 0.0)


def dimension_scores(
    db: Session, report: AuditReport,
) -> List[dict]:
    """23 boyutun güncel/potansiyel skorunu bulgulardan TÜRETİR.

    güncel     = baseline + Σ(kapanan bulgunun score_impact × durum ağırlığı)
    potansiyel = baseline + Σ(TÜM bulguların score_impact'i)   → hepsi kapanırsa
    Her ikisi de `score_target` ve 10 ile sınırlanır: rapordaki 90 gün hedefi
    üst sınırdır, aşılmaz (aksi halde puan etkileri toplamı notu şişirir).
    """
    dims = (
        db.query(AuditDimension)
        .filter(AuditDimension.report_id == report.id)
        .order_by(AuditDimension.no)
        .all()
    )
    findings = (
        db.query(AuditFinding)
        .filter(AuditFinding.report_id == report.id)
        .all()
    )

    by_dim = {}
    for f in findings:
        by_dim.setdefault(f.dimension_no, []).append(f)

    rows = []
    for d in dims:
        items = by_dim.get(d.no, [])
        baseline = float(d.score_baseline)
        target = float(d.score_target)
        ceiling = min(10.0, max(target, baseline))

        applied = sum(float(f.score_impact) * _weight(f.status) for f in items)
        possible = sum(float(f.score_impact) for f in items)

        rows.append({
            "no": d.no,
            "name": d.name,
            "layer": d.layer,
            "score_prev": float(d.score_prev) if d.score_prev is not None else None,
            "score_baseline": round(baseline, 2),
            "score_current": round(min(baseline + applied, ceiling), 2),
            "score_target": round(target, 2),
            "score_potential": round(min(baseline + possible, ceiling), 2),
            "reason": d.reason,
            "open_count": sum(1 for f in items if f.status in ("acik", "devam", "inceleme")),
            "closed_count": sum(1 for f in items if f.status in ("kapali", "kismen")),
            "total_count": len(items),
            "_ceiling": ceiling,
        })
    return rows


def finding_points(db: Session, report: AuditReport, finding: AuditFinding) -> dict:
    """Tek bir bulgunun genel nota (100'lük) katkısı.

    Boyut skoru tavana dayandığında bulgunun marjinal katkısı sıfırlanabilir —
    bu yüzden puan boyut bazında yeniden hesaplanır, `score_impact` doğrudan
    genel nota çevrilmez. Genel not 23 boyutun ortalaması × 10 olduğundan bir
    boyuttaki 1 puan, genel notta 10/23 ≈ 0,43 puan eder.
    """
    dims = {r["no"]: r for r in dimension_scores(db, report)}
    row = dims.get(finding.dimension_no)
    if not row:
        return {"applied": 0.0, "potential": 0.0}

    n = len(dims) or 1
    factor = 10.0 / n

    baseline = row["score_baseline"]
    ceiling = row["_ceiling"]

    # Bu bulgu olmasaydı boyut skoru ne olurdu → farkı bu bulguya yaz
    items = (
        db.query(AuditFinding)
        .filter(
            AuditFinding.report_id == report.id,
            AuditFinding.dimension_no == finding.dimension_no,
        )
        .all()
    )
    applied_all = sum(float(f.score_impact) * _weight(f.status) for f in items)
    applied_wo = applied_all - float(finding.score_impact) * _weight(finding.status)
    applied_delta = (
        min(baseline + applied_all, ceiling) - min(baseline + applied_wo, ceiling)
    )

    # Bu bulgu KAPANSAYDI ne kazanılırdı
    applied_if = applied_wo + float(finding.score_impact)
    potential_delta = (
        min(baseline + applied_if, ceiling) - min(baseline + applied_wo, ceiling)
    )

    return {
        "applied": round(applied_delta * factor, 2),
        "potential": round(potential_delta * factor, 2),
    }


def scoreboard(db: Session, report: AuditReport) -> dict:
    """Genel not paneli — canlı hesaplanmış skorlar + bulgu sayıları."""
    rows = dimension_scores(db, report)
    n = len(rows) or 1

    def _avg(key, rs):
        return round(sum(r[key] for r in rs) / len(rs), 2) if rs else 0.0

    core = [r for r in rows if r["layer"] == "cekirdek"]
    ops = [r for r in rows if r["layer"] == "operasyon"]

    findings = (
        db.query(AuditFinding).filter(AuditFinding.report_id == report.id).all()
    )
    counts = {
        "toplam": len(findings),
        "acik": sum(1 for f in findings if f.status == "acik"),
        "devam": sum(1 for f in findings if f.status == "devam"),
        "inceleme": sum(1 for f in findings if f.status == "inceleme"),
        "kismen": sum(1 for f in findings if f.status == "kismen"),
        "kapali": sum(1 for f in findings if f.status == "kapali"),
        "iptal": sum(1 for f in findings if f.status == "iptal"),
        "kritik_acik": sum(
            1 for f in findings if f.risk == "kritik" and f.status in ("acik", "devam", "inceleme")
        ),
        "yuksek_acik": sum(
            1 for f in findings if f.risk == "yuksek" and f.status in ("acik", "devam", "inceleme")
        ),
        "otomasyon_kuyrugu": sum(
            1 for f in findings
            if f.auto_enabled and f.automatable and f.status in ("acik", "devam")
        ),
    }

    for r in rows:
        r.pop("_ceiling", None)

    return {
        "report_key": report.key,
        "report_title": report.title,
        "report_date": report.report_date,
        "doc_path": report.doc_path,
        "baseline_score": round(sum(r["score_baseline"] for r in rows) / n * 10, 1),
        "current_score": round(sum(r["score_current"] for r in rows) / n * 10, 1),
        "potential_score": round(sum(r["score_potential"] for r in rows) / n * 10, 1),
        "target_score": round(sum(r["score_target"] for r in rows) / n * 10, 1),
        "declared_baseline": float(report.baseline_score) if report.baseline_score else None,
        "declared_target": float(report.target_score) if report.target_score else None,
        "core_avg": _avg("score_current", core),
        "ops_avg": _avg("score_current", ops),
        "counts": counts,
        "dimensions": rows,
    }


# ─── Claude Code prompt üreteci ──────────────────────────────

def build_prompt(db: Session, finding: AuditFinding, report: Optional[AuditReport] = None) -> str:
    """Bulguyu, kullanıcının Claude Code'a birebir yapıştıracağı komuta çevirir.

    Prompt KENDİ KENDİNE YETERLİ olmalıdır: ne yapılacağı, kanıtı, kapanış kriteri
    ve projenin zorunlu kuralları içinde geçer. Otomasyon cron'u da aynı metni
    kullanır — böylece elle çalıştırma ile otomasyon BİREBİR aynı işi yapar.
    """
    if finding.prompt_override:
        return finding.prompt_override

    if report is None:
        report = db.query(AuditReport).filter(AuditReport.id == finding.report_id).first()

    dim = None
    if report:
        dim = (
            db.query(AuditDimension)
            .filter(
                AuditDimension.report_id == report.id,
                AuditDimension.no == finding.dimension_no,
            )
            .first()
        )

    dim_name = dim.name if dim else f"Boyut {finding.dimension_no}"
    doc = report.doc_path if report and report.doc_path else "docs/denetim/"
    risk = RISK_LABEL.get(finding.risk, finding.risk)

    parts = [
        f"# Denetim bulgusu {finding.code} — düzelt ve kapat",
        "",
        f"**Kaynak:** `{doc}` · **Boyut:** {finding.dimension_no} — {dim_name} · "
        f"**Risk:** {risk} · **Efor:** {finding.effort}",
        "",
        "## Sorun",
        finding.title,
        "",
    ]

    if finding.evidence:
        parts += ["## Kanıt (denetimde ölçülen)", finding.evidence, ""]
    if finding.solution:
        parts += ["## Raporun önerdiği çözüm", finding.solution, ""]
    if finding.closure_criteria:
        parts += [
            "## Kapanış kriteri — BU SAĞLANMADAN kapalı sayma",
            finding.closure_criteria,
            "",
        ]

    parts += [
        "## Nasıl çalış",
        "1. Önce kanıtı **doğrula** — bulgu hâlâ geçerli mi? Değilse düzeltme yapma, "
        "neden geçersiz olduğunu kanıtla ve öyle raporla.",
        "2. `CLAUDE.md` kurallarına uy: Türkçe karakterler (ö/ü/ç/ş/ı/ğ/İ), Python 3.9 "
        "(`Optional[X]`, `X | None` yasak), mutasyon uçlarında `require_permission` + "
        "`check_approval` + `log_action`, merkezî sabitler, polling yasağı, "
        "UI'da tasarım sistemi bileşenleri.",
        "3. Değişikliği yaptıktan sonra **testleri koş**: "
        "`cd backend && source venv/bin/activate && "
        "DATABASE_URL=<sprenses_test> python -m pytest tests/ -q`. "
        "Kırmızı test bırakma.",
        "4. Bu bulgu için **regresyon testi yaz** — düzeltmeyi geri alınca testin "
        "kırmızıya döndüğünü fiilen doğrula (sahte-yeşil test yazma).",
        "5. Kapanış kriterini **ölç** ve ölçüm çıktısını yanıtına yapıştır.",
        "6. İlgili modül dokümanını ve `docs/denetim/` içindeki rapor durumunu güncelle.",
        "",
        "## Yanıt formatı",
        "Sonunda şu üç başlığı ver: **Yapılan değişiklikler** (dosya listesi) · "
        "**Kapanış kriteri ölçümü** (komut + çıktı) · **Kalan risk**.",
    ]
    return "\n".join(parts)


# ─── Bulgu CRUD (router + executor ORTAK) ────────────────────

def _plain(value):
    """Audit detayında JSON'a girebilecek sade değer."""
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def create_finding(db: Session, data: dict, report_id: int, actor_id: Optional[int] = None) -> AuditFinding:
    """Yeni bulgu ekle (rapor dışı takip kalemleri için)."""
    payload = dict(data)
    payload.pop("report_id", None)
    finding = AuditFinding(report_id=report_id, **payload)
    db.add(finding)
    db.flush()
    return finding


def apply_finding_update(
    db: Session, finding: AuditFinding, data: dict, actor_id: Optional[int] = None,
) -> dict:
    """Bulguyu güncelle; değişen alanları döndür.

    Durum `kapali`/`kismen`'e geçtiğinde kapanış damgası atılır; geri açılırsa
    damga temizlenir — böylece "kapandı" bilgisi durumla tutarsız kalamaz.
    """
    changes = {}
    for field, value in data.items():
        if not hasattr(finding, field):
            continue
        old = getattr(finding, field)
        if old == value:
            continue
        changes[field] = {"eski": _plain(old), "yeni": _plain(value)}
        setattr(finding, field, value)

    if "status" in changes:
        new_status = data["status"]
        if new_status in ("kapali", "kismen"):
            finding.closed_at = datetime.now(tz_istanbul)
            finding.closed_by = actor_id
        else:
            finding.closed_at = None
            finding.closed_by = None
            finding.closure_note = None

    db.flush()
    return changes


def delete_finding(db: Session, finding: AuditFinding) -> None:
    db.delete(finding)
    db.flush()


# ─── Otomasyon kuyruğu (cron ile ORTAK) ──────────────────────

def next_automation_candidate(db: Session, report: AuditReport, max_attempts: int) -> Optional[AuditFinding]:
    """Sıradaki otomasyon adayını seç.

    Sıra: risk (kritik önce) → efor (S önce) → skor etkisi (yüksek önce) → kod.
    "En yüksek etki / en düşük efor" önce koşar; raporun Hızlı Kazanımlar mantığı.
    """
    candidates = (
        db.query(AuditFinding)
        .filter(
            AuditFinding.report_id == report.id,
            AuditFinding.status.in_(("acik", "devam")),
            AuditFinding.automatable.is_(True),
            AuditFinding.auto_enabled.is_(True),
            AuditFinding.auto_attempts < max_attempts,
        )
        .all()
    )
    if not candidates:
        return None

    candidates.sort(key=lambda f: (
        RISK_RANK.get(f.risk, 9),
        EFFORT_RANK.get(f.effort, 9),
        -float(f.score_impact),
        f.code,
    ))
    return candidates[0]


def start_run(db: Session, finding: AuditFinding, trigger: str, model: str) -> AuditFindingRun:
    """Koşu kaydını aç ve bulguyu 'devam' durumuna al."""
    run = AuditFindingRun(
        finding_id=finding.id,
        trigger=trigger,
        status="calisiyor",
        model=model,
        started_at=datetime.now(tz_istanbul),
    )
    db.add(run)
    finding.status = "devam"
    finding.auto_attempts = (finding.auto_attempts or 0) + 1
    finding.last_run_at = run.started_at
    finding.last_run_status = "calisiyor"
    db.flush()
    return run


def finish_run(db: Session, run: AuditFindingRun, result: dict) -> AuditFindingRun:
    """Koşuyu kapat ve bulgunun durumunu sonuca göre ayarla.

    Durum eşlemesi:
      basarili + deployed  → kapali   (canlıda, kapanış kriteri ölçüldü)
      basarili             → inceleme (kod hazır, canlıda değil)
      basarisiz / atlandi  → acik     (tekrar denenebilir)
      geri_alindi          → acik     (deploy sağlık kontrolünden geçmedi)
    """
    finished = datetime.now(tz_istanbul)
    run.finished_at = finished
    started = run.started_at
    if started is not None:
        if started.tzinfo is None:
            started = tz_istanbul.localize(started)
        run.duration_sec = int((finished - started).total_seconds())

    for field in (
        "status", "branch", "commit_sha", "files_changed", "tests_passed",
        "tests_failed", "deployed", "rolled_back", "cost_usd", "summary",
        "log_excerpt", "error",
    ):
        if field in result and result[field] is not None:
            setattr(run, field, result[field])

    finding = db.query(AuditFinding).filter(AuditFinding.id == run.finding_id).first()
    if finding:
        finding.last_run_at = finished
        finding.last_run_status = run.status
        finding.branch_name = run.branch

        if run.status == "basarili" and run.deployed:
            finding.status = "kapali"
            finding.closed_at = finished
            finding.closure_note = (
                f"Otomasyon ile kapatıldı — koşu #{run.id}, branch {run.branch or '-'}, "
                f"commit {(run.commit_sha or '-')[:8]}"
            )
            finding.verification_output = run.summary
        elif run.status == "basarili":
            finding.status = "inceleme"
            finding.verification_output = run.summary
        else:
            finding.status = "acik"

    db.flush()
    return run
