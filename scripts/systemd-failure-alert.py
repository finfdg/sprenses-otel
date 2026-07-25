#!/usr/bin/env python3
"""Zamanlanmış iş başarısızlık alarmı — systemd `OnFailure=` hedefi (denetim DR-003/JOBS-002).

SORUN: yedek ve senkron işlerinin hiçbirinde `OnFailure=` yoktu. Bir iş çökerse yalnız
journald'a düşüyor, kimse haber almıyordu. Denetim bunu canlıda somut olarak buldu: döviz
cron'unun `amount_try` adımı **2 ay boyunca her koşuda** sessizce çöktü ve fark edilmedi.

NE YAPAR: başarısız birimin adını alır, son log satırlarını journald'dan toplar ve
  1) `error_logs` tablosuna CRITICAL kayıt yazar → Sistem ▸ Hata Logları ekranında görünür
  2) sistem izni olan aktif kullanıcılara e-posta atar (SMTP yapılandırılıysa)

Kullanım (systemd):
    OnFailure=sprenses-alert@%n.service
şablon birim: scripts/systemd/sprenses-alert@.service

Manuel:
    scripts/systemd-failure-alert.py <birim> --dry-run   # hiçbir şey yazmaz/göndermez
    scripts/systemd-failure-alert.py <birim>             # gerçekten yazar + gönderir

UYARI: --dry-run olmadan çalıştırmak izinli kullanıcılara GERÇEK bir "iş başarısız"
alarmı yollar. Doğrulama yaparken daima --dry-run kullan.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

MAX_LOG_LINES = 40


def _recent_logs(unit: str) -> str:
    """Birimin son koşusundaki log satırları (alarm e-postasına bağlam)."""
    try:
        out = subprocess.run(
            ["journalctl", "-u", unit, "-n", str(MAX_LOG_LINES), "--no-pager", "-o", "short-iso"],
            capture_output=True, text=True, timeout=20,
        )
        return out.stdout.strip() or "(log okunamadı)"
    except Exception as e:  # journalctl yoksa/izin yoksa alarm yine de gitsin
        return f"(journalctl okunamadı: {e})"


def _resolve_recipients(db) -> list:
    """Alıcı = SİSTEM İZNİ olan aktif kullanıcılar (rol ADINA göre DEĞİL).

    İlk sürüm `u.role.name == "Admin"` bakıyordu; ilişkinin gerçek adı `role_rel`
    olduğundan `getattr` sessizce None dönüyor ve alarm HİÇ e-posta göndermiyordu —
    kapatmaya çalıştığı sessiz-hata sınıfının aynısı (2026-07-25'te yakalandı).
    İzin sorgusu hem doğru hem de rol yeniden adlandırmalarına dayanıklı.
    """
    from app.middleware.auth import user_can
    from app.models.user import User

    # TEKİLLEŞTİR: e-posta artık benzersiz DEĞİL (migration e8f2b6d4a9c3 — ortak/rol posta
    # kutusuna izin verildi). Aynı adresi taşıyan iki hesap varsa aynı kutuya iki özdeş
    # alarm giderdi. Sıra korunur (dict.fromkeys), karşılaştırma küçük harf + trim'li.
    seen = {}
    for u in db.query(User).filter(User.is_active == True).all():  # noqa: E712
        if not u.email:
            continue
        if user_can(db, u, "system.server") or user_can(db, u, "system.error_logs"):
            key = u.email.strip().lower()
            seen.setdefault(key, u.email.strip())
    return list(seen.values())


def _mask(addr: str) -> str:
    return addr[:3] + "***@" + addr.split("@")[-1]


def _write_error_log(unit: str, message: str, logs: str) -> bool:
    from app.database import SessionLocal
    from app.models.error_log import ErrorLog

    db = SessionLocal()
    try:
        db.add(ErrorLog(level="CRITICAL", source=f"systemd:{unit}",
                        message=message, traceback=logs[:20000]))
        db.commit()
        return True
    finally:
        db.close()


def _send_mails(unit: str, message: str, logs: str, dry_run: bool) -> int:
    from app.database import SessionLocal
    from app.utils.mail import is_mail_enabled, send_email

    if not is_mail_enabled():
        print("NOT: SMTP yapılandırılmamış — e-posta atlandı")
        return 0

    db = SessionLocal()
    try:
        recipients = _resolve_recipients(db)
    finally:
        db.close()

    if not recipients:
        print("UYARI: sistem izinli alıcı bulunamadı — alarm e-postası gitmedi", file=sys.stderr)
        return 0

    if dry_run:
        print(f"[KURU ÇALIŞMA] {len(recipients)} alıcıya gönderilecekti: "
              + ", ".join(_mask(a) for a in recipients))
        return 0

    html = (
        f"<h3>⚠️ {message}</h3>"
        f"<p>Sunucu: <b>{os.uname().nodename}</b></p>"
        f"<p>Son {MAX_LOG_LINES} log satırı:</p>"
        f"<pre style='background:#f5f5f5;padding:10px;font-size:12px'>{logs[:8000]}</pre>"
    )
    sent = 0
    for addr in recipients:
        if send_email(addr, f"[Sprenses] {message}", html,
                      body_text=f"{message}\n\n{logs[:4000]}"):
            sent += 1
    return sent


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    unit = args[0] if args else "bilinmeyen-birim"

    logs = _recent_logs(unit)
    message = f"Zamanlanmış iş BAŞARISIZ: {unit}"

    if dry_run:
        print(f"[KURU ÇALIŞMA] error_logs'a CRITICAL kayıt yazılacaktı: {message}")
        db_state = "kuru"
    else:
        try:
            db_state = "OK" if _write_error_log(unit, message, logs) else "YAZILAMADI"
        except Exception as e:
            print(f"UYARI: error_logs'a yazılamadı: {e}", file=sys.stderr)
            db_state = "YAZILAMADI"

    try:
        sent = _send_mails(unit, message, logs, dry_run)
    except Exception as e:
        print(f"UYARI: e-posta gönderilemedi: {e}", file=sys.stderr)
        sent = 0

    print(f"alarm: unit={unit} error_logs={db_state} eposta={sent}"
          + (" (KURU ÇALIŞMA — hiçbir şey yazılmadı/gönderilmedi)" if dry_run else ""))
    # Alarm'ın kendisi başarısız olsa da systemd'yi meşgul etme — 0 dön (journald kaydı yeter)
    return 0


if __name__ == "__main__":
    sys.exit(main())
