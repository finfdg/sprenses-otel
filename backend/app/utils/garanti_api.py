"""Garanti BBVA — Account Transactions (Electronic Bank Statement) → ParseResult.

Doküman: developers.garantibbva.com.tr → Account Transactions (v9).
Hareketleri `ParseResult` (bank_parser) olarak döner; cron mevcut ekstre hattına
(`_process_statement`) besler → dedup + finance_events + otomatik eşleştirme yeniden kullanılır.

Garanti'ye özel:
1. **Token TEK KULLANIMLIK:** "The access token can be used only one time" → her istek öncesi YENİ
   token alınır (cache YOK).
2. **`consentId` ZORUNLU** (enrollment sonrası; VakıfBank Rıza'sı gibi bankadan/portaldan alınır).
3. Max 30 gün aralık (reasonCode 18); sayfalama `pageIndex`/`pageSize` (max 500).

Yön: `txnCreditDebitIndicator` **A=Alacak (gelir, +)** / **B=Borç (gider, −)**; `amount` işaretsiz.
`balanceAfterTransaction` = yürüyen bakiye; `activityDate` = YYYY-MM-DD; `explanation` = açıklama;
`transactionInstanceId` = dedup anahtarı. IBAN ile sorgulanır (hesaplarımızda IBAN var).

Kimlik .env'den (config.py), koda gömülmez.
"""
import logging
from datetime import date, datetime
from typing import List, Optional

import httpx

from app.config import settings
from app.utils.bank_parser import (
    ParsedHeader,
    ParsedTransaction,
    ParseResult,
    compute_tx_hash,
)

logger = logging.getLogger(__name__)

_TIMEOUT = 60.0
_PAGE_SIZE = 500  # doküman max


class GarantiUnavailable(Exception):
    """Garanti API erişilemediğinde / yapılandırılmadığında yükselir."""


def garanti_configured() -> bool:
    """Garanti özelliği etkin mi (client_id + secret + consentId)."""
    return bool(settings.garanti_client_id and settings.garanti_client_secret and settings.garanti_consent_id)


def _get_token() -> str:
    """OAuth2 client_credentials. ⚠️ Garanti token TEK KULLANIMLIK → HER istek öncesi yeni alınır (cache YOK)."""
    if not (settings.garanti_client_id and settings.garanti_client_secret):
        raise GarantiUnavailable("Garanti yapılandırılmamış (GARANTI_CLIENT_ID/SECRET boş).")
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.garanti_client_id,
        "client_secret": settings.garanti_client_secret,
    }
    if settings.garanti_scope:
        data["scope"] = settings.garanti_scope
    try:
        resp = httpx.post(
            settings.garanti_token_url, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as e:
        raise GarantiUnavailable(f"Garanti token bağlantı hatası: {e}") from e
    if resp.status_code >= 400:
        raise GarantiUnavailable(f"Garanti token reddi (HTTP {resp.status_code}): {resp.text[:250]}")
    at = resp.json().get("access_token")
    if not at:
        raise GarantiUnavailable(f"Garanti token yanıtında access_token yok: {resp.text[:200]}")
    return at


def fetch_garanti_statement(
    start: date,
    end: date,
    iban: Optional[str] = None,
    account_no: Optional[str] = None,
    unit_num: Optional[str] = None,
    currency: Optional[str] = None,
) -> ParseResult:
    """[start, end] arası hareketleri çek → ParseResult. Sayfalı (pageSize 500). IBAN ile sorgulanır."""
    txns: List[ParsedTransaction] = []
    seq_seen: dict = {}
    page = 1
    while True:
        body = _post_transactions(start, end, iban, account_no, unit_num, page)
        rows = body.get("transactions", []) or []
        txns.extend(_parse_txn_list(rows, seq_seen))
        if len(rows) < _PAGE_SIZE:
            break
        page += 1
        if page > 200:  # emniyet kesici (200×500 = 100k hareket)
            logger.warning("Garanti %s: 200 sayfa aşıldı, durduruldu.", iban or account_no)
            break

    header = ParsedHeader(
        iban=iban, currency=currency,
        account_no=str(account_no) if account_no else None,
        period_start=start, period_end=end,
    )
    logger.info("Garanti ekstre çekildi: %s dönem=%s..%s hareket=%d",
                iban or account_no, start, end, len(txns))
    return ParseResult(header=header, transactions=txns)


def _post_transactions(start, end, iban, account_no, unit_num, page) -> dict:
    """gettransactions POST (her çağrı yeni token). Sonuç gövdesi döner; hata → GarantiUnavailable."""
    token = _get_token()  # TEK KULLANIMLIK → sayfa başına taze token
    body = {
        "consentId": settings.garanti_consent_id,
        "startDate": _iso_ts(start),
        "endDate": _iso_ts(end, end=True),
        "pageIndex": page,
        "pageSize": _PAGE_SIZE,
    }
    if iban:
        body["IBAN"] = iban
    elif account_no:
        # Şube + hesap numarası BİRLİKTE gönderilmeli (reasonCode 5)
        body["accountNum"] = int(account_no) if str(account_no).isdigit() else account_no
        if unit_num:
            body["unitNum"] = int(unit_num) if str(unit_num).isdigit() else unit_num
    else:
        raise GarantiUnavailable("Garanti: IBAN veya (unitNum+accountNum) zorunlu.")

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
    url = f"{settings.garanti_base_url}{settings.garanti_transactions_path}"
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=_TIMEOUT)
    except httpx.HTTPError as e:
        raise GarantiUnavailable(f"Garanti hareket bağlantı hatası: {e}") from e
    if r.status_code >= 400:
        raise GarantiUnavailable(f"Garanti hareket reddi (HTTP {r.status_code}): {r.text[:250]}")
    body_json = r.json()
    # İş hatası HTTP 200 + result.returnCode != 200 olarak da gelebilir
    result = body_json.get("result") or {}
    rc = result.get("returnCode", result.get("code"))
    if rc is not None and str(rc) != "200":
        raise GarantiUnavailable(f"Garanti hata {rc}: {result.get('messageText') or result.get('info') or ''}")
    return body_json


