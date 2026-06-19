from typing import List, Set

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.constants import WSEvent
from app.database import get_db
from app.middleware.auth import get_current_user, invalidate_module_cache, require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.module import Module
from app.models.user import User
from app.schemas.module import ModuleCreate, ModuleResponse, ModuleUpdate
from app.utils.approval_check import check_approval
from app.utils.audit import log_action
from app.websocket.manager import manager


def _get_descendant_ids(module_id: int, db: Session) -> Set[int]:
    """Bir modülün tüm alt modül ID'lerini döndür (döngüsel referans kontrolü için)."""
    descendants: Set[int] = set()
    queue = [module_id]
    while queue:
        current = queue.pop()
        children = db.query(Module.id).filter(Module.parent_id == current).all()
        for (child_id,) in children:
            if child_id not in descendants:
                descendants.add(child_id)
                queue.append(child_id)
    return descendants

router = APIRouter()


@router.get("/", response_model=List[ModuleResponse])
def list_modules(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system.modules", "view")),
):
    return db.query(Module).order_by(Module.sort_order).all()


@router.get("/tree", response_model=List[ModuleResponse])
def get_module_tree(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return modules as hierarchical tree (for navbar)."""
    modules = db.query(Module).filter(Module.is_active == True).order_by(Module.sort_order).all()

    # Build tree
    module_map = {}
    roots = []
    for m in modules:
        module_map[m.id] = {
            "id": m.id,
            "name": m.name,
            "code": m.code,
            "description": m.description,
            "icon": m.icon,
            "parent_id": m.parent_id,
            "sort_order": m.sort_order,
            "is_active": m.is_active,
            "created_at": m.created_at,
            "children": [],
        }

    for m in modules:
        if m.parent_id and m.parent_id in module_map:
            module_map[m.parent_id]["children"].append(module_map[m.id])
        elif not m.parent_id:
            roots.append(module_map[m.id])

    return roots


@router.post("/", response_model=ModuleResponse, status_code=status.HTTP_201_CREATED)
def create_module(
    data: ModuleCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.modules", "use")),
):
    existing = db.query(Module).filter(Module.code == data.code).first()
    if existing:
        raise HTTPException(status_code=409, detail="Bu modül kodu zaten mevcut!")

    # parent_id geçerliliği kontrolü
    if data.parent_id is not None:
        parent = db.query(Module).filter(Module.id == data.parent_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Üst modül bulunamadı")

    approval_resp = check_approval(db, "system.modules", 0, current_user.id, "create", data.model_dump())
    if approval_resp:
        return approval_resp

    module = Module(**data.model_dump())
    db.add(module)
    db.flush()

    client_ip = get_client_ip(request)
    log_action(db, current_user.id, "create", "module", entity_id=module.id, ip_address=client_ip)
    db.commit()
    invalidate_module_cache()
    db.refresh(module)

    # Yeni modül oluşturuldu — tüm online kullanıcıları bildir
    background_tasks.add_task(
        manager.send_to_all,
        {"type": WSEvent.PERMISSION_CHANGED, "reason": "module_created"},
    )

    return module


@router.get("/{module_id}", response_model=ModuleResponse)
def get_module(
    module_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("system.modules", "view")),
):
    module = db.query(Module).filter(Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Modül bulunamadı")
    return module


@router.patch("/{module_id}", response_model=ModuleResponse)
def update_module(
    module_id: int,
    data: ModuleUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.modules", "use")),
):
    module = db.query(Module).filter(Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Modül bulunamadı")

    approval_resp = check_approval(db, "system.modules", module_id, current_user.id, "update", data.model_dump(exclude_unset=True))
    if approval_resp:
        return approval_resp

    update_data = data.model_dump(exclude_unset=True)

    # code değişiyorsa benzersizlik kontrolü
    if "code" in update_data and update_data["code"] != module.code:
        existing = db.query(Module).filter(Module.code == update_data["code"]).first()
        if existing:
            raise HTTPException(status_code=409, detail="Bu modül kodu zaten mevcut!")

    # parent_id değişiyorsa döngüsel referans kontrolü
    if "parent_id" in update_data and update_data["parent_id"] is not None:
        new_parent_id = update_data["parent_id"]
        if new_parent_id == module_id:
            raise HTTPException(status_code=400, detail="Bir modül kendisinin üst modülü olamaz")
        descendant_ids = _get_descendant_ids(module_id, db)
        if new_parent_id in descendant_ids:
            raise HTTPException(status_code=400, detail="Döngüsel referans: Alt modül üst modül olarak atanamaz")
        parent = db.query(Module).filter(Module.id == new_parent_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Üst modül bulunamadı")

    for key, value in update_data.items():
        setattr(module, key, value)

    client_ip = get_client_ip(request)
    log_action(db, current_user.id, "update", "module", entity_id=module_id, ip_address=client_ip)
    db.commit()
    invalidate_module_cache()
    db.refresh(module)

    # Modül değişikliğini tüm online kullanıcılara bildir
    background_tasks.add_task(
        manager.send_to_all,
        {"type": WSEvent.PERMISSION_CHANGED, "reason": "module_updated"},
    )

    return module


@router.delete("/{module_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_module(
    module_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("system.modules", "use")),
):
    module = db.query(Module).filter(Module.id == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Modül bulunamadı")

    approval_resp = check_approval(db, "system.modules", module_id, current_user.id, "delete", {})
    if approval_resp:
        return approval_resp

    # Alt modül kontrolü
    child_count = db.query(Module).filter(Module.parent_id == module_id).count()
    if child_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Bu modülün {child_count} alt modülü var. Önce alt modülleri silin veya taşıyın."
        )

    client_ip = get_client_ip(request)
    log_action(db, current_user.id, "delete", "module", entity_id=module_id, ip_address=client_ip)
    db.delete(module)
    db.commit()
    invalidate_module_cache()

    # Modül silme değişikliğini tüm online kullanıcılara bildir
    background_tasks.add_task(
        manager.send_to_all,
        {"type": WSEvent.PERMISSION_CHANGED, "reason": "module_deleted"},
    )
