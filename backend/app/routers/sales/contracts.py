"""Kontratlar modülü (sales.kontratlar) — acente kontrat arşivi + metadata CRUD.

16 tur operatörünün sözleşme/dönem/ödeme planı/aksiyon/kontenjan/kesinti kayıtları.
Mutasyon mantığı `services/contract_service.py`'de ORTAK (D1-2) — onay executor'ı
(`_handle_sales_kontratlar`) aynı fonksiyonları çağırır. Alt varlık mutasyonları tek
`kind` parametresiyle yönetilir; onay payload'ı `_kind` alanı taşır.

Belge yükleme/indirme onay akışı DIŞI (dosya endpoint istisnası, CLAUDE.md) ama
audit'li ve broadcast'li.
"""
import math
import os
import uuid
from datetime import date
from typing import Optional

from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query,
    Request, UploadFile, status,
)
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.constants import BroadcastModule
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.agency_group import AgencyGroup
from app.models.contract import (
    ALL_DOC_TYPES, INSTALLMENT_PENDING, AgencyContract, ContractAction,
    ContractDocument, ContractInstallment, ContractPaymentPlan,
)
from app.models.user import User
from app.schemas.contract import (
    ActionCreate, ActionTierCreate, AllotmentCreate, ContractCreate,
    ContractUpdate, DeductionCreate, DocumentMetaUpdate, InstallmentCreate,
    PaymentPlanCreate, PeriodCreate, RoomTypeMapCreate,
)
from app.services import contract_service
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.utils.file_validation import validate_upload_file
from app.utils.sales_broadcast import broadcast_sales_update

MODULE_CODE = "sales.kontratlar"

# kind → create şeması (PATCH'te de aynı şema partial kullanılır — exclude_unset)
_KIND_SCHEMAS = {
    "periods": PeriodCreate,
    "room-types": RoomTypeMapCreate,
    "plans": PaymentPlanCreate,
    "installments": InstallmentCreate,
    "actions": ActionCreate,
    "tiers": ActionTierCreate,
    "allotments": AllotmentCreate,
    "deductions": DeductionCreate,
}

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "uploads", "contract_files")

router = APIRouter(prefix="/kontratlar", tags=["Kontratlar"])


def _ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


# ─── Yanıt kurucular ────────────────────────────────────

def _row(c: AgencyContract, group_names: dict) -> dict:
    """Liste satırı — hafif alanlar + taksit özetleri."""
    pending = [i for p in c.payment_plans for i in p.installments
               if i.status == INSTALLMENT_PENDING and i.amount]
    return {
        "id": c.id,
        "agency_group_id": c.agency_group_id,
        "agency_group_name": group_names.get(c.agency_group_id),
        "code": c.code,
        "title": c.title,
        "season_code": c.season_code,
        "valid_from": c.valid_from.isoformat() if c.valid_from else None,
        "valid_to": c.valid_to.isoformat() if c.valid_to else None,
        "currency": c.currency,
        "status": c.status,
        "data_confidence": c.data_confidence,
        "pricing_model": c.pricing_model,
        "invoice_due_basis": c.invoice_due_basis,
        "invoice_due_days": c.invoice_due_days,
        "release_days_default": c.release_days_default,
        "markets": c.markets or [],
        "exclusive_markets": c.exclusive_markets or [],
        "plan_count": len(c.payment_plans),
        "action_count": len(c.actions),
        "document_count": len(c.documents),
        "pending_installment_total": round(sum(float(i.amount) for i in pending), 2),
        "pending_installment_count": len(pending),
    }


def _child_dict(obj) -> dict:
    """Alt varlık satırı — kolonları otomatik serileştir (date → ISO)."""
    out = {}
    for col in obj.__table__.columns:
        v = getattr(obj, col.name)
        if isinstance(v, date):
            v = v.isoformat()
        elif v is not None and col.type.__class__.__name__ == "Numeric":
            v = float(v)
        out[col.name] = v
    return out


