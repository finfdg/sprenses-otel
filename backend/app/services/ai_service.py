"""Yapay Zeka Asistanı — domain servis katmanı (HTTP'siz).

Claude API (Anthropic) tool-use döngüsünü yönetir. Asistan yalnız burada tanımlı
**salt-okuma** tool'larını çağırabilir; ham SQL ne kullanıcı ne de model tarafından
yazılır. Her tool, isteği yapan kullanıcının izinlerine (`user_can`) tabidir → düşük
yetkili bir kullanıcı, göremediği modülün verisini asistana sordurtamaz.

FAZ 1: yalnız okuma tool'ları (nakit akım özeti, bekleyen çekler, cari borç özeti).
Yazma/mutasyon tool'ları FAZ 2'de eklenecek ve `check_approval()` içinden geçecek
(bkz. docs/modules/ai-asistan.md).

Yazar: Sprenses Otel Yönetim Sistemi
"""

import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import anthropic
import pytz
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.config import settings
from app.middleware.auth import user_can
from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.check import Check
from app.models.credit_product import CreditProduct
from app.models.finance_event import (
    DIRECTION_EXPENSE,
    DIRECTION_INCOME,
    FinanceEvent,
)
from app.models.reservation import Reservation
from app.constants import SourceType
from app.models.scheduled import ScheduledDefinition
from app.models.user import User
from app.models.vendor import Vendor
from app.models.vendor import STATUS_NORMAL, STATUS_PAYMENT_BANNED, VENDOR_STATUS_LABELS
from app.models.vendor_transaction import VendorTransaction
from app.services import advance_service, check_service, scheduled_service, vendor_service
from app.utils.approval_check import check_approval
from app.utils.audit import log_action

logger = logging.getLogger(__name__)

# ── Sabitler ──────────────────────────────────────────────────────────────────
_TZ_ISTANBUL = pytz.timezone(settings.timezone)
_MAX_TOOL_ITERATIONS = 6          # sonsuz döngü koruması
_MAX_TOKENS = 2048                # kısa/öz yanıt

SYSTEM_PROMPT = (
    "Sen Sprenses Otel Yönetim Sistemi'nin yapay zeka asistanısın. Görevin, "
    "kullanıcının finans/otel verileriyle ilgili sorularını yanıtlamak.\n"
    "KURALLAR:\n"
    "- YALNIZCA Türkçe yanıt ver, doğru Türkçe karakter kullan (ö, ü, ç, ş, ı, ğ, İ).\n"
    "- Rakamsal/finansal bilgiyi ASLA uydurma. Yalnız sana verilen tool (araç) "
    "sonuçlarına dayan. Veriye ihtiyacın varsa ilgili tool'u çağır.\n"
    "- Bir tool 'yetkiniz yok' hatası dönerse, kullanıcıya bu veriye erişim izni "
    "olmadığını nazikçe söyle; tahmin yürütme.\n"
    "- Kısa ve öz yanıt ver. Para tutarlarını Türk formatında (binlik ayırıcı nokta, "
    "ondalık virgül) ve para birimini (₺/EUR/USD) MUTLAKA belirterek yaz.\n"
    "- BİÇİM: Birden fazla kalem/satır içeren verileri (listeler, dökümler, para-bazlı "
    "özetler, karşılaştırmalar) **markdown tablosu** olarak sun — düz cümle yerine tablo "
    "tercih et. Tutar kolonlarını sağa hizala. Önemli sayıları **kalın** yaz. Kısa "
    "başlıklar (##) kullanabilirsin. Cevaplar tutarlı ve okunur bir düzende olsun.\n"
    "- GRAFİK: Karşılaştırma (ör. en borçlu cariler) veya trend (ör. günlere/aylara göre "
    "akım) içeren sorularda, tablonun YANINDA `grafik_olustur` aracıyla uygun bir grafik "
    "de ekle (karşılaştırma=bar, zaman serisi=line). Grafik metnin yerine geçmez, EK olur.\n"
    "- Tarih bilmiyorsan bugünün tarihini tool'lara varsayılan bırakabilirsin.\n"
    "- Kullanıcı bir DEĞİŞİKLİK ya da EKLEME isterse (cari vadesi değiştir, çek durumu "
    "güncelle, ödeme yasağı koy/kaldır, avans ekle, düzenli ödeme ekle) ilgili aracı "
    "çağır. Bu araçlar işlemi HEMEN YAPMAZ; kullanıcının onayına sunar. Kullanıcıya "
    "onayını beklediğini belirt.\n"
    "- Sadece final cevabı yaz; iç muhakemeni kullanıcıya gösterme."
)


# ── Yardımcılar ───────────────────────────────────────────────────────────────
def _istanbul_today() -> date:
    """İstanbul-açık bugün (process TZ'sinden bağımsız — CLAUDE.md tarih kuralı)."""
    return datetime.now(_TZ_ISTANBUL).date()


def _parse_date(value: Optional[str], default: date) -> date:
    """ISO tarih string'ini date'e çevir; boş/geçersizse default döner."""
    if not value:
        return default
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return default


def _num(value: Any) -> float:
    """Decimal/None → float (JSON için)."""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _denied(module_code: str) -> Dict[str, Any]:
    return {
        "_error": True,
        "mesaj": f"Bu veriye erişim izniniz yok (modül: {module_code}).",
    }


# ── Tool uygulamaları (salt-okuma) ────────────────────────────────────────────
def _tool_nakit_akim_ozeti(
    db: Session, user: User, args: Dict[str, Any]
) -> Dict[str, Any]:
    """Verilen tarih aralığında gelir/gider/net — PARA BİRİMİNE GÖRE AYRI.

    Kayıtlar farklı para birimlerinde (EUR/TRY/USD) olabilir ve `amount` her zaman
    kaydın KENDİ para birimindedir. Farklı birimler BİRBİRİNE TOPLANMAZ (aksi halde
    EUR tutarı TL sanılır — gerçek hata örneği: 250.000 EUR giriş "250.000 TL" görünüyordu).
    """
    if not user_can(db, user, "finance.cash_flow", "view"):
        return _denied("finance.cash_flow")

    today = _istanbul_today()
    baslangic = _parse_date(args.get("baslangic_tarih"), today.replace(day=1))
    bitis = _parse_date(args.get("bitis_tarih"), today)
    if baslangic > bitis:
        baslangic, bitis = bitis, baslangic

    # amount her zaman kaydın kendi para birimindedir → currency'ye göre grupla
    rows = (
        db.query(FinanceEvent.currency, FinanceEvent.direction, func.sum(FinanceEvent.amount))
        .filter(FinanceEvent.event_date >= baslangic)
        .filter(FinanceEvent.event_date <= bitis)
        .group_by(FinanceEvent.currency, FinanceEvent.direction)
        .all()
    )
    acc: Dict[str, Dict[str, float]] = {}
    for currency, direction, total in rows:
        cur = currency or "TRY"
        entry = acc.setdefault(cur, {"gelir": 0.0, "gider": 0.0})
        if direction == DIRECTION_INCOME:
            entry["gelir"] = _num(total)
        elif direction == DIRECTION_EXPENSE:
            entry["gider"] = _num(total)

    para_bazli = [
        {
            "para_birimi": cur,
            "gelir": round(v["gelir"], 2),
            "gider": round(v["gider"], 2),
            "net": round(v["gelir"] - v["gider"], 2),
        }
        for cur, v in sorted(acc.items())
    ]

    return {
        "baslangic": baslangic.isoformat(),
        "bitis": bitis.isoformat(),
        "para_bazli": para_bazli,
        "not": "Her satır AYRI bir para birimidir; farklı para birimlerini birbirine "
               "TOPLAMA. Yanıtta her tutarı kendi para birimiyle (EUR/TRY/USD) belirt.",
    }


