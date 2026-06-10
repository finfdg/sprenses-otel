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
# Karşı-taraf hesapları: ana satıcı (320, config'ten) + avans (159, verilen sipariş avansı) +
# personel/ortak (335). Üçü de "verilen çek"tir → senkronlanır ki durum/vade güncel kalsın. 159/335
# çekleri 320-only import'ta hiç güncellenmiyordu → Sedna'da iptal edilse bile bizde "bekliyor" kalıyordu
# (ör. çek 0353815 Sedna'da pos=103 iptal ama bizde vadesi-geçen pending görünüyordu).
# {prefix_clause} güvenli (yalnızca rakam prefix'leri) → gömülü; execute() PARAMETRESİZ (LIKE '%' tuzağı).
_ISSUED_CHECK_PREFIXES_EXTRA = ("159", "335")  # ana 320'ye eklenen verilen-çek karşı-taraf hesapları
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
WHERE t.Deleted = 0 AND ({prefix_clause})
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
    t.Curr                      AS currency,
    t.CurrDebit                 AS amount_currency,
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
    t.Curr                      AS currency,
    t.CurrCredit                AS amount_currency,
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


# Alınan avanslar — 340 "Alınan Sipariş Avansları" (acente/müşteriden alınan; 159 = bizim verdiğimiz).
# Alacak = alınan avans, Borç = faturayla mahsup. Döviz: CurrCredit/CurrDebit (yoksa TL).
_ADVANCE_ACCOUNT_QUERY = """
SELECT
    t.AccountingCode AS code,
    MIN(acc.Remark)  AS name,
    MIN(t.Curr)      AS currency,
    SUM(CASE WHEN t.Curr <> 'TL' THEN t.CurrCredit ELSE t.Credit END) AS received,
    SUM(CASE WHEN t.Curr <> 'TL' THEN t.CurrDebit  ELSE t.Debit  END) AS consumed
FROM AccountingTrans t
LEFT JOIN Accounting acc ON acc.Code = t.AccountingCode
WHERE t.AccountingCode LIKE '340%' AND t.Deleted = 0
GROUP BY t.AccountingCode
HAVING SUM(t.Credit) > 0
ORDER BY SUM(t.Credit) DESC
"""


def sedna_configured() -> bool:
    """SEDNA_PASSWORD tanımlı mı (import özelliği etkin mi)."""
    return bool(settings.sedna_password)


def fetch_advance_accounts() -> List[dict]:
    """Sedna'dan 340 'Alınan Avanslar' hesaplarını çek (acente bazında alınan/mahsup, döviz).

    Anahtarlar: code, name, currency, received (native), consumed (native).
    """
    if not sedna_configured():
        raise SednaUnavailable("Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD boş).")

    import pymssql  # yerel import

    try:
        conn = pymssql.connect(
            server=settings.sedna_host, port=settings.sedna_port,
            user=settings.sedna_user, password=settings.sedna_password,
            database=settings.sedna_database, charset=settings.sedna_charset,
            tds_version="7.4", login_timeout=10, timeout=60,
        )
    except Exception as e:
        logger.warning("Sedna bağlantısı kurulamadı (avans mutabakat): %s", e)
        raise SednaUnavailable(
            f"Sedna'ya bağlanılamadı — SSH tüneli kapalı olabilir "
            f"({settings.sedna_host}:{settings.sedna_port})."
        )
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(_ADVANCE_ACCOUNT_QUERY)
        rows = cur.fetchall()
    finally:
        conn.close()
    logger.info("Sedna'dan %d alınan-avans (340) hesabı çekildi", len(rows))
    return rows


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
    """Sedna'dan **verilen çek** kayıtlarını dict listesi olarak çek (320 satıcı + 159 avans + 335 personel/ortak).

    Anahtarlar: vendor_code (noktalı), vendor_name, check_no, bank, city, due_date(date),
    amount_tl, currency, amount_currency, max_pos (güncel pozisyon → durum eşlemesi çağıranda).
    """
    if not sedna_configured():
        raise SednaUnavailable("Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD boş).")

    import pymssql  # yerel import — uygulama başlatımı pymssql'e bağlı olmasın

    prefix = "".join(c for c in (settings.sedna_account_prefix or "320") if c.isdigit()) or "320"
    # Ana satıcı (320) + avans (159) + personel/ortak (335) — üçü de verilen çek. Prefix'ler rakam →
    # gömülü (pymssql %-tuzağı için execute parametresiz). EXTRA'dan ana prefix'i çıkar (mükerrer OR olmasın).
    prefixes = [prefix] + [p for p in _ISSUED_CHECK_PREFIXES_EXTRA if p != prefix]
    prefix_clause = " OR ".join("t.AccountingCode LIKE '{}%'".format(p) for p in prefixes)
    query = _ISSUED_CHECK_QUERY.format(prefix_clause=prefix_clause)

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

    logger.info("Sedna'dan %d verilen çek çekildi (prefix'ler=%s)", len(rows), ",".join(prefixes))
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


