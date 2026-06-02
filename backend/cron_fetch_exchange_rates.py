#!/usr/bin/env python3
"""
TCMB döviz kurlarını çeken cron scripti.

Kullanım:
  python cron_fetch_exchange_rates.py           # Günlük güncelleme
  python cron_fetch_exchange_rates.py --bulk    # 2023-01-01'den bugüne toplu çekme
"""

import sys
import os
import time
import argparse
import logging
import urllib.request
import urllib.error
import json
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import func
from app.database import SessionLocal
from app.models.credit_product import CreditProduct  # noqa: F401 — model registry
from app.models.credit_card_statement import CreditCardStatement  # noqa: F401
from app.models.exchange_rate import ExchangeRate
from app.utils.tcmb import fetch_rates_for_date_sync, fetch_today_rates_sync, fetch_hourly_rates_sync
from app.utils.finance_event_service import finance_event_svc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BULK_START_DATE = date(2023, 1, 1)
RATE_LIMIT_DELAY = 0.5  # TCMB istekleri arasında bekleme (saniye)
INTERNAL_BROADCAST_URL = "http://127.0.0.1:8001/api/internal/broadcast-finance-update?module=exchange_rates&action=update"


def store_rates(db, rate_date, rates, source="tcmb"):
    """Kurları DB'ye kaydet. Mevcut olanları atla."""
    stored = 0
    for rate in rates:
        existing = db.query(ExchangeRate).filter(
            ExchangeRate.date == rate_date,
            ExchangeRate.currency_code == rate.currency_code,
        ).first()
        if existing:
            continue

        er = ExchangeRate(
            date=rate_date,
            currency_code=rate.currency_code,
            currency_name=rate.currency_name,
            unit=rate.unit,
            forex_buying=rate.forex_buying,
            forex_selling=rate.forex_selling,
            banknote_buying=rate.banknote_buying,
            banknote_selling=rate.banknote_selling,
            source=source,
        )
        db.add(er)
        stored += 1
    return stored


def upsert_rates(db, rate_date, rates, source="tcmb"):
    """Kurları DB'ye kaydet. Mevcut varsa güncelle (taşıma → TCMB geçişi için)."""
    updated = 0
    inserted = 0
    for rate in rates:
        existing = db.query(ExchangeRate).filter(
            ExchangeRate.date == rate_date,
            ExchangeRate.currency_code == rate.currency_code,
        ).first()
        if existing:
            # Aynı kaynak ve aynı değerse atla
            if (existing.source == source
                    and existing.forex_selling == rate.forex_selling
                    and existing.forex_buying == rate.forex_buying):
                continue
            existing.currency_name = rate.currency_name
            existing.unit = rate.unit
            existing.forex_buying = rate.forex_buying
            existing.forex_selling = rate.forex_selling
            existing.banknote_buying = rate.banknote_buying
            existing.banknote_selling = rate.banknote_selling
            existing.source = source
            updated += 1
        else:
            er = ExchangeRate(
                date=rate_date,
                currency_code=rate.currency_code,
                currency_name=rate.currency_name,
                unit=rate.unit,
                forex_buying=rate.forex_buying,
                forex_selling=rate.forex_selling,
                banknote_buying=rate.banknote_buying,
                banknote_selling=rate.banknote_selling,
                source=source,
            )
            db.add(er)
            inserted += 1
    return updated, inserted


def carry_forward_rates(db, target_date, prev_date):
    """Önceki iş gününün kurlarını taşıyarak hafta sonu/tatil günlerini doldur."""
    prev_rates = db.query(ExchangeRate).filter(
        ExchangeRate.date == prev_date,
    ).all()

    stored = 0
    for pr in prev_rates:
        existing = db.query(ExchangeRate).filter(
            ExchangeRate.date == target_date,
            ExchangeRate.currency_code == pr.currency_code,
        ).first()
        if existing:
            continue

        er = ExchangeRate(
            date=target_date,
            currency_code=pr.currency_code,
            currency_name=pr.currency_name,
            unit=pr.unit,
            forex_buying=pr.forex_buying,
            forex_selling=pr.forex_selling,
            banknote_buying=pr.banknote_buying,
            banknote_selling=pr.banknote_selling,
            source="carried",
        )
        db.add(er)
        stored += 1
    return stored