def _tool_bekleyen_cekler(
    db: Session, user: User, args: Dict[str, Any]
) -> Dict[str, Any]:
    """Vadesi önümüzdeki N gün içinde olan, durumu 'pending' verilen çekler."""
    if not user_can(db, user, "finance.checks", "view"):
        return _denied("finance.checks")

    try:
        gun = int(args.get("gun_sayisi", 30))
    except (ValueError, TypeError):
        gun = 30
    gun = max(1, min(gun, 365))

    today = _istanbul_today()
    son = today + timedelta(days=gun)

    q = (
        db.query(Check)
        .filter(Check.status == "pending")
        .filter(Check.due_date >= today)
        .filter(Check.due_date <= son)
        .order_by(Check.due_date.asc())
    )
    checks = q.all()
    toplam = sum(_num(c.amount_tl) for c in checks)
    liste = [
        {
            "cek_no": c.check_no,
            "cari": c.vendor_name,
            "vade": c.due_date.isoformat() if c.due_date else None,
            "tutar_tl": round(_num(c.amount_tl), 2),
            "banka": c.bank_name,
        }
        for c in checks[:20]
    ]
    return {
        "gun_sayisi": gun,
        "adet": len(checks),
        "toplam_tutar_tl": round(toplam, 2),
        "cekler": liste,
        "not": ("İlk 20 çek listelendi." if len(checks) > 20 else None),
    }


def _tool_cari_borc_ozeti(
    db: Session, user: User, args: Dict[str, Any]
) -> Dict[str, Any]:
    """En yüksek bakiyeli (borçlu) cariler — bakiye = SUM(borç) - SUM(alacak)."""
    if not user_can(db, user, "finance.cariler", "view"):
        return _denied("finance.cariler")

    try:
        limit = int(args.get("limit", 5))
    except (ValueError, TypeError):
        limit = 5
    limit = max(1, min(limit, 50))

    bakiye = (func.sum(VendorTransaction.borc) - func.sum(VendorTransaction.alacak))
    rows = (
        db.query(Vendor.hesap_kodu, Vendor.hesap_adi, bakiye.label("bakiye"))
        .join(VendorTransaction, VendorTransaction.vendor_id == Vendor.id)
        .group_by(Vendor.id, Vendor.hesap_kodu, Vendor.hesap_adi)
        .order_by(bakiye.desc())
        .limit(limit)
        .all()
    )
    liste = [
        {
            "hesap_kodu": r.hesap_kodu,
            "hesap_adi": r.hesap_adi,
            "bakiye": round(_num(r.bakiye), 2),
        }
        for r in rows
    ]
    return {"limit": limit, "cariler": liste, "para_birimi": "TRY"}


def _tool_cari_detay(
    db: Session, user: User, args: Dict[str, Any]
) -> Dict[str, Any]:
    """Bir carinin detayları: ödeme vadesi, durum, bakiye, iletişim."""
    if not user_can(db, user, "finance.cariler", "view"):
        return _denied("finance.cariler")
    kod = str(args.get("hesap_kodu") or "").strip()
    if not kod:
        return {"_error": True, "mesaj": "Cari hesap kodu ya da adı belirtilmeli."}
    v = db.query(Vendor).filter(Vendor.hesap_kodu == kod).first()
    if v is None:
        v = db.query(Vendor).filter(Vendor.hesap_adi.ilike(f"%{kod}%")).first()
    if v is None:
        return {"_error": True, "mesaj": f"'{kod}' ile eşleşen cari bulunamadı."}

    bakiye = (
        db.query(func.sum(VendorTransaction.borc) - func.sum(VendorTransaction.alacak))
        .filter(VendorTransaction.vendor_id == v.id)
        .scalar()
    )
    return {
        "hesap_kodu": v.hesap_kodu,
        "hesap_adi": v.hesap_adi,
        "odeme_vadesi_gun": v.payment_days,
        "durum": VENDOR_STATUS_LABELS.get(v.status, v.status),
        "bakiye": round(_num(bakiye), 2),
        "para_birimi": "TRY",
        "yetkili": v.contact_person,
        "telefon": v.phone,
        "eposta": v.email,
    }


def _tool_banka_bakiyeleri(
    db: Session, user: User, args: Dict[str, Any]
) -> Dict[str, Any]:
    """Aktif banka hesaplarının güncel bakiyeleri (her hesabın SON işlem bakiyesi)."""
    if not user_can(db, user, "finance.banks", "view"):
        return _denied("finance.banks")

    accounts = db.query(BankAccount).filter(BankAccount.is_active.is_(True)).all()
    if not accounts:
        return {"para_bazli": [], "hesaplar": [], "not": "Aktif banka hesabı yok."}

    account_ids = [a.id for a in accounts]
    # Her hesabın en son işleminin bakiyesi (window function — banks.py deseni)
    last_subq = (
        db.query(
            BankTransaction.account_id,
            BankTransaction.balance,
            func.row_number().over(
                partition_by=BankTransaction.account_id,
                order_by=[desc(BankTransaction.date), desc(BankTransaction.id)],
            ).label("rn"),
        )
        .filter(
            BankTransaction.account_id.in_(account_ids),
            BankTransaction.balance.isnot(None),
        )
        .subquery()
    )
    rows = (
        db.query(last_subq.c.account_id, last_subq.c.balance)
        .filter(last_subq.c.rn == 1)
        .all()
    )
    balance_map = {aid: bal for aid, bal in rows}

    acc_cur: Dict[str, float] = {}
    hesaplar = []
    for a in accounts:
        bal = _num(balance_map.get(a.id, 0))
        cur = a.currency or "TRY"
        acc_cur[cur] = acc_cur.get(cur, 0.0) + bal
        hesaplar.append({"banka": a.bank_name, "para_birimi": cur, "bakiye": round(bal, 2)})

    para_bazli = [{"para_birimi": c, "toplam_bakiye": round(v, 2)} for c, v in sorted(acc_cur.items())]
    hesaplar.sort(key=lambda h: h["bakiye"], reverse=True)
    return {
        "para_bazli": para_bazli,
        "hesaplar": hesaplar[:25],
        "not": "Her hesabın son işlem bakiyesi; para birimleri ayrıdır (toplama yok).",
    }


def _tool_kredi_durumu(
    db: Session, user: User, args: Dict[str, Any]
) -> Dict[str, Any]:
    """Aktif kredilerin para birimine göre toplam/kalan borcu + en büyük 10 kredi."""
    if not user_can(db, user, "finance.krediler", "view"):
        return _denied("finance.krediler")

    rows = (
        db.query(
            CreditProduct.currency,
            func.count(CreditProduct.id),
            func.sum(CreditProduct.total_amount),
            func.sum(CreditProduct.remaining_amount),
        )
        .filter(CreditProduct.status == "active")
        .group_by(CreditProduct.currency)
        .all()
    )
    para_bazli = [
        {
            "para_birimi": cur or "TRY",
            "adet": int(adet),
            "toplam": round(_num(tot), 2),
            "kalan_borc": round(_num(rem), 2),
        }
        for cur, adet, tot, rem in rows
    ]
    top = (
        db.query(CreditProduct)
        .filter(CreditProduct.status == "active")
        .order_by(CreditProduct.remaining_amount.desc())
        .limit(10)
        .all()
    )
    liste = [
        {
            "ad": c.name,
            "tip": c.type,
            "banka": c.bank_name,
            "kalan_borc": round(_num(c.remaining_amount), 2),
            "para_birimi": c.currency,
        }
        for c in top
    ]
    return {
        "para_bazli": para_bazli,
        "krediler": liste,
        "not": "Yalnız aktif krediler; para birimleri ayrıdır (toplama yok).",
    }


