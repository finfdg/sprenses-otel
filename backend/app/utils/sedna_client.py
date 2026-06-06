"""Sedna SQL Server (cari) istemcisi — ters SSH tüneli üzerinden SALT-OKUNUR erişim.

Bağlantı YALNIZCA cari içe aktarma tetiklenince kurulur; uygulamanın normal işleyişi
bu bağlantıya bağlı DEĞİLDİR (tünel kapalıysa import açık hata verir, uygulama çalışmaya
devam eder). Türkçe collation (cp1254) için `charset` ayarlanır.

Eşleme kaynağı: AccountingTrans (hareket) + AccountingOwner (fiş başlığı: tarih/fiş no)
+ Accounting (hesap kartı: ad/ödeme günü) + AccDocumentType (işlem tipi). Yalnızca 320
(satıcılar) grubu ve silinmemiş (Deleted=0) kayıtlar.
"""
import logging
from typing import List

from app.config import settings

logger = logging.getLogger(__name__)


class SednaUnavailable(Exception):
    """Sedna/tünel erişilemediğinde yükselir (503 ile dışa verilir)."""


# {prefix} güvenli (yalnızca rakam) → sorguya gömülür; execute() PARAMETRESİZ çağrılır
# ki pymssql %-biçimlendirme tuzağı (LIKE '320%' içindeki %) tetiklenmesin.
_CARI_QUERY = """
SELECT
    t.AccountingCode            AS hesap_kodu,
    COALESCE(acc.Remark, '')    AS hesap_adi,
    CONVERT(date, o.FicheDate)  AS tarih,
    t.DocumentNo                AS evrak_no,
    dt.DocumentRemark           AS islem_tipi,
    o.Voucher                   AS fis_no,
    t.Remark1                   AS aciklama,
    t.Debit                     AS borc,
    t.Credit                    AS alacak,
    acc.PayDay                  AS pay_day
FROM AccountingTrans t
JOIN AccountingOwner o ON o.RecId = t.AccOwnerId
LEFT JOIN Accounting acc ON acc.Code = t.AccountingCode
LEFT JOIN AccDocumentType dt ON dt.DocumentType = t.DocumentType
WHERE t.AccountingCode LIKE '{prefix}%'
  AND t.Deleted = 0 AND o.Deleted = 0
  AND o.FicheDate IS NOT NULL
ORDER BY t.AccountingCode, o.FicheDate, t.RecId
"""


# Cari (320) banka/IBAN kayıtları — dbo.Bank, cari koduna (AccountingCode) bağlı.
# AccountingCode VİRGÜLLÜ saklanır (320,01,01,0063); Accounting.Code NOKTALI (320.01.01.0063)
# → join'de REPLACE ile eşitlenir. Bir firma → 0..N IBAN. {prefix} güvenli (rakam) → gömülü.
_IBAN_QUERY = """
SELECT
    REPLACE(b.AccountingCode, ',', '.') AS hesap_kodu,
    b.BankName                          AS banka,
    b.IbanNo                            AS iban,
    b.Title                             AS unvan,
    b.Curr                              AS para_birimi
FROM Bank b
JOIN Accounting a ON a.Code = REPLACE(b.AccountingCode, ',', '.')
WHERE b.IbanNo IS NOT NULL AND LTRIM(RTRIM(b.IbanNo)) <> ''
  AND a.Code LIKE '{prefix}%'
ORDER BY a.Code, b.RecId
"""


# Verilen çekler — AccCheckTrans (hareket) + AccCheck (çek kimliği: no/banka) + Accounting (ad).
# "Verilen Çek" issuance = CheckPosition=100, ActionType=2 (cari-tarafı borç satırı, çek başına TEK).
# Güncel durum: aynı CheckId'nin EN YÜKSEK pozisyonu (100-105) → 101/102 ödendi, 103 iptal, gerisi bekliyor.
# {prefix} güvenli (rakam) → gömülü; execute() PARAMETRESİZ (LIKE '%' tuzağı).
_ISSUED_CHECK_QUERY = """
SELECT
    REPLACE(t.AccountingCode, ',', '.') AS vendor_code,
    COALESCE(a.Remark, '')              AS vendor_name,
    ck.CheckNo                          AS check_no,
    ck.Bank                             AS bank,
    ck.City                             AS city,
    CONVERT(date, t.DueDate)            AS due_date,
    t.Debit                             AS amount_tl,
    t.Curr                              AS currency,
    t.CurrDebit                         AS amount_currency,
    mp.maxpos                           AS max_pos
FROM AccCheckTrans t
LEFT JOIN AccCheck ck ON ck.RecId = t.CheckId
LEFT JOIN Accounting a ON a.Code = REPLACE(t.AccountingCode, ',', '.')
CROSS APPLY (
    SELECT MAX(t2.CheckPosition) AS maxpos
    FROM AccCheckTrans t2
    WHERE t2.CheckId = t.CheckId AND t2.Deleted = 0 AND t2.CheckPosition BETWEEN 100 AND 105
) mp
WHERE t.Deleted = 0 AND t.AccountingCode LIKE '{prefix}%'
  AND t.CheckPosition = 100 AND t.ActionType = 2
  AND t.DueDate IS NOT NULL AND ck.CheckNo IS NOT NULL
ORDER BY t.DueDate
"""


