"""Yapay Zeka Asistanı router'ı — /api/ai.

Kullanıcı doğal dilde soru sorar; Claude API + tool-use ile salt-okuma finans
verilerinden yanıt üretilir. Tüm veri erişimi, isteği yapan kullanıcının izinlerine
tabidir (bkz. services/ai_service.py). Her sorgu audit'e kaydedilir.

FAZ 1: yalnız okuma. Yazma/mutasyon FAZ 2'de (check_approval ile).
Detay: docs/modules/ai-asistan.md
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.user import User
from app.services import ai_service
from app.utils.audit import log_action

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Şemalar ───────────────────────────────────────────────────────────────────
class AiAskRequest(BaseModel):
    soru: str = Field(..., min_length=2, max_length=2000)


class AiAskResponse(BaseModel):
    cevap: str
    kullanilan_araclar: list
    bekleyen_islem: Optional[Dict[str, Any]] = None
    grafikler: Optional[list] = None


class AiExecuteRequest(BaseModel):
    """Kullanıcının ConfirmDialog'da onayladığı yazma aksiyonu (bekleyen_islem)."""
    action_key: str = Field(..., min_length=1, max_length=50)
    entity_id: int
    payload: Dict[str, Any]


class AiExecuteResponse(BaseModel):
    durum: str
    mesaj: str


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

    try:
        result = ai_service.answer_question(db, current_user, data.soru)
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
