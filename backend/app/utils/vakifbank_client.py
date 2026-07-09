"""VakıfBank Açık Bankacılık API istemcisi — banka hesap hareketlerini SALT-OKUNUR çeker.

Amaç: mevcut Excel/PDF ekstre yüklemesine ek olarak, VakıfBank hesap hareketlerini
doğrudan API'den çekip `bank_transactions`'a (aynı dedup + finance_event yoluyla) yazmak.
Bağlantı YALNIZCA senkron tetiklenince kurulur; uygulamanın normal işleyişi buna bağlı
DEĞİLDİR (kimlik yoksa/hata olursa import açık hata verir, uygulama çalışmaya devam eder).

Kimlik akışı (VakıfBank apiportal — Hesap Bilgi Servisleri):
  1. OAuth2 token  (B2B Credentials: client_id + api_secret)
  2. /accountTransactions  (POST, token + Rıza Numarası; tarih aralığı ile filtreli)

⚠️ İSKELET — DOLDURULACAK: token endpoint'i, request/response alan adları ve Rıza akışı
VakıfBank dokümanındaki "Models" (RequestData / List<AccountTransactions>) bölümlerine göre
kesinleştirilmelidir. `_normalize_transaction` ve `_build_transactions_payload` içindeki TODO
işaretli yerler gerçek alan adlarıyla değiştirilecek. Kimlik/IP whitelist tamamlanmadan
API 401/403 döner.
"""
import logging
import time
from datetime import date
from typing import List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# İstek zaman aşımı (sn) — ölü/yavaş uç uygulamayı kilitlemesin
_TIMEOUT = 20.0


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

        TODO: VakıfBank token endpoint'inin GERÇEK request biçimi dokümandan teyit edilmeli
        (grant_type/scope alan adları, client kimliğinin body'de mi Basic-Auth header'ında mı
        gideceği). Aşağıdaki client_credentials akışı standart bir varsayımdır.
        """
        if not vakifbank_configured():
            raise VakifbankUnavailable(
                "VakıfBank API yapılandırılmamış (VAKIFBANK_CLIENT_ID / VAKIFBANK_API_SECRET boş)."
            )
        if self._token and time.time() < self._token_expires - 60:
            return self._token

        url = f"{settings.vakifbank_base_url}{settings.vakifbank_token_path}"
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.post(
                    url,
                    data={  # TODO: doküman scope/grant alanlarını teyit et
                        "grant_type": "client_credentials",
                        "scope": settings.vakifbank_scope,
                    },
                    # TODO: kimlik Basic-Auth mı body mi? Doküman "Token Oluştur" akışına göre.
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
        self, iban: str, start_date: date, end_date: date,
    ) -> List[dict]:
        """Bir IBAN için [start_date, end_date] arası hareketleri normalize edilmiş dict listesi döndür.

        Dönen her öğe: {date, amount, balance, description, type, receipt_no}.
        **amount İŞARETLİDİR** (gider = negatif) — mevcut ekstre ayrıştırıcısıyla AYNI konvansiyon
        (`bank_parser`: `amount = -abs(borç)` / `+abs(alacak)`); bakiye-bazlı dedup buna dayanır.
        `type` = 'income' if amount >= 0 else 'expense'.

        TODO: Gerçek request/response VakıfBank "RequestData" ve "List<AccountTransactions>"
        modeline göre `_build_transactions_payload` + `_normalize_transaction`'da eşlenecek.
        """
        token = self._get_token()
        url = f"{settings.vakifbank_base_url}{settings.vakifbank_transactions_path}"
        payload = _build_transactions_payload(iban, start_date, end_date)
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        # TODO: Rıza Numarası hangi header/body alanında gidiyor? (doküman)
                        "rizaNo": settings.vakifbank_riza_no,
                    },
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as e:
            logger.error("VakıfBank hareket sorgusu hatası (IBAN %s): %s", iban[-4:], e)
            raise VakifbankUnavailable(f"VakıfBank hareket hatası: {e}") from e

        raw_list = _extract_transaction_list(body)
        out: List[dict] = []
        for raw in raw_list:
            norm = _normalize_transaction(raw)
            if norm is not None:
                out.append(norm)
        return out


# ── Modül-düzeyi tekil örnek (Amadeus deseni) ────────────────────────────────
_client_singleton: Optional[VakifbankClient] = None


def get_vakifbank_client() -> VakifbankClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = VakifbankClient()
    return _client_singleton


# ═══════════════════════════════════════════════════════════════════════════════
# Alan eşleme yardımcıları — VakıfBank "Models" JSON'ı gelince DOLDURULACAK (TODO)
# ═══════════════════════════════════════════════════════════════════════════════

def _build_transactions_payload(iban: str, start_date: date, end_date: date) -> dict:
    """/accountTransactions POST gövdesi. TODO: "RequestData" modeline göre alan adları.

    Aşağıdaki anahtar adları TAHMİNDİR (iban/startDate/endDate). VakıfBank IBAN yerine
    hesap no + şube isteyebilir; tarih formatı farklı olabilir (ör. 'yyyy-MM-dd' veya
    'ddMMyyyy'). Doküman gelince burası netleştirilecek.
    """
    return {
        "iban": iban,                        # TODO: gerçek alan adı (accountNumber/iban?)
        "startDate": start_date.isoformat(),  # TODO: gerçek tarih formatı
        "endDate": end_date.isoformat(),
    }


def _extract_transaction_list(body: dict) -> List[dict]:
    """Yanıt gövdesinden hareket listesini çıkar. TODO: gerçek zarf anahtarı.

    VakıfBank yanıtı genelde bir zarf içinde döner (ör. {"Data": {"transactions": [...]}}
    veya {"accountTransactions": [...]}). Doğru anahtar dokümandan teyit edilecek.
    """
    if not isinstance(body, dict):
        return []
    # TODO: gerçek anahtar(lar)ı doküman "List<AccountTransactions>" konumuna göre ayarla
    for key in ("accountTransactions", "transactions", "Data", "data"):
        val = body.get(key)
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            for inner in ("transactions", "accountTransactions", "items"):
                if isinstance(val.get(inner), list):
                    return val[inner]
    return []


def _normalize_transaction(raw: dict) -> Optional[dict]:
    """Bir ham hareketi ortak şemaya çevir. TODO: alan adları "AccountTransactions" modelinden.

    Ortak şema: {date: date, amount: float(İŞARETLİ; gider negatif), balance: float|None,
    description: str, type: 'income'|'expense', receipt_no: str|None}. Eşleme yapılamıyorsa
    None döner (atlanır). Şimdilik iskelet: gerçek alan adları bilinmediğinden None döndürür —
    böylece yanlış veri yazılmaz. Doküman gelince buradaki TODO'lar doldurulacak.
    """
    # TODO — VakıfBank alan adlarını eşle. ÖRNEK (doğrulanacak):
    #   raw_date  = raw["transactionDate"]        # 'yyyy-MM-dd' veya 'ddMMyyyy'
    #   drcr      = raw.get("debitCreditIndicator")  # 'A'/'B' veya 'CREDIT'/'DEBIT'
    #   raw_amt   = float(raw["amount"])          # tek alan mı, ayrı borç/alacak alanı mı?
    #   # İŞARETLİ amount üret (ekstre ayrıştırıcı konvansiyonu): gider negatif, gelir pozitif
    #   amount    = abs(raw_amt) if drcr in ("A", "CREDIT", "1") else -abs(raw_amt)
    #   balance   = float(raw.get("balance"))
    #   desc      = (raw.get("description") or "").strip()
    #   receipt   = raw.get("referenceNo")
    #   return {"date": _parse_date(raw_date), "amount": amount, "balance": balance,
    #           "description": desc, "type": "income" if amount >= 0 else "expense",
    #           "receipt_no": receipt}
    logger.warning(
        "VakıfBank hareket alan eşlemesi henüz yapılmadı (_normalize_transaction TODO) — "
        "kayıt atlandı. Doküman 'AccountTransactions' modelini paylaşın."
    )
    return None
