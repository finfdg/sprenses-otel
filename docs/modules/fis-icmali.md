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
- **Filtre barı:** Granularite (Aylık/Günlük) · dönem seçici (yıl dropdown / ay picker) ·
  tarih ekseni (Kayıt Tarihi / Fiş Tarihi) · Yenile.
- **Özet kartlar:** Toplam Fiş · Kullanıcı · En Aktif (ad + sayı) · Ø Kullanıcı Başı.
- **Pivot tablo:** satır=kullanıcı (azalan), sütun=dönem, hücre=fiş sayısı (**ısı gölgeleme**:
  koyu = yoğun); yapışkan kullanıcı sütunu + satır/sütun toplamları (tfoot TOPLAM).
- Tasarım sistemi: PageHeader, StatCard, EmptyState, Lucide. Günlük görünümde tablo yatay kayar.

## Tarih Ekseni — Kayıt vs Fiş Tarihi
- **Kayıt tarihi (`record`, varsayılan):** Fişin sisteme **girildiği** an (`RecordDate`) →
  "kim ne zaman çalışmış" (üretkenlik). Geçmişe dönük fiş bugünkü kayıt gününe düşer.
- **Fiş tarihi (`fiche`):** Muhasebe dönemi (`FicheDate`). Aynı fiş farklı güne düşebilir
  (ör. PEKSAN çekleri fiş 31.03 ama kayıt 08.06 = o gün girilmiş).

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
