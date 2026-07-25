#!/usr/bin/env python3
"""Denetim otomasyonu — 5 saatte bir açık bir denetim bulgusunu Claude Code'a düzelttirir.

AKIŞ
    1.  Kilit (flock) + acil durdurma anahtarı + bellek bekçisi
    2.  Sıradaki adayı seç (risk → efor → skor etkisi)
    3.  İzole git worktree aç (canlı çalışma ağacına DOKUNULMAZ)
    4.  `claude -p` headless çalıştır (izole dizinde, bütçe + zaman aşımı sınırlı)
    5.  Değişikliği commit et, TÜM test takımını koş
    6.  Test yeşilse master'a merge + deploy (kullanıcı kararı 2026-07-25)
    7.  Deploy sonrası /api/health doğrula — kırmızıysa OTOMATİK GERİ AL
    8.  Sonucu `audit_finding_runs`'a yaz, izinli kullanıcılara bildir

OTOMATİK DEPLOY'DAN MUAF TUTULAN DEĞİŞİKLİKLER (bilinçli — geri alınamaz/kendini vurur):
    · yeni alembic migration'ı  → üretim şeması gözetimsiz değiştirilmez
    · bu script veya systemd birimleri → otomasyon kendi ayağını kesemez
    · .env / kimlik / güvenlik yapılandırması
    Bu durumlarda kod branch'te kalır, bulgu "inceleme" durumuna geçer ve bildirim gider.

GÜVENLİK: `claude` alt süreci izole bir worktree'de koşar; kilit sayesinde aynı anda
tek koşu olur; bütçe (`--max-budget-usd`) ve zaman aşımı zorunludur. Bulgu metinleri
prompt'a gömülür — bu metinler yalnız yetkili kullanıcıların yazabildiği DB alanlarıdır.

Kullanım:
    python cron_denetim_auto.py                      # sıradaki adayı işle (timer bunu çağırır)
    python cron_denetim_auto.py --finding FIN-001    # belirli bulguyu işle
    python cron_denetim_auto.py --trigger elle       # elle tetikleme (kapalıyken de koşar)
    python cron_denetim_auto.py --dry-run            # yalnız aday seçimini göster
"""
import argparse
import fcntl
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal  # noqa: E402
from app.services import audit_tracker_service as svc  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [denetim-auto] %(message)s",
)
logger = logging.getLogger(__name__)

REPO_DIR = os.path.dirname(os.path.abspath(__file__)).rsplit("/backend", 1)[0]
WORKTREE_ROOT = "/home/ec2-user/otel-denetim"
LOCK_FILE = "/tmp/sprenses-denetim-auto.lock"
HEALTH_URL = "http://127.0.0.1:8001/api/health"
CLAUDE_BIN = "/usr/bin/claude"

# Otomatik deploy'u bloklayan yol desenleri (yukarıdaki muafiyet listesi)
DEPLOY_BLOCKERS = (
    "backend/alembic/versions/",
    "backend/cron_denetim_auto.py",
    "scripts/systemd/",
    ".env",
    ".claude/settings.json",
    "scripts/claude-guard-secrets.sh",
)


# ─── Ön koşullar ─────────────────────────────────────────────

def _acquire_lock():
    """Tek koşu garantisi. Kilit doluysa None döner (bu koşu atlanır)."""
    fh = open(LOCK_FILE, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    return fh


def _memory_headroom_mb() -> int:
    """MemAvailable + SwapFree (MB) — deploy-frontend.sh ile aynı bekçi mantığı."""
    values = {}
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith(("MemAvailable:", "SwapFree:")):
                key, val = line.split(":", 1)
                values[key] = int(val.strip().split()[0]) // 1024
    return values.get("MemAvailable", 0) + values.get("SwapFree", 0)


def _looks_secret(path: str) -> bool:
    """Commit'i engelleyen hassas dosya deseni (claude-guard-secrets.sh ile aynı ruh)."""
    low = path.lower()
    if low.endswith((".env", ".pem", ".key", ".p12", ".pfx", ".crt")):
        return True
    base = os.path.basename(low)
    return base.startswith(".env") or "credentials" in base or "secret" in base


def _log_error_row(source: str, message: str, detail: str = "") -> None:
    """Otomasyonun kendi hatasını error_logs'a yaz (Sistem ▸ Hata Logları'nda görünsün)."""
    try:
        from app.models.error_log import ErrorLog
        db = SessionLocal()
        try:
            db.add(ErrorLog(level="CRITICAL", source=source,
                            message=message[:2000], traceback=detail[:20000]))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning("error_logs'a yazılamadı: %s", e)


def _git(args, cwd=REPO_DIR, check=True, timeout=120):
    res = subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=timeout,
    )
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} başarısız: {res.stderr.strip()}")
    return res.stdout.strip()


