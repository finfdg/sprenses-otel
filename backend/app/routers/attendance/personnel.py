"""PDKS — yönetici personel yönetimi (CRUD, Excel içe aktarma, QR kart, cihaz sıfırlama)."""
from ._helpers import *  # noqa: F401,F403 — paylaşılan import/sabit/helper/şema (bkz. _helpers.__all__)

router = APIRouter()


# ═══ YÖNETİCİ — Personel yönetimi ════════════════════════

@router.post("/attendance/personnel/{personnel_id}/reset-device")
def reset_device(
    personnel_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("hr.attendance", "use")),
):
    """Personelin bağlı cihazını çöz — yeni telefon / tarayıcı verisi silme sonrası.

    Bağ kalkınca personel kartını okutan İLK cihaz yeniden bağlanır. Operasyonel
    güvenlik işlemi (şifre sıfırlama gibi) — onay akışına tabi değil, audit'lenir.
    """
    p = db.query(Personnel).filter(Personnel.id == personnel_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Personel bulunamadı")
    p.device_token_hash = None
    p.device_bound_at = None
    log_action(db, current_user.id, "device_reset", "attendance_device", p.id,
               f"Cihaz sıfırlandı: {p.full_name}", get_client_ip(request))
    db.commit()
    return {"ok": True}


@router.get("/attendance/personnel")
def list_personnel(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("hr.attendance", "view")),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    include_inactive: bool = Query(True),
):
    q = db.query(Personnel)
    if not include_inactive:
        q = q.filter(Personnel.is_active.is_(True))
    if search:
        like = f"%{search.strip()}%"
        q = q.filter((Personnel.full_name.ilike(like)) | (Personnel.employee_code.ilike(like)))
    total = q.count()
    items = q.order_by(Personnel.full_name).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [_personnel_dict(p) for p in items],
        "total": total, "page": page, "page_size": page_size,
        "pages": math.ceil(total / page_size) if total else 1,
    }


@router.post("/attendance/personnel", status_code=201)
def create_personnel(
    data: PersonnelCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("hr.attendance", "use")),
):
    code = data.employee_code.strip()
    if db.query(Personnel).filter(Personnel.employee_code == code).first():
        raise HTTPException(status_code=400, detail="Bu sicil no zaten kayıtlı")
    p = Personnel(
        full_name=data.full_name.strip(),
        employee_code=code,
        department=(data.department or "").strip() or None,
        title=(data.title or "").strip() or None,
        phone=(data.phone or "").strip() or None,
        access_token=secrets.token_urlsafe(24),
    )
    db.add(p)
    db.flush()
    log_action(db, current_user.id, "create", "personnel", p.id,
               f"Personel: {p.full_name} ({p.employee_code})", get_client_ip(request))
    db.commit()
    db.refresh(p)
    return _personnel_dict(p)


@router.post("/attendance/personnel/import")
async def import_personnel(
    request: Request,
    file: UploadFile = File(...),
    replace: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("hr.attendance", "use")),
):
    """Excel sicil listesinden personel içe aktar — upsert (sicil no = employee_code).

    Beklenen başlıklar (sırası önemsiz): Sicil No, Ad Soyad, Departman, Görev.
    Var olan sicil güncellenir (ad/departman/görev), yoksa yeni eklenir (kişisel token üretilir).
    replace=True ise içe aktarmadan önce TÜM personel (ve CASCADE ile giriş/çıkış kayıtları) silinir.
    """
    content = await validate_upload_file(file, allowed_types=["excel"])
    ext = os.path.splitext(file.filename or "")[1].lower() or ".xlsx"
    try:
        rows = _parse_personnel_excel(content, ext)
    except Exception:
        raise HTTPException(status_code=400, detail="Dosya ayrıştırılamadı. Geçerli bir Excel (.xls/.xlsx) yükleyin.")
    if not rows:
        raise HTTPException(
            status_code=400,
            detail="Beklenen kolonlar bulunamadı. Başlıkta en az 'Sicil No' ve 'Ad Soyad' olmalı (Departman/Görev opsiyonel).",
        )

    deleted = 0
    if replace:
        deleted = db.query(Personnel).delete(synchronize_session=False)  # CASCADE → attendance_logs

    created = updated = 0
    seen: set = set()
    for r in rows:
        if r["employee_code"] in seen:
            continue
        seen.add(r["employee_code"])
        existing = db.query(Personnel).filter(Personnel.employee_code == r["employee_code"]).first()
        if existing:
            existing.full_name = r["full_name"]
            existing.department = r["department"]
            existing.title = r["title"]
            existing.is_active = True
            updated += 1
        else:
            db.add(Personnel(
                full_name=r["full_name"],
                employee_code=r["employee_code"],
                department=r["department"],
                title=r["title"],
                access_token=secrets.token_urlsafe(24),
            ))
            created += 1
    log_action(db, current_user.id, "import", "personnel", None,
               f"Sicil içe aktarma: {created} yeni, {updated} güncel, {deleted} silindi ({len(seen)} satır)",
               get_client_ip(request))
    db.commit()
    return {"ok": True, "created": created, "updated": updated, "deleted": deleted, "total": len(seen)}


