"""VakıfBank Açık Bankacılık API istemcisi — banka hesap hareketlerini SALT-OKUNUR çeker.

Amaç: mevcut Excel/PDF ekstre yüklemesine ek olarak, VakıfBank hesap hareketlerini
doğrudan API'den çekip `bank_transactions`'a (aynı dedup + finance_event yoluyla) yazmak.
Bağlantı YALNIZCA senkron tetiklenince kurulur; uygulamanın normal işleyişi buna bağlı
DEĞİLDİR (kimlik yoksa/hata olursa import açık hata verir, uygulama çalışmaya devam eder).

Kimlik akışı (VakıfBank apiportal — Hesap Bilgi Servisleri):
  1. OAuth2 token  (B2B Credentials: client_id + api_secret [+ Rıza Numarası])
  2. POST /accountTransactions  (token; body = AccountNumber + StartDate + EndDate)

Şema (bankanın resmî Postman collection'ı + örnek yanıtla DOĞRULANDI 2026-07-10):
  Token    : POST {base}/auth/oauth/v2/token (form-urlencoded: client_id, client_secret,
             grant_type=b2b_credentials, scope=account, consentId, resource=sandbox|production)
  Request  : POST {base}/accountTransactions (Bearer token, JSON):
             {"AccountNumber": "...", "StartDate": "2024-09-26T00:00:00+03:00", "EndDate": ...}
             — tarih +03:00 offset'li ISO (collection örneği; Z DEĞİL). En fazla 100 kayıt.
  Response : {"Header": {"StatusCode": "APIGW000000", ...}, "Data": {"AccountTransactions": [ {
             CurrencyCode, TransactionType, Description, Amount(İŞARETLİ sayı — gider negatif,
             resmî örnek: -1.74), TransactionCode, VirtualIBAN, Balance, TransactionName,
             TransactionDate("2023-08-08T13:56:51" — Z'siz), TransactionId } ... ]}}
  Ek       : POST {base}/accountList (Bearer, JSON {}) — hesap listesi (sandbox keşfi/teşhis).
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
_NO_TRANSACTIONS_STATUS = "ACBH000202"  # "Seçilen tarih aralığında hesap hareketi bulunmamaktadır"
                                        # HTTP 400 ile döner (canlı sandbox 2026-07-10) — hata DEĞİL, boş sonuç

# TransactionType — resmî Postman örneğiyle doğrulandı (2026-07-10): "1" = giriş ("PARA
# Yatirma", tutar pozitif), "2" = çıkış ("Gecikmeli Kmh Tahsilatı", tutar NEGATİF). Asıl yön
# kaynağı işaretli Amount + bakiye zinciri; bunlar yalnız işaretsiz-pozitif satır yedeği.
_TX_TYPE_INCOME = {"1"}
_TX_TYPE_EXPENSE = {"2"}


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

        Doküman "Yetkilendirme" (2026-07-09): tüm parametreler GÖVDEDE (form-urlencoded):
        grant_type=b2b_credentials, client_id, client_secret, scope, consentId (Rıza), resource
        (sandbox/production). ⚠️ API Secret 5 kez hatalı gidince portal uygulaması KİLİTLENİR
        (ACBG000005/6) → yanlış secret ile tekrar tekrar deneme YAPMA.
        """
        if not vakifbank_configured():
            raise VakifbankUnavailable(
                "VakıfBank API yapılandırılmamış (VAKIFBANK_CLIENT_ID / VAKIFBANK_API_SECRET boş)."
            )
        if self._token and time.time() < self._token_expires - 60:
            return self._token

        url = f"{settings.vakifbank_base_url}{settings.vakifbank_token_path}"
        data = {
            "grant_type": settings.vakifbank_grant_type,
            "client_id": settings.vakifbank_client_id,
            "client_secret": settings.vakifbank_api_secret,
            "scope": settings.vakifbank_scope,
            "resource": settings.vakifbank_resource,
        }
        if settings.vakifbank_riza_no:
            data["consentId"] = settings.vakifbank_riza_no
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.post(
                    url, data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                # Hata gövdesini teşhis için sakla (VakıfBank ACBG kod + açıklama döndürür)
                if resp.status_code >= 400:
                    raise VakifbankUnavailable(
                        f"VakıfBank token reddi (HTTP {resp.status_code}): {resp.text[:300]}"
                    )
                body = resp.json()
        except VakifbankUnavailable:
            raise
        except httpx.HTTPError as e:
            logger.error("VakıfBank token alınamadı: %s", e)
            raise VakifbankUnavailable(f"VakıfBank token hatası: {e}") from e

        token = body.get("access_token")
        if not token:
            raise VakifbankUnavailable(f"VakıfBank token yanıtında access_token yok: {str(body)[:300]}")
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
        # B2B akışında consent (Rıza) token'a gömülü → API çağrısı yalnız Bearer token ister.
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.post(url, json=payload, headers=headers)
                if resp.status_code >= 400:
                    if _no_transactions(resp):  # boş dönem HTTP 400 ile gelir — hata değil
                        return []
                    raise VakifbankUnavailable(
                        f"VakıfBank hareket reddi (HTTP {resp.status_code}): {resp.text[:300]}"
                    )
                body = resp.json()
        except VakifbankUnavailable:
            raise
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

    # ── Hesap listesi ────────────────────────────────────────────────────────
    def fetch_account_list(self) -> list:
        """Müşterinin hesap listesini çek (POST /accountList, gövde {}).

        Sandbox'ta test hesaplarını keşfetmek + test-connection teşhisi için. Yanıt
        şeması collection'da örneklenmediğinden savunmacı çıkarılır: Data içindeki
        İLK liste değer (yoksa Data dict'in kendisi tek öğeli liste olarak) döner.
        """
        token = self._get_token()
        url = f"{settings.vakifbank_base_url}{settings.vakifbank_account_list_path}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.post(url, json={}, headers=headers)
                if resp.status_code >= 400:
                    raise VakifbankUnavailable(
                        f"VakıfBank hesap listesi reddi (HTTP {resp.status_code}): {resp.text[:300]}"
                    )
                body = resp.json()
        except VakifbankUnavailable:
            raise
        except httpx.HTTPError as e:
            logger.error("VakıfBank hesap listesi hatası: %s", e)
            raise VakifbankUnavailable(f"VakıfBank hesap listesi hatası: {e}") from e

        header = body.get("Header") or {}
        status = header.get("StatusCode")
        if status and status != _SUCCESS_STATUS:
            raise VakifbankUnavailable(
                f"VakıfBank yanıt hatası: {header.get('StatusDescription') or status}"
            )
        return _extract_account_list(body)


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
    """date → VakıfBank istek zaman damgası — +03:00 offset'li ISO (collection örneği:
    '2024-09-26T00:00:00+03:00'; eski varsayım ISO-Z İDİ, resmî collection ile düzeltildi)."""
    return f"{d.isoformat()}T{'23:59:59' if end else '00:00:00'}+03:00"


def _parse_iso_z(s) -> Optional[date]:
    """'2023-08-08T13:56:51' (resmî örnek, Z'siz) veya '...T10:47:47.000Z' → date.
    İlk 10 karakter dilim tabanlı — sonek biçiminden bağımsız, sağlam."""
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
    """/accountTransactions POST gövdesi (resmî Postman collection ile birebir doğrulandı)."""
    return {
        "AccountNumber": account_number,
        "StartDate": _iso_z(start_date),
        "EndDate": _iso_z(end_date, end=True),
    }


def _no_transactions(resp) -> bool:
    """Yanıt 'hareket yok' (ACBH000202) mu? Banka bunu HTTP 400 ile döndürür."""
    try:
        header = resp.json().get("Header") or {}
        return header.get("StatusCode") == _NO_TRANSACTIONS_STATUS
    except Exception:  # JSON değilse gerçek hata yoluna düşsün
        return False


def _extract_account_list(body: dict) -> list:
    """/accountList yanıtından hesap listesini savunmacı çıkar (şema örneklenmedi):
    Data liste ise kendisi; dict ise içindeki ilk liste değer; o da yoksa [Data]."""
    if not isinstance(body, dict):
        return []
    data = body.get("Data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
        return [data] if data else []
    return []


def _extract_transaction_list(body: dict) -> List[dict]:
    """Yanıttan hareket listesini çıkar: Data.AccountTransactions (doğrulandı)."""
    if not isinstance(body, dict):
        return []
    data = body.get("Data")
    if isinstance(data, dict) and isinstance(data.get("AccountTransactions"), list):
        return data["AccountTransactions"]
    return []


def _normalize_batch(raw_list: List[dict]) -> List[dict]:
    """Ham hareket listesini ortak şemaya çevir + İŞARETLİ tutar üret.

    Yön belirleme öncelik sırası (resmî örnek yanıtla güncellendi 2026-07-10):
      1. **Bakiye zinciri** (ekstre ayrıştırıcı felsefesi): kronolojik sırala
         (TransactionDate + TransactionId); signed[i] = Balance[i] − Balance[i-1];
         |signed| ≈ |Amount| ise BU kullanılır (kesin yön). Not: sandbox test verisinde
         bakiyeler tutarsız (999999...) → zincir orada nadiren kurulur; üretimde kurulur.
      2. **Amount işareti**: resmî örnekte gider satırı NEGATİF gelir ("Amount": -1.74)
         → negatifse kesin gider.
      3. **TransactionType yedeği** (yalnız işaretsiz-pozitif satır): "2"=gider → negate;
         aksi halde gelir.
    """
    parsed = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        d = _parse_iso_z(raw.get("TransactionDate"))
        amt = _to_float(raw.get("Amount"))
        if d is None or amt is None:
            continue
        parsed.append({
            "date": d,
            "amount_raw": amt,           # İŞARETLİ (banka negatif gönderirse korunur)
            "amount_abs": abs(amt),
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
                signed = delta  # 1) bakiye zinciri → kesin yön
        if signed is None and r["amount_raw"] < 0:
            signed = r["amount_raw"]  # 2) banka işaretli gönderdi → kesin gider
        if signed is None:  # 3) işaretsiz-pozitif → TransactionType yedeği
            signed = -r["amount_abs"] if r["tx_type"] in _TX_TYPE_EXPENSE else r["amount_abs"]
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