def _detail(c: AgencyContract, group_names: dict) -> dict:
    d = _row(c, group_names)
    d.update({
        "legal_counterparty": c.legal_counterparty,
        "signed_date": c.signed_date.isoformat() if c.signed_date else None,
        "fx_rule": c.fx_rule,
        "fx_fixed_rate": float(c.fx_fixed_rate) if c.fx_fixed_rate is not None else None,
        "board_default": c.board_default,
        "min_stay_default": c.min_stay_default,
        "closed_markets": c.closed_markets or [],
        "supersedes_contract_id": c.supersedes_contract_id,
        "sedna_contrack_ids": c.sedna_contrack_ids or [],
        "notes": c.notes,
        "periods": [_child_dict(p) for p in c.periods],
        "room_types": [_child_dict(r) for r in c.room_types],
        "payment_plans": [
            {**_child_dict(p), "installments": [_child_dict(i) for i in p.installments]}
            for p in c.payment_plans
        ],
        "actions": [
            {**_child_dict(a), "tiers": [_child_dict(t) for t in a.tiers]}
            for a in c.actions
        ],
        "allotments": [_child_dict(a) for a in c.allotments],
        "deductions": [_child_dict(x) for x in c.deductions],
        "documents": [_child_dict(x) for x in c.documents],
    })
    return d


def _group_names(db: Session) -> dict:
    return {g.id: g.name for g in db.query(AgencyGroup).all()}


# ─── Liste + özet ───────────────────────────────────────

@router.get("/")
def list_contracts(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    group_id: Optional[int] = Query(None),
    season: Optional[str] = Query(None, max_length=20),
    status_f: Optional[str] = Query(None, alias="status", max_length=20),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(MODULE_CODE, "view")),
):
    """Kontrat listesi — grup/sezon/durum filtreli, sayfalı."""
    q = db.query(AgencyContract).options(
        selectinload(AgencyContract.payment_plans)
        .selectinload(ContractPaymentPlan.installments),
        selectinload(AgencyContract.actions),
        selectinload(AgencyContract.documents),
    )
    if group_id:
        q = q.filter(AgencyContract.agency_group_id == group_id)
    if season:
        q = q.filter(AgencyContract.season_code == season)
    if status_f:
        q = q.filter(AgencyContract.status == status_f)
    total = q.count()
    items = (q.order_by(AgencyContract.season_code.desc(), AgencyContract.code)
             .offset((page - 1) * page_size).limit(page_size).all())
    names = _group_names(db)
    return {
        "items": [_row(c, names) for c in items],
        "total": total, "page": page, "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size)),
    }


@router.get("/summary")
def contracts_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(MODULE_CODE, "view")),
):
    """Stat kartları: aktif kontrat, bekleyen taksit toplamı, 30 gün içi vade, geciken."""
    today = date.today()
    active = (db.query(func.count(AgencyContract.id))
              .filter(AgencyContract.status == "active").scalar() or 0)
    inst = (
        db.query(ContractInstallment)
        .filter(ContractInstallment.status == INSTALLMENT_PENDING,
                ContractInstallment.amount.isnot(None),
                ContractInstallment.due_date.isnot(None))
        .all()
    )
    pending_total = round(sum(float(i.amount) for i in inst), 2)
    due_30 = round(sum(float(i.amount) for i in inst
                       if today <= i.due_date and (i.due_date - today).days <= 30), 2)
    overdue = round(sum(float(i.amount) for i in inst if i.due_date < today), 2)
    overdue_count = sum(1 for i in inst if i.due_date < today)
    return {
        "active_contracts": int(active),
        "pending_installment_total": pending_total,
        "due_next_30d": due_30,
        "overdue_total": overdue,
        "overdue_count": overdue_count,
    }


@router.get("/{contract_id}")
def get_contract_detail(
    contract_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(MODULE_CODE, "view")),
):
    c = contract_service.get_contract(db, contract_id)
    if not c:
        raise HTTPException(status_code=404, detail="Kontrat bulunamadı")
    return _detail(c, _group_names(db))


