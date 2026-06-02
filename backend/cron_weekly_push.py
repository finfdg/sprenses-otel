#!/usr/bin/env python3
"""
Haftalık finans özeti push bildirimi — her Pazartesi çalışır.

Tüm aktif push aboneliğine sahip kullanıcılara haftanın ödeme planını özetler:

  - Bu haftaki vadeli çekler (TL toplamı)
  - Bu haftaki cari ödemeler
  - Gecikmiş kredi kartı ödemeleri (son ödeme tarihi geçmiş)
  - Toplam nakit akım bakiyesi

Crontab örneği (her Pazartesi 08:30):
  30 8 * * 1 cd /home/ec2-user/otel/backend && source venv/bin/activate && python cron_weekly_push.py >> /var/log/cron_weekly_push.log 2>&1

Kullanım:
  python cron_weekly_push.py           # Bugünden itibaren 7 günlük özet
  python cron_weekly_push.py --dry-run # Gönderme, sadece özeti göster
"""

import sys
import os
import logging
import argparse
from datetime import date, timedelta
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytz
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import SessionLocal
# Model registry için gerekli importlar
from app.models.user import User
from app.models.push_subscription import PushSubscription
from app.models.check import Check
from app.models.vendor_transaction import VendorTransaction
from app.models.credit_card_statement import CreditCardStatement
from app.models.finance_event import FinanceEvent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

TZ_ISTANBUL = pytz.timezone("Europe/Istanbul")


# ─── Özet Hesaplama ─────────────────────────────────────────────────────────

def build_weekly_summary(db: Session, week_start: date, week_end: date) -> dict:
    """Bu haftaki finans özetini hesapla."""

    # 1. Vadeli çekler (bu hafta vadesi dolan)
    checks_this_week = db.query(
        func.count(Check.id).label("count"),
        func.coalesce(func.sum(Check.amount_tl), 0).label("total_tl"),
    ).filter(
        Check.due_date >= week_start,
        Check.due_date <= week_end,
        Check.status == "pending",
    ).first()

    # 2. Cari ödemeler (bu hafta ödeme tarihi gelecek faturalar)
    # VendorTransaction: payment_due bu hafta içinde olan açık faturalar
    vendor_payments = db.query(
        func.count(VendorTransaction.id).label("count"),
        func.coalesce(func.sum(VendorTransaction.alacak), 0).label("total"),
    ).filter(
        VendorTransaction.payment_due_date >= week_start,
        VendorTransaction.payment_due_date <= week_end,
        VendorTransaction.alacak > 0,
    ).first()

    # 3. Gecikmiş kredi kartı ödemeleri (son_odeme_tarihi < bugün AND unpaid)
    today = date.today()
    overdue_cc = db.query(
        func.count(CreditCardStatement.id).label("count"),
        func.coalesce(func.sum(CreditCardStatement.toplam_borc), 0).label("total"),
    ).filter(
        CreditCardStatement.son_odeme_tarihi < today,
        CreditCardStatement.is_paid == False,
    ).first()

    # 4. Toplam nakit akım bakiyesi (finance_events'ten gerçekleşmiş)
    balance_row = db.query(
        func.coalesce(
            func.sum(
                FinanceEvent.direction * FinanceEvent.amount_try
            ), 0
        ).label("balance"),
    ).filter(
        FinanceEvent.is_matched == False,
        FinanceEvent.is_realized == True,
    ).first()

    return {
        "week_start": week_start.strftime("%d.%m.%Y"),
        "week_end": week_end.strftime("%d.%m.%Y"),
        "checks_count": int(checks_this_week.count or 0),
        "checks_total": float(checks_this_week.total_tl or 0),
        "vendor_count": int(vendor_payments.count or 0),
        "vendor_total": float(vendor_payments.total or 0),
        "overdue_cc_count": int(overdue_cc.count or 0),
        "overdue_cc_total": float(overdue_cc.total or 0),
        "balance": float(balance_row.balance or 0),
    }


def format_currency(amount: float) -> str:
    """Parasal değeri Türkçe formatla."""
    if abs(amount) >= 1_000_000:
        return f"{amount/1_000_000:.1f}M ₺"
    elif abs(amount) >= 1_000:
        return f"{amount/1_000:.0f}K ₺"
    else:
        return f"{amount:,.0f} ₺"


