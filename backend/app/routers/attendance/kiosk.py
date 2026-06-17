"""PDKS — public kiosk ekranı + personel kimlik/basış + QR ayarları."""
from ._helpers import *  # noqa: F401,F403 — paylaşılan import/sabit/helper/şema (bkz. _helpers.__all__)

router = APIRouter()


# ═══ PUBLIC — Kiosk ekranı ═══════════════════════════════

@router.get("/attendance/kiosk/qr")
def kiosk_qr(key: str = Query(...)):
    """Girişteki ekranın gösterdiği dönen QR (SVG). KIOSK_KEY gerektirir."""
    if not hmac.compare_digest(key, KIOSK_KEY):
        raise HTTPException(status_code=403, detail="Geçersiz kiosk anahtarı")
    url = f"{PUBLIC_BASE}/devam?k={_make_token()}"
    return _svg_qr(url)


@router.get("/attendance/kiosk/config")
def kiosk_config(key: str = Query(...), db: Session = Depends(get_db)):
    """Kiosk ekranının yenileme süresi (saniye). KIOSK_KEY gerektirir."""
    if not hmac.compare_digest(key, KIOSK_KEY):
        raise HTTPException(status_code=403, detail="Geçersiz kiosk anahtarı")
    refresh = _get_refresh(db)
    return {"refresh_sec": refresh, "ttl_sec": _ttl_for(refresh)}


