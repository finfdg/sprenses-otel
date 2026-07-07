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
from app.services import check_service, vendor_service
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
    "- Kısa ve öz yanıt ver. Para tutarlarını Türk Lirası formatında (binlik ayırıcı "
    "nokta, ondalık virgül) ve gerekirse ₺/EUR belirterek yaz.\n"
    "- Tarih bilmiyorsan bugünün tarihini tool'lara varsayılan bırakabilirsin.\n"
    "- Kullanıcı bir DEĞİŞİKLİK isterse (cari ödeme vadesini değiştir, çek durumunu "
    "güncelle vb.) ilgili 'değiştir' aracını çağır. Bu araçlar işlemi HEMEN YAPMAZ; "
    "değişikliği kullanıcının onayına sunar. Kullanıcıya onayını beklediğini belirt.\n"
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


# Uygulama (execute) kaydı — action_key → hedef modül + varlık + mutasyon fonksiyonu.
# execute_action bunları payload whitelist'i + izin + check_approval ile korur.
_WRITE_ACTIONS: Dict[str, Dict[str, Any]] = {
    "cari_vade": {
        "module": "finance.cariler",
        "allowed_keys": {"payment_days"},
        "resolve": lambda db, eid: db.query(Vendor).filter(Vendor.id == eid).first(),
        "apply": lambda db, ent, p: vendor_service.apply_vendor_update(
            db, ent, {"payment_days": p["payment_days"]}
        ),
    },
    "cek_durum": {
        "module": "finance.checks",
        "allowed_keys": {"new_status"},
        "resolve": lambda db, eid: db.query(Check).filter(Check.id == eid).first(),
        "apply": lambda db, ent, p: check_service.apply_check_status(
            db, ent, p["new_status"]
        ),
    },
}


def _validate_payload(action_key: str, payload: Dict[str, Any]) -> Optional[str]:
    """Payload değerlerini doğrula. Hata mesajı döner; geçerliyse None."""
    if action_key == "cari_vade":
        pd = payload.get("payment_days")
        if not isinstance(pd, int) or isinstance(pd, bool) or pd < 0:
            return "Geçersiz vade gün sayısı."
    elif action_key == "cek_durum":
        if payload.get("new_status") not in ("pending", "paid", "cancelled"):
            return "Geçersiz çek durumu."
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

    try:
        entity_id = int(entity_id)
    except (TypeError, ValueError):
        return {"durum": "hata", "mesaj": "Geçersiz kayıt."}
    entity = action["resolve"](db, entity_id)
    if entity is None:
        return {"durum": "hata", "mesaj": "Kayıt bulunamadı (silinmiş olabilir)."}

    # Onay kontrolü — router ile BİREBİR aynı modül/aksiyon/payload
    approval_resp = check_approval(db, action["module"], entity_id, user.id, "update", payload)
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
        action["apply"](db, entity, payload)
    except ValueError as exc:
        db.rollback()
        return {"durum": "hata", "mesaj": str(exc)}
    log_action(
        db, user.id, "ai_execute", "ai_assistant", entity_id,
        details=f"{action_key}: {json.dumps(payload, ensure_ascii=False)}",
        ip_address=ip_address,
    )
    db.commit()
    return {"durum": "uygulandi", "mesaj": "İşlem başarıyla uygulandı."}


# Proposer araçları okuma araçlarının yanına eklenir (chat döngüsünde sunulur)
_TOOL_IMPL["cari_vade_degistir"] = _propose_cari_vade
_TOOL_IMPL["cek_durum_degistir"] = _propose_cek_durum
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
])


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
    pending_actions: List[Dict[str, Any]] = []

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

            if result.get("_propose"):
                # Yazma önerisi — mutasyon YAPILMADI; kullanıcı onayına sunulur.
                pending_actions.append({
                    "action_key": result["action_key"],
                    "entity_id": result["entity_id"],
                    "payload": result["payload"],
                    "ozet": result["ozet"],
                })
                tool_payload: Dict[str, Any] = {
                    "durum": "onay_bekliyor",
                    "aciklama": "Öneri hazırlandı ve kullanıcının onayına sunuldu. "
                                "İşlem, kullanıcı onaylarsa yapılacak.",
                    "ozet": result["ozet"],
                }
                is_error = False
            else:
                tool_payload = result
                is_error = bool(result.get("_error"))

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(tool_payload, ensure_ascii=False, default=str),
                "is_error": is_error,
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

    # Yalnız SON öneriyi kullanıcı onayına sun (tek seferde tek işlem — basit ve güvenli)
    bekleyen = pending_actions[-1] if pending_actions else None
    return {
        "cevap": cevap,
        "kullanilan_araclar": used_tools,
        "bekleyen_islem": bekleyen,
    }
