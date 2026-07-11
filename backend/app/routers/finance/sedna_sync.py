"""Merkezi Sedna senkronizasyonu — tüm içe aktarmaları TEK noktadan çalıştırır.

Topbar'daki tek "Sedna'dan Veri Çek" butonu bu router'ı çağırır. Her içe aktarma bir
**adım** (`_STEPS` registry'si): cari hareketleri, cari IBAN'ları, verilen çekler.
Kullanıcı yalnızca **izni olan** adımları çalıştırır (diğerleri "yetki yok" atlanır).
Bir adımın hatası diğerlerini durdurmaz (adım-bazlı izolasyon).

**Yeni Sedna içe aktarma eklemek için:**
1. İlgili modülde `run_xxx_import(db, current_user, ip) -> dict` servis fonksiyonu yaz
   (HTTP'siz, broadcast'siz; hata → HTTPException).
2. `_STEPS`'e bir satır ekle (`key`, `label`, `module`, `run`, `broadcast`).
3. `_summarize()`'a kısa Türkçe özet ekle.
Frontend butonu otomatik olarak yeni adımı çalıştırıp sonucunu gösterir.
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.constants import BroadcastModule, WSEvent
from app.database import get_db
from app.middleware.auth import get_current_user, user_can
from app.middleware.rate_limit import get_client_ip
from app.models.user import User
from app.utils.finance_broadcast import broadcast_finance_update, notify_finance_update_sync
from app.websocket.manager import manager
from app.services.reservation_service import run_reservation_import
from app.services.stock_service import run_stock_import
from app.utils.recurring_vendor_sync import run_recurring_vendor_sync
from app.utils.sedna_client import sedna_configured

from .cariler.sedna_import import run_cari_import, run_iban_import
from .check_import import run_check_import
from .sales_invoices import run_sales_invoice_import

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sedna")

# Sedna içe aktarma adımları — sıralı çalışır. Yeni import = buraya bir satır
# ("broadcast" None olabilir → o adım WS bildirimi tetiklemez).
_STEPS = [
    {"key": "cariler", "label": "Cari hareketleri", "module": "finance.cariler",
     "run": run_cari_import, "broadcast": BroadcastModule.CARILER},
    {"key": "ibans", "label": "Cari IBAN'ları", "module": "finance.cariler",
     "run": run_iban_import, "broadcast": BroadcastModule.CARILER},
    {"key": "checks", "label": "Verilen çekler", "module": "finance.checks",
     "run": run_check_import, "broadcast": BroadcastModule.CHECKS},
    {"key": "sales_invoices", "label": "Satış faturaları", "module": "finance.sales_invoices",
     "run": run_sales_invoice_import, "broadcast": BroadcastModule.SALES_INVOICES},
    {"key": "stock", "label": "Stok / depo", "module": "stok.maliyet",
     "run": run_stock_import, "broadcast": BroadcastModule.STOK},
    {"key": "reservations", "label": "Otel rezervasyonları", "module": "sales.acente_mahsup",
     "run": run_reservation_import, "broadcast": None},
    # Sedna çekmez; carilerden TÜRETİR (cari adımından SONRA çalışmalı). Cari-bağlı düzenli
    # ödemelerin (Elektrik→CK, Su→ASAT) tahmini tutarlarını cari gerçek faturayla senkronlar.
    {"key": "recurring_sync", "label": "Düzenli ödeme ↔ cari senkronu", "module": "accounting.recurring",
     "run": run_recurring_vendor_sync, "broadcast": BroadcastModule.ACCOUNTING},
    # Banka ↔ Sedna mutabakat taraması (Uyuşmayan Veriler) — banka verisi otorite,
    # yalnız sınıflandırır; Sedna kopuksa adım-izolasyonla diğer adımlar sürer.
    {"key": "bank_recon", "label": "Banka ↔ Sedna mutabakatı", "module": "accounting.mutabakat",
     "run": lambda db, user, ip: _run_bank_recon(db, user), "broadcast": BroadcastModule.RECON},
]


def _run_bank_recon(db, user):
    from app.services.sedna_recon_service import run_reconciliation, run_vendor_reconciliation

    summary = run_reconciliation(db, triggered_by=user.id)
    # Faz C: cari bakiye mutabakatı (best-effort — banka taraması sonucu korunur)
    try:
        summary.update(run_vendor_reconciliation(db))
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error("Cari bakiye mutabakatı hatası: %s", e)
    return summary


def _summarize(key: str, d: dict) -> str:
    """Adım sonucundan kısa Türkçe özet (frontend'de gösterilir)."""
    if key == "cariler":
        return f"{d.get('new_transactions', 0)} yeni hareket · {d.get('skipped_transactions', 0)} mevcut"
    if key == "ibans":
        return f"{d.get('new_ibans', 0)} yeni IBAN ({d.get('vendors_matched', 0)} cari)"
    if key == "checks":
        m = d.get("matched_to_bank", 0)
        rd = d.get("removed_dupes", 0)
        extra = f" · {m} banka eşleşti" if m else ""
        extra += f" · {rd} mükerrer temizlendi" if rd else ""
        return (f"{d.get('new_checks', 0)} yeni çek · {d.get('updated_checks', 0)} güncel"
                f"{extra}")
    if key == "sales_invoices":
        extra = ""
        if d.get("invoices_updated") or d.get("invoices_removed"):
            extra = f" · {d.get('invoices_updated', 0)} güncel · {d.get('invoices_removed', 0)} silindi"
        return f"{d.get('invoices_new', 0)} yeni fatura · {d.get('collections_new', 0)} yeni tahsilat{extra}"
    if key == "recurring_sync":
        return f"{d.get('entries_synced', 0)} ay senkron ({d.get('definitions', 0)} cari-bağlı kalem)"
    if key == "stock":
        return (f"{d.get('movements_new', 0)} yeni hareket · {d.get('products', 0)} ürün · "
                f"{d.get('depots', 0)} depo")
    if key == "reservations":
        return (f"{d.get('reservations_new', 0)} yeni · {d.get('reservations_updated', 0)} güncel · "
                f"{d.get('removed', 0)} iptal/kaldırılan")
    if key == "bank_recon":
        extra = ""
        if d.get("balance_diffs") is not None:
            extra = f" · {d.get('balance_diffs', 0)} cari bakiye farkı"
        return (f"{d.get('accounts_scanned', 0)} hesap · {d.get('new', 0)} yeni uyuşmazlık · "
                f"{d.get('auto_closed', 0)} otomatik kapandı · {d.get('open', 0)} açık{extra}")
    return "Tamamlandı"


@router.get("/status")
def sedna_sync_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Merkezi sync etkin mi + kullanıcının çalıştırabileceği adımlar (buton gösterimi)."""
    steps = [
        {"key": s["key"], "label": s["label"],
         "allowed": user_can(db, current_user, s["module"], "use")}
        for s in _STEPS
    ]
    return {
        "configured": sedna_configured(),
        "any_allowed": any(s["allowed"] for s in steps),
        "steps": steps,
    }


def run_sync_all_steps(db: Session, user: User, ip: str, progress=None) -> dict:
    """Tüm izinli adımları sırayla koştur (adım-bazlı izolasyon) — SENKRON çekirdek.

    `progress(event_dict)` verilirse her adımın başlangıç/bitişinde çağrılır
    (arka plan işi WS SEDNA_SYNC_PROGRESS yayınlar; testler doğrudan çağırabilir).
    Adım yayını ANINDA yapılır (sona biriktirme kaldırıldı — cariler biter bitmez
    cariler ekranı tazelenir; Faz 2 #18).
    """
    results = []
    allowed = [st for st in _STEPS if user_can(db, user, st["module"], "use")]
    skipped = [st for st in _STEPS if st not in allowed]
    for st in skipped:
        results.append({"key": st["key"], "label": st["label"], "ok": False,
                        "skipped": True, "summary": "Yetki yok"})
    total = len(allowed)

    for idx, st in enumerate(allowed, start=1):
        base = {"key": st["key"], "label": st["label"], "index": idx, "total": total}
        if progress:
            progress({"type": WSEvent.SEDNA_SYNC_PROGRESS, **base, "status": "running"})
        try:
            detail = st["run"](db, user, ip)
            summary = _summarize(st["key"], detail)
            ok = True
        except HTTPException as e:
            db.rollback()
            summary, ok = str(e.detail), False
        except Exception as e:  # noqa: BLE001 — adım izolasyonu: biri patlarsa diğerleri sürer
            db.rollback()
            logger.error("Sedna sync adımı '%s' hatası: %s", st["key"], e, exc_info=True)
            summary, ok = "Beklenmeyen hata", False
        results.append({"key": st["key"], "label": st["label"], "ok": ok,
                        "skipped": False, "summary": summary})
        if progress:
            progress({"type": WSEvent.SEDNA_SYNC_PROGRESS, **base,
                      "status": "ok" if ok else "error", "summary": summary})
        if ok and st.get("broadcast"):
            notify_finance_update_sync(st["broadcast"], "upload")
        if ok and st["key"] == "reservations":
            manager.send_to_all_sync({"type": WSEvent.SALES_UPDATED,
                                      "module": BroadcastModule.HOTEL_RESERVATION,
                                      "action": "upload"})

    summary_dict = {
        "configured": True,
        "ok_count": sum(1 for r in results if r["ok"]),
        "total": len(results),
        "steps": results,
    }
    if progress:
        progress({"type": WSEvent.SEDNA_SYNC_PROGRESS, "status": "done",
                  "ok_count": summary_dict["ok_count"], "total": total,
                  "steps": results})
    return summary_dict


def _run_sync_all_job(user_id: int, ip: str) -> None:
    """Arka plan Sedna senkron işi — kendi DB oturumu + WS ilerleme yayını."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            return
        run_sync_all_steps(db, user, ip, progress=manager.send_to_all_sync)
    except Exception as e:  # noqa: BLE001
        logger.error("Sedna arka plan senkron işi hatası: %s", e, exc_info=True)
        try:
            manager.send_to_all_sync({"type": WSEvent.SEDNA_SYNC_PROGRESS,
                                      "status": "done", "ok_count": 0, "total": 0,
                                      "error": "Senkron beklenmedik şekilde durdu"})
        except Exception:
            pass
    finally:
        db.close()


@router.post("/sync-all")
def sedna_sync_all(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tüm Sedna içe aktarmalarını ARKA PLANDA başlat (Faz 2 #18).

    Eskiden 7-8 adım tek bloklayan HTTP isteğinde koşuyordu (timeout riski +
    ilerleme görünmüyordu). Artık 202 benzeri hemen döner; adım adım ilerleme
    WS `sedna_sync_progress` event'leriyle yayınlanır (Topbar canlı gösterir),
    her adımın modül yayını adım biter bitmez gider.
    """
    if not sedna_configured():
        raise HTTPException(status_code=503, detail="Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD).")

    allowed = [st for st in _STEPS if user_can(db, current_user, st["module"], "use")]
    if not allowed:
        raise HTTPException(status_code=403, detail="Hiçbir senkron adımı için yetkiniz yok.")

    background_tasks.add_task(_run_sync_all_job, current_user.id, get_client_ip(request))
    return {
        "started": True,
        "total": len(allowed),
        "steps": [{"key": st["key"], "label": st["label"]} for st in allowed],
    }


@router.get("/last-sync")
def sedna_last_sync(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Sedna verisinin tazeliği — Topbar rozeti için (Faz 2 #18).

    Kaynaklar: cari (VendorUpload sedna://import), çek (CheckUpload sedna://import),
    banka mutabakatı (sedna_recon_runs). oldest_hours = kritik adımların en eskisi.
    """
    from app.models import SednaReconRun, VendorUpload
    from app.models.check import CheckUpload

    last_cari = (db.query(VendorUpload.uploaded_at)
                 .filter(VendorUpload.file_url == "sedna://import")
                 .order_by(VendorUpload.uploaded_at.desc()).first())
    last_check = (db.query(CheckUpload.uploaded_at)
                  .filter(CheckUpload.file_url == "sedna://import")
                  .order_by(CheckUpload.uploaded_at.desc()).first())
    last_recon = db.query(SednaReconRun.run_at).order_by(SednaReconRun.id.desc()).first()

    from datetime import datetime, timezone

    def _age_hours(ts):
        if not ts or not ts[0]:
            return None
        dt = ts[0]
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - dt).total_seconds() / 3600, 1)

    ages = [a for a in (_age_hours(last_cari), _age_hours(last_check)) if a is not None]
    return {
        "last_cari_sync": last_cari[0].isoformat() if last_cari and last_cari[0] else None,
        "last_check_sync": last_check[0].isoformat() if last_check and last_check[0] else None,
        "last_bank_recon": last_recon[0].isoformat() if last_recon and last_recon[0] else None,
        "oldest_hours": max(ages) if ages else None,
    }