@router.get("/attendance/kiosk/recent")
def kiosk_recent(
    key: str = Query(...),
    limit: int = Query(8, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """Girişteki ekranın sağ paneli için son giriş/çıkış hareketleri. KIOSK_KEY gerektirir."""
    if not hmac.compare_digest(key, KIOSK_KEY):
        raise HTTPException(status_code=403, detail="Geçersiz kiosk anahtarı")
    rows = (
        db.query(AttendanceLog, Personnel)
        .join(Personnel, Personnel.id == AttendanceLog.personnel_id)
        .filter(AttendanceLog.deleted_at.is_(None))
        .order_by(desc(AttendanceLog.punched_at))
        .limit(limit)
        .all()
    )
    return {"items": [{
        "id": lg.id,
        "full_name": p.full_name,
        "department": p.department,
        "type": lg.type,
        "punched_at": lg.punched_at.isoformat(),
    } for lg, p in rows]}


# ═══ PUBLIC — Personel kimlik + basış ════════════════════

@router.get("/attendance/pdks-manifest")
def pdks_manifest(t: str = Query(...), db: Session = Depends(get_db)):
    """Kişiye özel PWA manifest'i — "Ana Ekrana Ekle" ikonu kişisel basış sayfasını açsın.

    Global manifest (start_url="/") /devam'da KULLANILMAZ; orada login'e gidiyordu.
    Burada start_url personelin token'ını taşır (`/devam/kur?t=<token>`) → ikon doğrudan
    kişisel sayfayı standalone açar VE tarayıcı geçmişi/verisi silinse bile token URL'de
    kaldığından kimlik kendi kendine geri yüklenir (localStorage'a yeniden yazılır).
    """
    tok = (t or "").strip()
    p = db.query(Personnel).filter(
        Personnel.access_token == tok, Personnel.is_active.is_(True)
    ).first()
    label = f"{p.full_name.split()[0]} · Devam" if p else "Devam Takip"
    manifest = {
        "name": label,
        "short_name": "Devam",
        "start_url": f"/devam/kur?t={tok}",
        "scope": "/devam",
        "display": "standalone",
        "background_color": "#f9fafb",
        "theme_color": "#0d9488",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    return Response(
        content=json.dumps(manifest, ensure_ascii=False),
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/attendance/setup")
def setup(data: SetupRequest, request: Request, db: Session = Depends(get_db)):
    """Kişisel kurulum (enrollment) — access_token ile BU cihazı bağla, cihaz token'ı döndür.

    Tek aktif cihaz: personel zaten bir cihaza bağlıysa **409** → yönetici 'Cihaz Sıfırla'
    yapmadan yeni telefonda kullanılamaz. Dönen `device_token` yalnızca bu telefonun
    localStorage'ında saklanır ve basışta `X-Pdks-Device` ile gönderilir (URL'de/QR'da olmaz)
    → kopyalanan kişisel link başka telefonda basış yapamaz.
    """
    punch_limiter.check(f"pdks-setup-{get_client_ip(request)}")
    p = db.query(Personnel).filter(
        Personnel.access_token == data.token.strip(), Personnel.is_active.is_(True)
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Geçersiz veya pasif personel linki")
    if p.device_token_hash:
        raise HTTPException(
            status_code=409,
            detail="Bu kart başka bir cihaza tanımlı. Yöneticiden 'Cihaz Sıfırla' isteyin.",
        )
    device_token = secrets.token_urlsafe(32)
    p.device_token_hash = _hash_device(device_token)
    p.device_bound_at = datetime.now(TZ)
    log_action(db, None, "device_bound", "attendance_device", p.id,
               f"Cihaz bağlandı: {p.full_name}", get_client_ip(request))
    db.commit()
    return {"ok": True, "full_name": p.full_name, "employee_code": p.employee_code, "device_token": device_token}


@router.get("/attendance/me")
def me(request: Request, db: Session = Depends(get_db)):
    """Cihaza bağlı personelin bilgisi + bugünkü durumu (X-Pdks-Device)."""
    p = _personnel_from_device(request, db)
    if not p:
        raise HTTPException(status_code=401, detail="Cihaz tanımlı değil — kurulum gerekli")
    summary = _today_summary(db, p.id)
    last = _last_log(db, p.id)
    return {
        "full_name": p.full_name, "employee_code": p.employee_code, "department": p.department,
        "inside": summary["inside"], "minutes_today": summary["minutes_today"],
        "last_punch": last.punched_at.isoformat() if last else None,
        "last_type": last.type if last else None,
    }


@router.post("/attendance/punch")
def punch(data: PunchRequest, request: Request, db: Session = Depends(get_db)):
    """Kiosk QR'ı okutunca çağrılır — token doğrula, giriş/çıkış kaydet."""
    punch_limiter.check(f"pdks-punch-{get_client_ip(request)}")
    p = _personnel_from_device(request, db)
    if not p:
        raise HTTPException(status_code=401, detail="Cihaz tanımlı değil — kurulum gerekli")
    if not _valid_token(data.k, _ttl_for(_get_refresh(db))):
        raise HTTPException(status_code=400, detail="Karekod süresi doldu — ekrandaki güncel kodu tekrar okutun")

    now = datetime.now(TZ)
    last = _last_log(db, p.id)
    if last and (now - last.punched_at).total_seconds() < PUNCH_DEBOUNCE_SEC:
        raise HTTPException(status_code=429, detail="Çok hızlı — birkaç saniye sonra tekrar deneyin")

    new_type = TYPE_OUT if (last and last.type == TYPE_IN) else TYPE_IN
    lg = AttendanceLog(personnel_id=p.id, type=new_type, source=SOURCE_PHONE)
    db.add(lg)
    db.commit()
    # Canlı pano: bağlı yöneticilere sinyal (PII yok — veri izin-korumalı uçtan çekilir)
    manager.send_to_all_sync({"type": WSEvent.ATTENDANCE_UPDATED, "action": "punch"})

    summary = _today_summary(db, p.id)
    return {
        "ok": True,
        "type": new_type,
        "full_name": p.full_name,
        "time": now.strftime("%H:%M"),
        "minutes_today": summary["minutes_today"],
        "message": f"{'Giriş' if new_type == TYPE_IN else 'Çıkış'} yapıldı — hoş geldin {p.full_name.split()[0]}!"
        if new_type == TYPE_IN else f"Çıkış yapıldı — iyi günler {p.full_name.split()[0]}!",
    }


# ═══ YÖNETİCİ — Kiosk linki + QR ayarları ════════════════

@router.get("/attendance/kiosk-link")
def kiosk_link(_: User = Depends(require_permission("hr.attendance", "view"))):
    """Giriş ekranı için açılacak link (KIOSK_KEY dahil) — admin cihaza kurar."""
    return {"url": f"{PUBLIC_BASE}/devam/ekran?key={KIOSK_KEY}"}


@router.get("/attendance/settings")
def get_settings(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("hr.attendance", "view")),
):
    """PDKS ayarları — QR yenileme süresi + türetilen güvenlik geçerliliği."""
    refresh = _get_refresh(db)
    return {
        "refresh_sec": refresh,
        "ttl_sec": _ttl_for(refresh),
        "min": MIN_REFRESH_SEC,
        "max": MAX_REFRESH_SEC,
    }


@router.patch("/attendance/settings")
def update_settings(
    data: SettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("hr.attendance", "use")),
):
    """QR yenileme süresini güncelle (saniye). Bu modül onay akışından muaftır (ops/HR)."""
    refresh = data.refresh_sec
    if refresh < MIN_REFRESH_SEC or refresh > MAX_REFRESH_SEC:
        raise HTTPException(
            status_code=400,
            detail=f"Süre {MIN_REFRESH_SEC}-{MAX_REFRESH_SEC} saniye arasında olmalı",
        )
    row = db.query(AttendanceSetting).filter(AttendanceSetting.id == 1).first()
    if not row:
        row = AttendanceSetting(id=1, refresh_sec=refresh)
        db.add(row)
    else:
        row.refresh_sec = refresh
    log_action(db, current_user.id, "update", "attendance_settings", 1,
               f"QR yenileme süresi: {refresh}sn", get_client_ip(request))
    db.commit()
    return {
        "refresh_sec": refresh,
        "ttl_sec": _ttl_for(refresh),
        "min": MIN_REFRESH_SEC,
        "max": MAX_REFRESH_SEC,
    }
