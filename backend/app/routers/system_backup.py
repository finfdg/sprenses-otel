"""Yedekleme — git/GitHub yedek durumu izleme, manuel yedek (commit+push), geri yükleme.

Sunucu modülüyle aynı desende (subprocess + whitelist + audit). DB tablosu yoktur;
veri kaynağı git'in kendisidir. Tüm git komutları list-arg ile çağrılır (shell
injection yok). Geri yükleme güvenli "ileri-commit" semantiği kullanır: seçilen
commit'in dosyaları çalışma ağacına getirilip YENİ bir commit olarak kaydedilir —
geçmiş asla yeniden yazılmaz, force-push yapılmaz, hiçbir şey kaybolmaz.
"""

import logging
import os
import subprocess
from datetime import datetime

import pytz
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.user import User
from app.utils.audit import log_action

logger = logging.getLogger(__name__)

REPO_DIR = "/home/ec2-user/otel"
BRANCH = "master"
TZ = pytz.timezone("Europe/Istanbul")

# git push, kimlik bilgisini gh credential-helper'dan alır; systemd ortamında
# HOME ve PATH'i açıkça verelim ki helper (gh) bulunabilsin.
GIT_ENV = {
    **os.environ,
    "HOME": "/home/ec2-user",
    "PATH": "/usr/local/bin:/usr/bin:/bin:" + os.environ.get("PATH", ""),
    "GIT_TERMINAL_PROMPT": "0",  # asla interaktif kimlik sorma
}

US = "\x1f"  # unit separator — git --format alan ayırıcısı

router = APIRouter()