def _tool_yaklasan_odemeler(
    db: Session, user: User, args: Dict[str, Any]
) -> Dict[str, Any]:
    """Önümüzdeki N günde vadesi gelen giderler (finance_events) — para bazlı + liste."""
    if not user_can(db, user, "finance.cash_flow", "view"):
        return _denied("finance.cash_flow")

    try:
        gun = int(args.get("gun_sayisi", 7))
    except (TypeError, ValueError):
        gun = 7
    gun = max(1, min(gun, 90))

    today = _istanbul_today()
    son = today + timedelta(days=gun)
    events = (
        db.query(FinanceEvent)
        .filter(FinanceEvent.direction == DIRECTION_EXPENSE)
        .filter(FinanceEvent.event_date >= today)
        .filter(FinanceEvent.event_date <= son)
        .order_by(FinanceEvent.event_date.asc())
        .all()
    )
    acc: Dict[str, float] = {}
    for e in events:
        cur = e.currency or "TRY"
        acc[cur] = acc.get(cur, 0.0) + _num(e.amount)
    para_bazli = [{"para_birimi": c, "toplam": round(v, 2)} for c, v in sorted(acc.items())]
    liste = [
        {
            "tarih": e.event_date.isoformat() if e.event_date else None,
            "aciklama": (e.description or e.category_name or e.vendor_code or "")[:80],
            "tutar": round(_num(e.amount), 2),
            "para_birimi": e.currency or "TRY",
        }
        for e in events[:20]
    ]
    return {
        "gun_sayisi": gun,
        "adet": len(events),
        "para_bazli": para_bazli,
        "odemeler": liste,
        "not": ("İlk 20 kalem listelendi." if len(events) > 20 else None),
    }


def _tool_rezervasyon_ozeti(
    db: Session, user: User, args: Dict[str, Any]
) -> Dict[str, Any]:
    """Giriş tarihi verilen aralıkta olan rezervasyonlar: adet, oda, geceleme, ciro."""
    if not user_can(db, user, "sales.hotel_reservation", "view"):
        return _denied("sales.hotel_reservation")

    today = _istanbul_today()
    baslangic = _parse_date(args.get("baslangic_tarih"), today)
    bitis = _parse_date(args.get("bitis_tarih"), today + timedelta(days=30))
    if baslangic > bitis:
        baslangic, bitis = bitis, baslangic

    row = (
        db.query(
            func.count(Reservation.id),
            func.sum(Reservation.rooms),
            func.sum(Reservation.nights),
            func.sum(Reservation.net_amount),
        )
        .filter(Reservation.checkin_date >= baslangic)
        .filter(Reservation.checkin_date <= bitis)
        .first()
    )
    adet = int(row[0] or 0)
    return {
        "baslangic": baslangic.isoformat(),
        "bitis": bitis.isoformat(),
        "rezervasyon_adedi": adet,
        "toplam_oda": int(row[1] or 0),
        "toplam_geceleme": int(row[2] or 0),
        "toplam_ciro_eur": round(_num(row[3]), 2),
        "not": "Giriş (check-in) tarihine göre; ciro net tutar (EUR) toplamıdır.",
    }


def compute_digest(db: Session, user: User, gun: int = 7) -> Dict[str, Any]:
    """Günün özeti — kullanıcının görme yetkisi olan bölümlerden derlenir.

    Bölümler: yaklaşan ödemeler (cash_flow), vadesi gelen çekler (checks), bugünkü
    rezervasyon girişleri (hotel_reservation). Her bölüm yalnız izin varsa eklenir.
    Hem `gunun_ozeti` tool'u hem sabah bildirim script'i bunu kullanır.
    """
    today = _istanbul_today()
    son = today + timedelta(days=gun)
    bolumler: List[Dict[str, Any]] = []

    if user_can(db, user, "finance.cash_flow", "view"):
        rows = (
            db.query(FinanceEvent.currency, func.sum(FinanceEvent.amount))
            .filter(FinanceEvent.direction == DIRECTION_EXPENSE)
            .filter(FinanceEvent.event_date >= today)
            .filter(FinanceEvent.event_date <= son)
            .group_by(FinanceEvent.currency)
            .all()
        )
        adet = (
            db.query(func.count(FinanceEvent.id))
            .filter(FinanceEvent.direction == DIRECTION_EXPENSE)
            .filter(FinanceEvent.event_date >= today)
            .filter(FinanceEvent.event_date <= son)
            .scalar()
        )
        bolumler.append({
            "baslik": f"Önümüzdeki {gun} günde ödemeler",
            "adet": int(adet or 0),
            "para_bazli": [{"para_birimi": c or "TRY", "toplam": round(_num(t), 2)} for c, t in rows],
        })

    if user_can(db, user, "finance.checks", "view"):
        checks = (
            db.query(Check)
            .filter(Check.status == "pending")
            .filter(Check.due_date >= today)
            .filter(Check.due_date <= son)
            .all()
        )
        bolumler.append({
            "baslik": f"Önümüzdeki {gun} günde vadesi gelen çekler",
            "adet": len(checks),
            "toplam_tl": round(sum(_num(c.amount_tl) for c in checks), 2),
        })

    if user_can(db, user, "sales.hotel_reservation", "view"):
        row = (
            db.query(func.count(Reservation.id), func.sum(Reservation.rooms))
            .filter(Reservation.checkin_date == today)
            .first()
        )
        bolumler.append({
            "baslik": "Bugün giriş yapan rezervasyonlar",
            "adet": int(row[0] or 0),
            "oda": int(row[1] or 0),
        })

    return {"tarih": today.isoformat(), "gun": gun, "bolumler": bolumler}


def _tool_gunun_ozeti(
    db: Session, user: User, args: Dict[str, Any]
) -> Dict[str, Any]:
    """Bugünün finans/satış özeti — yaklaşan ödemeler, çekler, rezervasyon girişleri."""
    try:
        gun = int(args.get("gun_sayisi", 7))
    except (TypeError, ValueError):
        gun = 7
    gun = max(1, min(gun, 30))
    d = compute_digest(db, user, gun)
    if not d["bolumler"]:
        return {"_error": True, "mesaj": "Özet için görme yetkiniz olan bir modül yok."}
    return d