def fetch_date_range(db, start_date, end_date):
    """Tarih aralığındaki kurları çek. Hafta sonları/tatiller için carry-forward uygula."""
    current = start_date
    last_successful_date = None
    total_fetched = 0
    total_carried = 0

    # Başlangıç tarihinden önceki son TCMB kur tarihi (carry-forward için)
    prev = db.query(ExchangeRate.date).filter(
        ExchangeRate.date < start_date,
        ExchangeRate.source == "tcmb",
    ).order_by(ExchangeRate.date.desc()).first()
    if prev:
        last_successful_date = prev[0]

    while current <= end_date:
        # Zaten var mı kontrol et
        exists = db.query(ExchangeRate).filter(
            ExchangeRate.date == current,
        ).first()
        if exists:
            if exists.source == "tcmb":
                last_successful_date = current
            current += timedelta(days=1)
            continue

        # TCMB'den çek
        response = fetch_rates_for_date_sync(current)

        if response and response.rates:
            stored = store_rates(db, current, response.rates, source="tcmb")
            total_fetched += stored
            last_successful_date = current
            logger.info("[TCMB] %s: %d kur kaydedildi", current, stored)
        else:
            # TCMB'den veri yok: önceki iş gününden taşı
            if last_successful_date:
                carried = carry_forward_rates(db, current, last_successful_date)
                total_carried += carried
                logger.info("[TAŞIMA] %s: %d kur taşındı (%s'den)", current, carried, last_successful_date)
            else:
                logger.warning("[ATLA] %s: Taşınacak önceki kur bulunamadı", current)

        db.commit()
        time.sleep(RATE_LIMIT_DELAY)
        current += timedelta(days=1)

    return total_fetched, total_carried


def update_amount_try_for_date(db, target_date):
    """Belirli tarih için EUR/USD cinsinden finance_events.amount_try'ı güncelle."""
    try:
        eur_rate = (
            db.query(ExchangeRate.forex_selling)
            .filter(ExchangeRate.currency_code == "EUR", ExchangeRate.date <= target_date)
            .order_by(ExchangeRate.date.desc())
            .scalar()
        )
        if eur_rate:
            updated = finance_event_svc.update_amount_try(db, target_date, float(eur_rate))
            if updated:
                logger.info("[amount_try] %s: EUR kuru=%.4f, %d event güncellendi", target_date, float(eur_rate), updated)
        db.commit()
    except Exception as e:
        logger.warning("[amount_try] Güncelleme hatası %s: %s", target_date, e)


