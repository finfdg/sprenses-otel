"""Yapay Zeka Asistanı router'ı — /api/ai.

Kullanıcı doğal dilde soru sorar; Claude API + tool-use ile salt-okuma finans
verilerinden yanıt üretilir. Tüm veri erişimi, isteği yapan kullanıcının izinlerine
tabidir (bkz. services/ai_service.py). Her sorgu audit'e kaydedilir.

FAZ 1: yalnız okuma. Yazma/mutasyon FAZ 2'de (check_approval ile).
Detay: docs/modules/ai-asistan.md
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import ai_daily_limiter, ai_limiter, get_client_ip
from app.models.ai_conversation import AiConversation, AiMessage
from app.models.user import User
from app.services import ai_service
from app.utils import ai_export
from app.utils.audit import log_action

_TR_MAP = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def _slug(text: str) -> str:
    """Türkçe başlıktan ASCII dosya adı üret."""
    s = (text or "").translate(_TR_MAP)
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", s).strip("-").lower()
    return s[:60] or "asistan-raporu"


def _resolve_conversation(db: Session, user_id: int, konusma_id, soru: str) -> AiConversation:
    """Verilen konuşmayı (kullanıcıya ait) getir; yoksa yeni oluştur (başlık = soru özeti)."""
    if konusma_id:
        conv = (
            db.query(AiConversation)
            .filter(AiConversation.id == konusma_id, AiConversation.user_id == user_id)
            .first()
        )
        if conv:
            return conv
    title = (soru or "Yeni sohbet").strip()[:60]
    conv = AiConversation(user_id=user_id, title=title)
    db.add(conv)
    db.flush()
    return conv


def _save_message(db: Session, conversation_id: int, role: str, content: str) -> None:
    db.add(AiMessage(conversation_id=conversation_id, role=role, content=content or ""))

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Şemalar ───────────────────────────────────────────────────────────────────
class AiHistoryTurn(BaseModel):
    rol: str = Field(..., max_length=20)
    metin: str = Field("", max_length=8000)


class AiAskRequest(BaseModel):
    soru: str = Field(..., min_length=2, max_length=2000)
    gecmis: Optional[List[AiHistoryTurn]] = Field(None, max_length=40)
    konusma_id: Optional[int] = None


class AiAskResponse(BaseModel):
    cevap: str
    kullanilan_araclar: list
    bekleyen_islem: Optional[Dict[str, Any]] = None
    grafikler: Optional[list] = None
    konusma_id: Optional[int] = None


class AiExecuteRequest(BaseModel):
    """Kullanıcının ConfirmDialog'da onayladığı yazma aksiyonu (bekleyen_islem)."""
    action_key: str = Field(..., min_length=1, max_length=50)
    entity_id: int
    payload: Dict[str, Any]


class AiExecuteResponse(BaseModel):
    durum: str
    mesaj: str


class AiExportRequest(BaseModel):
    """Asistan tablosunu Excel/PDF'e aktarma (frontend markdown tablodan çıkarır)."""
    baslik: str = Field("Rapor", max_length=150)
    format: str = Field("xlsx", max_length=8)  # xlsx | pdf
    basliklar: List[str] = Field(..., min_length=1, max_length=40)
    satirlar: List[List[str]] = Field(..., max_length=3000)


# ── Endpoint ──────────────────────────────────────────────────────────────────
@router.post("/sor", response_model=AiAskResponse)
def sor(
    data: AiAskRequest,
    request: Request,
    current_user: User = Depends(require_permission("ai.asistan", "view")),
    db: Session = Depends(get_db),
):
    """Asistana bir soru sor (salt-okuma). Yanıtı ve kullanılan araçları döner."""
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Yapay zeka asistanı henüz yapılandırılmamış (API anahtarı yok).",
        )
    ai_limiter.check(f"ai:{current_user.id}")
    ai_daily_limiter.check(f"aid:{current_user.id}")

    conv = _resolve_conversation(db, current_user.id, data.konusma_id, data.soru)
    _save_message(db, conv.id, "user", data.soru)

    gecmis = [t.model_dump() for t in data.gecmis] if data.gecmis else None
    try:
        result = ai_service.answer_question(db, current_user, data.soru, gecmis)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    except Exception as exc:
        logger.error("AI asistan yanıt hatası: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Asistan şu an yanıt veremiyor, lütfen tekrar deneyin.",
        )

    # Asistan yanıtını konuşmaya kaydet
    _save_message(db, conv.id, "assistant", result.get("cevap", ""))
    result["konusma_id"] = conv.id

    # Token/maliyet kaydı
    try:
        ai_service.record_usage(
            db, current_user.id, result.get("usage", {}),
            len(result.get("kullanilan_araclar", [])),
        )
    except Exception:
        logger.warning("AI usage kaydı başarısız", exc_info=True)

    # Audit — hangi kullanıcı ne sordu (yanıt kaydedilmez, soru ilk 500 karakter)
    log_action(
        db,
        current_user.id,
        "ai_query",
        "ai_assistant",
        None,
        details=data.soru[:500],
        ip_address=get_client_ip(request),
    )
    db.commit()

    return result


@router.post("/uygula", response_model=AiExecuteResponse)
def uygula(
    data: AiExecuteRequest,
    request: Request,
    current_user: User = Depends(require_permission("ai.asistan", "use")),
    db: Session = Depends(get_db),
):
    """Asistanın önerdiği bir yazma işlemini uygula (kullanıcı ConfirmDialog'da onayladıktan sonra).

    ai.asistan can_use izni gerekir (birinci kapı). execute_action ayrıca hedef modülün
    can_use iznini + check_approval'ı uygular (ikinci/üçüncü kapı). Onay gerekiyorsa
    mutasyon yapılmaz, talep oluşur.
    """
    try:
        result = ai_service.execute_action(
            db,
            current_user,
            data.action_key,
            data.entity_id,
            data.payload,
            ip_address=get_client_ip(request),
        )
    except Exception as exc:
        logger.error("AI asistan uygulama hatası: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="İşlem uygulanırken bir hata oluştu.",
        )
    return result


