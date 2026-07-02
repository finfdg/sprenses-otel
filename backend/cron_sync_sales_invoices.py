#!/usr/bin/env python3
"""Satış faturası + tahsilat + avans + acente-köprüsü Sedna senkron cronu.

Hak Ediş Takibi (finance.hakedis) verisinin düzenli tazelenmesi için:
`run_sales_invoice_import` (finance.sales_invoices modülünün import'u) admin
kullanıcısıyla çağrılır — fatura/tahsilat upsert + 340 avans tazeleme +
PMS acente→120 köprüsü. Systemd timer: sprenses-sales-sync.timer
(hafta içi/sonu 08:00-22:00 arası 2 saatte bir, Europe/Istanbul).

Tünel/Sedna kapalıysa uyarı loglar ve 0 ile çıkar (timer'ı düşürmez).
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sales-sync-cron")


def main() -> int:
    from fastapi import HTTPException

    from app.database import SessionLocal
    from app.models.user import User
    from app.routers.finance.sales_invoices import run_sales_invoice_import

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            logger.error("admin kullanıcısı bulunamadı — senkron atlandı.")
            return 1
        result = run_sales_invoice_import(db, admin, ip="cron")
        logger.info(
            "Satış senkronu tamam: %s yeni fatura, %s yeni tahsilat, %s avans hesabı",
            result.get("invoices_new"), result.get("collections_new"),
            result.get("advance_accounts"),
        )
        return 0
    except HTTPException as e:
        # 503 = tünel kapalı / Sedna erişilemez — beklenen durum, timer'ı düşürme
        logger.warning("Satış senkronu yapılamadı (HTTP %s): %s", e.status_code, e.detail)
        return 0
    except Exception:
        logger.exception("Satış senkronu beklenmeyen hata")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