def _tool_grafik_olustur(
    db: Session, user: User, args: Dict[str, Any]
) -> Dict[str, Any]:
    """Bir veri kümesini grafik olarak göstermek için çağrılır (mutasyon yok).

    Veriyi çizmez; yalnız doğrulanmış bir grafik spec'i döndürür. Frontend hafif SVG
    olarak çizer. Veri, izin-kontrollü okuma araçlarından geldiği için ayrı izin gerekmez.
    """
    tip = str(args.get("tip") or "bar").strip().lower()
    if tip not in ("bar", "line"):
        tip = "bar"
    baslik = str(args.get("baslik") or "").strip()[:120]
    para = str(args.get("para_birimi") or "").strip()[:5]

    seri_ham = args.get("seri")
    seri: List[Dict[str, Any]] = []
    if isinstance(seri_ham, list):
        for item in seri_ham[:40]:  # en çok 40 nokta
            if not isinstance(item, dict):
                continue
            etiket = str(item.get("etiket") or "").strip()[:60]
            try:
                deger = float(item.get("deger"))
            except (TypeError, ValueError):
                continue
            if not etiket:
                continue
            seri.append({"etiket": etiket, "deger": round(deger, 2)})

    if len(seri) < 2:
        return {"_error": True, "mesaj": "Grafik için en az 2 geçerli veri noktası gerekli."}

    return {
        "_grafik": True,
        "grafik": {"tip": tip, "baslik": baslik, "para_birimi": para, "seri": seri},
    }


# Tool adı → uygulama eşlemesi
_TOOL_IMPL = {
    "nakit_akim_ozeti": _tool_nakit_akim_ozeti,
    "bekleyen_cekler": _tool_bekleyen_cekler,
    "cari_borc_ozeti": _tool_cari_borc_ozeti,
    "cari_detay": _tool_cari_detay,
    "banka_bakiyeleri": _tool_banka_bakiyeleri,
    "kredi_durumu": _tool_kredi_durumu,
    "yaklasan_odemeler": _tool_yaklasan_odemeler,
    "rezervasyon_ozeti": _tool_rezervasyon_ozeti,
    "gunun_ozeti": _tool_gunun_ozeti,
    "grafik_olustur": _tool_grafik_olustur,
}

# Claude'a sunulan tool tanımları (JSON şeması)
_TOOL_DEFS: List[Dict[str, Any]] = [
    {
        "name": "nakit_akim_ozeti",
        "description": (
            "Belirli bir tarih aralığındaki nakit girişi (gelir), çıkışı (gider) ve "
            "net akışı PARA BİRİMİNE GÖRE AYRI döndürür (EUR/TRY/USD). Tek gün için "
            "başlangıç ve bitişi aynı ver. Tarih verilmezse ay başından bugüne. "
            "ÖNEMLİ: Farklı para birimlerini birbirine TOPLAMA; her tutarı kendi "
            "birimiyle belirt."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "baslangic_tarih": {
                    "type": "string",
                    "description": "Başlangıç tarihi (YYYY-AA-GG). Opsiyonel.",
                },
                "bitis_tarih": {
                    "type": "string",
                    "description": "Bitiş tarihi (YYYY-AA-GG). Opsiyonel.",
                },
            },
        },
    },
    {
        "name": "bekleyen_cekler",
        "description": (
            "Vadesi önümüzdeki N gün içinde dolacak, henüz ödenmemiş (pending) "
            "verilen çekleri listeler; toplam tutar ve adet döndürür."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gun_sayisi": {
                    "type": "integer",
                    "description": "Kaç gün ilerisine bakılacak (varsayılan 30).",
                },
            },
        },
    },
    {
        "name": "cari_borc_ozeti",
        "description": (
            "En yüksek bakiyeli (en borçlu) carileri listeler. Bakiye = toplam borç "
            "- toplam alacak. 'limit' ile kaç cari döneceği belirlenir (varsayılan 5)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Listelenecek cari sayısı (varsayılan 5).",
                },
            },
        },
    },
    {
        "name": "cari_detay",
        "description": (
            "Belirli bir carinin detaylarını döndürür: ödeme vadesi (gün), durum "
            "(normal/ödeme yasaklısı), güncel bakiye ve iletişim bilgileri. 'X carisinin "
            "vadesi kaç gün', 'X'in bakiyesi ne' gibi sorularda kullan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hesap_kodu": {"type": "string", "description": "Cari hesap kodu veya adı."},
            },
            "required": ["hesap_kodu"],
        },
    },
    {
        "name": "banka_bakiyeleri",
        "description": (
            "Aktif banka hesaplarının güncel bakiyelerini (her hesabın son işlem "
            "bakiyesi) para birimine göre toplam + hesap listesi olarak döndürür. "
            "'Bankada ne kadar param var', 'banka bakiyeleri' gibi sorularda kullan."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "kredi_durumu",
        "description": (
            "Aktif kredilerin para birimine göre toplam ve kalan borcunu, ayrıca en "
            "büyük kredileri döndürür. 'Kredi borcum ne kadar', 'hangi kredilerim var' "
            "gibi sorularda kullan."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "yaklasan_odemeler",
        "description": (
            "Önümüzdeki N günde vadesi gelen giderleri (çek/kredi/vergi/kira/maaş vb. "
            "tüm nakit çıkışları) para birimine göre toplam + liste olarak döndürür. "
            "'Bu hafta ne ödeyeceğim', 'yaklaşan ödemeler' gibi sorularda kullan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gun_sayisi": {
                    "type": "integer",
                    "description": "Kaç gün ilerisine bakılacak (varsayılan 7).",
                },
            },
        },
    },
    {
        "name": "rezervasyon_ozeti",
        "description": (
            "Giriş (check-in) tarihi verilen aralıkta olan otel rezervasyonlarının "
            "özetini döndürür: rezervasyon adedi, toplam oda, geceleme ve ciro (EUR). "
            "Tarih verilmezse bugünden 30 gün ileri."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "baslangic_tarih": {"type": "string", "description": "Başlangıç (YYYY-AA-GG). Opsiyonel."},
                "bitis_tarih": {"type": "string", "description": "Bitiş (YYYY-AA-GG). Opsiyonel."},
            },
        },
    },
    {
        "name": "gunun_ozeti",
        "description": (
            "Bugünün finans/satış özetini döndürür: önümüzdeki günlerde yaklaşan "
            "ödemeler, vadesi gelen çekler ve bugün giriş yapan rezervasyonlar. "
            "'Bugünün özeti', 'gündemimde ne var', 'neye dikkat etmeliyim' gibi "
            "sorularda kullan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gun_sayisi": {
                    "type": "integer",
                    "description": "Kaç gün ileriye bakılacak (varsayılan 7).",
                },
            },
        },
    },
    {
        "name": "grafik_olustur",
        "description": (
            "Bir veri kümesini GRAFİK olarak göstermek için çağrılır. Kategorik "
            "karşılaştırmalar (en borçlu cariler, para-bazlı özet) için tip='bar'; "
            "zaman serisi/trend (günlere veya aylara göre nakit akım) için tip='line'. "
            "Veriyi önce ilgili okuma aracından al, sonra noktaları buraya aktar. "
            "En az 2 nokta gerekir. Grafik metin/tabloya EK olarak gösterilir."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tip": {"type": "string", "description": "'bar' veya 'line'."},
                "baslik": {"type": "string", "description": "Grafik başlığı."},
                "para_birimi": {
                    "type": "string",
                    "description": "Değerlerin para birimi (varsa, ör. EUR/TRY).",
                },
                "seri": {
                    "type": "array",
                    "description": "Veri noktaları (2-40 adet).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "etiket": {"type": "string", "description": "Kategori/tarih etiketi."},
                            "deger": {"type": "number", "description": "Sayısal değer."},
                        },
                        "required": ["etiket", "deger"],
                    },
                },
            },
            "required": ["tip", "seri"],
        },
    },
]


