"""PDKS — yönetici izleme/raporlar (durum, log, puantaj) + elle giriş/düzenle/sil + onay bekleyenler."""
from ._helpers import *  # noqa: F401,F403 — paylaşılan import/sabit/helper/şema (bkz. _helpers.__all__)

router = APIRouter()


# ═══ YÖNETİCİ — İzleme + raporlar ════════════════════════

@router.get("/attendance/status")
def who_is_inside(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("hr.attendance", "view")),
):
    """Şu an içeride olan personeller (son basışı 'in' olanlar)."""
    # Her personelin son log'u
    sub = (
        db.query(AttendanceLog.personnel_id, func.max(AttendanceLog.punched_at).label("mx"))
        .filter(AttendanceLog.deleted_at.is_(None))
        .group_by(AttendanceLog.personnel_id)
        .subquery()
    )
    rows = (
        db.query(AttendanceLog, Personnel)
        .join(sub, (AttendanceLog.personnel_id == sub.c.personnel_id) & (AttendanceLog.punched_at == sub.c.mx))
        .join(Personnel, Personnel.id == AttendanceLog.personnel_id)
        .filter(AttendanceLog.type == TYPE_IN, AttendanceLog.deleted_at.is_(None))
        .order_by(desc(AttendanceLog.punched_at))
        .all()
    )
    inside = [{
        "personnel_id": p.id, "full_name": p.full_name, "department": p.department,
        "since": lg.punched_at.isoformat(),
    } for lg, p in rows]
    return {"inside_count": len(inside), "inside": inside}