# ── Parse yardımcıları (doküman "Account Transactions" modeli) ────────────────

def _iso_ts(d: date, end: bool = False) -> str:
    """date → Garanti timestamp (ör. '2026-07-01T00:00:00.000'; Z yok, millis var)."""
    return f"{d.isoformat()}T{'23:59:59.999' if end else '00:00:00.000'}"


def _to_float(v) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        return round(float(str(v).replace(",", ".")), 2)
    except (TypeError, ValueError):
        return None


def _parse_date(s) -> Optional[date]:
    """activityDate 'YYYY-MM-DD' → date."""
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()
    except (ValueError, IndexError):
        return None


def _parse_txn_list(rows: Optional[List[dict]], seq_seen: dict) -> List[ParsedTransaction]:
    """Garanti transactions[] → ParsedTransaction listesi (işaretli tutar A/B'den)."""
    out: List[ParsedTransaction] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        amt_abs = _to_float(row.get("amount"))
        tx_dt = _parse_date(row.get("activityDate"))
        if amt_abs is None or tx_dt is None:
            continue
        # A = Alacak (hesaba giriş/gelir, +) · B = Borç (hesaptan çıkış/gider, −)
        drcr = (row.get("txnCreditDebitIndicator") or "").strip().upper()
        amount = abs(amt_abs) if drcr == "A" else -abs(amt_abs)
        desc = (row.get("explanation") or "").strip()
        receipt = str(row.get("transactionInstanceId") or row.get("transactionReferenceId") or "").strip() or None

        base_key = f"{tx_dt.isoformat()}|{receipt or ''}|{amount:.2f}|{desc[:50]}"
        seq = seq_seen.get(base_key, 0)
        seq_seen[base_key] = seq + 1

        out.append(ParsedTransaction(
            date=tx_dt,
            receipt_no=receipt,
            description=desc,
            amount=amount,
            balance=_to_float(row.get("balanceAfterTransaction")),
            type="income" if amount >= 0 else "expense",
            tx_hash=compute_tx_hash(tx_dt, receipt, amount, desc, seq=seq),
            time=None,
        ))
    return out