# ══ FAZ 2 — Yazma aksiyonları (öner → onayla → uygula) ═══════════════════════════
# GÜVENLİK: Chat döngüsündeki "öner" araçları ASLA mutasyon yapmaz — yalnız doğrular
# ve bir öneri döndürür. Gerçek mutasyon SADECE kullanıcı arayüzde (ConfirmDialog)
# onayladıktan sonra ayrı /api/ai/uygula endpoint'inden execute_action() ile yapılır
# ve check_approval() + hedef modül can_use izninden geçer. Böylece bir prompt injection
# bile korumaların ötesine geçemez (en fazla onay talebi oluşturur). Payload anahtarları
# router endpoint'leriyle BİREBİR aynıdır → onay gerekirse mevcut executor doğru uygular.

_DURUM_ES = {  # kullanıcı ifadesi → çek durum kodu
    "paid": "paid", "odendi": "paid", "ödendi": "paid", "ödendı": "paid",
    "cancelled": "cancelled", "canceled": "cancelled", "iptal": "cancelled",
    "pending": "pending", "bekliyor": "pending", "beklemede": "pending",
}
_DURUM_LABEL = {"pending": "Bekliyor", "paid": "Ödendi", "cancelled": "İptal"}


def _propose_cari_vade(db: Session, user: User, args: Dict[str, Any]) -> Dict[str, Any]:
    """Cari ödeme vadesi değişikliğini ÖNERİR (mutasyon yok)."""
    if not user_can(db, user, "finance.cariler", "use"):
        return {"_error": True, "mesaj": "Cari güncelleme yetkiniz yok (finance.cariler)."}
    kod = str(args.get("hesap_kodu") or "").strip()
    if not kod:
        return {"_error": True, "mesaj": "Cari hesap kodu ya da adı belirtilmeli."}
    try:
        yeni = int(args.get("yeni_vade_gun"))
    except (TypeError, ValueError):
        return {"_error": True, "mesaj": "Geçerli bir vade gün sayısı belirtilmeli."}
    if yeni < 0:
        return {"_error": True, "mesaj": "Vade gün sayısı negatif olamaz."}

    vendor = db.query(Vendor).filter(Vendor.hesap_kodu == kod).first()
    if vendor is None:
        vendor = db.query(Vendor).filter(Vendor.hesap_adi.ilike(f"%{kod}%")).first()
    if vendor is None:
        return {"_error": True, "mesaj": f"'{kod}' ile eşleşen cari bulunamadı."}

    return {
        "_propose": True,
        "action_key": "cari_vade",
        "entity_id": vendor.id,
        "payload": {"payment_days": yeni},
        "ozet": (
            f"'{vendor.hesap_adi}' ({vendor.hesap_kodu}) carisinin ödeme vadesi "
            f"{vendor.payment_days} → {yeni} gün olarak güncellenecek."
        ),
    }


def _propose_cek_durum(db: Session, user: User, args: Dict[str, Any]) -> Dict[str, Any]:
    """Çek durumu değişikliğini ÖNERİR (mutasyon yok)."""
    if not user_can(db, user, "finance.checks", "use"):
        return {"_error": True, "mesaj": "Çek güncelleme yetkiniz yok (finance.checks)."}
    cek_no = str(args.get("cek_no") or "").strip()
    yeni = _DURUM_ES.get(str(args.get("yeni_durum") or "").strip().lower())
    if not cek_no:
        return {"_error": True, "mesaj": "Çek numarası belirtilmeli."}
    if yeni is None:
        return {"_error": True, "mesaj": "Durum 'ödendi', 'iptal' veya 'bekliyor' olmalı."}

    checks = db.query(Check).filter(Check.check_no == cek_no).all()
    if not checks:
        return {"_error": True, "mesaj": f"'{cek_no}' numaralı çek bulunamadı."}
    if len(checks) > 1:
        return {
            "_error": True,
            "mesaj": f"'{cek_no}' numarasıyla birden fazla çek var; bu işlemi "
                     "Çekler modülünden yapmanız gerekiyor.",
        }
    check = checks[0]
    return {
        "_propose": True,
        "action_key": "cek_durum",
        "entity_id": check.id,
        "payload": {"new_status": yeni},
        "ozet": (
            f"'{check.check_no}' numaralı çekin ({check.vendor_name}) durumu "
            f"{_DURUM_LABEL.get(check.status, check.status)} → {_DURUM_LABEL[yeni]} "
            "olarak güncellenecek."
        ),
    }


_FREKANS_ES = {  # kullanıcı ifadesi → frequency kodu
    "monthly": "monthly", "aylik": "monthly", "aylık": "monthly", "her ay": "monthly",
    "quarterly": "quarterly", "ceyreklik": "quarterly", "çeyreklik": "quarterly",
    "3 aylik": "quarterly", "3 aylık": "quarterly", "uc aylik": "quarterly",
    "yearly": "yearly", "yillik": "yearly", "yıllık": "yearly", "senelik": "yearly",
}
_FREKANS_LABEL = {"monthly": "aylık", "quarterly": "3 aylık", "yearly": "yıllık"}


def _propose_cari_odeme_yasagi(db: Session, user: User, args: Dict[str, Any]) -> Dict[str, Any]:
    """Cari ödeme yasağı koyma/kaldırmayı ÖNERİR (mutasyon yok)."""
    if not user_can(db, user, "finance.cariler", "use"):
        return {"_error": True, "mesaj": "Cari güncelleme yetkiniz yok (finance.cariler)."}
    kod = str(args.get("hesap_kodu") or "").strip()
    if not kod:
        return {"_error": True, "mesaj": "Cari hesap kodu ya da adı belirtilmeli."}
    yasakli = bool(args.get("yasakli"))

    vendor = db.query(Vendor).filter(Vendor.hesap_kodu == kod).first()
    if vendor is None:
        vendor = db.query(Vendor).filter(Vendor.hesap_adi.ilike(f"%{kod}%")).first()
    if vendor is None:
        return {"_error": True, "mesaj": f"'{kod}' ile eşleşen cari bulunamadı."}

    yeni_status = STATUS_PAYMENT_BANNED if yasakli else STATUS_NORMAL
    eylem = "ödeme yasağı KONACAK" if yasakli else "ödeme yasağı KALDIRILACAK"
    return {
        "_propose": True,
        "action_key": "cari_durum",
        "entity_id": vendor.id,
        "payload": {"status": yeni_status},
        "ozet": f"'{vendor.hesap_adi}' ({vendor.hesap_kodu}) carisine {eylem}.",
    }


def _propose_avans_ekle(db: Session, user: User, args: Dict[str, Any]) -> Dict[str, Any]:
    """Yeni avans kaydı eklemeyi ÖNERİR (mutasyon yok)."""
    if not user_can(db, user, "finance.avanslar", "use"):
        return {"_error": True, "mesaj": "Avans ekleme yetkiniz yok (finance.avanslar)."}
    acente = str(args.get("acente_adi") or "").strip()
    if not acente:
        return {"_error": True, "mesaj": "Acente/operatör adı belirtilmeli."}
    try:
        tutar = float(args.get("tutar"))
    except (TypeError, ValueError):
        return {"_error": True, "mesaj": "Geçerli bir tutar belirtilmeli."}
    if tutar <= 0:
        return {"_error": True, "mesaj": "Tutar sıfırdan büyük olmalı."}
    try:
        tarih = date.fromisoformat(str(args.get("tarih"))[:10])
    except (ValueError, TypeError):
        return {"_error": True, "mesaj": "Geçerli bir tarih (YYYY-AA-GG) belirtilmeli."}
    para = str(args.get("para_birimi") or "EUR").strip().upper()[:5] or "EUR"

    return {
        "_propose": True,
        "action_key": "avans_ekle",
        "entity_id": 0,
        "payload": {
            "agency_name": acente,
            "amount": tutar,
            "currency": para,
            "advance_date": tarih.isoformat(),
            "notes": (str(args.get("aciklama")).strip() or None) if args.get("aciklama") else None,
        },
        "ozet": f"'{acente}' için {tutar:,.2f} {para} avans (tarih {tarih.isoformat()}) eklenecek.",
    }


