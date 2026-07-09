"""VakıfBank API'den banka hesap hareketlerini çekme — servis + router.

Mevcut Excel/PDF ekstre yüklemesine EK bir kaynak: VakıfBank Açık Bankacılık API'sinden
hesap hareketlerini çekip `bank_transactions`'a yazar. Yazma yolu ekstre yüklemesiyle
BİREBİR AYNI: bakiye-bazlı dedup + `finance_event_svc.upsert_bank_tx` (nakit akıma yansır,
çift kayıt olmaz). Kaynak alanı `source="api"` ile ayrılır (ekstre='statement', elle='manual').

Onaydan MUAF (operasyonel içe-aktarma — dosya yükleme/Sedna gibi), audit'li, `finance.banks` use.
Kimlik yoksa/hata olursa 503 (VakifbankUnavailable) → uygulamanın geri kalanı etkilenmez.

⚠️ Alan eşlemesi tamamlanana kadar (`vakifbank_client._normalize_transaction` TODO) senkron
0 hareket yazar; token/bağlantı ise `test-connection` ile doğrulanabilir.
"""
import logging
from datetime import date, timedelta
from typing import List, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import BroadcastModule
from app.database import get_db
from app.middleware.auth import require_permission
from app.middleware.rate_limit import get_client_ip
from app.models.bank_account import BankAccount
from app.models.bank_transaction import BankTransaction
from app.models.user import User
from app.utils.audit import log_action
from app.utils.bank_parser import compute_tx_hash
from app.utils.finance_broadcast import broadcast_finance_update
from app.utils.finance_event_service import finance_event_svc
from app.utils.vakifbank_client import (
    VakifbankUnavailable,
    get_vakifbank_client,
    vakifbank_configured,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/vakifbank")

SOURCE_API = "api"


def _is_vakifbank(bank_name: str) -> bool:
    """Hesabın bankası VakıfBank mı (ad, Türkçe-duyarsız 'vak' içeriyor mu)."""
    n = (bank_name or "").casefold()
    return "vak" in n  # 'vakıf'/'vakif'/'vakıfbank' — casefold ile İ/ı toleranslı


def _vakifbank_accounts(db: Session) -> List[BankAccount]:
    """Senkronlanacak aktif VakıfBank hesapları (IBAN'lı)."""
    return [
        a for a in db.query(BankAccount)
        .filter(BankAccount.is_active.is_(True))
        .all()
        if _is_vakifbank(a.bank_name) and a.iban
    ]


def _ingest_transactions(db: Session, acc: BankAccount, rows: List[dict]) -> Tuple[int, int]:
    """Normalize edilmiş hareketleri hesaba yaz (dedup + finance_event). (yeni, atlanan) döner.

    Dedup ekstre yüklemesiyle aynı: bakiye-bazlı (tarih+tutar+bakiye = aynı işlem) → hash fallback.
    `rows` öğeleri: {date, amount(İŞARETLİ), balance, description, type, receipt_no}.
    """
    existing_balances = set()
    for r in db.query(
        BankTransaction.date, BankTransaction.amount, BankTransaction.balance
    ).filter(BankTransaction.account_id == acc.id).all():
        existing_balances.add((r.date, float(r.amount), float(r.balance or 0)))

    existing_hashes = {
        row[0] for row in db.query(BankTransaction.tx_hash)
        .filter(BankTransaction.account_id == acc.id).all()
    }

    new_count = 0
    skipped = 0
    for tx in rows:
        d = tx.get("date")
        if d is None or tx.get("amount") is None:
            skipped += 1
            continue
        amt = float(tx["amount"])
        bal = tx.get("balance")
        desc = (tx.get("description") or "").strip()
        receipt = tx.get("receipt_no")

        balance_key = (d, amt, float(bal or 0))
        if balance_key in existing_balances:
            skipped += 1
            continue

        final_hash = compute_tx_hash(d, receipt, amt, desc)
        if final_hash in existing_hashes:
            for seq in range(1, 20):
                cand = compute_tx_hash(d, receipt, amt, desc, seq)
                if cand not in existing_hashes:
                    final_hash = cand
                    break
            else:
                skipped += 1
                continue

        db_tx = BankTransaction(
            account_id=acc.id,
            date=d,
            receipt_no=receipt,
            description=desc,
            amount=amt,
            balance=bal,
            type=tx.get("type") or ("income" if amt >= 0 else "expense"),
            source=SOURCE_API,
            tx_hash=final_hash,
        )
        db.add(db_tx)
        db.flush()
        finance_event_svc.upsert_bank_tx(db, db_tx, acc)
        existing_hashes.add(final_hash)
        existing_balances.add(balance_key)
        new_count += 1

    return new_count, skipped


def run_vakifbank_import(db: Session, current_user: User, ip: str) -> dict:
    """Aktif VakıfBank hesaplarının son `lookback` günlük hareketlerini çek + yaz.

    HTTP'siz, broadcast'siz (çağıran eder). Hata → HTTPException (503/500). Sedna
    orchestrator deseniyle uyumlu imza — ileride tek "Banka Senkronu" butonuna bağlanabilir.
    """
    if not vakifbank_configured():
        raise HTTPException(
            status_code=503,
            detail="VakıfBank API yapılandırılmamış (VAKIFBANK_CLIENT_ID / VAKIFBANK_API_SECRET).",
        )

    accounts = _vakifbank_accounts(db)
    if not accounts:
        return {"accounts": 0, "new_transactions": 0, "skipped": 0, "errors": []}

    client = get_vakifbank_client()
    today = date.today()
    start = today - timedelta(days=max(1, settings.vakifbank_sync_lookback_days))

    total_new = 0
    total_skipped = 0
    errors: List[str] = []
    for acc in accounts:
        try:
            rows = client.fetch_account_transactions(acc.iban, start, today)
            n, s = _ingest_transactions(db, acc, rows)
            total_new += n
            total_skipped += s
        except VakifbankUnavailable as e:
            db.rollback()
            errors.append(f"{acc.bank_name} …{acc.iban[-4:]}: {e}")
            logger.error("VakıfBank senkron hatası (hesap %s): %s", acc.id, e)

    db.commit()
    log_action(
        db, current_user.id, "import", "bank_transaction", None,
        f"VakıfBank API senkron: {total_new} yeni, {total_skipped} mevcut, "
        f"{len(accounts)} hesap, {len(errors)} hata",
        ip,
    )
    db.commit()
    return {
        "accounts": len(accounts),
        "new_transactions": total_new,
        "skipped": total_skipped,
        "errors": errors,
    }


# ── Endpoint'ler ──────────────────────────────────────────────────────────────

@router.get("/status")
def vakifbank_status(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("finance.banks", "view")),
):
    """API etkin mi + senkronlanabilecek VakıfBank hesap sayısı (buton gösterimi için)."""
    accounts = _vakifbank_accounts(db) if vakifbank_configured() else []
    return {
        "configured": vakifbank_configured(),
        "has_riza": bool(settings.vakifbank_riza_no),
        "account_count": len(accounts),
        "lookback_days": settings.vakifbank_sync_lookback_days,
    }


@router.post("/test-connection")
def vakifbank_test_connection(
    _: User = Depends(require_permission("finance.banks", "use")),
):
    """Yalnız token akışını dener (DB'ye YAZMAZ) — kimlik/IP whitelist doğrulaması için."""
    if not vakifbank_configured():
        raise HTTPException(status_code=503, detail="VakıfBank API yapılandırılmamış.")
    client = get_vakifbank_client()
    try:
        token = client._get_token()  # noqa: SLF001 — bilinçli: bağlantı testi
        return {"ok": True, "token_prefix": (token[:6] + "…") if token else None}
    except VakifbankUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/sync")
def vakifbank_sync(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("finance.banks", "use")),
):
    """VakıfBank hesap hareketlerini çek + banka işlemlerine yaz (audit + WS broadcast)."""
    ip = get_client_ip(request)
    result = run_vakifbank_import(db, current_user, ip)
    broadcast_finance_update(background_tasks, BroadcastModule.BANKS, "upload")
    return result