# ─── STOK / DEPO (Stok Maliyet modülü) ──────────────────────────────────────
# Kaynak: Store (depo/departman) + Product (ürün kartı) + StockOwner/StockTrans
# (hareket başlığı+satırı) + Accounting (tedarikçi). Type: 12=Alış, 29=Tüketim, 20=Çıkış…

def _stock_connect(timeout: int = 120):
    """Stok sorguları için Sedna bağlantısı (salt-okunur). Tünel kapalıysa SednaUnavailable."""
    import pymssql
    try:
        return pymssql.connect(
            server=settings.sedna_host, port=settings.sedna_port,
            user=settings.sedna_user, password=settings.sedna_password,
            database=settings.sedna_database, charset=settings.sedna_charset,
            tds_version="7.4", login_timeout=10, timeout=timeout,
        )
    except Exception as e:
        logger.warning("Sedna bağlantısı kurulamadı (stok): %s", e)
        raise SednaUnavailable(
            f"Sedna'ya bağlanılamadı — SSH tüneli kapalı olabilir "
            f"({settings.sedna_host}:{settings.sedna_port})."
        )


_STOCK_DEPOT_QUERY = """
SELECT StoreCode AS code, Remark AS name,
       ISNULL(NoConsumption,0) AS no_consumption, ISNULL(Expense,0) AS is_expense
FROM Store WHERE StoreCode IS NOT NULL AND Remark IS NOT NULL
"""

# Ürün kartı + anlık stok (son hareketin yürüyen bakiyesi StockQuantity) + son birim maliyet
_STOCK_PRODUCT_QUERY = """
SELECT p.RecId AS sedna_id, p.Code AS code, p.Remark AS name,
       p.CurrencyCode AS currency, p.StockType AS stock_type,
       s.qty AS current_stock, s.cost AS last_cost
FROM Product p
LEFT JOIN (
  SELECT st.CardId, st.StockQuantity AS qty, st.Cost AS cost
  FROM StockTrans st
  JOIN (SELECT CardId, MAX(RecId) mx FROM StockTrans GROUP BY CardId) m
    ON st.CardId = m.CardId AND st.RecId = m.mx
) s ON p.RecId = s.CardId
WHERE p.Remark IS NOT NULL
"""

# Tüm stok hareketleri (denormalize: ürün adı, depo kodları, tedarikçi). DB yıl-bazlı (Mhs2026).
_STOCK_MOVEMENT_QUERY = """
SELECT so.RecId AS owner_id, st.RecId AS line_id, so.Type AS type_code, so.Dates AS date,
       so.DocumNo AS doc_no, so.ConsumptionDepot AS cons_depot,
       sup.Code AS supplier_code, sup.Remark AS supplier_name,
       st.CardId AS product_id, p.Code AS product_code, p.Remark AS product_name,
       st.EntryingDepot AS entry_depot, st.ExitingDepot AS exit_depot,
       st.Quantity AS quantity, st.Cost AS unit_cost, st.NetAmount AS net_amount
FROM StockTrans st
JOIN StockOwner so ON st.StockOwnerId = so.RecId
LEFT JOIN Product p ON st.CardId = p.RecId
LEFT JOIN Accounting sup ON so.CurrentId = sup.RecId
WHERE so.Status = 1 AND so.Dates IS NOT NULL
"""


def fetch_stock_depots() -> List[dict]:
    """Sedna Store → depo/departman tanımları (code, name, no_consumption, is_expense)."""
    if not sedna_configured():
        raise SednaUnavailable("Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD boş).")
    conn = _stock_connect(60)
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(_STOCK_DEPOT_QUERY)
        rows = cur.fetchall()
    finally:
        conn.close()
    logger.info("Sedna'dan %d depo çekildi", len(rows))
    return rows