# ─── Worktree yönetimi ───────────────────────────────────────

def _prepare_worktree(code: str) -> tuple:
    """İzole worktree + branch oluştur. (yol, branch) döner.

    venv symlink + .env kopyası gerekir: worktree'de backend testleri ancak bunlarla
    koşar. İkisi de `.git/info/exclude`'a yazılır — `.gitignore` worktree'de
    yakalamıyor (2026-07 worktree kurulum dersi).
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", code.lower()).strip("-")
    branch = f"denetim/{slug}-{stamp}"
    path = os.path.join(WORKTREE_ROOT, slug)

    if os.path.exists(path):
        _cleanup_worktree(path)
    os.makedirs(WORKTREE_ROOT, exist_ok=True)

    _git(["worktree", "add", "-b", branch, path, "master"])

    # venv symlink + .env kopyası
    src_venv = os.path.join(REPO_DIR, "backend", "venv")
    dst_venv = os.path.join(path, "backend", "venv")
    if os.path.exists(src_venv) and not os.path.exists(dst_venv):
        os.symlink(src_venv, dst_venv)
    src_env = os.path.join(REPO_DIR, "backend", ".env")
    dst_env = os.path.join(path, "backend", ".env")
    if os.path.exists(src_env) and not os.path.exists(dst_env):
        shutil.copy2(src_env, dst_env)

    exclude = os.path.join(path, ".git")
    if os.path.isfile(exclude):  # worktree'de .git bir dosyadır → gerçek dizini bul
        with open(exclude) as f:
            gitdir = f.read().strip().split("gitdir:", 1)[-1].strip()
        info_dir = os.path.join(gitdir, "info")
        os.makedirs(info_dir, exist_ok=True)
        with open(os.path.join(info_dir, "exclude"), "a") as f:
            f.write("\nbackend/venv\nbackend/.env\n")

    return path, branch


def _cleanup_worktree(path: str) -> None:
    try:
        _git(["worktree", "remove", "--force", path], check=False)
    except Exception as e:
        logger.warning("worktree kaldırılamadı: %s", e)
    if os.path.exists(path):
        shutil.rmtree(path, ignore_errors=True)
    _git(["worktree", "prune"], check=False)


# ─── Claude çalıştırma ───────────────────────────────────────

def _run_claude(prompt: str, cwd: str, model: str, budget: float, timeout_min: int) -> dict:
    """Headless Claude Code koşusu. {ok, text, cost_usd, error} döner.

    `--setting-sources user`: proje `.claude/settings.json`'ı YÜKLENMEZ. Sebep, oradaki
    Stop hook'unun `cd /home/ec2-user/otel` ile CANLI çalışma ağacını commit'leyip
    GitHub'a push etmesidir — otomasyon worktree'de çalışırken bu istenmeyen bir yan
    etkidir (üstelik depo public, SEC-001). CLAUDE.md kuralları prompt'ta ve
    worktree'deki CLAUDE.md dosyasında zaten mevcut.
    """
    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--model", model,
        "--permission-mode", "bypassPermissions",
        "--output-format", "json",
        "--max-budget-usd", str(budget),
        "--setting-sources", "user",
        "--no-session-persistence",
    ]
    env = dict(os.environ, TZ="Europe/Istanbul")
    try:
        res = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            timeout=timeout_min * 60, env=env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "text": "", "cost_usd": None,
                "error": f"Zaman aşımı ({timeout_min} dk)"}

    raw = res.stdout.strip()
    payload = {}
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"result": raw}

    text = payload.get("result") or raw
    cost = payload.get("total_cost_usd")
    if res.returncode != 0 and not text:
        return {"ok": False, "text": "", "cost_usd": cost,
                "error": (res.stderr or "claude çıkış kodu %d" % res.returncode)[:4000]}
    return {"ok": True, "text": text or "", "cost_usd": cost, "error": None}


# ─── Test + deploy ───────────────────────────────────────────

def _test_db_url() -> str:
    """Testler DAİMA `_test` DB'sinde koşar (conftest.py bunu zorunlu kılar)."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        env_path = os.path.join(REPO_DIR, "backend", ".env")
        with open(env_path) as f:
            for line in f:
                if line.startswith("DATABASE_URL="):
                    url = line.split("=", 1)[1].strip()
                    break
    if url.endswith("_test"):
        return url
    return re.sub(r"/([^/?]+)$", r"/\1_test", url)


