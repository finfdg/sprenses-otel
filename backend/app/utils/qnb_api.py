"""QNB Açık Bankacılık — Account Statement V2 (hesap hareketleri) → ParseResult.

Doküman: developer.qnb.com.tr → API Products → Account Statement - Version 2.
Hareketleri `ParseResult` (bank_parser) olarak döner; cron mevcut ekstre hattına
(`_process_statement`) besler → dedup + finance_events + otomatik eşleştirme yeniden kullanılır.

QNB'ye özel iki nokta:
1. **Token = refresh_token grant (ROTATING):** her token çağrısı YENİ bir refresh_token döndürür;
   eskisi geçersizleşir → yeni token HEMEN `.qnb_refresh_token` dosyasına yazılır (yoksa kilitlenir).
   İlk refresh_token e-posta ile gelir (`QNB_REFRESH_TOKEN` tohumu). Access token dönüş süresi ~30 gün
   → süreç içinde önbelleklenir (aynı koşuda tek token çağrısı → tek rotasyon).
2. **Doğrudan `GET /account-statement` 1 GÜNLÜK:** geniş aralık için gün-gün döngü; "çok kayıt"
   dönerse (`resultCode=1` + `ticketNo`) `/ticket` servisi sayfalı çekilir.

Kimlik .env'den (config.py), koda gömülmez.
"""
import logging
import os
import time
from datetime import date, datetime, timedelta
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
_TICKET_PAGE_SIZE = 100

# Rotating refresh_token'ın kalıcı yazıldığı dosya (git'te DEĞİL — .gitignore'da).
_REFRESH_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    ".qnb_refresh_token",
)

# Süreç-içi access token önbelleği (aynı koşuda tekrar token çağrısı/rotasyonu olmasın)
_access_cache = {"token": None, "exp": 0.0}


class QnbUnavailable(Exception):
    """QNB API erişilemediğinde / yapılandırılmadığında yükselir."""


def _read_refresh_token() -> str:
    """Geçerli refresh_token'ı oku: önce dosya (dönmüş son değer), yoksa .env tohumu."""
    try:
        if os.path.exists(_REFRESH_FILE):
            with open(_REFRESH_FILE, encoding="utf-8") as f:
                tok = f.read().strip()
                if tok:
                    return tok
    except OSError as e:
        logger.error("QNB refresh_token dosyası okunamadı: %s", e)
    return (settings.qnb_refresh_token or "").strip()


def _write_refresh_token(tok: str) -> None:
    """Dönen yeni refresh_token'ı kalıcı yaz (mode 600)."""
    try:
        with open(_REFRESH_FILE, "w", encoding="utf-8") as f:
            f.write(tok.strip())
        os.chmod(_REFRESH_FILE, 0o600)
    except OSError as e:
        logger.error("QNB refresh_token yazılamadı (%s): %s — sonraki çağrı kilitlenebilir!", _REFRESH_FILE, e)


def qnb_configured() -> bool:
    """QNB özelliği etkin mi (client_id + secret + bir refresh_token tohumu/dosyası)."""
    return bool(settings.qnb_client_id and settings.qnb_client_secret and _read_refresh_token())