def fetch_stock_products() -> List[dict]:
    """Sedna Product → ürün kartları + anlık stok (son StockQuantity) + son maliyet."""
    if not sedna_configured():
        raise SednaUnavailable("Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD boş).")
    conn = _stock_connect(120)
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(_STOCK_PRODUCT_QUERY)
        rows = cur.fetchall()
    finally:
        conn.close()
    logger.info("Sedna'dan %d ürün çekildi", len(rows))
    return rows


def fetch_stock_movements() -> List[dict]:
    """Sedna StockOwner+StockTrans → tüm stok hareketleri (alış/tüketim/çıkış), denormalize."""
    if not sedna_configured():
        raise SednaUnavailable("Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD boş).")
    conn = _stock_connect(180)
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(_STOCK_MOVEMENT_QUERY)
        rows = cur.fetchall()
    finally:
        conn.close()
    logger.info("Sedna'dan %d stok hareketi çekildi", len(rows))
    return rows


# Kullanıcı fiş icmali — AccountingOwner (fiş başlığı) kesen kullanıcı (RecordUser) + Users (ad).
# Her AccountingOwner = bir fiş; kullanıcı × dönem (gün/ay) sayımı. Tarih: RecordDate (ne zaman
# girdi = üretkenlik) veya FicheDate (muhasebe tarihi). {datecol}/{plen} whitelist, {start}/{end}
# çağıranca doğrulanmış ISO → güvenli gömülü, execute() PARAMETRESİZ (pymssql %-tuzağı yok).
_VOUCHER_SUMMARY_QUERY = """
SELECT COALESCE(NULLIF(o.RecordUser, ''), '(boş)') AS user_code,
       MAX(u.UserName)                             AS user_name,
       CONVERT(varchar({plen}), o.{datecol}, 120)  AS period,
       COUNT(*)                                    AS cnt
FROM AccountingOwner o
LEFT JOIN Users u ON u.UserCode = o.RecordUser
WHERE o.Deleted = 0 AND o.{datecol} >= '{start}' AND o.{datecol} < '{end}'
GROUP BY COALESCE(NULLIF(o.RecordUser, ''), '(boş)'), CONVERT(varchar({plen}), o.{datecol}, 120)
"""


def fetch_voucher_summary(start: str, end: str, granularity: str = "month",
                          date_field: str = "record") -> List[dict]:
    """Muhasebe fişlerini kesen kullanıcıya göre dönem (gün/ay) bazında say.

    `start`/`end` ISO tarih (end EXCLUSIVE); whitelist dışı granularity/date_field reddedilir.
    """
    if not sedna_configured():
        raise SednaUnavailable("Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD boş).")
    datecol = "RecordDate" if date_field == "record" else "FicheDate"
    plen = 7 if granularity == "month" else 10  # YYYY-MM | YYYY-MM-DD
    conn = _stock_connect(120)  # fişler muhasebe DB'sinde (settings.sedna_database)
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(_VOUCHER_SUMMARY_QUERY.format(plen=plen, datecol=datecol, start=start, end=end))
        rows = cur.fetchall()
    finally:
        conn.close()
    logger.info("Sedna fiş icmali: %d satır (%s..%s, %s/%s)", len(rows), start, end, granularity, date_field)
    return rows


def fetch_user_vouchers(user_code: str, start: str, end: str, date_field: str = "record") -> List[dict]:
    """Bir kullanıcının (RecordUser) bir aralıkta kestiği fişler (drill-down). end EXCLUSIVE.

    **RecordUser SQL'de FİLTRELENMEZ:** Türkçe karakterli kullanıcı kodu (TUĞÇE/Şule/İlker) SQL
    karşılaştırmasında eşleşmez — FreeTDS sorgu metnindeki Ğ/Ş/İ'yi CP1254'e kodlamaz (param da, literal
    de), ama sonuçları CP1254 ile DOĞRU decode eder. Bu yüzden aralık çekilir ve **Python'da** decode
    edilmiş `RecordUser` ile filtrelenir (string eşitliği güvenli). datecol whitelist; date'ler ISO-güvenli
    gömülü → parametresiz execute (pymssql %-tuzağı yok).
    """
    if not sedna_configured():
        raise SednaUnavailable("Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD boş).")
    datecol = "RecordDate" if date_field == "record" else "FicheDate"
    query = (
        "SELECT o.RecId AS rec_id, o.Voucher AS voucher, "
        "CONVERT(date, o.FicheDate) AS fiche_date, CONVERT(date, o.RecordDate) AS record_date, "
        "o.Remark AS remark, o.Total AS total, o.RecordUser AS record_user "
        "FROM AccountingOwner o "
        f"WHERE o.Deleted = 0 AND o.{datecol} >= '{start}' AND o.{datecol} < '{end}' "
        f"ORDER BY o.{datecol}, o.Voucher"
    )
    conn = _stock_connect(120)
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(query)
        rows = cur.fetchall()
    finally:
        conn.close()
    uc = (user_code or "").strip()
    filtered = [r for r in rows if (r.get("record_user") or "").strip() == uc]
    logger.info("Sedna fiş listesi: %s → %d/%d fiş (%s..%s)", uc, len(filtered), len(rows), start, end)
    return filtered


