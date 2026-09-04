"""Cari analitik görünümleri — Aylık Bakiye (FIFO Kalan / Dönem Sonu) ve Yıllık Ciro.

2026-07-23 "Cariler modülü yeniden tasarımı" ile eklendi. Salt-okuma GET'ler —
onaydan muaf, finance.cariler view yeterli. Satır sayısı cari sayısıyla sınırlı
(≈300) olduğundan sayfalama yoktur; sıralama frontend'de yapılır.

**Yeniden yapılandırma (2026-09-02):** `_DEVIR_MATCH` / `_MIN_AMOUNT` sabitleri, `_vendor_map`
ve iki endpoint'in gövdesi BİREBİR `app/services/vendor_analytics_service.py`'ye
(`monthly_balances` / `yearly_turnover`) taşındı; bu router yalnız `router` + iki ince sarmalayıcı
endpoint'i tutar ve taşınan adları geriye uyumluluk için modül düzeyinde yeniden dışa verir
(`services/audit_finance_invariants.py` endpoint fonksiyonlarını bu yoldan `(db=db, _=None)` ile çağırır).
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.user import User
from app.services.vendor_analytics_service import (  # noqa: F401 — geriye uyumluluk: testler/parmak izi bu yoldan import eder (2026-09-02 çıkarımı)
    _DEVIR_MATCH,
    _MIN_AMOUNT,
    _vendor_map,
    monthly_balances,
    yearly_turnover,
)

router = APIRouter()


@router.get("/monthly-balances")
def get_monthly_balances(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    mode: str = Query("fifo", pattern="^(fifo|period)$"),
    hide_zero: bool = Query(True),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cariler", "view")),
):
    """Ay bazlı cari bakiye görünümü (Aylık Bakiye sekmesi).

    mode=fifo  → **FIFO Kalan**: ay SONUNA KADAR kesilmiş TÜM faturaların (alacak)
                 bugüne dek ödenmeyen kalanı — önceki aylardan DEVREDEN dahil
                 (2026-07-23 kullanıcı geri bildirimi: "Ocak'tan devreden tutar her ay
                 sonunda kalan bakiye üzerinden görünsün"). Ödemeler (havale/EFT, çek,
                 kredi kartı — sonraki aylardakiler dahil) en eski faturadan düşülür —
                 Ödeme Planı / Vadesi Geçmiş kartıyla AYNI `calculate_fifo_amounts`
                 kaynağı. Tamamen kapananlar listelenmez.
    mode=period→ **Dönem Sonu Bakiye**: ay sonu itibarıyla yürüyen bakiye
                 (o tarihe kadarki tüm borç/alacak toplamları). `hide_zero`
                 sıfır bakiyeli carileri gizler (yalnız bu modda anlamlı).
    """
    return monthly_balances(db, year=year, month=month, mode=mode, hide_zero=hide_zero)


@router.get("/yearly-turnover")
def get_yearly_turnover(
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.cariler", "view")),
):
    """Yıllık Ciro sekmesi — firma bazında yıl içi fatura (alacak) hacmi.

    Devir/açılış kayıtları hariç (match_number=-1 veya işlem tipinde devir/açılış).
    Aylık dağılım (12 kalem) + fatura sayısı + toplam ciro döner.
    """
    return yearly_turnover(db, year=year)
