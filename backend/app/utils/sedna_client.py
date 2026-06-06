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