def _propose_duzenli_odeme(db: Session, user: User, args: Dict[str, Any]) -> Dict[str, Any]:
    """Yeni düzenli ödeme (planlı gider) tanımı eklemeyi ÖNERİR (mutasyon yok)."""
    if not user_can(db, user, "accounting.recurring", "use"):
        return {"_error": True, "mesaj": "Düzenli ödeme ekleme yetkiniz yok (accounting.recurring)."}
    ad = str(args.get("ad") or "").strip()
    if not ad:
        return {"_error": True, "mesaj": "Ödeme adı belirtilmeli."}
    try:
        tutar = float(args.get("tutar"))
    except (TypeError, ValueError):
        return {"_error": True, "mesaj": "Geçerli bir tutar belirtilmeli."}
    if tutar <= 0:
        return {"_error": True, "mesaj": "Tutar sıfırdan büyük olmalı."}
    frekans = _FREKANS_ES.get(str(args.get("siklik") or "monthly").strip().lower(), "monthly")
    try:
        odeme_gunu = int(args.get("odeme_gunu", 1))
    except (TypeError, ValueError):
        odeme_gunu = 1
    odeme_gunu = max(1, min(odeme_gunu, 28))
    try:
        baslangic_ayi = int(args.get("baslangic_ayi", 1))
    except (TypeError, ValueError):
        baslangic_ayi = 1
    baslangic_ayi = max(1, min(baslangic_ayi, 12))
    para = str(args.get("para_birimi") or "TRY").strip().upper()[:3] or "TRY"

    return {
        "_propose": True,
        "action_key": "duzenli_odeme_ekle",
        "entity_id": 0,
        "payload": {
            "name": ad,
            "amount": tutar,
            "currency": para,
            "frequency": frekans,
            "payment_day": odeme_gunu,
            "start_month": baslangic_ayi,
            "category": (str(args.get("kategori")).strip() or None) if args.get("kategori") else None,
            "notes": (str(args.get("aciklama")).strip() or None) if args.get("aciklama") else None,
        },
        "ozet": (
            f"'{ad}' düzenli ödemesi eklenecek: {tutar:,.2f} {para}, {_FREKANS_LABEL[frekans]}, "
            f"her ayın {odeme_gunu}. günü (başlangıç ayı {baslangic_ayi})."
        ),
    }


# ── Create (ekleme) mutasyonları — router↔executor ile birebir ────────────────
def _create_advance(db: Session, user: User, payload: Dict[str, Any]):
    """Avans oluştur (tarih string→date coercion — D1-2 kuralı)."""
    data = dict(payload)
    data["advance_date"] = date.fromisoformat(str(payload["advance_date"])[:10])
    return advance_service.create_advance(db, data, user.id)


def _create_recurring(db: Session, user: User, payload: Dict[str, Any]):
    """Düzenli ödeme tanımı oluştur — approval_executor._handle_scheduled (create) BİREBİR mirror'ı."""
    defn = ScheduledDefinition(
        source_type=SourceType.RECURRING,
        name=payload.get("name", ""),
        category=payload.get("category"),
        amount=payload.get("amount", 0),
        currency=payload.get("currency", "TRY"),
        frequency=payload.get("frequency", "monthly"),
        payment_day=payload.get("payment_day", 1),
        start_month=payload.get("start_month", 1),
        year=date.today().year,
        notes=payload.get("notes"),
        vendor_id=None,
        billing_offset_months=0,
        pay_next_month=False,
        is_active=True,
        created_by=user.id,
    )
    db.add(defn)
    db.flush()
    scheduled_service.post_create(db, defn, direction=-1)  # recurring = gider
    return defn


# Uygulama (execute) kaydı — action_key → hedef modül + varlık + mutasyon fonksiyonu.
# execute_action bunları payload whitelist'i + izin + check_approval ile korur.
# action_type: "update" (mevcut kaydı çözümle) veya "create" (payload'dan yeni kayıt üret).
_WRITE_ACTIONS: Dict[str, Dict[str, Any]] = {
    "cari_vade": {
        "module": "finance.cariler",
        "action_type": "update",
        "allowed_keys": {"payment_days"},
        "resolve": lambda db, eid: db.query(Vendor).filter(Vendor.id == eid).first(),
        "apply": lambda db, ent, p: vendor_service.apply_vendor_update(
            db, ent, {"payment_days": p["payment_days"]}
        ),
    },
    "cari_durum": {  # ödeme yasağı koy/kaldır
        "module": "finance.cariler",
        "action_type": "update",
        "allowed_keys": {"status"},
        "resolve": lambda db, eid: db.query(Vendor).filter(Vendor.id == eid).first(),
        "apply": lambda db, ent, p: vendor_service.apply_vendor_update(
            db, ent, {"status": p["status"]}
        ),
    },
    "cek_durum": {
        "module": "finance.checks",
        "action_type": "update",
        "allowed_keys": {"new_status"},
        "resolve": lambda db, eid: db.query(Check).filter(Check.id == eid).first(),
        "apply": lambda db, ent, p: check_service.apply_check_status(
            db, ent, p["new_status"]
        ),
    },
    "avans_ekle": {
        "module": "finance.avanslar",
        "action_type": "create",
        "allowed_keys": {"agency_name", "amount", "currency", "advance_date", "notes"},
        "apply_create": _create_advance,
    },
    "duzenli_odeme_ekle": {
        "module": "accounting.recurring",
        "action_type": "create",
        "allowed_keys": {
            "name", "amount", "currency", "frequency",
            "payment_day", "start_month", "category", "notes",
        },
        "apply_create": _create_recurring,
    },
}


def _validate_payload(action_key: str, payload: Dict[str, Any]) -> Optional[str]:
    """Payload değerlerini doğrula. Hata mesajı döner; geçerliyse None."""
    if action_key == "cari_vade":
        pd = payload.get("payment_days")
        if not isinstance(pd, int) or isinstance(pd, bool) or pd < 0:
            return "Geçersiz vade gün sayısı."
    elif action_key == "cari_durum":
        if payload.get("status") not in (STATUS_NORMAL, STATUS_PAYMENT_BANNED):
            return "Geçersiz cari durumu."
    elif action_key == "cek_durum":
        if payload.get("new_status") not in ("pending", "paid", "cancelled"):
            return "Geçersiz çek durumu."
    elif action_key == "avans_ekle":
        if not str(payload.get("agency_name") or "").strip():
            return "Acente adı boş olamaz."
        amt = payload.get("amount")
        if not isinstance(amt, (int, float)) or isinstance(amt, bool) or amt <= 0:
            return "Geçersiz tutar."
        try:
            date.fromisoformat(str(payload.get("advance_date"))[:10])
        except (ValueError, TypeError):
            return "Geçersiz tarih."
    elif action_key == "duzenli_odeme_ekle":
        if not str(payload.get("name") or "").strip():
            return "Ödeme adı boş olamaz."
        amt = payload.get("amount")
        if not isinstance(amt, (int, float)) or isinstance(amt, bool) or amt <= 0:
            return "Geçersiz tutar."
        if payload.get("frequency") not in ("monthly", "quarterly", "yearly"):
            return "Geçersiz sıklık."
        pd = payload.get("payment_day")
        if not isinstance(pd, int) or isinstance(pd, bool) or not (1 <= pd <= 28):
            return "Ödeme günü 1-28 arası olmalı."
        sm = payload.get("start_month")
        if not isinstance(sm, int) or isinstance(sm, bool) or not (1 <= sm <= 12):
            return "Başlangıç ayı 1-12 arası olmalı."
    return None


