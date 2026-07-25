#!/usr/bin/env python3
"""Sessiz arıza eşikleri — periyodik kontrol + alarm (denetim OBS-001 / SRV-001 / JOBS).

`OnFailure=` yalnız BİR İŞ ÇÖKERSE tetiklenir. Ama en pahalı arızalar hiçbir işi
çökertmeden ilerler:
  · Disk dolar          → PostgreSQL DURUR (denetim: disk alarmı yok)
  · Kur bayatlar        → tüm EUR/TRY dönüşümleri sessizce yanlışlanır
  · TLS bitişe yaklaşır → 2026-07-18'de site fiilen düştü (v3 SRV-001)
  · Yedek alınmaz       → fark edilmeden haftalarca korumasız kalınır

Bu script eşikleri kontrol eder; ihlal varsa `systemd-failure-alert.py` ile AYNI kanaldan
(error_logs CRITICAL + izinli kullanıcılara e-posta) bildirir.

Kullanım:
    scripts/health-thresholds.py --dry-run   # yalnız rapor, yazmaz/göndermez
    scripts/health-thresholds.py             # ihlal varsa alarm üretir
"""

import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

# ─── Eşikler (ortam değişkeniyle geçersiz kılınabilir) ───────────────────────
DISK_PCT          = int(os.environ.get("SPRENSES_DISK_PCT", "80"))    # % — üstü ihlal
RATE_STALE_HOURS  = int(os.environ.get("SPRENSES_RATE_HOURS", "24"))  # sa — üstü ihlal
TLS_DAYS          = int(os.environ.get("SPRENSES_TLS_DAYS", "21"))    # gün — altı ihlal
BACKUP_MAX_HOURS  = int(os.environ.get("SPRENSES_BACKUP_HOURS", "30"))# sa — üstü ihlal (günlük + pay)
TLS_SERVERNAME    = os.environ.get("SPRENSES_TLS_SERVERNAME", "sprenses.com")
BACKUP_DIR        = "/var/backups/sprenses-db"


def check_disk():
    usage = shutil.disk_usage("/")
    pct = usage.used / usage.total * 100
    free_gb = usage.free / 1024**3
    if pct >= DISK_PCT:
        return (f"Disk %{pct:.0f} dolu (eşik %{DISK_PCT}) — {free_gb:.1f} GB boş. "
                f"Disk dolarsa PostgreSQL DURUR.")
    return None


def check_exchange_rate():
    """Kur bayatlığı — en son kur kaydının yaşı."""
    try:
        from app.database import SessionLocal
        from app.models.exchange_rate import ExchangeRate
        db = SessionLocal()
        try:
            row = (db.query(ExchangeRate.date)
                     .filter(ExchangeRate.currency_code == "EUR")
                     .order_by(ExchangeRate.date.desc()).first())
            if row is None:
                return "Hiç EUR kuru yok — tüm EUR/TRY dönüşümleri yapılamaz."
            age_h = (datetime.now().date() - row[0]).days * 24
            if age_h > RATE_STALE_HOURS:
                return (f"EUR kuru {age_h // 24} gündür güncellenmedi (son: {row[0]}, "
                        f"eşik {RATE_STALE_HOURS} sa) — dönüşümler bayat kurla yapılıyor.")
        finally:
            db.close()
    except Exception as e:
        return f"Kur kontrolü yapılamadı: {e}"
    return None