@router.post("/sor-stream")
def sor_stream(
    data: AiAskRequest,
    request: Request,
    current_user: User = Depends(require_permission("ai.asistan", "view")),
):
    """Asistana soru sor — yanıt SSE ile token token akar (perceived latency düşük)."""
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Yapay zeka asistanı henüz yapılandırılmamış.",
        )
    ai_limiter.check(f"ai:{current_user.id}")
    ai_daily_limiter.check(f"aid:{current_user.id}")
    uid = current_user.id
    soru = data.soru
    gecmis = [t.model_dump() for t in data.gecmis] if data.gecmis else None
    konusma_id = data.konusma_id
    ip = get_client_ip(request)

    def gen():
        # Generator kendi DB oturumunu açar (stream süresince yaşamalı → Depends'e güvenme)
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            user = db.get(User, uid)
            conv = _resolve_conversation(db, uid, konusma_id, soru)
            _save_message(db, conv.id, "user", soru)
            db.flush()
            usage_ev = None
            answer_buf: List[str] = []
            for ev in ai_service.answer_question_stream(db, user, soru, gecmis):
                if ev.get("t") == "usage":  # iç kayıt olayı — istemciye gönderme
                    usage_ev = ev
                    continue
                if ev.get("t") == "delta":
                    answer_buf.append(ev.get("v", ""))
                elif ev.get("t") == "meta":
                    ev["konusma_id"] = conv.id
                yield "data: " + json.dumps(ev, ensure_ascii=False, default=str) + "\n\n"
            _save_message(db, conv.id, "assistant", "".join(answer_buf))
            if usage_ev:
                ai_service.record_usage(db, uid, usage_ev, usage_ev.get("tool_count", 0))
            log_action(db, uid, "ai_query", "ai_assistant", None, details=soru[:500], ip_address=ip)
            db.commit()
        except Exception as exc:
            logger.error("AI stream hatası: %s", exc, exc_info=True)
            db.rollback()
            yield "data: " + json.dumps({"t": "error", "mesaj": "Asistan yanıt veremedi."}) + "\n\n"
        finally:
            yield "data: " + json.dumps({"t": "done"}) + "\n\n"
            db.close()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/gunun-ozeti")
def gunun_ozeti(
    current_user: User = Depends(require_permission("ai.asistan", "view")),
    db: Session = Depends(get_db),
):
    """Panel kartı için günün özeti (deterministik, AI çağrısı yok)."""
    return ai_service.compute_digest(db, current_user, 7)


@router.post("/disa-aktar")
def disa_aktar(
    data: AiExportRequest,
    current_user: User = Depends(require_permission("ai.asistan", "view")),
):
    """Asistan yanıtındaki bir tabloyu Excel (.xlsx) veya PDF olarak indir."""
    if not data.basliklar or not data.satirlar:
        raise HTTPException(status_code=400, detail="Aktarılacak tablo verisi yok.")

    baslik = data.baslik or "Rapor"
    satirlar = [[str(c) for c in row] for row in data.satirlar]
    ad = _slug(baslik)
    try:
        if data.format.lower() == "pdf":
            content = ai_export.build_pdf(baslik, data.basliklar, satirlar)
            media = "application/pdf"
            ext = "pdf"
        else:
            content = ai_export.build_xlsx(baslik, data.basliklar, satirlar)
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ext = "xlsx"
    except Exception as exc:
        logger.error("AI dışa aktarma hatası: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Dosya oluşturulamadı.")

    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{ad}.{ext}"'},
    )


# ── Konuşma kalıcılığı ────────────────────────────────────────────────────────
@router.get("/konusmalar")
def konusmalar(
    current_user: User = Depends(require_permission("ai.asistan", "view")),
    db: Session = Depends(get_db),
):
    """Kullanıcının geçmiş sohbetleri (en güncel önce)."""
    rows = (
        db.query(AiConversation)
        .filter(AiConversation.user_id == current_user.id)
        .order_by(AiConversation.updated_at.desc())
        .limit(100)
        .all()
    )
    return [
        {"id": c.id, "title": c.title, "updated_at": str(c.updated_at) if c.updated_at else None}
        for c in rows
    ]


@router.get("/konusmalar/{konusma_id}")
def konusma_detay(
    konusma_id: int,
    current_user: User = Depends(require_permission("ai.asistan", "view")),
    db: Session = Depends(get_db),
):
    """Bir sohbetin mesajları (yalnız sahibi)."""
    conv = (
        db.query(AiConversation)
        .filter(AiConversation.id == konusma_id, AiConversation.user_id == current_user.id)
        .first()
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Konuşma bulunamadı.")
    return {
        "id": conv.id,
        "title": conv.title,
        "mesajlar": [{"rol": m.role, "metin": m.content or ""} for m in conv.messages],
    }


@router.delete("/konusmalar/{konusma_id}", status_code=status.HTTP_204_NO_CONTENT)
def konusma_sil(
    konusma_id: int,
    current_user: User = Depends(require_permission("ai.asistan", "view")),
    db: Session = Depends(get_db),
):
    """Bir sohbeti sil (mesajları CASCADE)."""
    conv = (
        db.query(AiConversation)
        .filter(AiConversation.id == konusma_id, AiConversation.user_id == current_user.id)
        .first()
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Konuşma bulunamadı.")
    db.delete(conv)
    db.commit()
