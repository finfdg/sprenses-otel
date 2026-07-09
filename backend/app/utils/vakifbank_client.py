"""VakıfBank Açık Bankacılık API istemcisi — banka hesap hareketlerini SALT-OKUNUR çeker.

Amaç: mevcut Excel/PDF ekstre yüklemesine ek olarak, VakıfBank hesap hareketlerini
doğrudan API'den çekip `bank_transactions`'a (aynı dedup + finance_event yoluyla) yazmak.
Bağlantı YALNIZCA senkron tetiklenince kurulur; uygulamanın normal işleyişi buna bağlı
DEĞİLDİR (kimlik yoksa/hata olursa import açık hata verir, uygulama çalışmaya devam eder).

Kimlik akışı (VakıfBank apiportal — Hesap Bilgi Servisleri):
  1. OAuth2 token  (B2B Credentials: client_id + api_secret [+ Rıza Numarası])
  2. POST /accountTransactions  (token; body = AccountNumber + StartDate + EndDate)

Şema (dokümandan doğrulandı 2026-07-09):
  Request  : {"AccountNumber": "...", "StartDate": "...Z", "EndDate": "...Z"}  (en fazla 100 kayıt)
  Response : {"Header": {"StatusCode": "APIGW000000", ...}, "Data": {"AccountTransactions": [ {
             CurrencyCode, TransactionType, Description, Amount, TransactionCode, Balance,
             TransactionName, TransactionDate, TransactionId } ... ]}}

⚠️ HÂLÂ DOKÜMANDAN GEREKENLER: sandbox **base URL (gateway host)**, **token endpoint** (URL +
Rıza/secret'in nasıl gittiği), **Rıza Numarası** test değeri. Bunlar config'de
(`vakifbank_base_url/token_path`) + `.env`'de (`VAKIFBANK_RIZA_NO`) — gelince kesinleşecek.
"""
import logging
import time
from datetime import date
from typing import List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 20.0
_SUCCESS_STATUS = "APIGW000000"

# TransactionType → gelir mi? Bakiye zinciri kurulamayan (ilk) satır için YEDEK varsayım.
# Doküman örneğinde "1" = "Senet tahsilatı" (tahsilat = alacak/gelir) → {"1"} gelir varsaydık.
# Sandbox gerçek veriyle DOĞRULANACAK (bakiye zinciri zaten çoğu satırda yön verir → yedek nadiren devrede).
_TX_TYPE_INCOME = {"1"}


class VakifbankUnavailable(Exception):
    """VakıfBank API erişilemediğinde / yapılandırılmadığında yükselir (503 ile dışa verilir)."""


def vakifbank_configured() -> bool:
    """VakıfBank API özelliği etkin mi (client_id + api_secret tanımlı)."""
    return bool(settings.vakifbank_client_id and settings.vakifbank_api_secret)


