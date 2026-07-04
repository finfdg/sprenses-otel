"""Kredi kartı ekstresi projeksiyonu — nakit akım için tahmini gelecek ekstreler.

Yüklü ekstresi olmayan aylar için, kartın kesim/son-ödeme günlerinden (en son yüklü
ekstreden türetilir, yoksa `details`'ten) tahmini ekstre kalemleri üretir. **Okuma-anında**
hesaplanır — kalıcı `finance_event` YAZILMAZ (bir tarih geçince bayat kalan FE sınıfı
sorununu önler; 2026-07-04 CC otomatik-eşleştirme düzeltmesindeki dersle aynı gerekçe).

Kural (kullanıcı kararı 2026-07-04):
- **Cari ay**, gerçek ekstre yoksa → tutar = kart **LİMİTİ** (`total_amount`) — en kötü
  senaryo rezervi; nakit planlamasında ayın giderine dahil (kullanıcı: "borç olarak yaz").
- **İleri aylar** → tutar = **0** (yalnız kesim + son ödeme tarihi göstergesi).
- Gerçek (yüklü) ekstresi olan due-ay atlanır — mevcut `upsert_cc_statement` mekanizması gösterir.
- Yalnız **aktif** kredi kartları (`type='kredi_karti'`, `status='active'`).

Bu servis router'dan import ETMEZ (services/ → model, tek yön). Router (`cc_projections.py`)
bu fonksiyonu çağırır.
"""

import calendar
import json
from datetime import date
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.credit_card_statement import CreditCardStatement
from app.models.credit_product import CreditProduct

# Cari ay + 11 ileri ay (bir yıllık ekstre takvimi)
HORIZON_MONTHS = 12


def _clamp_day(year: int, month: int, day: int) -> date:
    """Ay uzunluğunu aşan günü ayın son gününe kırp (ör. 31 → Şubat'ta 28/29)."""
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(max(day, 1), last))


def _add_months(year: int, month: int, delta: int) -> Tuple[int, int]:
    """(year, month) + delta ay → (year, month)."""
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _derive_days(db: Session, card: CreditProduct) -> Optional[dict]:
    """Kartın {cut_day, due_day, offset} değerlerini türet.

    Öncelik: EN SON yüklü ekstrenin gerçek günleri (kullanıcı: "yüklü ekstrelere bakarak
    çıkart"); yoksa `details.ekstre_kesim_gunu`/`son_odeme_gunu`. `offset` = son ödeme ile
    kesim arasındaki ay farkı (0 = aynı ay, 1 = sonraki ay). Hiçbiri yoksa None → kart atlanır.
    """
    latest = (
        db.query(CreditCardStatement)
        .filter(CreditCardStatement.credit_product_id == card.id)
        .order_by(CreditCardStatement.son_odeme_tarihi.desc())
        .first()
    )
    if latest and latest.kesim_tarihi and latest.son_odeme_tarihi:
        offset = (latest.son_odeme_tarihi.year - latest.kesim_tarihi.year) * 12 + (
            latest.son_odeme_tarihi.month - latest.kesim_tarihi.month
        )
        return {
            "cut_day": latest.kesim_tarihi.day,
            "due_day": latest.son_odeme_tarihi.day,
            "offset": max(0, offset),
        }

    try:
        det = json.loads(card.details) if card.details else {}
    except (json.JSONDecodeError, TypeError):
        det = {}
    cut_day = det.get("ekstre_kesim_gunu")
    due_day = det.get("son_odeme_gunu")
    if not cut_day or not due_day:
        return None
    cut_day, due_day = int(cut_day), int(due_day)
    # son ödeme günü kesimden küçükse ödeme sonraki aya taşar
    offset = 0 if due_day >= cut_day else 1
    return {"cut_day": cut_day, "due_day": due_day, "offset": offset}


def _projection_item(card: CreditProduct, due_date: date, cut_date: date,
                     amount: float, is_current: bool, has_limit: bool, seq: int) -> dict:
    """Frontend CashFlowItem şekliyle uyumlu tahmini kalem (null-safe alanlar dahil)."""
    amt = round(amount, 2)
    return {
        # gerçek FE id'leriyle çakışmayan yüksek-aralık sentetik id (yalnız {#each} anahtarı)
        "id": 900_000_000 + card.id * 1000 + seq,
        "date": due_date.isoformat(),
        "kesim_date": cut_date.isoformat(),
        "description": f"[Kredi Kartı] {card.name}",
        "amount": amt,
        "type": "expense",
        "source": "cc_payment",
        "currency": "TRY",
        "bank_name": card.bank_name,
        "card_id": card.id,
        "is_projected": True,
        "is_current_month": is_current,
        "has_limit": has_limit,
        "event_status": "projected",
        # CashFlowItem null-safe alanları
        "balance": None, "receipt_no": None, "iban": None, "account_id": None,
        "check_no": None, "check_status": None,
        "category_id": None, "category_name": None, "category_color": None,
        "tag_note": None, "tag_source": None,
        "vendor_id": None, "vendor_name": None, "vendor_code": None,
        "payment_method": "kredi_karti", "match_number": None,
        "amount_try": amt, "invoice_count": None,
        "is_matched": False,
    }


def compute_cc_projections(db: Session, today: Optional[date] = None,
                           horizon_months: int = HORIZON_MONTHS) -> List[dict]:
    """Tüm aktif kredi kartları için tahmini ekstre kalemleri (yüklü olmayan aylar)."""
    if today is None:
        today = date.today()

    cards = (
        db.query(CreditProduct)
        .filter(CreditProduct.type == "kredi_karti", CreditProduct.status == "active")
        .order_by(CreditProduct.id)
        .all()
    )

    out: List[dict] = []
    for card in cards:
        days = _derive_days(db, card)
        if not days:
            continue
        limit = float(card.total_amount or 0)
        has_limit = limit > 0

        # gerçek (yüklü) ekstresi olan due-aylar — projeksiyonda atlanır
        real_due = {
            (s.son_odeme_tarihi.year, s.son_odeme_tarihi.month)
            for s in db.query(CreditCardStatement).filter(
                CreditCardStatement.credit_product_id == card.id
            ).all()
            if s.son_odeme_tarihi
        }

        for i in range(horizon_months):
            y, m = _add_months(today.year, today.month, i)
            if (y, m) in real_due:
                continue
            due_date = _clamp_day(y, m, days["due_day"])
            cy, cm = _add_months(y, m, -days["offset"])
            cut_date = _clamp_day(cy, cm, days["cut_day"])
            is_current = i == 0
            # Cari ay → limit (rezerv); ileri aylar → 0 (yalnız tarih göstergesi)
            amount = limit if is_current else 0.0
            out.append(_projection_item(card, due_date, cut_date, amount, is_current, has_limit, i))

    return out