def check_tls():
    """TLS bitişi — SERVİS EDİLEN sertifikadan okunur, diskteki dosyadan DEĞİL.

    İlk sürüm `/etc/letsencrypt/live/.../fullchain.pem` dosyasını okuyordu; ama script
    `ec2-user` olarak koşuyor ve o dizin root'a ait → `openssl` "Permission denied" verip
    fonksiyon SESSİZCE None dönüyordu. Yani kontrol HİÇBİR ZAMAN ateşlemezdi (test
    sırasında yakalandı — eşiği 9999 güne çekmek bile ihlal üretmedi).

    `s_client` ile canlı uçtan okumak hem izin sorununu çözer hem STRİCTLY DAHA İYİDİR:
    diskteki dosya yenilenmiş ama nginx reload edilmemişse ESKİ sertifika servis edilmeye
    devam eder — denetimin belgelediği tuzak. Bu yöntem gerçekte sunulanı ölçer.
    """
    try:
        proc = subprocess.run(
            ["openssl", "s_client", "-connect", "127.0.0.1:443",
             "-servername", TLS_SERVERNAME],
            input="", capture_output=True, text=True, timeout=15,
        )
        end_out = subprocess.run(
            ["openssl", "x509", "-enddate", "-noout"],
            input=proc.stdout, capture_output=True, text=True, timeout=10,
        )
        if end_out.returncode != 0 or "notAfter=" not in end_out.stdout:
            return "TLS sertifikası okunamadı (canlı uçtan) — kontrol edilmeli."
        end = datetime.strptime(end_out.stdout.strip().split("=", 1)[1],
                                "%b %d %H:%M:%S %Y %Z")
        days = (end - datetime.now()).days
        if days < TLS_DAYS:
            return (f"TLS sertifikası {days} gün sonra doluyor ({end:%Y-%m-%d}, eşik "
                    f"{TLS_DAYS} gün) — bitmesi TÜM siteyi erişilemez yapar.")
    except Exception as e:
        return f"TLS kontrolü yapılamadı: {str(e)[:120]}"
    return None


def check_backup_freshness():
    try:
        dumps = [os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR)
                 if f.startswith("sprenses-") and f.endswith(".dump")]
    except Exception:
        return f"Yedek dizini okunamadı: {BACKUP_DIR}"
    if not dumps:
        return f"Hiç yedek yok: {BACKUP_DIR}"
    newest = max(dumps, key=os.path.getmtime)
    age_h = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(newest))).total_seconds() / 3600
    if age_h > BACKUP_MAX_HOURS:
        return (f"En son yedek {age_h:.0f} saatlik (eşik {BACKUP_MAX_HOURS} sa) — "
                f"günlük yedek çalışmıyor olabilir: {os.path.basename(newest)}")
    return None


CHECKS = [
    ("disk", check_disk),
    ("döviz kuru", check_exchange_rate),
    ("TLS sertifikası", check_tls),
    ("yedek tazeliği", check_backup_freshness),
]


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    violations = []

    for name, fn in CHECKS:
        try:
            msg = fn()
        except Exception as e:
            msg = f"kontrol hatası: {e}"
        status = "İHLAL" if msg else "ok"
        print(f"  {status:5} {name}" + (f" — {msg}" if msg else ""))
        if msg:
            violations.append(f"[{name}] {msg}")

    if not violations:
        print("eşik kontrolü: ihlal YOK")
        return 0

    summary = f"{len(violations)} eşik ihlali"
    print(f"\neşik kontrolü: {summary}")

    if dry_run:
        print("[KURU ÇALIŞMA] alarm üretilmedi")
        return 0

    # Alarm — systemd-failure-alert ile AYNI kanal (error_logs + e-posta)
    try:
        from app.database import SessionLocal
        from app.models.error_log import ErrorLog
        db = SessionLocal()
        try:
            db.add(ErrorLog(level="CRITICAL", source="health-thresholds",
                            message=f"Sistem eşik ihlali: {summary}",
                            traceback="\n".join(violations)[:20000]))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        print(f"UYARI: error_logs'a yazılamadı: {e}", file=sys.stderr)

    # E-posta: systemd-failure-alert.py ile AYNI kanal. Dosya adı tireli olduğundan
    # import edilemez → alt süreçle çağrılır (tek alarm yolu, tek alıcı mantığı).
    try:
        subprocess.run([sys.executable,
                        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "systemd-failure-alert.py"),
                        "esik-ihlali"], timeout=90)
    except Exception as e:
        print(f"UYARI: alarm e-postası gönderilemedi: {e}", file=sys.stderr)
    return 0   # systemd'yi 'failed' yapma — alarm zaten gitti


if __name__ == "__main__":
    sys.exit(main())