def _git(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """git komutu yardımcısı — repo dizininde, güvenli ortamla, list-arg ile."""
    return subprocess.run(
        ["git", "-C", REPO_DIR, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=GIT_ENV,
    )


def _parse_commits(raw: str) -> list:
    """git log --format çıktısını [{short,subject,date,author}] listesine çevir."""
    commits = []
    for line in raw.strip().split("\n"):
        if not line:
            continue
        parts = line.split(US)
        if len(parts) >= 4:
            commits.append({
                "short": parts[0],
                "subject": parts[1],
                "date": parts[2],
                "author": parts[3],
            })
    return commits


# ─── İZLEME ──────────────────────────────────────────────


@router.get("/backup/status")
def get_backup_status(
    _: User = Depends(require_permission("system.backup", "view")),
):
    """Yedek durumu — son commit, bekleyen değişiklik, senkron, uzak depo, geçmiş."""
    fmt = US.join(["%h", "%s", "%cI", "%an"])

    # Son commit
    last = _git("log", "-1", f"--format={fmt}")
    last_commit = None
    if last.returncode == 0 and last.stdout.strip():
        c = _parse_commits(last.stdout)
        last_commit = c[0] if c else None

    # Bekleyen (commit'lenmemiş) değişiklik sayısı
    porcelain = _git("status", "--porcelain")
    pending = len([ln for ln in porcelain.stdout.strip().split("\n") if ln.strip()]) if porcelain.stdout.strip() else 0

    # Uzakla fark (ahead/behind) — origin/branch...branch
    ahead = behind = 0
    rl = _git("rev-list", "--left-right", "--count", f"origin/{BRANCH}...{BRANCH}")
    if rl.returncode == 0 and rl.stdout.strip():
        try:
            behind_s, ahead_s = rl.stdout.split()
            behind, ahead = int(behind_s), int(ahead_s)
        except ValueError:
            pass

    # Uzak depo URL
    remote = _git("remote", "get-url", "origin")
    remote_url = remote.stdout.strip() if remote.returncode == 0 else None

    # Geçmiş (son 30)
    history = _git("log", "-30", f"--format={fmt}")
    commits = _parse_commits(history.stdout) if history.returncode == 0 else []

    return {
        "branch": BRANCH,
        "last_commit": last_commit,
        "pending_changes": pending,
        "ahead": ahead,        # yerelde olup uzağa gitmemiş commit sayısı
        "behind": behind,      # uzakta olup yerele gelmemiş
        "in_sync": ahead == 0 and pending == 0,
        "remote_url": remote_url,
        "history": commits,
        "fetched_at": datetime.now(TZ).isoformat(),
    }


# ─── YEDEK (commit + push) ───────────────────────────────


@router.post("/backup/run")
def run_backup(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.backup", "use")),
):
    """Manuel yedek — değişiklik varsa commit'le, sonra GitHub'a push et."""
    porcelain = _git("status", "--porcelain")
    changed = len([ln for ln in porcelain.stdout.strip().split("\n") if ln.strip()]) if porcelain.stdout.strip() else 0

    committed = False
    if changed > 0:
        add = _git("add", "-A")
        if add.returncode != 0:
            raise HTTPException(status_code=500, detail=(add.stderr.strip() or "git add başarısız")[:300])
        ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        msg = f"Manuel yedek: {ts} ({current_user.username})"
        commit = _git("commit", "-q", "-m", msg)
        # commit returncode != 0 olabilir (commit'lenecek bir şey yoksa) — değişiklik vardı, sorun olmamalı
        committed = commit.returncode == 0

    # Push (yerel ileride mi?)
    push_out = ""
    pushed = False
    try:
        push = _git("push", "origin", BRANCH, timeout=120)
        pushed = push.returncode == 0
        push_out = (push.stderr or push.stdout).strip()
        if not pushed:
            logger.error("Yedek push başarısız: %s", push_out)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Push 120 saniyede tamamlanamadı")

    log_action(
        db, current_user.id, "backup", "system_backup",
        entity_id=0,
        details=f"Manuel yedek: {changed} değişiklik, committed={committed}, pushed={pushed}",
        ip_address=get_client_ip(request),
    )
    db.commit()

    return {
        "changed_files": changed,
        "committed": committed,
        "pushed": pushed,
        "message": (
            "Yedekleme tamamlandı" if pushed
            else "Push başarısız — sunucu git kimlik bilgisini kontrol edin"
        ),
        "detail": push_out[:300],
    }


# ─── GERİ YÜKLEME (güvenli ileri-commit) ─────────────────


class RestoreRequest(BaseModel):
    commit: str  # geri dönülecek commit'in (kısa veya tam) hash'i


@router.post("/backup/restore")
def restore_backup(
    data: RestoreRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.backup", "use")),
):
    """Seçilen commit'in durumuna güvenli şekilde geri dön.

    GÜVENLİ semantik: önce mevcut durum otomatik yedeklenir, sonra hedef commit'in
    dosyaları çalışma ağacına getirilip YENİ bir commit olarak kaydedilir. Geçmiş
    yeniden yazılmaz, force-push yok, kayıp yok. Geri yükleme sonrası kod değiştiği
    için yeniden deploy (backend restart + frontend build) gerekir.
    """
    target = data.commit.strip()
    # Hash doğrulama — sadece commit nesnesi olmalı (injection'a karşı zaten list-arg)
    if not target or len(target) > 64 or not all(c in "0123456789abcdefABCDEF" for c in target):
        raise HTTPException(status_code=400, detail="Geçersiz commit hash")

    verify = _git("cat-file", "-t", target)
    if verify.returncode != 0 or verify.stdout.strip() != "commit":
        raise HTTPException(status_code=404, detail="Commit bulunamadı")

    # 1) Mevcut durumu güvenlik için yedekle (commit'lenmemiş değişiklik varsa)
    porcelain = _git("status", "--porcelain")
    if porcelain.stdout.strip():
        _git("add", "-A")
        ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        _git("commit", "-q", "-m", f"Geri yükleme öncesi otomatik yedek: {ts} ({current_user.username})")

    # 2) Hedef commit'in dosyalarını çalışma ağacına + index'e getir
    checkout = _git("checkout", target, "--", ".")
    if checkout.returncode != 0:
        raise HTTPException(status_code=500, detail=(checkout.stderr.strip() or "Geri yükleme başarısız")[:300])

    # 3) Fark var mı? Varsa ileri-commit olarak kaydet
    staged = _git("diff", "--cached", "--quiet")
    restored = staged.returncode != 0  # !=0 → staged değişiklik var
    if restored:
        short = target[:8]
        ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        commit = _git("commit", "-q", "-m", f"Geri yükleme: {short} durumuna dönüldü — {ts} ({current_user.username})")
        if commit.returncode != 0:
            raise HTTPException(status_code=500, detail=(commit.stderr.strip() or "Geri yükleme commit'i başarısız")[:300])

    # 4) Push
    pushed = False
    try:
        push = _git("push", "origin", BRANCH, timeout=120)
        pushed = push.returncode == 0
    except subprocess.TimeoutExpired:
        pushed = False

    log_action(
        db, current_user.id, "restore", "system_backup",
        entity_id=0,
        details=f"Geri yükleme: hedef={target[:12]}, uygulandı={restored}, pushed={pushed}",
        ip_address=get_client_ip(request),
    )
    db.commit()

    return {
        "restored": restored,
        "restored_to": target[:12],
        "pushed": pushed,
        "redeploy_needed": restored,
        "message": (
            "Geri yükleme uygulandı — değişikliklerin çalışması için yeniden deploy gerekir"
            if restored else "Kod zaten bu commit ile aynıydı, değişiklik yapılmadı"
        ),
    }