class VakifbankClient:
    """Token cache'li VakıfBank REST istemcisi (süreç boyunca tek örnek)."""

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._token_expires: float = 0.0

    # ── OAuth2 token ─────────────────────────────────────────────────────────
    def _get_token(self) -> str:
        """B2B Credentials ile OAuth2 access token al (cache'lenir, süresi dolunca yenilenir).

        TODO: VakıfBank token endpoint'inin GERÇEK biçimi dokümandan teyit edilmeli — özellikle
        **Rıza Numarası'nın burada mı** yoksa istek header'ında mı gittiği (portalda "Token Oluştur"
        API Secret + Rıza Numarası ile birlikte gösteriliyor → Rıza büyük olasılıkla TOKEN adımında).
        """
        if not vakifbank_configured():
            raise VakifbankUnavailable(
                "VakıfBank API yapılandırılmamış (VAKIFBANK_CLIENT_ID / VAKIFBANK_API_SECRET boş)."
            )
        if self._token and time.time() < self._token_expires - 60:
            return self._token

        url = f"{settings.vakifbank_base_url}{settings.vakifbank_token_path}"
        data = {"grant_type": "client_credentials", "scope": settings.vakifbank_scope}
        if settings.vakifbank_riza_no:
            data["consentId"] = settings.vakifbank_riza_no  # TODO: gerçek alan adı (rizaNo/consentId?)
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.post(
                    url,
                    data=data,
                    auth=(settings.vakifbank_client_id, settings.vakifbank_api_secret),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as e:
            logger.error("VakıfBank token alınamadı: %s", e)
            raise VakifbankUnavailable(f"VakıfBank token hatası: {e}") from e

        token = body.get("access_token")
        if not token:
            raise VakifbankUnavailable("VakıfBank token yanıtında access_token yok.")
        self._token = token
        self._token_expires = time.time() + int(body.get("expires_in", 1800))
        return token

    # ── Hesap hareketleri ────────────────────────────────────────────────────
    def fetch_account_transactions(
        self, account_number: str, start_date: date, end_date: date,
    ) -> List[dict]:
        """Bir HESAP NUMARASI (IBAN değil!) için [start, end] arası hareketleri normalize et.

        Dönen her öğe: {date, amount(İŞARETLİ), balance, description, type, receipt_no}.
        **amount İŞARETLİ** (gider negatif) — bakiye zincirinden türetilir (bkz. `_normalize_batch`);
        `bank_parser` konvansiyonuyla aynı → bakiye-bazlı dedup uyumlu. En fazla 100 kayıt döner.
        """
        token = self._get_token()
        url = f"{settings.vakifbank_base_url}{settings.vakifbank_transactions_path}"
        payload = _build_transactions_payload(account_number, start_date, end_date)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if settings.vakifbank_riza_no:
            headers["rizaNo"] = settings.vakifbank_riza_no  # TODO: token'da yeterliyse kaldırılacak
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as e:
            logger.error("VakıfBank hareket sorgusu hatası (hesap …%s): %s", account_number[-4:], e)
            raise VakifbankUnavailable(f"VakıfBank hareket hatası: {e}") from e

        header = body.get("Header") or {}
        status = header.get("StatusCode")
        if status and status != _SUCCESS_STATUS:
            raise VakifbankUnavailable(
                f"VakıfBank yanıt hatası: {header.get('StatusDescription') or status}"
            )
        return _normalize_batch(_extract_transaction_list(body))


# ── Modül-düzeyi tekil örnek (Amadeus deseni) ────────────────────────────────
_client_singleton: Optional[VakifbankClient] = None


def get_vakifbank_client() -> VakifbankClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = VakifbankClient()
    return _client_singleton


# ═══════════════════════════════════════════════════════════════════════════════
# Şema yardımcıları (doküman doğrulandı — request/response alan adları)
# ═══════════════════════════════════════════════════════════════════════════════

def _iso_z(d: date, end: bool = False) -> str:
    """date → VakıfBank ISO-Z zaman damgası (ör. '2026-07-01T00:00:00.000Z')."""
    return f"{d.isoformat()}T{'23:59:59.999' if end else '00:00:00.000'}Z"


def _parse_iso_z(s) -> Optional[date]:
    """'2020-02-05T10:47:47.000Z' → date. Sabit biçim → dilim tabanlı, sağlam."""
    if not s or not isinstance(s, str) or len(s) < 10:
        return None
    try:
        return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
    except (ValueError, IndexError):
        return None


def _to_float(v) -> Optional[float]:
    """VakıfBank sayı string'ini float'a çevir ('4957.61' / '650,0')."""
    if v is None:
        return None
    try:
        return round(float(str(v).replace(",", ".")), 2)
    except (TypeError, ValueError):
        return None


def _build_transactions_payload(account_number: str, start_date: date, end_date: date) -> dict:
    """/accountTransactions POST gövdesi (RequestData modeli — doğrulandı)."""
    return {
        "AccountNumber": account_number,
        "StartDate": _iso_z(start_date),
        "EndDate": _iso_z(end_date, end=True),
    }


def _extract_transaction_list(body: dict) -> List[dict]:
    """Yanıttan hareket listesini çıkar: Data.AccountTransactions (doğrulandı)."""
    if not isinstance(body, dict):
        return []
    data = body.get("Data")
    if isinstance(data, dict) and isinstance(data.get("AccountTransactions"), list):
        return data["AccountTransactions"]
    return []


def _normalize_batch(raw_list: List[dict]) -> List[dict]:
    """Ham hareket listesini ortak şemaya çevir + İŞARETLİ tutar üret (bakiye zinciri).

    Yön belirleme (mevcut ekstre ayrıştırıcı felsefesi = bakiye zinciri kral):
      - Kronolojik sırala (TransactionDate + TransactionId).
      - signed[i] = Balance[i] − Balance[i-1]; |signed| ≈ Amount ise BU kullanılır (kesin yön).
      - Bakiye zinciri kurulamayan (ilk satır / eksik bakiye) satır → `TransactionType` yedeği.
    """
    parsed = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        d = _parse_iso_z(raw.get("TransactionDate"))
        amt_abs = _to_float(raw.get("Amount"))
        if d is None or amt_abs is None:
            continue
        parsed.append({
            "date": d,
            "amount_abs": abs(amt_abs),
            "balance": _to_float(raw.get("Balance")),
            "description": (raw.get("Description") or raw.get("TransactionName") or "").strip(),
            "receipt_no": (str(raw.get("TransactionId")).strip() or None) if raw.get("TransactionId") else None,
            "tx_type": str(raw.get("TransactionType") or ""),
            "sort_key": (str(raw.get("TransactionDate") or ""), str(raw.get("TransactionId") or "")),
        })
    parsed.sort(key=lambda r: r["sort_key"])

    out: List[dict] = []
    prev_bal: Optional[float] = None
    for r in parsed:
        signed: Optional[float] = None
        if prev_bal is not None and r["balance"] is not None:
            delta = round(r["balance"] - prev_bal, 2)
            if abs(delta) > 0 and abs(abs(delta) - r["amount_abs"]) < 0.02:
                signed = delta  # bakiye zinciri → kesin yön
        if signed is None:  # ilk satır / eksik bakiye → TransactionType yedeği
            signed = r["amount_abs"] if r["tx_type"] in _TX_TYPE_INCOME else -r["amount_abs"]
        out.append({
            "date": r["date"],
            "amount": signed,
            "balance": r["balance"],
            "description": r["description"],
            "type": "income" if signed >= 0 else "expense",
            "receipt_no": r["receipt_no"],
        })
        if r["balance"] is not None:
            prev_bal = r["balance"]
    return out
