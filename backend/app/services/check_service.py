"""Çek domain servis katmanı — durum güncelleme + iptal kademesi + finance_event tazeleme (HTTP'siz).

D1-2 (2026-06-22): Çek durum güncelleme mutasyon mantığı TEK kaynakta. Hem router endpoint'i
(`checks.py::update_check_status`) hem onay executor handler'ı (`_handle_finance_checks`) AYNI
fonksiyonu çağırır → router↔executor sapması (sessiz bug) yapısal olarak engellenir. Özellikle
**iptal kademesi** (eşleşmiş çek iptal → cari + banka eşleşmesini kaldır) iki yerde elle
tekrarlanıyordu; router değişse executor sessizce saparak yetim/yanlış eşleşme bırakabilirdi.

Yeniden yapılandırma (2026-09-02, grup "checks_summary"): `checks_summary(db)` gövdesi
`app/routers/finance/checks.py::checks_summary` endpoint'inden BİREBİR (verbatim) buraya taşındı —
parametre/ifade/yuvarlama/`date.today()`/`max(ExchangeRate.date)` aramaları değiştirilmedi
(finansal parmak-izi kapısı eski-kod/yeni-kod farkı SIFIR olmalı). Router endpoint'i aynı adla
kalır ve ince sarmalayıcı olarak `check_service.checks_summary(db)` döndürür; geriye uyumluluk için
`from app.routers.finance.checks import checks_summary` çağrısı (parmak-izi değişmezleri) aynı
sonucu üretmeye devam eder. Gövde içi lazy import'lar (`dt_date`, `ExchangeRate`) bilerek lazy kaldı.
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.bank_transaction import BankTransaction
from app.models.check import Check
from app.models.vendor_transaction import VendorTransaction
from app.services.finance_event_service import finance_event_svc


def apply_check_status(db: Session, check: Check, new_status: str) -> None:
    """Çek durumunu güncelle. İptal ise eşleşmeyi (cari + banka) kaldır, sonra finance_event tazele.

    HTTP'siz, commit'siz (çağıran commit eder). Router (`update_check_status`) ve onay executor'ı
    (`_handle_finance_checks`) ORTAK çağırır → davranış birebir.
    """
    # Eşleştirilmiş çekin iptal edilmesi → eşleşmeyi de kaldır
    if new_status == "cancelled":
        # Cari eşleşmesi (match_number ile direkt bul)
        if check.match_number:
            matched_vtx = db.query(VendorTransaction).filter(
                VendorTransaction.match_number == check.match_number,
            ).first()
            if matched_vtx:
                matched_vtx.match_number = None
                matched_vtx.payment_method = None
            check.match_number = None
            check.matched_vendor_id = None

        # Banka eşleşmesini de kaldır
        if check.bank_transaction_id:
            btx = db.query(BankTransaction).filter(BankTransaction.id == check.bank_transaction_id).first()
            if btx:
                btx.match_number = None
            check.bank_transaction_id = None

    check.status = new_status

    # finance_events'i güncelle (eşleşmişse banka hareketiyle birlikte)
    bank_tx = None
    if check.bank_transaction_id:
        bank_tx = db.query(BankTransaction).filter(BankTransaction.id == check.bank_transaction_id).first()
    finance_event_svc.upsert_check(db, check, bank_tx)


def checks_summary(db: Session):
    """Çek özeti — toplam, bekleyen, ödenen + EUR karşılığı.

    `checks.py::checks_summary` endpoint gövdesinin birebir taşınmış hâli (2026-09-02).
    """
    from datetime import date as dt_date

    from app.models.exchange_rate import ExchangeRate

    today = dt_date.today()

    total = db.query(func.count(Check.id)).scalar() or 0
    total_amount = db.query(func.coalesce(func.sum(Check.amount_tl), 0)).scalar()

    pending = db.query(func.count(Check.id)).filter(Check.status == "pending").scalar() or 0
    pending_amount = db.query(func.coalesce(func.sum(Check.amount_tl), 0)).filter(Check.status == "pending").scalar()

    overdue = db.query(func.count(Check.id)).filter(
        Check.status == "pending", Check.due_date < today
    ).scalar() or 0
    overdue_amount = db.query(func.coalesce(func.sum(Check.amount_tl), 0)).filter(
        Check.status == "pending", Check.due_date < today
    ).scalar()

    # EUR karşılığı: TL çekler kura bölünür, EUR çekler direkt eklenir
    pending_amount_eur = None
    # EUR çeklerin orijinal tutarı
    pending_eur_direct = float(
        db.query(func.coalesce(func.sum(Check.amount_currency), 0))
        .filter(Check.status == "pending", Check.currency == "EUR")
        .scalar()
    )
    # TL çeklerin toplamı
    pending_tl_only = float(
        db.query(func.coalesce(func.sum(Check.amount_tl), 0))
        .filter(Check.status == "pending", Check.currency != "EUR")
        .scalar()
    )
    latest_date = db.query(func.max(ExchangeRate.date)).scalar()
    if latest_date:
        eur_rate = db.query(ExchangeRate).filter(
            ExchangeRate.date == latest_date,
            ExchangeRate.currency_code == "EUR",
        ).first()
        if eur_rate and eur_rate.forex_buying and float(eur_rate.forex_buying) > 0:
            tl_as_eur = pending_tl_only / float(eur_rate.forex_buying)
            pending_amount_eur = round(tl_as_eur + pending_eur_direct, 2)
        elif pending_eur_direct > 0:
            # Kur yoksa sadece EUR çekleri göster
            pending_amount_eur = round(pending_eur_direct, 2)

    return {
        "total_count": total,
        "total_amount": float(total_amount),
        "pending_count": pending,
        "pending_amount": float(pending_amount),
        "pending_amount_eur": pending_amount_eur,
        "overdue_count": overdue,
        "overdue_amount": float(overdue_amount),
    }