def fetch_voucher_detail(rec_id: int) -> dict:
    """Tek fişin (AccountingOwner.RecId) başlığı + muhasebe satırları (AccountingTrans + hesap adı)."""
    if not sedna_configured():
        raise SednaUnavailable("Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD boş).")
    conn = _stock_connect(60)
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT o.RecId AS rec_id, o.Voucher AS voucher, CONVERT(date, o.FicheDate) AS fiche_date, "
            "CONVERT(date, o.RecordDate) AS record_date, o.Remark AS remark, o.Total AS total, "
            "o.RecordUser AS record_user, o.ChangeUser AS change_user "
            "FROM AccountingOwner o WHERE o.RecId = %s AND o.Deleted = 0",
            (rec_id,),
        )
        header = cur.fetchone()
        cur.execute(
            "SELECT t.AccountingCode AS code, acc.Remark AS account_name, t.Debit AS debit, "
            "t.Credit AS credit, t.Remark1 AS remark "
            "FROM AccountingTrans t LEFT JOIN Accounting acc ON acc.Code = t.AccountingCode "
            "WHERE t.AccOwnerId = %s AND t.Deleted = 0 ORDER BY t.RecId",
            (rec_id,),
        )
        lines = cur.fetchall()
    finally:
        conn.close()
    return {"header": header, "lines": lines}


# ─── Mizan (geçici mizan / trial balance) ───────────────────────────────────
# AccountingTrans (Debit/Credit, AccountingCode NOKTALI = leaf hesap) + AccountingOwner (FicheDate).
# Mizan = hesap bazında SUM(Debit)/SUM(Credit). Leaf bazında çekilir; KADEME (ana/alt hesap) aggregasyonu
# router'da Python'da yapılır → tek sorgu tüm kademeleri besler. Çift taraflı kayıt → toplam borç=alacak
# (denge kontrolü). {start}/{end} çağıranca doğrulanmış ISO (end EXCLUSIVE) → gömülü, execute PARAMETRESİZ.
_MIZAN_QUERY = """
SELECT
    t.AccountingCode AS code,
    SUM(t.Debit)     AS borc,
    SUM(t.Credit)    AS alacak
FROM AccountingTrans t
JOIN AccountingOwner o ON o.RecId = t.AccOwnerId
WHERE t.Deleted = 0 AND o.Deleted = 0
  AND o.FicheDate >= '{start}' AND o.FicheDate < '{end}'
GROUP BY t.AccountingCode
"""


def fetch_mizan(start: str, end: str) -> List[dict]:
    """Dönem mizanı: leaf hesap bazında borç/alacak toplamı (FicheDate aralığı, end EXCLUSIVE).

    Kademe (ana hesap / alt hesap) aggregasyonu router'da. `start`/`end` ISO-doğrulanmış (çağıran).
    """
    if not sedna_configured():
        raise SednaUnavailable("Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD boş).")
    conn = _stock_connect(120)
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(_MIZAN_QUERY.format(start=start, end=end))
        rows = cur.fetchall()
    finally:
        conn.close()
    logger.info("Sedna mizan: %d leaf hesap (%s..%s)", len(rows), start, end)
    return rows


