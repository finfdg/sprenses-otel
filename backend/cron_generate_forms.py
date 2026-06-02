#!/usr/bin/env python3
"""
Kalite formlarını otomatik oluşturan cron scripti.

Aktif şablonların sıklığına (daily/weekly/monthly) göre
ilgili dönem tarihinde form yoksa yeni form oluşturur.

Kullanım:
  python cron_generate_forms.py

Systemd timer ile her gün 00:01'de çalıştırılır.
"""

import sys
import os
from datetime import date, timedelta

# Proje kök dizinini path'e ekle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.quality_template import QualityTemplate
from app.models.quality_form import QualityForm


def get_period_date(frequency: str, today: date):
    """Şablon sıklığına göre periyod tarihini hesapla."""
    if frequency == "daily":
        return today
    elif frequency == "weekly":
        return today - timedelta(days=today.weekday())
    elif frequency == "monthly":
        return today.replace(day=1)
    return None


def main():
    db = SessionLocal()
    try:
        today = date.today()
        templates = (
            db.query(QualityTemplate)
            .filter(QualityTemplate.is_active == True)
            .all()
        )

        generated = 0
        for t in templates:
            period_date = get_period_date(t.frequency, today)
            if not period_date:
                continue

            existing = (
                db.query(QualityForm)
                .filter(
                    QualityForm.template_id == t.id,
                    QualityForm.period_date == period_date,
                )
                .first()
            )
            if existing:
                continue

            form = QualityForm(
                template_id=t.id,
                period_date=period_date,
                status="draft",
            )
            db.add(form)
            generated += 1

        if generated > 0:
            db.commit()

        print(f"[{today}] {generated} form oluşturuldu, {len(templates) - generated} atlandı")
    except Exception as e:
        print(f"HATA: {e}", file=sys.stderr)
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
