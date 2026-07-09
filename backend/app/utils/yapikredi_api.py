"""Yapı Kredi API entegrasyonu — hesap hareketlerini çekip ParseResult'a dönüştürür.

API dökümanı: apiportal.yapikredi.com.tr
- Account Transaction List (OAuth2 Client Credentials)
- Endpoint: POST /api/currentAccounts/account/v1/accountTransactionList

Kimlik bilgileri .env'den okunur (config.py), koda gömülmez.
"""
import base64
import logging
from datetime import date, datetime
from typing import Optional

import httpx

from app.config import settings
from app.utils.bank_parser import (
    ParsedHeader,
    ParsedTransaction,
    ParseResult,
    compute_tx_hash,
)

logger = logging.getLogger(__name__)

TXN_URL = "https://api.yapikredi.com.tr/api/currentAccounts/account/v1/accountTransactionList"
_PAGE_SIZE = 100


def _get_token() -> str:
    """OAuth2 client_credentials ile access token alır."""
    creds = base64.b64encode(
        f"{settings.ykb_client_id}:{settings.ykb_client_secret}".encode()
    ).decode()
    resp = httpx.post(
        settings.ykb_token_url,
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials", "scope": settings.ykb_scope},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_yapikredi_statement(
    account_no: str,
    ccy: str,
    start: date,
    end: date,
    iban: Optional[str] = None,
) -> ParseResult:
    """Verilen hesap + tarih aralığı için hareketleri çeker, ParseResult döner.

    amount işaretli: negatif = borç/gider, pozitif = alacak/gelir.
    Aynı gün+tutar+açıklama tekrarları compute_tx_hash seq ile ayrıştırılır.
    """
    token = _get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    txns: list[ParsedTransaction] = []
    no_of_page = 1
    post_no = 0
    seq_seen: dict[str, int] = {}

    while True:
        body = {
            "accountNo": account_no,
            "ccy": ccy,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "continuousSearch": True,
            "descSort": False,
            "noOfPage": no_of_page,
            "noOfRecs": _PAGE_SIZE,
            "postNo": post_no,
        }
        r = httpx.post(TXN_URL, headers=headers, json=body, timeout=60)
        r.raise_for_status()
        ret = r.json().get("response", {}).get("return", {}) or {}
        rows = ret.get("list", []) or []

        for row in rows:
            amount = float(row["amount"])  # negatif = borç
            tx_date = datetime.strptime(row["inputDate"], "%d.%m.%Y").date()
            desc = (row.get("postNarr") or "").strip()
            receipt_no = row.get("receiptId")

            # aynı gün+tutar+açıklama tekrarlarını ayırt etmek için seq
            base_key = f"{tx_date.isoformat()}|{receipt_no or ''}|{amount:.2f}|{desc[:50]}"
            seq = seq_seen.get(base_key, 0)
            seq_seen[base_key] = seq + 1

            txns.append(
                ParsedTransaction(
                    date=tx_date,
                    receipt_no=receipt_no,
                    description=desc,
                    amount=amount,
                    balance=(
                        float(row["balance"])
                        if row.get("balance") not in (None, "")
                        else None
                    ),
                    type="income" if amount >= 0 else "expense",
                    tx_hash=compute_tx_hash(tx_date, receipt_no, amount, desc, seq=seq),
                    time=row.get("createTime"),
                )
            )

        # sayfalama: sayfa doluysa devam et, değilse son sayfa
        if len(rows) < _PAGE_SIZE:
            break
        no_of_page += 1
        post_no = int(ret.get("postNo", 0) or 0)

    header = ParsedHeader(
        iban=iban,
        currency=ccy,
        account_no=account_no,
        period_start=start,
        period_end=end,
    )
    logger.info(
        "Yapı Kredi ekstre çekildi: hesap=%s dönem=%s..%s hareket=%d",
        account_no,
        start,
        end,
        len(txns),
    )
    return ParseResult(header=header, transactions=txns)
