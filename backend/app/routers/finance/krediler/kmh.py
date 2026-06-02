"""KMH (Kredili Mevduat Hesabı) durumu — anlık adat/faiz/projeksiyon."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import require_permission
from app.models.credit_product import CreditProduct
from app.models.user import User

router = APIRouter()


@router.get("/{product_id}/kmh-status")
def get_kmh_status(
    product_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.krediler", "view")),
):
    """KMH için anlık + projeksiyonlu durum (adat, faiz, BSMV, komisyon, hareketler).

    Sadece type='kmh' ve linked_account_id dolu olan krediler için çalışır.
    """
    from app.utils.kmh_calculator import calculate_kmh_status, sync_kmh_to_finance_events

    product = db.query(CreditProduct).filter(CreditProduct.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Kredi ürünü bulunamadı")
    if product.type != "kmh":
        raise HTTPException(status_code=400, detail="Bu endpoint yalnızca KMH kredileri için çalışır")
    if not product.linked_account_id:
        raise HTTPException(status_code=400, detail="KMH'nin bağlı banka hesabı tanımlı değil (linked_account_id)")

    # Geçmiş + mevcut ay tahakkuklarını nakit akıma yansıt (idempotent)
    sync_kmh_to_finance_events(product, db)

    status_data = calculate_kmh_status(product, db)
    if status_data is None:
        raise HTTPException(status_code=500, detail="KMH durumu hesaplanamadı")
    return status_data