@router.patch("/attendance/personnel/{pid}")
def update_personnel(
    pid: int,
    data: PersonnelUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("hr.attendance", "use")),
):
    p = db.query(Personnel).filter(Personnel.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Personel bulunamadı")
    payload = data.model_dump(exclude_unset=True)
    if "employee_code" in payload and payload["employee_code"]:
        code = payload["employee_code"].strip()
        clash = db.query(Personnel).filter(Personnel.employee_code == code, Personnel.id != pid).first()
        if clash:
            raise HTTPException(status_code=400, detail="Bu sicil no başka personelde")
        p.employee_code = code
    for f in ("full_name", "department", "title", "phone", "is_active"):
        if f in payload:
            setattr(p, f, payload[f])
    log_action(db, current_user.id, "update", "personnel", p.id,
               f"Personel güncellendi: {p.full_name}", get_client_ip(request))
    db.commit()
    db.refresh(p)
    return _personnel_dict(p)


@router.delete("/attendance/personnel/{pid}")
def delete_personnel(
    pid: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("hr.attendance", "use")),
):
    p = db.query(Personnel).filter(Personnel.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Personel bulunamadı")
    log_action(db, current_user.id, "delete", "personnel", p.id,
               f"Personel silindi: {p.full_name} ({p.employee_code})", get_client_ip(request))
    db.delete(p)  # CASCADE logları siler
    db.commit()
    return {"detail": "Personel silindi"}


@router.get("/attendance/personnel/{pid}/qr")
def personnel_setup_qr(
    pid: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("hr.attendance", "view")),
):
    """Personelin kişisel kurulum linkinin QR'ı (kart basmak için)."""
    p = db.query(Personnel).filter(Personnel.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Personel bulunamadı")
    return _svg_qr(f"{PUBLIC_BASE}/devam/kur?t={p.access_token}")


@router.get("/attendance/personnel/cards.pdf")
def personnel_cards_pdf(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("hr.attendance", "view")),
):
    """Tüm aktif personelin QR kartlarını tek PDF'te üretir (yazdırılıp kesilebilir)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as rl_canvas

    from app.utils.pdf_fonts import register_turkish_fonts

    base_font, bold_font = register_turkish_fonts()
    people = (
        db.query(Personnel)
        .filter(Personnel.is_active.is_(True))
        .order_by(Personnel.employee_code)
        .all()
    )

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    cols, rows = 2, 5
    margin = 10 * mm
    gap = 5 * mm
    cw = (W - 2 * margin - (cols - 1) * gap) / cols
    ch = (H - 2 * margin - (rows - 1) * gap) / rows
    per_page = cols * rows
    qsize = 28 * mm

    for idx, p in enumerate(people):
        pos = idx % per_page
        if idx > 0 and pos == 0:
            c.showPage()
        col = pos % cols
        row = pos // cols
        x = margin + col * (cw + gap)
        y = H - margin - (row + 1) * ch - row * gap
        c.setStrokeColorRGB(0.82, 0.82, 0.82)
        c.roundRect(x, y, cw, ch, 6, stroke=1, fill=0)
        # QR (kurulum linki)
        qr = segno.make(f"{PUBLIC_BASE}/devam/kur?t={p.access_token}", error="m")
        qb = io.BytesIO()
        qr.save(qb, kind="png", scale=6, border=1)
        qb.seek(0)
        c.drawImage(ImageReader(qb), x + 4 * mm, y + (ch - qsize) / 2, qsize, qsize)
        # Metin
        tx = x + qsize + 8 * mm
        ty = y + ch - 9 * mm
        c.setFillColorRGB(0, 0, 0)
        c.setFont(bold_font, 10)
        c.drawString(tx, ty, (p.full_name or "")[:24])
        c.setFont(base_font, 8)
        c.drawString(tx, ty - 13, f"Sicil: {p.employee_code}")
        if p.department:
            c.drawString(tx, ty - 25, p.department[:22])
        if p.title:
            c.setFillColorRGB(0.3, 0.3, 0.3)
            c.drawString(tx, ty - 37, p.title[:22])
        c.setFont(base_font, 6.5)
        c.setFillColorRGB(0.55, 0.55, 0.55)
        c.drawString(tx, y + 5 * mm, "Uygulamandan 'Tara' ile okut")

    if not people:
        c.setFont(base_font, 12)
        c.drawString(margin, H / 2, "Aktif personel yok")
    c.showPage()
    c.save()
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=personel-qr-kartlari.pdf"},
    )