def notify_finance_update():
    """Backend'e internal broadcast isteği gönder — online kullanıcılar finance_updated alır."""
    try:
        from app.config import settings as app_settings
        secret = app_settings.internal_secret
    except Exception:
        logger.warning("[broadcast] internal_secret okunamadı, bildirim atlandı")
        return

    try:
        req = urllib.request.Request(
            INTERNAL_BROADCAST_URL,
            data=b"",
            method="POST",
            headers={"X-Internal-Secret": secret, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())
            logger.info("[broadcast] finance_updated gönderildi: online=%d", body.get("online_users", 0))
    except urllib.error.URLError as e:
        logger.warning("[broadcast] Backend'e ulaşılamadı (devam ediliyor): %s", e)
    except Exception as e:
        logger.warning("[broadcast] Bildirim hatası (devam ediliyor): %s", e)


def main():
    parser = argparse.ArgumentParser(description="TCMB döviz kurlarını çek")
    parser.add_argument("--bulk", action="store_true", help="2023-01-01'den bugüne toplu çekme")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        today = date.today()

        if args.bulk:
            logger.info("Toplu çekme başlatıldı: %s -> %s", BULK_START_DATE, today)
            fetched, carried = fetch_date_range(db, BULK_START_DATE, today)
            logger.info("Toplu çekme tamamlandı: %d TCMB + %d taşıma", fetched, carried)
        else:
            # Günlük mod: son tarihten bugüne
            latest = db.query(func.max(ExchangeRate.date)).scalar()
            if latest:
                start = latest + timedelta(days=1)
            else:
                start = BULK_START_DATE

            yesterday = today - timedelta(days=1)

            # 1) Eksik geçmiş tarihleri tarihsel URL ile doldur (önceki gün hariç)
            two_days_ago = today - timedelta(days=2)
            if start <= two_days_ago:
                logger.info("Geçmiş güncelleme: %s -> %s", start, two_days_ago)
                fetched, carried = fetch_date_range(db, start, two_days_ago)
                logger.info("[Geçmiş] %d TCMB + %d taşıma", fetched, carried)

            # 2) Dünün kurunu günlük tarihsel URL'den al (upsert)
            #    — gün içi today.xml'den gelen saatlik kurları kesinleşmiş günlük kurla günceller
            logger.info("[%s] Dün için günlük kur kontrol ediliyor...", yesterday)
            response_yesterday = fetch_rates_for_date_sync(yesterday)
            if response_yesterday and response_yesterday.rates:
                updated, inserted = upsert_rates(db, yesterday, response_yesterday.rates, source="tcmb")
                db.commit()
                if updated or inserted:
                    logger.info("[%s] Günlük kur → %d güncellendi, %d eklendi", yesterday, updated, inserted)
                else:
                    logger.info("[%s] Günlük kur zaten güncel", yesterday)
            else:
                # Dün tatil/hafta sonu — carry-forward
                exists_yesterday = db.query(ExchangeRate).filter(ExchangeRate.date == yesterday).first()
                if not exists_yesterday:
                    prev = db.query(ExchangeRate.date).filter(
                        ExchangeRate.date < yesterday,
                    ).order_by(ExchangeRate.date.desc()).first()
                    if prev:
                        carried = carry_forward_rates(db, yesterday, prev[0])
                        db.commit()
                        logger.info("[%s] %d kur taşındı (%s'den)", yesterday, carried, prev[0])

            # 3) Bugünü saatlik kurdan güncelle (reeskontkur endpoint)
            logger.info("[%s] Saatlik kur kontrol ediliyor...", today)
            response = fetch_hourly_rates_sync(today)
            if response and response.rates:
                # Saatlik kur bulundu → upsert
                updated, inserted = upsert_rates(db, today, response.rates, source="tcmb")
                db.commit()
                if updated or inserted:
                    logger.info("[%s] Saatlik kur → %d güncellendi, %d eklendi", today, updated, inserted)
                else:
                    logger.info("[%s] Saatlik kur zaten güncel", today)
            else:
                # Saatlik kur yok (hafta sonu/tatil veya saat erken)
                logger.info("[%s] Saatlik kur bulunamadı, today.xml deneniyor...", today)
                response_today = fetch_today_rates_sync()
                if response_today and response_today.rates and response_today.date == today:
                    updated, inserted = upsert_rates(db, today, response_today.rates, source="tcmb")
                    db.commit()
                    logger.info("[%s] today.xml → %d güncellendi, %d eklendi", today, updated, inserted)
                else:
                    # Hiçbir kaynak bugünün kurunu yayınlamamış → carry-forward
                    exists_today = db.query(ExchangeRate).filter(ExchangeRate.date == today).first()
                    if not exists_today:
                        prev = db.query(ExchangeRate.date).filter(
                            ExchangeRate.date < today,
                        ).order_by(ExchangeRate.date.desc()).first()
                        if prev:
                            carried = carry_forward_rates(db, today, prev[0])
                            db.commit()
                            logger.info("[%s] %d kur taşındı (%s'den)", today, carried, prev[0])

    except Exception as e:
        logger.error("HATA: %s", e, exc_info=True)
        db.rollback()
        sys.exit(1)
    else:
        # Başarıyla tamamlandı — amount_try güncelle + online kullanıcıları bildir
        from datetime import date as _date
        update_amount_try_for_date(db, _date.today())
        notify_finance_update()
    finally:
        db.close()


if __name__ == "__main__":
    main()