def fetch_account_names() -> dict:
    """Hesap planı ad haritası {Code: Remark} — mizan kademesindeki prefix'lerin adını çözmek için.

    Ana + alt + leaf tüm hesapları içerir (canlı ~9.5K). Yalnız server-side lookup; tümü frontend'e
    gönderilmez (yalnız mizan satırlarına ad eklenir).
    """
    if not sedna_configured():
        raise SednaUnavailable("Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD boş).")
    conn = _stock_connect(60)
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute("SELECT Code, Remark FROM Accounting WHERE Code IS NOT NULL")
        rows = cur.fetchall()
    finally:
        conn.close()
    return {(r["Code"] or "").strip(): (r["Remark"] or "").strip() for r in rows}


def fetch_account_transactions(code: str, start: str, end: str, limit: int = 1000) -> List[dict]:
    """Bir hesabın (ve alt hesaplarının) dönem hareketleri (mizan drill-down → defter).

    `code` = tam leaf (`320.01.01.P033`) veya prefix (`320` → tüm 320.* alt hesapları). Çağıran
    `code`'u `[A-Za-z0-9.]` ile doğrular → güvenli gömülü (pymssql %-tuzağı: LIKE % + parametresiz execute).
    En fazla `limit` satır (FicheDate sıralı). `start`/`end` ISO-doğrulanmış.
    """
    if not sedna_configured():
        raise SednaUnavailable("Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD boş).")
    top = max(1, min(int(limit), 5000))
    query = (
        f"SELECT TOP {top} CONVERT(date, o.FicheDate) AS fiche_date, o.Voucher AS voucher, "
        "t.AccountingCode AS code, t.Remark1 AS remark, t.Debit AS debit, t.Credit AS credit, "
        "o.RecId AS rec_id "
        "FROM AccountingTrans t JOIN AccountingOwner o ON o.RecId = t.AccOwnerId "
        "WHERE t.Deleted = 0 AND o.Deleted = 0 "
        f"AND o.FicheDate >= '{start}' AND o.FicheDate < '{end}' "
        f"AND (t.AccountingCode = '{code}' OR t.AccountingCode LIKE '{code}.%') "
        "ORDER BY o.FicheDate, o.Voucher, t.RecId"
    )
    conn = _stock_connect(120)
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(query)
        rows = cur.fetchall()
    finally:
        conn.close()
    logger.info("Sedna mizan hareket: %s → %d satır (%s..%s)", code, len(rows), start, end)
    return rows


# ─── Önbüro/PMS (SednaPrenses) — rezervasyon/doluluk ────────────────────────
# Stok/cari muhasebe DB'sinden (SednaPrensesMhs2026) AYRI bir DB (SednaPrenses) — aynı
# btadmin login'i ikisini de okur. Doluluk (geceleme/pax) maliyet KPI'larını besler.

def _pms_connect(timeout: int = 120):
    """Önbüro (SednaPrenses) bağlantısı — salt-okunur. Tünel kapalıysa SednaUnavailable."""
    import pymssql
    try:
        return pymssql.connect(
            server=settings.sedna_host, port=settings.sedna_port,
            user=settings.sedna_user, password=settings.sedna_password,
            database=settings.sedna_pms_database, charset=settings.sedna_charset,
            tds_version="7.4", login_timeout=10, timeout=timeout,
        )
    except Exception as e:
        logger.warning("Sedna bağlantısı kurulamadı (önbüro): %s", e)
        raise SednaUnavailable(
            f"Sedna'ya bağlanılamadı — SSH tüneli kapalı olabilir "
            f"({settings.sedna_host}:{settings.sedna_port})."
        )


# Rezervasyon (doluluk) — Reservation + Agency (acente adı) + Contrack (para birimi). pax =
# Pax(yetişkin) + PaidChild + FreeChild + Baby. nation = NationalityMarketCode (DEU/RUS/GBR —
# 3 harf, Excel ile aynı). **Para birimi `Contrack.Currency`** (EUR/TL/USD) — RoomCon boş, milliyet
# değil sözleşme belirler (yerli/WEBRES = TL). RoomPrice o para biriminde; içe aktarmada EUR'ya
# çevrilir. Status -1 = iptal (içe aktarmada silinir).
# {start} güvenli (ISO tarih, yalnız rakam/tire) → gömülü; execute() PARAMETRESİZ (pymssql %-tuzağı).
_RESERVATION_QUERY = """
SELECT
    r.RecId                        AS rec_id,
    a.Name                         AS agency,
    r.RoomType                     AS room_type,
    r.Voucher                      AS voucher,
    r.Guests                       AS guests,
    CONVERT(date, r.CheckinDate)   AS checkin_date,
    CONVERT(date, r.CheckOutDate)  AS checkout_date,
    CONVERT(date, r.RecordDate)    AS record_date,
    r.Board                        AS board,
    r.VipTypeCode                  AS vip_type,
    r.Pax                          AS adult,
    r.PaidChild                    AS child_paid,
    r.FreeChild                    AS child_free,
    r.Baby                         AS baby,
    r.NationalityMarketCode        AS nation,
    r.RoomPrice                    AS room_price,
    c.Currency                     AS currency,
    r.Status                       AS status_code,
    CONVERT(date, r.CancelDate)    AS cancel_date
FROM Reservation r
LEFT JOIN Agency a ON a.RecId = r.AgencyId
LEFT JOIN Contrack c ON c.RecId = r.ContrackId
WHERE r.CheckinDate >= '{start}'
ORDER BY r.CheckinDate, r.RecId
"""