# Otel satış faturaları + tahsilat — 120/Alıcılar (cariler 320'nin aynası).
# Fatura = 120 Borç hareketi (DocumentType=1 Hizmet Satış Fatura); tahsilat = 120 Alacak hareketi.
_SALES_INVOICE_QUERY = """
SELECT
    t.AccountingCode            AS customer_code,
    COALESCE(acc.Remark, '')    AS customer_name,
    CONVERT(date, o.FicheDate)  AS invoice_date,
    t.DocumentNo                AS invoice_no,
    t.Debit                     AS amount,
    t.Remark1                   AS aciklama
FROM AccountingTrans t
JOIN AccountingOwner o ON o.RecId = t.AccOwnerId
LEFT JOIN Accounting acc ON acc.Code = t.AccountingCode
WHERE t.AccountingCode LIKE '120%'
  AND t.DocumentType = 1 AND t.Debit > 0
  AND t.Deleted = 0 AND o.Deleted = 0 AND o.FicheDate IS NOT NULL
ORDER BY o.FicheDate, t.RecId
"""

_SALES_COLLECTION_QUERY = """
SELECT
    t.AccountingCode            AS customer_code,
    COALESCE(acc.Remark, '')    AS customer_name,
    CONVERT(date, o.FicheDate)  AS collection_date,
    t.Credit                    AS amount,
    t.Remark1                   AS aciklama,
    o.Voucher                   AS fis_no
FROM AccountingTrans t
JOIN AccountingOwner o ON o.RecId = t.AccOwnerId
LEFT JOIN Accounting acc ON acc.Code = t.AccountingCode
WHERE t.AccountingCode LIKE '120%'
  AND t.Credit > 0
  AND t.Deleted = 0 AND o.Deleted = 0 AND o.FicheDate IS NOT NULL
ORDER BY o.FicheDate, t.RecId
"""


def sedna_configured() -> bool:
    """SEDNA_PASSWORD tanımlı mı (import özelliği etkin mi)."""
    return bool(settings.sedna_password)


def fetch_cari_transactions() -> List[dict]:
    """Sedna'dan cari (varsayılan 320) hareketlerini dict listesi olarak çek.

    Anahtarlar: hesap_kodu, hesap_adi, tarih(date), evrak_no, islem_tipi, fis_no,
    aciklama, borc, alacak, pay_day.
    """
    if not sedna_configured():
        raise SednaUnavailable("Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD boş).")

    import pymssql  # yerel import — uygulama başlatımı pymssql'e bağlı olmasın

    # Prefix'i güvenli kıl (yalnızca rakam) → injection yok, sorguya gömülebilir
    prefix = "".join(c for c in (settings.sedna_account_prefix or "320") if c.isdigit()) or "320"
    query = _CARI_QUERY.format(prefix=prefix)

    try:
        conn = pymssql.connect(
            server=settings.sedna_host, port=settings.sedna_port,
            user=settings.sedna_user, password=settings.sedna_password,
            database=settings.sedna_database, charset=settings.sedna_charset,
            tds_version="7.4", login_timeout=10, timeout=180,
        )
    except Exception as e:
        logger.warning("Sedna bağlantısı kurulamadı: %s", e)
        raise SednaUnavailable(
            f"Sedna'ya bağlanılamadı — SSH tüneli kapalı olabilir "
            f"({settings.sedna_host}:{settings.sedna_port})."
        )

    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(query)  # PARAMETRESİZ (bkz. %-tuzağı notu)
        rows = cur.fetchall()
    finally:
        conn.close()

    logger.info("Sedna'dan %d cari hareket çekildi (prefix=%s)", len(rows), prefix)
    return rows