def execute_action(
    db: Session,
    user: User,
    action_key: str,
    entity_id: int,
    payload: Dict[str, Any],
    ip_address: Optional[str] = None,
) -> Dict[str, Any]:
    """Onaylanan bir yazma aksiyonunu uygular (router↔executor ile birebir yol).

    Katmanlar: (1) bilinen aksiyon, (2) hedef modül can_use izni, (3) payload
    whitelist + değer doğrulama, (4) varlık doğrulama, (5) check_approval — onay
    gerekiyorsa mutasyon YAPILMAZ, talep oluşur. Dönüş: {"durum", "mesaj"}.
    """
    action = _WRITE_ACTIONS.get(action_key)
    if action is None:
        return {"durum": "hata", "mesaj": "Bilinmeyen işlem."}
    if not user_can(db, user, action["module"], "use"):
        return {"durum": "hata", "mesaj": f"Bu işlem için yetkiniz yok ({action['module']})."}

    # payload whitelist (istemci fazladan/keyfi anahtar gönderemez) + doğrulama
    payload = {k: v for k, v in (payload or {}).items() if k in action["allowed_keys"]}
    hata = _validate_payload(action_key, payload)
    if hata:
        return {"durum": "hata", "mesaj": hata}

    action_type = action["action_type"]
    entity = None

    if action_type == "update":
        try:
            entity_id = int(entity_id)
        except (TypeError, ValueError):
            return {"durum": "hata", "mesaj": "Geçersiz kayıt."}
        entity = action["resolve"](db, entity_id)
        if entity is None:
            return {"durum": "hata", "mesaj": "Kayıt bulunamadı (silinmiş olabilir)."}
        # Onay kontrolü — router ile BİREBİR aynı modül/aksiyon/payload
        approval_resp = check_approval(db, action["module"], entity_id, user.id, "update", payload)
    else:  # create — entity_id=0, router create yoluyla birebir
        entity_id = 0
        approval_resp = check_approval(db, action["module"], 0, user.id, "create", payload)

    if approval_resp is not None:
        if approval_resp.status_code == 202:
            return {"durum": "onaya_gonderildi", "mesaj": "İşlem onay sürecine alındı."}
        try:
            body = json.loads(approval_resp.body)
            mesaj = body.get("message", "Bu kayıt için bekleyen onay var.")
        except Exception:
            mesaj = "Bu kayıt için bekleyen onay var."
        return {"durum": "bekleyen_talep", "mesaj": mesaj}

    # Onay gerekmiyor → uygula
    try:
        if action_type == "update":
            action["apply"](db, entity, payload)
            audit_id = entity_id
        else:
            obj = action["apply_create"](db, user, payload)
            audit_id = getattr(obj, "id", None)
    except ValueError as exc:
        db.rollback()
        return {"durum": "hata", "mesaj": str(exc)}
    log_action(
        db, user.id, "ai_execute", "ai_assistant", audit_id,
        details=f"{action_key}: {json.dumps(payload, ensure_ascii=False)}",
        ip_address=ip_address,
    )
    db.commit()
    return {"durum": "uygulandi", "mesaj": "İşlem başarıyla uygulandı."}


# Proposer araçları okuma araçlarının yanına eklenir (chat döngüsünde sunulur)
_TOOL_IMPL["cari_vade_degistir"] = _propose_cari_vade
_TOOL_IMPL["cek_durum_degistir"] = _propose_cek_durum
_TOOL_IMPL["cari_odeme_yasagi"] = _propose_cari_odeme_yasagi
_TOOL_IMPL["avans_ekle"] = _propose_avans_ekle
_TOOL_IMPL["duzenli_odeme_ekle"] = _propose_duzenli_odeme
_TOOL_DEFS.extend([
    {
        "name": "cari_vade_degistir",
        "description": (
            "Bir carinin ödeme vadesini (gün) değiştirmeyi ÖNERİR. İşlemi HEMEN "
            "YAPMAZ; değişikliği kullanıcının onayına sunar. Kullanıcı 'X carisinin "
            "vadesini N güne çek' gibi bir değişiklik istediğinde kullan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hesap_kodu": {
                    "type": "string",
                    "description": "Cari hesap kodu (ör. 320.01.01.B086) veya cari adı.",
                },
                "yeni_vade_gun": {
                    "type": "integer",
                    "description": "Yeni ödeme vadesi (gün).",
                },
            },
            "required": ["hesap_kodu", "yeni_vade_gun"],
        },
    },
    {
        "name": "cek_durum_degistir",
        "description": (
            "Bir çekin durumunu (ödendi / iptal / bekliyor) değiştirmeyi ÖNERİR. "
            "İşlemi HEMEN YAPMAZ; kullanıcının onayına sunar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cek_no": {"type": "string", "description": "Çek numarası."},
                "yeni_durum": {
                    "type": "string",
                    "description": "Yeni durum: 'ödendi', 'iptal' veya 'bekliyor'.",
                },
            },
            "required": ["cek_no", "yeni_durum"],
        },
    },
    {
        "name": "cari_odeme_yasagi",
        "description": (
            "Bir cariye ödeme yasağı KOYMAYI veya KALDIRMAYI ÖNERİR. İşlemi hemen "
            "yapmaz; kullanıcının onayına sunar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hesap_kodu": {"type": "string", "description": "Cari hesap kodu veya adı."},
                "yasakli": {
                    "type": "boolean",
                    "description": "true = ödeme yasağı koy, false = yasağı kaldır.",
                },
            },
            "required": ["hesap_kodu", "yasakli"],
        },
    },
    {
        "name": "avans_ekle",
        "description": (
            "Yeni bir avans (acenteden alınan) kaydı eklemeyi ÖNERİR. İşlemi hemen "
            "yapmaz; kullanıcının onayına sunar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "acente_adi": {"type": "string", "description": "Acente/operatör adı."},
                "tutar": {"type": "number", "description": "Avans tutarı (pozitif)."},
                "tarih": {"type": "string", "description": "Avans tarihi (YYYY-AA-GG)."},
                "para_birimi": {"type": "string", "description": "Para birimi (varsayılan EUR)."},
                "aciklama": {"type": "string", "description": "Opsiyonel not."},
            },
            "required": ["acente_adi", "tutar", "tarih"],
        },
    },
    {
        "name": "duzenli_odeme_ekle",
        "description": (
            "Yeni bir düzenli ödeme (aylık/3 aylık/yıllık planlı gider) tanımı "
            "eklemeyi ÖNERİR. İşlemi hemen yapmaz; kullanıcının onayına sunar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ad": {"type": "string", "description": "Ödeme adı (ör. Elektrik, İnternet)."},
                "tutar": {"type": "number", "description": "Ödeme tutarı (pozitif)."},
                "siklik": {
                    "type": "string",
                    "description": "Sıklık: 'aylık', '3 aylık' veya 'yıllık' (varsayılan aylık).",
                },
                "odeme_gunu": {"type": "integer", "description": "Ayın kaçında ödenir (1-28, varsayılan 1)."},
                "baslangic_ayi": {"type": "integer", "description": "Başlangıç ayı (1-12, varsayılan 1)."},
                "para_birimi": {"type": "string", "description": "Para birimi (varsayılan TRY)."},
                "kategori": {"type": "string", "description": "Opsiyonel kategori."},
                "aciklama": {"type": "string", "description": "Opsiyonel not."},
            },
            "required": ["ad", "tutar"],
        },
    },
])