@router.get("/attendance/logs")
def list_logs(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("hr.attendance", "view")),
    personnel_id: Optional[int] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    q = db.query(AttendanceLog, Personnel).join(Personnel, Personnel.id == AttendanceLog.personnel_id)
    if personnel_id:
        q = q.filter(AttendanceLog.personnel_id == personnel_id)
    if start_date:
        q = q.filter(AttendanceLog.punched_at >= TZ.localize(datetime.combine(start_date, datetime.min.time())))
    if end_date:
        q = q.filter(AttendanceLog.punched_at < TZ.localize(datetime.combine(end_date + timedelta(days=1), datetime.min.time())))
    total = q.count()
    rows = q.order_by(desc(AttendanceLog.punched_at)).offset((page - 1) * page_size).limit(page_size).all()
    items = [{
        "id": lg.id, "personnel_id": p.id, "full_name": p.full_name, "department": p.department,
        "type": lg.type, "punched_at": lg.punched_at.isoformat(), "source": lg.source,
        "note": lg.note,
        "edited_at": lg.edited_at.isoformat() if lg.edited_at else None,
        "deleted_at": lg.deleted_at.isoformat() if lg.deleted_at else None,
    } for lg, p in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": math.ceil(total / page_size) if total else 1}


@router.get("/attendance/summary")
def monthly_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("hr.attendance", "view")),
    month: Optional[str] = Query(None),  # YYYY-MM
):
    """Aylık puantaj — personel başına toplam içeride-süre (dakika) + gün sayısı."""
    now = datetime.now(TZ)
    if month:
        try:
            y, m = map(int, month.split("-"))
        except ValueError:
            raise HTTPException(status_code=400, detail="month formatı YYYY-MM olmalı")
    else:
        y, m = now.year, now.month
    start = TZ.localize(datetime(y, m, 1))
    end = TZ.localize(datetime(y + (m // 12), (m % 12) + 1, 1))

    logs = (
        db.query(AttendanceLog, Personnel)
        .join(Personnel, Personnel.id == AttendanceLog.personnel_id)
        .filter(AttendanceLog.punched_at >= start, AttendanceLog.punched_at < end,
                AttendanceLog.deleted_at.is_(None))
        .order_by(AttendanceLog.personnel_id, AttendanceLog.punched_at)
        .all()
    )
    # Personel başına in→out eşle
    by_p: dict = {}
    for lg, p in logs:
        d = by_p.setdefault(p.id, {"full_name": p.full_name, "department": p.department,
                                    "minutes": 0.0, "days": set(), "open_in": None})
        if lg.type == TYPE_IN:
            d["open_in"] = lg.punched_at
        elif lg.type == TYPE_OUT and d["open_in"]:
            d["minutes"] += (lg.punched_at - d["open_in"]).total_seconds() / 60
            d["days"].add(lg.punched_at.date())
            d["open_in"] = None
    result = [{
        "personnel_id": pid, "full_name": v["full_name"], "department": v["department"],
        "total_minutes": round(v["minutes"]), "total_hours": round(v["minutes"] / 60, 1),
        "days_worked": len(v["days"]),
    } for pid, v in by_p.items()]
    result.sort(key=lambda r: r["full_name"])
    return {"month": f"{y:04d}-{m:02d}", "personnel": result}


@router.post("/attendance/manual", status_code=201)
def manual_punch(
    data: ManualPunch,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("hr.attendance", "use")),
):
    """Yönetici elle giriş/çıkış kaydı (telefonu olmayan / unutulan için).

    - **Durum tutarlılığı:** içerideki kişiye tekrar 'giriş' (veya dışarıdakine 'çıkış')
      engellenir — komşu hareketlerle art arda aynı tip olamaz.
    - **Onay akışı:** hr.attendance için aktif workflow + talep edenin rolü requestor ise
      işlem onaya düşer (202); aksi halde doğrudan kaydedilir.
    """
    if data.type not in (TYPE_IN, TYPE_OUT):
        raise HTTPException(status_code=400, detail="type 'in' veya 'out' olmalı")
    p = db.query(Personnel).filter(Personnel.id == data.personnel_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Personel bulunamadı")

    when = _localize(data.punched_at or datetime.now(TZ))
    _assert_alternation(db, p.id, when, data.type)

    # Onay akışı — aktif workflow + requestor rolü varsa 202 döner, kayıt onaya gider
    payload = data.model_dump()
    payload["punched_at"] = when.isoformat()
    approval_resp = check_approval(db, "hr.attendance", 0, current_user.id, "create", payload)
    if approval_resp:
        return approval_resp

    lg = AttendanceLog(
        personnel_id=p.id, type=data.type, source=SOURCE_MANUAL,
        recorded_by=current_user.id, note=(data.note or "").strip() or None,
        punched_at=when,
    )
    db.add(lg)
    db.flush()
    log_action(db, current_user.id, "manual_punch", "attendance", lg.id,
               f"Elle {data.type} ({when.strftime('%d.%m %H:%M')}): {p.full_name}", get_client_ip(request))
    db.commit()
    manager.send_to_all_sync({"type": WSEvent.ATTENDANCE_UPDATED, "action": "manual"})
    return {"ok": True, "type": data.type, "personnel": p.full_name}


@router.patch("/attendance/logs/{log_id}")
def update_log(
    log_id: int,
    data: LogUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("hr.attendance", "use")),
):
    """Mevcut giriş/çıkış kaydını elle düzenle (tip / zaman / not).

    Çift giriş/çıkış engeli (kendisi hariç komşulara göre) + audit + onay akışına tabi.
    """
    lg = db.query(AttendanceLog).filter(AttendanceLog.id == log_id).first()
    if not lg:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
    if lg.deleted_at:
        raise HTTPException(status_code=400, detail="Silinmiş kayıt düzenlenemez")

    fields = data.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="Güncellenecek alan yok")
    new_type = fields.get("type") or lg.type
    if new_type not in (TYPE_IN, TYPE_OUT):
        raise HTTPException(status_code=400, detail="type 'in' veya 'out' olmalı")
    new_when = _localize(fields["punched_at"]) if fields.get("punched_at") else lg.punched_at
    _assert_alternation(db, lg.personnel_id, new_when, new_type, exclude_id=lg.id)

    # Onay akışı — payload'da punched_at concrete isoformat
    payload = dict(fields)
    if fields.get("punched_at"):
        payload["punched_at"] = new_when.isoformat()
    approval_resp = check_approval(db, "hr.attendance", lg.id, current_user.id, "update", payload)
    if approval_resp:
        return approval_resp

    old_type, old_when, old_note = lg.type, lg.punched_at, lg.note
    if "type" in fields:
        lg.type = new_type
    if "note" in fields:
        lg.note = (fields["note"] or "").strip() or None
    if fields.get("punched_at"):
        lg.punched_at = new_when
    lg.edited_at = datetime.now(TZ)
    detail = _edit_detail(old_type, old_when, old_note, lg.type, lg.punched_at, lg.note)
    log_action(db, current_user.id, "update", "attendance", lg.id, detail, get_client_ip(request))
    db.commit()
    manager.send_to_all_sync({"type": WSEvent.ATTENDANCE_UPDATED, "action": "edit"})
    return {"ok": True, "id": lg.id, "type": lg.type,
            "punched_at": lg.punched_at.isoformat(), "note": lg.note}


@router.delete("/attendance/logs/{log_id}")
def delete_log(
    log_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("hr.attendance", "use")),
):
    """Giriş/çıkış kaydını sil (soft delete — kayıt kalır, soluk gösterilir). Audit + onay akışına tabi."""
    lg = db.query(AttendanceLog).filter(AttendanceLog.id == log_id).first()
    if not lg:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
    if lg.deleted_at:
        raise HTTPException(status_code=400, detail="Kayıt zaten silinmiş")

    approval_resp = check_approval(db, "hr.attendance", lg.id, current_user.id, "delete", {})
    if approval_resp:
        return approval_resp

    log_action(db, current_user.id, "delete", "attendance", lg.id,
               f"Kayıt #{lg.id} silindi ({_type_tr(lg.type)} {lg.punched_at.astimezone(TZ).strftime('%d.%m %H:%M')})",
               get_client_ip(request))
    lg.deleted_at = datetime.now(TZ)  # soft delete
    db.commit()
    manager.send_to_all_sync({"type": WSEvent.ATTENDANCE_UPDATED, "action": "delete"})
    return {"ok": True}


