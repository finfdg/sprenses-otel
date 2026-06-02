"""Sunucu izleme — CPU/RAM/disk metrikleri, servis durumları, restart, log görüntüleme."""

import logging
import shutil
import subprocess
from datetime import datetime
from typing import List, Optional

import psutil
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.user import User
from app.utils.audit import log_action

logger = logging.getLogger(__name__)

# İzin verilen servisler — restart/log güvenliği için whitelist
ALLOWED_SERVICES = [
    "sprenses-api",
    "sprenses-frontend",
    "sprenses-exchange-rates",
    "sprenses-quality-forms",
    "postgresql",
    "nginx",
]

# uptime, load, swap, log/uploads boyut için yardımcı sabit
LOG_DIR = "/home/ec2-user/otel/backend/logs"
UPLOADS_DIR = "/home/ec2-user/otel/backend/uploads"

router = APIRouter()


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    """systemctl çağrısı yardımcısı — timeout 10 sn, stderr de yakalar."""
    return subprocess.run(
        ["systemctl", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )


def _service_status(service_name: str) -> dict:
    """Bir servisin active/inactive durumu + RAM kullanımı."""
    is_active_proc = _systemctl("is-active", service_name)
    active = is_active_proc.stdout.strip() == "active"

    memory_bytes = 0
    main_pid = 0
    if active:
        # `systemctl show` ile MainPID + MemoryCurrent al
        show = _systemctl("show", service_name, "--property=MainPID,MemoryCurrent")
        for line in show.stdout.strip().split("\n"):
            if line.startswith("MainPID="):
                try:
                    main_pid = int(line.split("=", 1)[1])
                except ValueError:
                    main_pid = 0
            elif line.startswith("MemoryCurrent="):
                try:
                    memory_bytes = int(line.split("=", 1)[1])
                except ValueError:
                    memory_bytes = 0

    return {
        "name": service_name,
        "active": active,
        "memory_bytes": memory_bytes,
        "memory_mb": round(memory_bytes / 1024 / 1024, 1) if memory_bytes else 0,
        "main_pid": main_pid,
    }


def _dir_size(path: str) -> int:
    """Bir dizinin toplam boyutu (bytes). Dizin yoksa 0 döner."""
    try:
        result = subprocess.run(
            ["du", "-sb", path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return int(result.stdout.split()[0])
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        pass
    return 0


@router.get("/server/info")
def get_server_info(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.server", "view")),
):
    """Sunucu durumu — CPU, RAM, disk, servisler, DB boyutu, uploads/logs boyutu."""

    # CPU
    cpu_percent = psutil.cpu_percent(interval=0.5)
    cpu_count = psutil.cpu_count(logical=True)
    load_avg = list(psutil.getloadavg())

    # RAM
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # Disk (root partition)
    disk = shutil.disk_usage("/")

    # Uptime
    boot_time = psutil.boot_time()
    uptime_seconds = int(datetime.now().timestamp() - boot_time)

    # Servisler
    services = [_service_status(s) for s in ALLOWED_SERVICES]

    # PostgreSQL DB boyutu
    db_size_mb: Optional[float] = None
    try:
        result = db.execute(text("SELECT pg_database_size(current_database())")).scalar()
        if result is not None:
            db_size_mb = round(int(result) / 1024 / 1024, 1)
    except Exception:
        logger.debug("DB boyutu alınamadı", exc_info=True)

    # Uploads + log boyut
    uploads_bytes = _dir_size(UPLOADS_DIR)
    logs_bytes = _dir_size(LOG_DIR)

    return {
        "cpu": {
            "percent": cpu_percent,
            "cores": cpu_count,
            "load_avg_1m": round(load_avg[0], 2),
            "load_avg_5m": round(load_avg[1], 2),
            "load_avg_15m": round(load_avg[2], 2),
        },
        "memory": {
            "total_mb": round(mem.total / 1024 / 1024, 0),
            "used_mb": round(mem.used / 1024 / 1024, 0),
            "free_mb": round(mem.available / 1024 / 1024, 0),
            "percent": mem.percent,
            "swap_total_mb": round(swap.total / 1024 / 1024, 0),
            "swap_used_mb": round(swap.used / 1024 / 1024, 0),
        },
        "disk": {
            "total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
            "used_gb": round(disk.used / 1024 / 1024 / 1024, 1),
            "free_gb": round(disk.free / 1024 / 1024 / 1024, 1),
            "percent": round((disk.used / disk.total) * 100, 1),
        },
        "uptime_seconds": uptime_seconds,
        "services": services,
        "storage": {
            "db_size_mb": db_size_mb,
            "uploads_mb": round(uploads_bytes / 1024 / 1024, 1),
            "logs_mb": round(logs_bytes / 1024 / 1024, 1),
        },
        "fetched_at": datetime.now().isoformat(),
    }


@router.post("/server/services/{service_name}/restart")
def restart_service(
    service_name: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.server", "use")),
):
    """Bir servisi restart et — sadece whitelist'teki servisler."""
    if service_name not in ALLOWED_SERVICES:
        raise HTTPException(status_code=400, detail="Bu servis restart edilemez")

    try:
        result = subprocess.run(
            ["sudo", "-n", "systemctl", "restart", service_name],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Restart 30 saniyede tamamlanamadı")

    if result.returncode != 0:
        logger.error("Servis restart başarısız: %s — %s", service_name, result.stderr)
        # sudo NOPASSWD eksikse "sudo: a password is required" hatası verir
        detail = result.stderr.strip() or "Restart başarısız"
        raise HTTPException(status_code=500, detail=detail[:500])

    log_action(
        db, current_user.id, "restart", "service",
        entity_id=0,
        details=f"Servis restart edildi: {service_name}",
        ip_address=get_client_ip(request),
    )
    db.commit()

    return {"success": True, "service": service_name, "message": f"{service_name} yeniden başlatıldı"}


@router.get("/server/services/{service_name}/logs")
def get_service_logs(
    service_name: str,
    lines: int = 50,
    current_user: User = Depends(require_permission("system.server", "view")),
):
    """Bir servisin son N satır journalctl logu."""
    if service_name not in ALLOWED_SERVICES:
        raise HTTPException(status_code=400, detail="Bu servisin logları görüntülenemez")

    if lines < 1 or lines > 500:
        raise HTTPException(status_code=400, detail="lines parametresi 1-500 arası olmalı")

    try:
        result = subprocess.run(
            ["journalctl", "-u", service_name, "-n", str(lines), "--no-pager", "--output=short"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Log alımı 15 saniyede tamamlanamadı")

    if result.returncode != 0:
        # journalctl bazı durumlarda permission isteyebilir
        detail = result.stderr.strip() or "Log alınamadı"
        raise HTTPException(status_code=500, detail=detail[:500])

    return {
        "service": service_name,
        "lines": lines,
        "log": result.stdout,
    }