def _run_tests(worktree: str) -> dict:
    """Worktree'de tüm backend takımını koş. {passed, failed, ok, tail} döner."""
    venv_py = os.path.join(worktree, "backend", "venv", "bin", "python")
    env = dict(os.environ, DATABASE_URL=_test_db_url(), TZ="Europe/Istanbul")
    try:
        res = subprocess.run(
            [venv_py, "-m", "pytest", "tests/", "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=os.path.join(worktree, "backend"),
            capture_output=True, text=True, timeout=45 * 60, env=env,
        )
    except subprocess.TimeoutExpired:
        return {"passed": None, "failed": None, "ok": False, "tail": "Test zaman aşımı (45 dk)"}

    out = (res.stdout or "") + (res.stderr or "")
    passed = failed = None
    m = re.search(r"(\d+) passed", out)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) failed", out)
    failed = int(m.group(1)) if m else 0
    m = re.search(r"(\d+) error", out)
    if m:
        failed = (failed or 0) + int(m.group(1))

    return {
        "passed": passed,
        "failed": failed,
        "ok": res.returncode == 0 and not failed,
        "tail": out[-4000:],
    }


def _health_ok(attempts: int = 20, delay_sec: int = 3) -> bool:
    """`/api/health` 200 dönene kadar dene (açılış payı ile).

    `systemctl restart` systemd birim başlatılınca döner ama uvicorn'un dinlemeye
    başlaması birkaç saniye daha sürer. Tek seferlik kontrol bu boşlukta HER ZAMAN
    başarısız olur ve sağlıklı bir deploy'u geri aldırır — 2026-07-25'te canlıda
    yaşandı (DOC-D01 koşusu: 2007 test yeşil, deploy iyi, yine de geri alındı).
    """
    for i in range(attempts):
        try:
            res = subprocess.run(
                ["curl", "-fsS", "-m", "5", "-o", "/dev/null", "-w", "%{http_code}",
                 HEALTH_URL],
                capture_output=True, text=True, timeout=10,
            )
            if res.stdout.strip() == "200":
                if i:
                    logger.info("Sağlık kontrolü %d. denemede geçti", i + 1)
                return True
        except Exception:
            pass
        if i < attempts - 1:
            time.sleep(delay_sec)
    logger.error("Sağlık kontrolü %d denemede 200 döndürmedi", attempts)
    return False


def _needs_api_restart(changed_files: list) -> bool:
    """Yalnız çalışan uygulamayı etkileyen backend değişikliği restart gerektirir.

    `backend/tests/` altındaki dosyalar üretim sürecine yüklenmez → gereksiz restart
    (ve gereksiz kesinti riski) doğurmasın.
    """
    return any(
        f.startswith("backend/") and not f.startswith("backend/tests/")
        for f in changed_files
    )