def _get_access_token() -> str:
    """refresh_token grant ile access token al. Dönen YENİ refresh_token'ı HEMEN sakla (rotating)."""
    if _access_cache["token"] and time.time() < _access_cache["exp"] - 60:
        return _access_cache["token"]

    rt = _read_refresh_token()
    if not (settings.qnb_client_id and settings.qnb_client_secret and rt):
        raise QnbUnavailable("QNB yapılandırılmamış (QNB_CLIENT_ID/SECRET/REFRESH_TOKEN boş).")

    try:
        resp = httpx.post(
            settings.qnb_token_url,
            data={
                "grant_type": settings.qnb_grant_type,  # refresh_token
                "refresh_token": rt,
                "client_id": settings.qnb_client_id,
                "client_secret": settings.qnb_client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as e:
        raise QnbUnavailable(f"QNB token bağlantı hatası: {e}") from e

    if resp.status_code >= 400:
        raise QnbUnavailable(f"QNB token reddi (HTTP {resp.status_code}): {resp.text[:250]}")
    body = resp.json()

    # ROTATING: yeni refresh_token'ı access token'ı döndürmeden ÖNCE sakla (kritik).
    new_rt = body.get("refresh_token")
    if new_rt and new_rt != rt:
        _write_refresh_token(new_rt)

    at = body.get("access_token")
    if not at:
        raise QnbUnavailable(f"QNB token yanıtında access_token yok: {str(body)[:250]}")
    _access_cache["token"] = at
    _access_cache["exp"] = time.time() + int(body.get("expires_in", 2591999))
    return at


def fetch_qnb_account_list() -> List[dict]:
    """GET /list — yetkili hesapların {iban, accountNo} listesi."""
    token = _get_access_token()
    try:
        r = httpx.get(
            f"{settings.qnb_base_url}/list",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise QnbUnavailable(f"QNB hesap listesi hatası: {e}") from e
    return r.json().get("accountInfoList", []) or []


def fetch_qnb_statement(
    start: date,
    end: date,
    iban: Optional[str] = None,
    account_no: Optional[str] = None,
    currency: Optional[str] = None,
) -> ParseResult:
    """[start, end] arası hareketleri çek → ParseResult. Doğrudan GET 1-günlük → gün-gün döngü.

    iban VEYA account_no verilmeli (doküman: biri zorunlu). amount İŞARETLİ (B=Borç→gider negatif,
    A=Alacak→gelir pozitif); balance = balanceAfterTransaction (yürüyen); receipt_no = transactionId.
    """
    token = _get_access_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    txns: List[ParsedTransaction] = []
    seq_seen: dict = {}

    cur = start
    while cur <= end:
        txns.extend(_fetch_one_day(cur, iban, account_no, headers, seq_seen))
        cur += timedelta(days=1)

    header = ParsedHeader(
        iban=iban, currency=currency, account_no=account_no,
        period_start=start, period_end=end,
    )
    logger.info("QNB ekstre çekildi: %s dönem=%s..%s hareket=%d",
                iban or account_no, start, end, len(txns))
    return ParseResult(header=header, transactions=txns)


def _fetch_one_day(day: date, iban, account_no, headers, seq_seen) -> List[ParsedTransaction]:
    """Tek gün için GET /account-statement; çok kayıtta ticket servisine düşer."""
    params = {
        "startDateTime": f"{day.isoformat()}T00:00:00",
        "endDateTime": f"{day.isoformat()}T23:59:59",
    }
    if iban:
        params["iban"] = iban
    elif account_no:
        params["accountNo"] = account_no
    else:
        raise QnbUnavailable("QNB: iban veya accountNo zorunlu.")

    try:
        r = httpx.get(settings.qnb_base_url, params=params, headers=headers, timeout=_TIMEOUT)
    except httpx.HTTPError as e:
        raise QnbUnavailable(f"QNB hareket bağlantı hatası: {e}") from e
    if r.status_code >= 400:
        raise QnbUnavailable(f"QNB hareket reddi (HTTP {r.status_code}): {r.text[:250]}")
    body = r.json()

    # "Çok kayıt" → ticket servisi (resultCode=1 + ticketNo)
    if body.get("ticketNo") and str(body.get("resultCode")) == "1":
        return _fetch_via_ticket(body["ticketNo"], headers, seq_seen)
    return _parse_txn_list(body.get("accountTransactionList", []), seq_seen)


def _fetch_via_ticket(ticket_no: str, headers, seq_seen) -> List[ParsedTransaction]:
    """GET /ticket — büyük sonuç kümesini sayfalı çek (nextPageExist='true' oldukça)."""
    out: List[ParsedTransaction] = []
    page = 1
    while True:
        try:
            r = httpx.get(
                f"{settings.qnb_base_url}/ticket",
                params={"ticketNo": ticket_no, "pageNo": page, "pageSize": _TICKET_PAGE_SIZE},
                headers=headers, timeout=_TIMEOUT,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise QnbUnavailable(f"QNB ticket hatası: {e}") from e
        body = r.json()
        out.extend(_parse_txn_list(body.get("accountTransactionList", []), seq_seen))
        if str(body.get("nextPageExist", "")).lower() != "true":
            break
        page += 1
        if page > 500:  # emniyet kesici
            logger.warning("QNB ticket %s: 500 sayfa aşıldı, durduruldu.", ticket_no)
            break
    return out


# ── Parse yardımcıları (doküman "Account Statement" modeli) ───────────────────

def _to_float(v) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        return round(float(str(v).replace(",", ".")), 2)
    except (TypeError, ValueError):
        return None


def _parse_qnb_date(s) -> Optional[date]:
    """transactionDate → date. İki biçim: 'DD.MM.YYYY HH:MM:SS' veya 'YYYYMMDD'."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    try:
        if "." in s:                                  # 11.04.2025 13:26:36
            return datetime.strptime(s.split(" ")[0], "%d.%m.%Y").date()
        if len(s) == 8 and s.isdigit():               # 20241210
            return datetime.strptime(s, "%Y%m%d").date()
    except (ValueError, IndexError):
        return None
    return None


def _parse_qnb_time(s) -> Optional[str]:
    """'DD.MM.YYYY HH:MM:SS' → 'HH:MM:SS' (aynı gün sıralama için); yoksa None."""
    if isinstance(s, str) and " " in s and ":" in s:
        return s.split(" ", 1)[1].strip() or None
    return None


def _parse_txn_list(rows: Optional[List[dict]], seq_seen: dict) -> List[ParsedTransaction]:
    """QNB accountTransactionList → ParsedTransaction listesi (işaretli tutar A/B'den)."""
    out: List[ParsedTransaction] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        amt_abs = _to_float(row.get("transactionAmount"))
        tx_dt = _parse_qnb_date(row.get("transactionDate"))
        if amt_abs is None or tx_dt is None:
            continue
        # A=Alacak (hesaba giriş/gelir, +) · B=Borç (hesaptan çıkış/gider, −)
        drcr = (row.get("debitOrCreditCode") or "").strip().upper()
        amount = abs(amt_abs) if drcr == "A" else -abs(amt_abs)
        desc = (row.get("transactionDescription") or row.get("processDescription") or "").strip()
        receipt = str(row.get("transactionId")).strip() if row.get("transactionId") else None

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
            time=_parse_qnb_time(row.get("transactionDate")),
        ))
    return out