@router.get("/attendance/logs/{log_id}/history")
def log_history(
    log_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("hr.attendance", "view")),
):
    """Bir kaydın değişiklik tarihçesi (audit_logs) + varsa bekleyen onay işlemi."""
    lg = db.query(AttendanceLog).filter(AttendanceLog.id == log_id).first()
    if not lg:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı")
    rows = (
        db.query(AuditLog, User)
        .outerjoin(User, User.id == AuditLog.user_id)
        .filter(AuditLog.entity_type == "attendance", AuditLog.entity_id == log_id)
        .order_by(AuditLog.created_at)
        .all()
    )
    history = [{
        "action": a.action,
        "user_name": (u.full_name if u else None),
        "details": a.details,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    } for a, u in rows]
    pending = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.module_code == "hr.attendance",
                ApprovalRequest.entity_id == log_id,
                ApprovalRequest.status == STATUS_PENDING)
        .first()
    )
    return {
        "id": lg.id,
        "edited_at": lg.edited_at.isoformat() if lg.edited_at else None,
        "history": history,
        "pending_action": pending.action_type if pending else None,
    }


# ═══ YÖNETİCİ — Onay bekleyenler (PDKS) ══════════════════

@router.get("/attendance/pending")
def list_pending(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("hr.attendance", "view")),
):
    """Bekleyen hr.attendance onay talepleri (ekle/düzenle/sil) — pano + filtre + iptal."""
    reqs = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.module_code == "hr.attendance",
                ApprovalRequest.status == STATUS_PENDING)
        .order_by(desc(ApprovalRequest.requested_at))
        .all()
    )
    user_ids = {r.requested_by for r in reqs if r.requested_by}
    users = {}
    if user_ids:
        users = {u.id: u.full_name for u in db.query(User).filter(User.id.in_(user_ids)).all()}
    items = []
    for r in reqs:
        try:
            payload = json.loads(r.payload_json) if r.payload_json else {}
        except (json.JSONDecodeError, TypeError):
            payload = {}
        pid = payload.get("personnel_id")
        ptype = payload.get("type")
        ptime = payload.get("punched_at")
        if r.action_type in ("update", "delete") and r.entity_id:
            lg = db.query(AttendanceLog).filter(AttendanceLog.id == r.entity_id).first()
            if lg:
                pid = lg.personnel_id
                ptype = ptype or lg.type
                ptime = ptime or lg.punched_at.isoformat()
        pname = None
        if pid:
            per = db.query(Personnel).filter(Personnel.id == pid).first()
            pname = per.full_name if per else None
        items.append({
            "request_id": r.id,
            "action_type": r.action_type,
            "entity_id": r.entity_id,
            "personnel_id": pid,
            "personnel_name": pname,
            "type": ptype,
            "punched_at": ptime,
            "note": payload.get("note"),
            "requested_by": r.requested_by,
            "requested_by_name": users.get(r.requested_by),
            "requested_at": r.requested_at.isoformat() if r.requested_at else None,
            "can_cancel": r.requested_by == current_user.id,
        })
    return {"items": items, "count": len(items)}


@router.post("/attendance/pending/{request_id}/cancel")
def cancel_pending(
    request_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("hr.attendance", "use")),
):
    """Kendi bekleyen hr.attendance onay talebini iptal et (talep sahibi)."""
    req = db.query(ApprovalRequest).filter(ApprovalRequest.id == request_id).first()
    if not req or req.module_code != "hr.attendance":
        raise HTTPException(status_code=404, detail="Onay talebi bulunamadı")
    if req.requested_by != current_user.id:
        raise HTTPException(status_code=403, detail="Yalnızca kendi talebinizi iptal edebilirsiniz")
    if req.status not in (STATUS_PENDING, STATUS_RETURNED):
        raise HTTPException(status_code=400, detail="Bu talep iptal edilebilir durumda değil")
    process_action(db, req, ACTION_CANCEL, current_user.id, None)
    log_action(db, current_user.id, "cancel", "approval_request", req.id,
               f"PDKS onay talebi iptal edildi ({req.action_type})", get_client_ip(request))
    db.commit()
    manager.send_to_all_sync({"type": WSEvent.APPROVAL_STATUS_CHANGED, "module_code": "hr.attendance"})
    manager.send_to_all_sync({"type": WSEvent.ATTENDANCE_UPDATED, "action": "cancel"})
    return {"ok": True}