def _deploy(changed_files: list) -> list:
    """Değişen dosyalara göre gereken deploy adımlarını koş; yapılanları döndür."""
    steps = []
    if _needs_api_restart(changed_files):
        subprocess.run(
            ["sudo", "systemctl", "restart", "sprenses-api.service"],
            check=True, timeout=120,
        )
        steps.append("backend restart")
    if any(f.startswith("frontend/") for f in changed_files):
        subprocess.run(
            [os.path.join(REPO_DIR, "scripts", "deploy-frontend.sh")],
            check=True, timeout=20 * 60,
        )
        steps.append("frontend build+restart")
    return steps


# ─── Bildirim ────────────────────────────────────────────────

def _notify(db, finding, run, cfg, extra: str = "") -> None:
    """Denetim modülü iznine sahip aktif kullanıcılara bildir (rol adına göre DEĞİL).

    Alıcı seçimi izinden türetilir — DR-003'te yakalanan "rol adına bakan alarm sessizce
    kimseye ulaşmıyor" hatasının tekrarını engeller.
    """
    if not cfg.notify_inapp and not cfg.notify_email:
        return
    try:
        from app.middleware.auth import user_can
        from app.models.user import User
        from app.utils.notification import create_and_send_notifications_sync

        user_ids = [
            u.id for u in db.query(User).filter(User.is_active.is_(True)).all()
            if user_can(db, u, "system.denetim", "view")
        ]
        if not user_ids:
            logger.warning("system.denetim izinli kullanıcı yok — bildirim gönderilmedi")
            return

        durum = {
            "basarili": "tamamlandı",
            "basarisiz": "başarısız oldu",
            "atlandi": "atlandı",
            "geri_alindi": "geri alındı",
        }.get(run.status, run.status)

        baslik = f"Denetim otomasyonu: {finding.code} {durum}"
        govde_parcalari = [finding.title[:200]]
        if run.tests_passed is not None:
            govde_parcalari.append(
                f"Testler: {run.tests_passed} geçti / {run.tests_failed or 0} hata",
            )
        if run.deployed:
            govde_parcalari.append("Canlıya alındı ✔")
        if run.rolled_back:
            govde_parcalari.append("Sağlık kontrolü başarısız → GERİ ALINDI")
        if extra:
            govde_parcalari.append(extra)

        create_and_send_notifications_sync(
            db, user_ids,
            type="denetim",
            title=baslik,
            body=" · ".join(govde_parcalari),
            link="/dashboard/sistem/denetim",
            email=cfg.notify_email,
        )
    except Exception as e:
        logger.error("Bildirim gönderilemedi: %s", e)


# ─── Ana akış ────────────────────────────────────────────────