# ── Ana giriş ─────────────────────────────────────────────────────────────────
_MAX_GECMIS_TUR = 12       # modele gönderilen en fazla önceki tur sayısı
_MAX_TUR_UZUNLUK = 6000    # bir turun en fazla karakteri (token/maliyet sınırı)


def _seed_messages(soru: str, gecmis: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Önceki konuşma turlarından + yeni sorudan mesaj dizisi kur.

    gecmis: [{"rol": "user"|"assistant", "metin": str}, ...] (istemciden gelir).
    İlk mesaj 'user' olmalı → baştaki assistant turları atılır. Uzunluk sınırlanır.
    """
    messages: List[Dict[str, Any]] = []
    if gecmis:
        for turn in gecmis[-_MAX_GECMIS_TUR:]:
            rol = turn.get("rol")
            metin = str(turn.get("metin") or "")[:_MAX_TUR_UZUNLUK].strip()
            if rol in ("user", "assistant") and metin:
                messages.append({"role": rol, "content": metin})
    # API kuralı: ilk mesaj user olmalı
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    messages.append({"role": "user", "content": soru})
    return messages


def _run_tool_block(
    db: Session,
    user: User,
    block: Any,
    used_tools: List[str],
    pending_actions: List[Dict[str, Any]],
    grafikler: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Tek bir tool_use bloğunu işle → tool_result dict döndür (listeleri günceller).

    answer_question ve answer_question_stream ORTAK kullanır (tek kaynak).
    """
    used_tools.append(block.name)
    impl = _TOOL_IMPL.get(block.name)
    if impl is None:
        result = {"_error": True, "mesaj": "Bilinmeyen araç."}
    else:
        try:
            result = impl(db, user, dict(block.input or {}))
        except Exception as exc:  # tek tool hatası tüm sohbeti düşürmesin
            logger.error("AI tool hatası (%s): %s", block.name, exc, exc_info=True)
            result = {"_error": True, "mesaj": "Araç çalıştırılırken hata oluştu."}

    if result.get("_grafik"):
        grafikler.append(result["grafik"])
        tool_payload: Dict[str, Any] = {
            "durum": "grafik_eklendi",
            "aciklama": "Grafik kullanıcıya gösterilecek. Metinde tekrar sayma; kısa yorumla yetin.",
        }
        is_error = False
    elif result.get("_propose"):
        pending_actions.append({
            "action_key": result["action_key"],
            "entity_id": result["entity_id"],
            "payload": result["payload"],
            "ozet": result["ozet"],
        })
        tool_payload = {
            "durum": "onay_bekliyor",
            "aciklama": "Öneri hazırlandı ve kullanıcının onayına sunuldu. "
                        "İşlem, kullanıcı onaylarsa yapılacak.",
            "ozet": result["ozet"],
        }
        is_error = False
    else:
        tool_payload = result
        is_error = bool(result.get("_error"))

    return {
        "type": "tool_result",
        "tool_use_id": block.id,
        "content": json.dumps(tool_payload, ensure_ascii=False, default=str),
        "is_error": is_error,
    }


def answer_question(
    db: Session,
    user: User,
    soru: str,
    gecmis: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Kullanıcının sorusunu Claude + tool-use döngüsüyle yanıtlar.

    gecmis verilirse önceki konuşma turları modele bağlam olarak eklenir → takip
    soruları ('peki geçen ay?') çalışır. Dönüş: {"cevap", "kullanilan_araclar",
    "bekleyen_islem", "grafikler"}. ANTHROPIC_API_KEY boşsa RuntimeError.
    """
    if not settings.anthropic_api_key:
        raise RuntimeError("Asistan yapılandırılmamış (ANTHROPIC_API_KEY yok).")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    messages: List[Dict[str, Any]] = _seed_messages(soru, gecmis)
    used_tools: List[str] = []
    pending_actions: List[Dict[str, Any]] = []
    grafikler: List[Dict[str, Any]] = []

    response = None
    for _ in range(_MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=_TOOL_DEFS,
            messages=messages,
        )
        if response.stop_reason != "tool_use":
            break

        messages.append({"role": "assistant", "content": response.content})
        tool_results = [
            _run_tool_block(db, user, block, used_tools, pending_actions, grafikler)
            for block in response.content
            if block.type == "tool_use"
        ]
        messages.append({"role": "user", "content": tool_results})
    else:
        # döngü tükendi (çok fazla tool turu)
        logger.warning("AI asistan tool döngüsü limiti aşıldı (kullanıcı %s)", user.id)

    cevap = ""
    if response is not None:
        cevap = "".join(
            b.text for b in response.content if getattr(b, "type", None) == "text"
        ).strip()
    if not cevap:
        cevap = "Üzgünüm, bu soruya şu an yanıt üretemedim."

    # Yalnız SON öneriyi kullanıcı onayına sun (tek seferde tek işlem — basit ve güvenli)
    bekleyen = pending_actions[-1] if pending_actions else None
    return {
        "cevap": cevap,
        "kullanilan_araclar": used_tools,
        "bekleyen_islem": bekleyen,
        "grafikler": grafikler,
    }


def answer_question_stream(
    db: Session,
    user: User,
    soru: str,
    gecmis: Optional[List[Dict[str, Any]]] = None,
):
    """answer_question'ın STREAMING sürümü — üretici (generator).

    Yield edilen olaylar (dict):
      {"t": "delta", "v": <metin parçası>}  — modelin ürettiği metin token'ları
      {"t": "meta",  "kullanilan_araclar", "bekleyen_islem", "grafikler"}  — sonda
    Tool turları arka planda döner; metin token token akıtılır. Router bunu SSE'ye sarar.
    """
    if not settings.anthropic_api_key:
        raise RuntimeError("Asistan yapılandırılmamış (ANTHROPIC_API_KEY yok).")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    messages: List[Dict[str, Any]] = _seed_messages(soru, gecmis)
    used_tools: List[str] = []
    pending_actions: List[Dict[str, Any]] = []
    grafikler: List[Dict[str, Any]] = []

    for _ in range(_MAX_TOOL_ITERATIONS):
        with client.messages.stream(
            model=settings.anthropic_model,
            max_tokens=_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=_TOOL_DEFS,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                if text:
                    yield {"t": "delta", "v": text}
            response = stream.get_final_message()

        if response.stop_reason != "tool_use":
            break

        messages.append({"role": "assistant", "content": response.content})
        tool_results = [
            _run_tool_block(db, user, block, used_tools, pending_actions, grafikler)
            for block in response.content
            if block.type == "tool_use"
        ]
        messages.append({"role": "user", "content": tool_results})

    yield {
        "t": "meta",
        "kullanilan_araclar": used_tools,
        "bekleyen_islem": pending_actions[-1] if pending_actions else None,
        "grafikler": grafikler,
    }