def fetch_reservations(start: str) -> List[dict]:
    """SednaPrenses Reservation → check-in >= start olan tüm rezervasyonlar (iptaller dahil).

    `start` ISO tarih (YYYY-MM-DD) — yalnız rakam/tire olduğu çağıran tarafça garanti edilir.
    """
    if not sedna_configured():
        raise SednaUnavailable("Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD boş).")
    conn = _pms_connect(180)
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(_RESERVATION_QUERY.format(start=start))
        rows = cur.fetchall()
    finally:
        conn.close()
    logger.info("Sedna önbürodan %d rezervasyon çekildi (check-in>=%s)", len(rows), start)
    return rows


# Günlük hareket — RecordDate (gelen) / CancelDate (iptal) eksenli. RecordDate/CancelDate
# datetime olduğundan gün sınırı yarı açık aralıkla [start, end_next) güvenli kesilir.
# {start}/{end_next} güvenli (ISO tarih) → gömülü; execute() PARAMETRESİZ (pymssql %-tuzağı).
_RESERVATION_ACTIVITY_QUERY = """
SELECT
    r.RecId                        AS rec_id,
    a.Name                         AS agency,
    r.RoomType                     AS room_type,
    r.Voucher                      AS voucher,
    r.Guests                       AS guests,
    CONVERT(date, r.CheckinDate)   AS checkin_date,
    CONVERT(date, r.CheckOutDate)  AS checkout_date,
    CONVERT(date, r.RecordDate)    AS record_date,
    r.Board                        AS board,
    r.Pax                          AS adult,
    r.PaidChild                    AS child_paid,
    r.FreeChild                    AS child_free,
    r.Baby                         AS baby,
    r.NationalityMarketCode        AS nation,
    r.RoomPrice                    AS room_price,
    c.Currency                     AS currency,
    r.Status                       AS status_code,
    CONVERT(date, r.CancelDate)    AS cancel_date
FROM Reservation r
LEFT JOIN Agency a ON a.RecId = r.AgencyId
LEFT JOIN Contrack c ON c.RecId = r.ContrackId
WHERE (r.RecordDate >= '{start}' AND r.RecordDate < '{end_next}')
   OR (r.CancelDate >= '{start}' AND r.CancelDate < '{end_next}')
ORDER BY r.RecordDate, r.RecId
"""


def fetch_reservation_activity(start: str, end_next: str) -> List[dict]:
    """SednaPrenses Reservation → kayıt (RecordDate) VEYA iptal (CancelDate) tarihi
    [start, end_next) aralığına düşen rezervasyonlar — günlük gelen/iptal akışı için.

    `start`/`end_next` ISO tarih (YYYY-MM-DD) — yalnız rakam/tire olduğu çağıran tarafça
    garanti edilir. Bir satır hem gelen (record_date) hem iptal (cancel_date) olarak
    görünebilir; ayrıştırma çağıran taraftadır.
    """
    if not sedna_configured():
        raise SednaUnavailable("Sedna bağlantısı yapılandırılmamış (SEDNA_PASSWORD boş).")
    conn = _pms_connect(120)
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(_RESERVATION_ACTIVITY_QUERY.format(start=start, end_next=end_next))
        rows = cur.fetchall()
    finally:
        conn.close()
    logger.info("Sedna önbürodan %d günlük-hareket satırı çekildi (%s → %s)", len(rows), start, end_next)
    return rows
