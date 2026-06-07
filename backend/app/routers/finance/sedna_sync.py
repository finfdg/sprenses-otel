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

from app.constants import BroadcastModule
from app.database import get_db
from app.middleware.auth import get_current_user, user_can
from app.middleware.rate_limit import get_client_ip
from app.models.user import User
from app.utils.finance_broadcast import broadcast_finance_update
from app.routers.stock import run_stock_import
from app.utils.recurring_vendor_sync import run_recurring_vendor_sync
from app.utils.sedna_client import sedna_configured

from .cariler.sedna_import import run_cari_import, run_iban_import
from .checks import run_check_import
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
     "run": run_sales_invoice_import, "broadcast": None},
    {"key": "stock", "label": "Stok / depo", "module": "stok.maliyet",
     "run": run_stock_import, "broadcast": None},
    # Sedna çekmez; carilerden TÜRETİR (cari adımından SONRA çalışmalı). Cari-bağlı düzenli
    # ödemelerin (Elektrik→CK, Su→ASAT) tahmini tutarlarını cari gerçek faturayla senkronlar.
    {"key": "recurring_sync", "label": "Düzenli ödeme ↔ cari senkronu", "module": "accounting.recurring",
     "run": run_recurring_vendor_sync, "broadcast": BroadcastModule.ACCOUNTING},
]


def _summarize(key: str, d: dict) -> str:
    """Adım sonucundan kısa Türkçe özet (frontend'de gösterilir)."""
    if key == "cariler":
        return f"{d.get('new_transactions', 0)} yeni hareket · {d.get('skipped_transactions', 0)} mevcut"
    if key == "ibans":
        return f"{d.get('new_ibans', 0)} yeni IBAN ({d.get('vendors_matched', 0)} cari)"
    if key == "checks":
        m = d.get("matched_to_bank", 0)
        extra = f" · {m} banka eşleşti" if m else ""
        return (f"{d.get('new_checks', 0)} yeni çek · {d.get('updated_checks', 0)} durum güncel"
                f"{extra}")
    if key == "sales_invoices":
        return f"{d.get('invoices_new', 0)} yeni fatura · {d.get('collections_new', 0)} yeni tahsilat"
    if key == "recurring_sync":
        return f"{d.get('entries_synced', 0)} ay senkron ({d.get('definitions', 0)} cari-bağlı kalem)"
    if key == "stock":
        return (f"{d.get('movements_new', 0)} yeni hareket · {d.get('products', 0)} ürün · "
                f"{d.get('depots', 0)} depo")
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


@router.post("/sync-all")
def sedna_sync_all(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tüm Sedna içe aktarmalarını sırayla çalıştır (izinli adımlar). Adım-bazlı izole."""
    if not sedna_configured():
        raise HTTPException(status_code=503, detail="Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD).")

    ip = get_client_ip(request)
    results = []
    touched = set()

    for s in _STEPS:
        base = {"key": s["key"], "label": s["label"]}
        if not user_can(db, current_user, s["module"], "use"):
            results.append({**base, "ok": False, "skipped": True, "summary": "Yetki yok"})
            continue
        try:
            detail = s["run"](db, current_user, ip)
            results.append({**base, "ok": True, "skipped": False, "summary": _summarize(s["key"], detail)})
            if s.get("broadcast"):
                touched.add(s["broadcast"])
        except HTTPException as e:
            db.rollback()
            results.append({**base, "ok": False, "skipped": False, "summary": str(e.detail)})
        except Exception as e:  # noqa: BLE001 — adım izolasyonu: biri patlarsa diğerleri sürer
            db.rollback()
            logger.error("Sedna sync adımı '%s' hatası: %s", s["key"], e, exc_info=True)
            results.append({**base, "ok": False, "skipped": False, "summary": "Beklenmeyen hata"})

    for mod in touched:
        broadcast_finance_update(background_tasks, mod, "upload")

    return {
        "configured": True,
        "ok_count": sum(1 for r in results if r["ok"]),
        "total": len(results),
        "steps": results,
    }