def process(db, finding, cfg, trigger: str) -> None:
    report = svc.get_active_report(db)
    prompt = svc.build_prompt(db, finding, report)

    run = svc.start_run(db, finding, trigger, cfg.model)
    db.commit()
    logger.info("Koşu #%d başladı — %s (%s/%s)", run.id, finding.code, finding.risk, finding.effort)

    worktree = branch = None
    result = {"status": "basarisiz"}
    extra = ""

    try:
        worktree, branch = _prepare_worktree(finding.code)
        result["branch"] = branch
        logger.info("Worktree: %s (branch %s)", worktree, branch)

        claude_out = _run_claude(
            prompt, worktree, cfg.model, float(cfg.max_budget_usd), cfg.timeout_min,
        )
        result["cost_usd"] = claude_out.get("cost_usd")
        result["summary"] = (claude_out.get("text") or "")[:20000]

        if not claude_out["ok"]:
            result["error"] = claude_out["error"]
            logger.error("Claude koşusu başarısız: %s", claude_out["error"])
            return

        # Değişiklik var mı
        status_out = _git(["status", "--porcelain"], cwd=worktree, check=False)
        if not status_out:
            result["status"] = "atlandi"
            result["error"] = "Claude hiçbir dosya değiştirmedi"
            logger.info("Değişiklik yok — atlandı")
            return

        changed = [
            line[3:].strip() for line in status_out.splitlines() if len(line) > 3
        ]
        result["files_changed"] = len(changed)

        # Sır sızıntısı bekçisi — `--setting-sources user` proje settings.json'ını
        # devre dışı bıraktığı için PreToolUse gizli-dosya guard'ı bu koşuda ÇALIŞMAZ.
        # Aynı korumayı burada kuruyoruz: hassas dosya değiştiyse commit edilmez.
        leaked = [f for f in changed if _looks_secret(f)]
        if leaked:
            result["status"] = "basarisiz"
            result["error"] = (
                "Hassas dosya değişikliği reddedildi: " + ", ".join(leaked[:5])
            )
            logger.error(result["error"])
            return

        _git(["add", "-A"], cwd=worktree)
        _git([
            "commit", "-q", "-m",
            f"Denetim {finding.code}: {finding.title[:100]}\n\n"
            f"Otomatik düzeltme (koşu #{run.id}). Risk={finding.risk} Efor={finding.effort}",
        ], cwd=worktree)
        result["commit_sha"] = _git(["rev-parse", "HEAD"], cwd=worktree)

        # Testler
        logger.info("Testler koşuluyor (%d dosya değişti)...", len(changed))
        tests = _run_tests(worktree)
        result["tests_passed"] = tests["passed"]
        result["tests_failed"] = tests["failed"]
        result["log_excerpt"] = tests["tail"]

        if not tests["ok"]:
            result["status"] = "basarisiz"
            result["error"] = (
                f"Testler kırmızı ({tests['failed']} hata) — branch {branch} incelenmeli"
            )
            logger.error("Testler başarısız: %s hata", tests["failed"])
            return

        logger.info("Testler yeşil: %s geçti", tests["passed"])

        # Otomatik deploy muafiyeti
        blocked = [f for f in changed if any(f.startswith(b) or b in f for b in DEPLOY_BLOCKERS)]
        if blocked:
            result["status"] = "basarili"
            extra = (
                "Otomatik deploy ATLANDI (gözetim gerektiren dosya: "
                + ", ".join(blocked[:3]) + f") — branch {branch}"
            )
            logger.warning(extra)
            return
        if not cfg.auto_deploy:
            result["status"] = "basarili"
            extra = f"Otomatik deploy kapalı — branch {branch} incelemede"
            return

        # Merge + deploy
        # Geri alma güvenliği: master checkout'unun GERÇEKTEN master'da ve TEMİZ
        # olduğunu doğrula. Aksi halde `reset --hard` başkasının işini silebilir.
        current_branch = _git(["rev-parse", "--abbrev-ref", "HEAD"])
        if current_branch != "master":
            result["status"] = "basarili"
            extra = (f"Otomatik deploy atlandı: çalışma ağacı '{current_branch}' "
                     f"dalında — branch {branch} incelemede")
            logger.warning(extra)
            return
        if _git(["status", "--porcelain"], check=False):
            result["status"] = "basarili"
            extra = (f"Otomatik deploy atlandı: canlı çalışma ağacında kaydedilmemiş "
                     f"değişiklik var — branch {branch} incelemede")
            logger.warning(extra)
            return

        before_sha = _git(["rev-parse", "HEAD"])
        _git(["merge", "--no-ff", "-m",
              f"Denetim {finding.code} otomatik düzeltmesi (koşu #{run.id})", branch])
        after_sha = _git(["rev-parse", "HEAD"])
        try:
            steps = _deploy(changed)
            if not _health_ok():
                raise RuntimeError("Deploy sonrası /api/health 200 dönmedi")
            result["deployed"] = True
            result["status"] = "basarili"
            extra = "Deploy: " + (", ".join(steps) or "gerekmedi")
            logger.info("Canlıya alındı — %s", extra)
        except Exception as deploy_err:
            logger.error("Deploy başarısız: %s", deploy_err)
            if cfg.auto_rollback:
                # Yalnız KENDİ oluşturduğumuz merge commit'i HEAD'deyse geri sar —
                # arada başka bir commit düştüyse reset onu da silerdi.
                head_now = _git(["rev-parse", "HEAD"], check=False)
                if head_now == after_sha:
                    _git(["reset", "--hard", before_sha], check=False)
                    subprocess.run(
                        ["sudo", "systemctl", "restart", "sprenses-api.service"],
                        check=False, timeout=120,
                    )
                    result["rolled_back"] = True
                    result["status"] = "geri_alindi"
                    result["error"] = f"Deploy başarısız, geri alındı: {deploy_err}"
                    extra = "Sağlık kontrolü başarısız → master geri alındı"
                else:
                    result["status"] = "basarisiz"
                    result["error"] = (
                        f"Deploy başarısız ve GERİ ALINAMADI (HEAD değişmiş): {deploy_err}"
                    )
                    extra = "ELLE MÜDAHALE GEREKLİ — master geri alınamadı"
                    logger.error(extra)
            else:
                result["status"] = "basarisiz"
                result["error"] = str(deploy_err)

    except Exception as e:
        logger.exception("Koşu hatası")
        result["status"] = "basarisiz"
        result["error"] = str(e)[:4000]
        _log_error_row(
            "cron:denetim-otomasyon",
            f"{finding.code} koşusu hata verdi: {e}",
            (result.get("log_excerpt") or "") + "\n" + (result.get("summary") or ""),
        )
    finally:
        svc.finish_run(db, run, result)
        cfg.last_run_at = datetime.now(svc.tz_istanbul)
        db.commit()
        db.refresh(run)
        db.refresh(finding)
        _notify(db, finding, run, cfg, extra)
        # Başarısız koşularda branch İNCELEME İÇİN KALIR; worktree dizini temizlenir
        if worktree:
            _cleanup_worktree(worktree)
        logger.info("Koşu #%d bitti — durum=%s", run.id, run.status)


