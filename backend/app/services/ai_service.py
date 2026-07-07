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
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.middleware.auth import user_can
from app.models.check import Check
from app.models.finance_event import (
    DIRECTION_EXPENSE,
    DIRECTION_INCOME,
    FinanceEvent,
)
from app.models.user import User
from app.models.vendor import Vendor
from app.models.vendor_transaction import VendorTransaction

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
    "- Kısa ve öz yanıt ver. Para tutarlarını Türk Lirası formatında (binlik ayırıcı "
    "nokta, ondalık virgül) ve gerekirse ₺/EUR belirterek yaz.\n"
    "- Tarih bilmiyorsan bugünün tarihini tool'lara varsayılan bırakabilirsin.\n"
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
    """Verilen tarih aralığında toplam gelir/gider/net (TRY, finance_events)."""
    if not user_can(db, user, "finance.cash_flow", "view"):
        return _denied("finance.cash_flow")

    today = _istanbul_today()
    baslangic = _parse_date(args.get("baslangic_tarih"), today.replace(day=1))
    bitis = _parse_date(args.get("bitis_tarih"), today)
    if baslangic > bitis:
        baslangic, bitis = bitis, baslangic

    amount_try = func.coalesce(FinanceEvent.amount_try, FinanceEvent.amount)
    rows = (
        db.query(FinanceEvent.direction, func.sum(amount_try))
        .filter(FinanceEvent.event_date >= baslangic)
        .filter(FinanceEvent.event_date <= bitis)
        .group_by(FinanceEvent.direction)
        .all()
    )
    gelir = 0.0
    gider = 0.0
    for direction, total in rows:
        if direction == DIRECTION_INCOME:
            gelir = _num(total)
        elif direction == DIRECTION_EXPENSE:
            gider = _num(total)

    return {
        "baslangic": baslangic.isoformat(),
        "bitis": bitis.isoformat(),
        "toplam_gelir": round(gelir, 2),
        "toplam_gider": round(gider, 2),
        "net": round(gelir - gider, 2),
        "para_birimi": "TRY",
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


# Tool adı → uygulama eşlemesi
_TOOL_IMPL = {
    "nakit_akim_ozeti": _tool_nakit_akim_ozeti,
    "bekleyen_cekler": _tool_bekleyen_cekler,
    "cari_borc_ozeti": _tool_cari_borc_ozeti,
}

# Claude'a sunulan tool tanımları (JSON şeması)
_TOOL_DEFS: List[Dict[str, Any]] = [
    {
        "name": "nakit_akim_ozeti",
        "description": (
            "Belirli bir tarih aralığındaki toplam nakit girişi (gelir), çıkışı "
            "(gider) ve net akışı TRY cinsinden döndürür. Tarih verilmezse içinde "
            "bulunulan ay başından bugüne kadar hesaplanır."
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
]


# ── Ana giriş ─────────────────────────────────────────────────────────────────
def answer_question(db: Session, user: User, soru: str) -> Dict[str, Any]:
    """Kullanıcının sorusunu Claude + tool-use döngüsüyle yanıtlar.

    Dönüş: {"cevap": str, "kullanilan_araclar": [tool adları]}.
    ANTHROPIC_API_KEY boşsa RuntimeError fırlatır (router 503'e çevirir).
    """
    if not settings.anthropic_api_key:
        raise RuntimeError("Asistan yapılandırılmamış (ANTHROPIC_API_KEY yok).")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    messages: List[Dict[str, Any]] = [{"role": "user", "content": soru}]
    used_tools: List[str] = []

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
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            used_tools.append(block.name)
            impl = _TOOL_IMPL.get(block.name)
            if impl is None:
                result = {"_error": True, "mesaj": "Bilinmeyen araç."}
            else:
                try:
                    result = impl(db, user, dict(block.input or {}))
                except Exception as exc:  # tek bir tool hatası tüm sohbeti düşürmesin
                    logger.error("AI tool hatası (%s): %s", block.name, exc, exc_info=True)
                    result = {"_error": True, "mesaj": "Araç çalıştırılırken hata oluştu."}
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False, default=str),
                "is_error": bool(result.get("_error")),
            })
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

    return {"cevap": cevap, "kullanilan_araclar": used_tools}