def fetch_vendor_ibans() -> List[dict]:
    """Sedna'dan cari (varsayılan 320) banka/IBAN kayıtlarını dict listesi olarak çek.

    Anahtarlar: hesap_kodu (noktalı), banka, iban, unvan, para_birimi. Bir firma birden
    çok IBAN taşıyabilir. Kaynak: dbo.Bank (cari = dbo.Accounting, AccountingCode üzerinden).
    """
    if not sedna_configured():
        raise SednaUnavailable("Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD boş).")

    import pymssql  # yerel import — uygulama başlatımı pymssql'e bağlı olmasın

    prefix = "".join(c for c in (settings.sedna_account_prefix or "320") if c.isdigit()) or "320"
    query = _IBAN_QUERY.format(prefix=prefix)

    try:
        conn = pymssql.connect(
            server=settings.sedna_host, port=settings.sedna_port,
            user=settings.sedna_user, password=settings.sedna_password,
            database=settings.sedna_database, charset=settings.sedna_charset,
            tds_version="7.4", login_timeout=10, timeout=60,
        )
    except Exception as e:
        logger.warning("Sedna bağlantısı kurulamadı (IBAN): %s", e)
        raise SednaUnavailable(
            f"Sedna'ya bağlanılamadı — SSH tüneli kapalı olabilir "
            f"({settings.sedna_host}:{settings.sedna_port})."
        )

    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(query)  # PARAMETRESİZ (bkz. %-tuzağı notu)
        rows = cur.fetchall()
    finally:
        conn.close()

    logger.info("Sedna'dan %d cari IBAN kaydı çekildi (prefix=%s)", len(rows), prefix)
    return rows


def fetch_issued_checks() -> List[dict]:
    """Sedna'dan cari (varsayılan 320) **verilen çek** kayıtlarını dict listesi olarak çek.

    Anahtarlar: vendor_code (noktalı), vendor_name, check_no, bank, city, due_date(date),
    amount_tl, currency, amount_currency, max_pos (güncel pozisyon → durum eşlemesi çağıranda).
    """
    if not sedna_configured():
        raise SednaUnavailable("Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD boş).")

    import pymssql  # yerel import — uygulama başlatımı pymssql'e bağlı olmasın

    prefix = "".join(c for c in (settings.sedna_account_prefix or "320") if c.isdigit()) or "320"
    query = _ISSUED_CHECK_QUERY.format(prefix=prefix)

    try:
        conn = pymssql.connect(
            server=settings.sedna_host, port=settings.sedna_port,
            user=settings.sedna_user, password=settings.sedna_password,
            database=settings.sedna_database, charset=settings.sedna_charset,
            tds_version="7.4", login_timeout=10, timeout=120,
        )
    except Exception as e:
        logger.warning("Sedna bağlantısı kurulamadı (çek): %s", e)
        raise SednaUnavailable(
            f"Sedna'ya bağlanılamadı — SSH tüneli kapalı olabilir "
            f"({settings.sedna_host}:{settings.sedna_port})."
        )

    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(query)  # PARAMETRESİZ (bkz. %-tuzağı notu)
        rows = cur.fetchall()
    finally:
        conn.close()

    logger.info("Sedna'dan %d verilen çek çekildi (prefix=%s)", len(rows), prefix)
    return rows


def fetch_sales_invoices() -> dict:
    """Sedna'dan otel satış faturalarını (120 Borç) + tahsilatları (120 Alacak) çek.

    Döner: {"invoices": [...], "collections": [...]}.
    invoice anahtarları: customer_code, customer_name, invoice_date(date), invoice_no, amount, aciklama.
    collection anahtarları: customer_code, collection_date(date), amount, aciklama, fis_no.
    """
    if not sedna_configured():
        raise SednaUnavailable("Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD boş).")

    import pymssql  # yerel import — uygulama başlatımı pymssql'e bağlı olmasın

    try:
        conn = pymssql.connect(
            server=settings.sedna_host, port=settings.sedna_port,
            user=settings.sedna_user, password=settings.sedna_password,
            database=settings.sedna_database, charset=settings.sedna_charset,
            tds_version="7.4", login_timeout=10, timeout=180,
        )
    except Exception as e:
        logger.warning("Sedna bağlantısı kurulamadı (satış faturası): %s", e)
        raise SednaUnavailable(
            f"Sedna'ya bağlanılamadı — SSH tüneli kapalı olabilir "
            f"({settings.sedna_host}:{settings.sedna_port})."
        )

    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(_SALES_INVOICE_QUERY)     # PARAMETRESİZ (LIKE '120%' tuzağı)
        invoices = cur.fetchall()
        cur.execute(_SALES_COLLECTION_QUERY)
        collections = cur.fetchall()
    finally:
        conn.close()

    logger.info("Sedna'dan %d satış faturası + %d tahsilat çekildi", len(invoices), len(collections))
    return {"invoices": invoices, "collections": collections}
