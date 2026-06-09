# Kullanıcı Fiş İcmali

## Genel Bilgi
- **Modül kodu:** `accounting.fis_icmali` (Muhasebe altı)
- **Frontend rota:** `/dashboard/muhasebe/fis-icmali`
- **Backend prefix:** `/api/accounting/fis-icmali`
- **İzin:** `accounting.fis_icmali` view
- **Kaynak:** Sedna muhasebe DB'si — **canlı** sorgu (yerel saklama/model/migration YOK)

Sedna'da kesilen muhasebe fişlerini **kesen kullanıcıya göre** gün/ay bazında icmal eder:
"kim, ne zaman, ne kadar fiş kesmiş". Üretkenlik / hesap verebilirlik görünümü.

## Veri Kaynağı (Sedna)
- **`AccountingOwner`** = fiş başlığı (her satır = bir fiş). `RecordUser` = fişi **kesen**
  kullanıcı kodu, `RecordDate` = kayıt (sisteme giriş) tarihi, `FicheDate` = muhasebe (fiş)
  tarihi, `ChangeUser` = değiştiren, `ApprovalUser` = onaylayan, `DeleteUser` = silen.
- **`Users`** = kullanıcı kartı (`UserCode` → `UserName` tam ad).
- Sorgu: `COUNT(*)` GROUP BY `RecordUser` + dönem (`CONVERT(varchar(7|10), date, 120)` = YYYY-MM
  veya YYYY-MM-DD). Bağlantı muhasebe DB'si (`settings.sedna_database`, `_stock_connect`).
- `fetch_voucher_summary(start, end, granularity, date_field)` — `sedna_client.py`. `end` EXCLUSIVE;
  `datecol`/`plen` whitelist, `start`/`end` çağıranca doğrulanmış ISO → güvenli gömülü (pymssql %-tuzağı yok).