def main() -> int:
    parser = argparse.ArgumentParser(description="Denetim bulgusu otomatik düzeltme")
    parser.add_argument("--finding", help="Belirli bulgu kodu (ör. FIN-001)")
    parser.add_argument("--trigger", default="otomatik", choices=["otomatik", "elle"])
    parser.add_argument("--dry-run", action="store_true", help="Yalnız aday seçimini göster")
    args = parser.parse_args()

    lock = _acquire_lock()
    if lock is None:
        logger.info("Başka bir denetim koşusu sürüyor — atlandı")
        return 0

    db = SessionLocal()
    try:
        cfg = svc.get_config(db)
        # Kilit bizde → başka koşan süreç YOK; asılı kalmış `calisiyor` satırları ölüdür.
        reaped = svc.reap_stale_runs(db)
        if reaped:
            logger.warning("%d yarıda kesilmiş koşu kapatıldı", reaped)
        db.commit()

        if not cfg.enabled and args.trigger != "elle":
            logger.info("Otomasyon kapalı (acil durdurma anahtarı) — çıkılıyor")
            return 0

        headroom = _memory_headroom_mb()
        if headroom < cfg.min_free_mb:
            logger.warning(
                "Yetersiz bellek: %d MB < %d MB — koşu atlandı (earlyoom riski)",
                headroom, cfg.min_free_mb,
            )
            return 0

        report = svc.get_active_report(db)
        if not report:
            logger.warning("Aktif denetim raporu yok — çıkılıyor")
            return 0

        if args.finding:
            from app.models.audit_tracker import AuditFinding
            finding = (
                db.query(AuditFinding)
                .filter(
                    AuditFinding.report_id == report.id,
                    AuditFinding.code == args.finding,
                )
                .first()
            )
            if not finding:
                logger.error("Bulgu bulunamadı: %s", args.finding)
                return 1
            if not finding.automatable:
                logger.error("%s otomasyona uygun değil (repo dışı iş)", args.finding)
                return 1
        else:
            finding = svc.next_automation_candidate(db, report, cfg.max_attempts)
            if not finding:
                logger.info("Otomasyon kuyruğunda uygun bulgu yok — çıkılıyor")
                return 0

        if args.dry_run:
            logger.info(
                "[KURU ÇALIŞMA] Aday: %s — %s (risk=%s efor=%s deneme=%d)",
                finding.code, finding.title[:80], finding.risk,
                finding.effort, finding.auto_attempts or 0,
            )
            return 0

        process(db, finding, cfg, args.trigger)
        return 0
    finally:
        db.close()
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
