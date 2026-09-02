"""Sağlık kontrolü — gerçek bağımlılık doğrulaması (denetim OBS-002).

ÖNCEKİ HÂLİ SABİT JSON DÖNDÜRÜYORDU: `{"status":"ok"}` — veritabanı çökmüş olsa bile
200 dönerdi. Bu, deploy sonrası "health 200 ✔" doğrulamalarını ANLAMSIZ kılıyordu
(2026-07-25 denetimi: readiness probe gerçek mi?). Artık gerçek kontrol yapılır.

Sertlik sınıflandırması — bilinçli:
  · **DB = SERT bağımlılık** → erişilemezse HTTP 503. Uygulama DB'siz hiçbir iş yapamaz.
  · **Sedna tüneli = YUMUŞAK** → kapalıysa yalnız bilgi olarak raporlanır, 503 ÜRETMEZ.
    Tünelin kapalı olması BEKLENEN bir işletme durumudur (LAN makinesi kapalı olabilir);
    yalnız içe-aktarma adımları 503 döner, API'nin geri kalanı sağlıklıdır. Bunu sert
    saymak, her akşam sahte alarm üretirdi.

Uçlar:
  GET /api/health       → tam kontrol (DB dahil); sağlıklıysa 200, DB düşükse 503
  GET /api/health/live  → yalnız süreç ayakta mı (bağımlılık kontrolü YOK, daima 200)
"""
import socket
import time

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db

router = APIRouter()

SEDNA_PROBE_TIMEOUT = 0.3  # sn — yerel soket, health'i yavaşlatmamalı


def _check_sedna_tunnel() -> dict:
    """Sedna ters tüneli dinleniyor mu (yalnız TCP connect — sorgu YAPMAZ)."""
    host, port = settings.sedna_host, settings.sedna_port
    try:
        with socket.create_connection((host, port), timeout=SEDNA_PROBE_TIMEOUT):
            return {"status": "up"}
    except Exception:
        # Kapalı olması normal → "down" bilgidir, hata değil (yukarıdaki nota bkz)
        return {"status": "down", "note": "içe-aktarma adımları 503 döner; API sağlıklı"}


@router.get("/health")
def health_check(response: Response, db: Session = Depends(get_db)):
    checks = {}
    healthy = True

    # ─── SERT: veritabanı ────────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {
            "status": "ok",
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
        }
    except Exception as e:
        checks["database"] = {"status": "error", "detail": str(e)[:200]}
        healthy = False

    # ─── YUMUŞAK: Sedna tüneli (yalnız yapılandırılmışsa sorulur) ────────
    checks["sedna_tunnel"] = (
        _check_sedna_tunnel() if settings.sedna_password else {"status": "disabled"}
    )

    response.status_code = 200 if healthy else 503
    return {
        "status": "ok" if healthy else "unhealthy",
        "service": "sprenses-api",
        "checks": checks,
    }


@router.get("/health/live")
def liveness():
    """Yalnız süreç canlılığı — bağımlılık kontrol EDİLMEZ, daima 200.

    DB bakımı sırasında süreç öldürülmesin isteyen orkestratörler için (systemd bunu
    kullanmıyor; ayrım gelecekteki çok-instance kurulum için baştan doğru tanımlanıyor).
    """
    return {"status": "alive", "service": "sprenses-api"}