# ─── Kontrat CRUD ───────────────────────────────────────

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_contract(
    data: ContractCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Yeni kontrat oluştur."""
    if not db.query(AgencyGroup).filter(AgencyGroup.id == data.agency_group_id).first():
        raise HTTPException(status_code=404, detail="Acente grubu bulunamadı")

    approval_resp = check_approval(
        db, MODULE_CODE, 0, current_user.id, "create", data.model_dump())
    if approval_resp:
        return approval_resp

    try:
        c = contract_service.create_contract(db, data.model_dump())
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400,
                            detail=f"Bu kontrat kodu zaten kayıtlı: {data.code}")

    log_action(db, current_user.id, "create", "agency_contract", entity_id=c.id,
               details=f"{c.code} — {c.season_code}", ip_address=get_client_ip(request))
    db.commit()
    broadcast_sales_update(background_tasks, BroadcastModule.KONTRATLAR, "create")
    fresh = contract_service.get_contract(db, c.id)
    return _detail(fresh, _group_names(db))


@router.patch("/{contract_id}")
def update_contract(
    contract_id: int,
    data: ContractUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    c = db.query(AgencyContract).filter(AgencyContract.id == contract_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Kontrat bulunamadı")

    payload = data.model_dump(exclude_unset=True)
    approval_resp = check_approval(
        db, MODULE_CODE, contract_id, current_user.id, "update", payload)
    if approval_resp:
        return approval_resp

    try:
        contract_service.apply_contract_update(db, c, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Bu kontrat kodu zaten kayıtlı")

    log_action(db, current_user.id, "update", "agency_contract", entity_id=c.id,
               details=f"{c.code} — {c.season_code}", ip_address=get_client_ip(request))
    db.commit()
    broadcast_sales_update(background_tasks, BroadcastModule.KONTRATLAR, "update")
    fresh = contract_service.get_contract(db, contract_id)
    return _detail(fresh, _group_names(db))


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contract(
    contract_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    c = db.query(AgencyContract).filter(AgencyContract.id == contract_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Kontrat bulunamadı")

    approval_resp = check_approval(
        db, MODULE_CODE, contract_id, current_user.id, "delete", {})
    if approval_resp:
        return approval_resp

    code = c.code
    try:
        contract_service.delete_contract(db, c)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_action(db, current_user.id, "delete", "agency_contract", entity_id=contract_id,
               details=code, ip_address=get_client_ip(request))
    db.commit()
    broadcast_sales_update(background_tasks, BroadcastModule.KONTRATLAR, "delete")


# ─── Alt varlık CRUD (kind-tabanlı) ─────────────────────

def _validate_kind(kind: str):
    if kind not in _KIND_SCHEMAS:
        raise HTTPException(status_code=404,
                            detail=f"Bilinmeyen alt varlık türü: {kind}")


@router.post("/{contract_id}/children/{kind}", status_code=status.HTTP_201_CREATED)
def create_child(
    contract_id: int,
    kind: str,
    body: dict,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Kontrata alt varlık ekle (dönem/oda-eşleme/plan/taksit/aksiyon/band/kontenjan/kesinti)."""
    _validate_kind(kind)
    if not db.query(AgencyContract).filter(AgencyContract.id == contract_id).first():
        raise HTTPException(status_code=404, detail="Kontrat bulunamadı")

    data = _KIND_SCHEMAS[kind](**body).model_dump()

    approval_resp = check_approval(
        db, MODULE_CODE, 0, current_user.id, "create",
        {"_kind": kind, "_contract_id": contract_id, **data})
    if approval_resp:
        return approval_resp

    try:
        obj = contract_service.create_child(db, kind, contract_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_action(db, current_user.id, "create", f"contract_{kind}", entity_id=obj.id,
               details=f"kontrat #{contract_id}", ip_address=get_client_ip(request))
    db.commit()
    broadcast_sales_update(background_tasks, BroadcastModule.KONTRATLAR, "create")
    return _child_dict(obj)


@router.patch("/children/{kind}/{child_id}")
def update_child(
    kind: str,
    child_id: int,
    body: dict,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    _validate_kind(kind)
    obj = contract_service.get_child(db, kind, child_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı")

    # Partial update: mevcut kayıt + gönderilenler create şemasından geçirilir
    # (tam doğrulama), sonra yalnız gönderilen alanlar uygulanır.
    schema = _KIND_SCHEMAS[kind]
    merged = {**_child_dict(obj), **body}
    merged.pop("id", None)
    try:
        validated = schema(**merged).model_dump()
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Geçersiz alan değeri: {e}")
    data = {k: v for k, v in validated.items() if k in body}

    approval_resp = check_approval(
        db, MODULE_CODE, child_id, current_user.id, "update",
        {"_kind": kind, **data})
    if approval_resp:
        return approval_resp

    contract_service.apply_child_update(db, kind, obj, data)
    log_action(db, current_user.id, "update", f"contract_{kind}", entity_id=child_id,
               details=None, ip_address=get_client_ip(request))
    db.commit()
    broadcast_sales_update(background_tasks, BroadcastModule.KONTRATLAR, "update")
    return _child_dict(obj)


@router.delete("/children/{kind}/{child_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_child(
    kind: str,
    child_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    _validate_kind(kind)
    obj = contract_service.get_child(db, kind, child_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı")

    approval_resp = check_approval(
        db, MODULE_CODE, child_id, current_user.id, "delete", {"_kind": kind})
    if approval_resp:
        return approval_resp

    try:
        contract_service.delete_child(db, kind, obj)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    log_action(db, current_user.id, "delete", f"contract_{kind}", entity_id=child_id,
               details=None, ip_address=get_client_ip(request))
    db.commit()
    broadcast_sales_update(background_tasks, BroadcastModule.KONTRATLAR, "delete")


# ─── Belge arşivi (onay akışı DIŞI — dosya istisnası; audit + broadcast VAR) ───

@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    agency_group_id: int = Form(...),
    contract_id: Optional[int] = Form(None),
    doc_type: str = Form("other"),
    doc_date: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Kontrat belgesi yükle (PDF/Excel) — arşive kaydeder, istenirse kontrata bağlar."""
    if doc_type not in ALL_DOC_TYPES:
        raise HTTPException(status_code=400, detail=f"Geçersiz belge türü: {doc_type}")
    if not db.query(AgencyGroup).filter(AgencyGroup.id == agency_group_id).first():
        raise HTTPException(status_code=404, detail="Acente grubu bulunamadı")
    if contract_id and not db.query(AgencyContract).filter(
            AgencyContract.id == contract_id).first():
        raise HTTPException(status_code=404, detail="Kontrat bulunamadı")

    content = await validate_upload_file(file, allowed_types=["pdf", "excel"])
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()

    _ensure_upload_dir()
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)
    with open(file_path, "wb") as f:
        f.write(content)

    doc = contract_service.create_document(
        db, agency_group_id, file_path, (file.filename or unique_name)[:255],
        doc_type, current_user.id, contract_id, doc_date, notes)

    log_action(db, current_user.id, "create", "contract_document", entity_id=doc.id,
               details=doc.original_name, ip_address=get_client_ip(request))
    db.commit()
    broadcast_sales_update(background_tasks, BroadcastModule.KONTRATLAR, "create")
    return _child_dict(doc)


@router.get("/documents/{doc_id}/download")
def download_document(
    doc_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(MODULE_CODE, "view")),
):
    doc = db.query(ContractDocument).filter(ContractDocument.id == doc_id).first()
    if not doc or not os.path.isfile(doc.file_path):
        raise HTTPException(status_code=404, detail="Belge bulunamadı")
    return FileResponse(doc.file_path, filename=doc.original_name,
                        headers={"Content-Disposition":
                                 f'attachment; filename="{doc.original_name}"'})


@router.patch("/documents/{doc_id}")
def update_document_meta(
    doc_id: int,
    data: DocumentMetaUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Belge metadata güncelle (kontrata bağlama, tür, tarih) — dosya istisnası kapsamı."""
    doc = db.query(ContractDocument).filter(ContractDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Belge bulunamadı")
    payload = data.model_dump(exclude_unset=True)
    if payload.get("contract_id") and not db.query(AgencyContract).filter(
            AgencyContract.id == payload["contract_id"]).first():
        raise HTTPException(status_code=404, detail="Kontrat bulunamadı")

    contract_service.apply_document_meta(db, doc, payload)
    log_action(db, current_user.id, "update", "contract_document", entity_id=doc.id,
               details=doc.original_name, ip_address=get_client_ip(request))
    db.commit()
    broadcast_sales_update(background_tasks, BroadcastModule.KONTRATLAR, "update")
    return _child_dict(doc)


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    doc_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(MODULE_CODE, "use")),
):
    """Belgeyi sil — dosya diskten de kaldırılır (audit'li)."""
    doc = db.query(ContractDocument).filter(ContractDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Belge bulunamadı")
    name, path = doc.original_name, doc.file_path
    db.delete(doc)
    log_action(db, current_user.id, "delete", "contract_document", entity_id=doc_id,
               details=name, ip_address=get_client_ip(request))
    db.commit()
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass  # dosya silinemese de DB kaydı gitti — yetim dosya zararsız
    broadcast_sales_update(background_tasks, BroadcastModule.KONTRATLAR, "delete")