def build_notification_text(summary: dict) -> tuple:
    """Push bildirimi başlık ve içeriğini oluştur."""
    parts = []

    if summary["checks_count"] > 0:
        parts.append(
            f"📝 {summary['checks_count']} çek vadesi: {format_currency(summary['checks_total'])}"
        )

    if summary["vendor_count"] > 0:
        parts.append(
            f"🏪 {summary['vendor_count']} cari ödeme: {format_currency(summary['vendor_total'])}"
        )

    if summary["overdue_cc_count"] > 0:
        parts.append(
            f"⚠️ {summary['overdue_cc_count']} gecikmiş kart borcu: {format_currency(summary['overdue_cc_total'])}"
        )

    if not parts:
        parts.append("Bu hafta bekleyen ödeme bulunmuyor 🎉")

    balance = summary["balance"]
    balance_icon = "📈" if balance >= 0 else "📉"
    balance_text = f"{balance_icon} Güncel bakiye: {format_currency(abs(balance))}"

    title = f"💼 Haftalık Finans Özeti ({summary['week_start']} – {summary['week_end']})"
    body = "\n".join(parts) + f"\n{balance_text}"

    return title, body


# ─── Push Gönderimi ──────────────────────────────────────────────────────────

def get_users_with_push(db: Session):
    """Aktif push aboneliği olan kullanıcı ID listesi."""
    rows = (
        db.query(PushSubscription.user_id)
        .filter(PushSubscription.is_active == True)
        .distinct()
        .all()
    )
    return [r.user_id for r in rows]


def send_weekly_push(
    db: Session,
    title: str,
    body: str,
    dry_run: bool = False,
) -> int:
    """Tüm push abonelikli kullanıcılara haftalık özet gönder."""
    from app.config import settings

    if not settings.vapid_private_key or not settings.vapid_public_key:
        logger.warning("VAPID anahtarları yapılandırılmamış — push atlandı")
        return 0

    if dry_run:
        logger.info("[DRY-RUN] Bildirim gönderilecekti:")
        logger.info("  Başlık: %s", title)
        logger.info("  İçerik: %s", body)
        return 0

    import json
    from pywebpush import webpush, WebPushException

    user_ids = get_users_with_push(db)
    logger.info("Push gönderilecek kullanıcı sayısı: %d", len(user_ids))

    sent_count = 0
    deactivated_ids = []

    for user_id in user_ids:
        subs = (
            db.query(PushSubscription)
            .filter(
                PushSubscription.user_id == user_id,
                PushSubscription.is_active == True,
            )
            .all()
        )

        payload = json.dumps({
            "title": title,
            "body": body,
            "url": "/dashboard/finans/nakit-akis",
            "tag": "weekly-finance-summary",
            "icon": "/icon-192.png",
            "badge": "/icon-192.png",
        })

        for sub in subs:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {
                            "p256dh": sub.p256dh_key,
                            "auth": sub.auth_key,
                        },
                    },
                    data=payload,
                    vapid_private_key=settings.vapid_private_key,
                    vapid_claims={"sub": settings.vapid_mailto},
                )
                sent_count += 1
                logger.info("Push gönderildi: user_id=%d", user_id)
            except WebPushException as e:
                if e.response and e.response.status_code in (404, 410):
                    sub.is_active = False
                    deactivated_ids.append(sub.id)
                    logger.info(
                        "Geçersiz abonelik deaktive edildi: sub_id=%d user_id=%d",
                        sub.id, user_id,
                    )
                else:
                    logger.warning(
                        "Push başarısız: user_id=%d hata=%s", user_id, e
                    )
            except Exception as e:
                logger.warning("Push hatası: user_id=%d hata=%s", user_id, e)

    if deactivated_ids:
        db.commit()
        logger.info("%d geçersiz abonelik deaktive edildi", len(deactivated_ids))

    return sent_count


# ─── Ana Fonksiyon ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Haftalık finans özeti push bildirimi")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Push göndermeden özeti ekrana yazdır",
    )
    args = parser.parse_args()

    today = date.today()
    week_start = today
    week_end = today + timedelta(days=6)

    logger.info(
        "Haftalık özet hesaplanıyor: %s – %s",
        week_start.strftime("%d.%m.%Y"),
        week_end.strftime("%d.%m.%Y"),
    )

    db = SessionLocal()
    try:
        summary = build_weekly_summary(db, week_start, week_end)

        logger.info("Haftalık özet:")
        logger.info("  Vadeli çekler: %d adet / %.2f ₺", summary["checks_count"], summary["checks_total"])
        logger.info("  Cari ödemeler: %d adet / %.2f ₺", summary["vendor_count"], summary["vendor_total"])
        logger.info("  Gecikmiş kart: %d adet / %.2f ₺", summary["overdue_cc_count"], summary["overdue_cc_total"])
        logger.info("  Nakit bakiye: %.2f ₺", summary["balance"])

        title, body = build_notification_text(summary)

        sent = send_weekly_push(db, title, body, dry_run=args.dry_run)

        if not args.dry_run:
            logger.info("Toplam gönderilen push: %d", sent)
        else:
            logger.info("[DRY-RUN] Tamamlandı — gerçek gönderim yapılmadı")

    finally:
        db.close()


if __name__ == "__main__":
    main()