## API
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/accounting/fis-icmali/status` | login | Sedna etkin mi (`{configured}`) |
| GET | `/accounting/fis-icmali/summary` | accounting.fis_icmali view | Kullanıcı × dönem pivot |
| GET | `/accounting/fis-icmali/vouchers` | accounting.fis_icmali view | **Drill-down:** kullanıcının aralıktaki fişleri (rec_id/no/tarih/tutar/açıklama) |
| GET | `/accounting/fis-icmali/voucher-detail` | accounting.fis_icmali view | **Drill-down:** tek fişin muhasebe satırları (hesap, borç, alacak) |

**`/summary` parametreleri:** `start_date`, `end_date` (YYYY-AA-GG, **dahil**), `granularity`
(`month`\|`day`), `date_field` (`record`=kayıt tarihi varsayılan \| `fiche`=fiş tarihi). Aralık
en fazla **400 gün** (günlük görünümde sütun/sorgu patlamasını önler). Tünel kapalıysa 503.

**Yanıt (pivot):**
```json
{
  "periods": ["2026-01", "2026-02", ...],
  "users": [{"user_code": "MERYEM", "user_name": "MERYEM CENGİZ", "by_period": {"2026-01": 80, ...}, "total": 2257}, ...],
  "period_totals": {"2026-01": 160, ...}, "grand_total": 6956, "user_count": 7,
  "granularity": "month", "date_field": "record", "start_date": "...", "end_date": "..."
}
```
`users` toplama göre azalan sıralı. `_build_pivot()` (router) Sedna satırlarını pivotlar.

## Frontend
- **Filtre barı:** Granularite (Aylık/Günlük) · dönem seçici (yıl dropdown / ay picker) **+ ◀ ▶
  önceki/sonraki butonları** (`shiftPeriod`: aylıkta yıl±1, günlükte ay±1; yıl listesi seçili yılı
  her zaman içerir) · tarih ekseni (Kayıt Tarihi / Fiş Tarihi) · Yenile.
- **Özet kartlar:** Toplam Fiş · Kullanıcı · En Aktif (ad + sayı) · Ø Kullanıcı Başı.
- **Pivot tablo:** satır=kullanıcı (azalan), sütun=dönem, hücre=fiş sayısı (**ısı gölgeleme**:
  koyu = yoğun); yapışkan kullanıcı sütunu + satır/sütun toplamları (tfoot TOPLAM).
- **Drill-down (modal):** hücreye tıkla → o kullanıcının o dönemdeki **fişleri** (tarih/no/tutar/açıklama);
  kullanıcı adı/toplamına tıkla → tüm dönem fişleri. Fişe tıkla → **muhasebe satırları** açılır
  (hesap kodu/adı, borç, alacak + TOPLAM, fiş tarihi + kesen/değiştiren). `/vouchers` + `/voucher-detail`
  endpoint'leri (canlı Sedna; rec_id = `AccountingOwner.RecId`).
- Tasarım sistemi: PageHeader, StatCard, EmptyState, Lucide. Günlük görünümde tablo yatay kayar.

## Tarih Ekseni — Kayıt vs Fiş Tarihi
- **Kayıt tarihi (`record`, varsayılan):** Fişin sisteme **girildiği** an (`RecordDate`) →
  "kim ne zaman çalışmış" (üretkenlik). Geçmişe dönük fiş bugünkü kayıt gününe düşer.
- **Fiş tarihi (`fiche`):** Muhasebe dönemi (`FicheDate`). Aynı fiş farklı güne düşebilir
  (ör. PEKSAN çekleri fiş 31.03 ama kayıt 08.06 = o gün girilmiş).

## Türkçe Kullanıcı Kodu — SQL'de Filtrelenemez (drill-down, KRİTİK)
`AccountingOwner.RecordUser` Türkçe karakterli olabilir (TUĞÇE, Şule, İlker). **SQL `WHERE
RecordUser = 'TUĞÇE'` 0 döner** (param da, literal de): FreeTDS sorgu METNİNDEKİ Ğ/Ş/İ'yi CP1254'e
kodlamaz (Ç/Ö/Ü gibi Latin-1'de olanlar tutar, Ğ/Ş/İ tutmaz; `LIKE 'TU_ÇE'` çalışır ama hatalı eşleşir).
Sonuçlar CP1254 ile DOĞRU decode edilir → `GROUP BY RecordUser` (summary) sorunsuz. Bu yüzden
`fetch_user_vouchers` RecordUser'ı **SQL'de filtrelemez**: aralığı çeker, **Python'da** decode edilmiş
`record_user == user_code` ile filtreler. (Aynı sebeple cari/çek importları da Türkçe değerleri SQL'de
karşılaştırmaz.) TUĞÇE vs TUĞÇEÖZEN tam ayrışır (prefix değil tam eşitlik).

## Tasarım Kararları
- **Canlı sorgu, import yok:** Rapor niteliğinde + Sedna source-of-truth → yerel model/migration/
  sync adımı eklenmedi (avans-Sedna mutabakatı gibi). Her sayfa yüklemesi Sedna'ya gider (~7 bin
  fiş/yıl, GROUP BY aggregate hızlı). Tünel kapalı → 503, uygulama etkilenmez.
- **Tip kırılımı yok:** `AccountingOwner.Type` 2026'da %99.7 tek değer (3) → ayrım anlamsız;
  ana metrik fiş **sayısı**.
- **Salt-okunur:** audit/finance_event/broadcast yok (mutasyon yok).

## Test
`tests/test_fis_icmali.py` (8 test): pivot kurulum + sıralama + toplamlar · izin (403) · 503 ·
geçersiz/aşırı/ters tarih (422) · status. `fetch_voucher_summary` mock'lanır (CI'da tünel yok).
Canlı (7 Haz 2026): 7 kullanıcı · 6.956 fiş/2026 · SERCAN BALCI 2354, MERYEM CENGİZ 2257.
