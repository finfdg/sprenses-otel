# Günlük Rezervasyon Hareketleri (Günlük Hareketler)

## Genel Bilgi

| Alan | Değer |
|---|---|
| **Modül kodu** | `sales.daily_reservations` |
| **Üst modül** | Satış (`sales`) |
| **Frontend rota** | `/dashboard/satis/gunluk-hareketler` |
| **Backend prefix** | `/api/sales/daily-activity` |
| **İzin kodu** | `sales.daily_reservations` (tüm endpoint'ler `view`) |
| **Veri kaynağı** | **Sedna önbüro (canlı)** — yerel tablo YOK |

Gün gün **gelen yeni rezervasyonlar** ve **iptaller**: adet, geceleme, misafir sayısı, EUR ciro +
rezervasyon bazında drill-down (voucher, acente, ülke, konaklama, tutar).

> **Kişisel veri kararı:** Misafir **isimleri** modülde YER ALMAZ — Sedna sorgusu `Guests`
> kolonunu hiç çekmez, API yanıtında alan yoktur, arayüzde kolon yoktur. Misafir *sayısı*
> (pax) gösterilir. Bu alan ileride eklenecekse bilinçli bir karar olarak buradan kaldırılmalıdır.

## Neden Canlı Sorgu? (mimari karar)

Rezervasyon senkronu (`sedna_import.py`) **iptalleri tablodan siler** — `occupancy_metrics`
aktif-yalnız değişmezliği gereği `reservations` tablosu Sedna'nın aktif rezervasyonlarının
aynasıdır. Dolayısıyla **yerel tabloda iptal tarihçesi yoktur** ve "dün kaç iptal geldi?"
sorusu yerel veriyle cevaplanamaz. Sedna `Reservation` tablosu ise hem `RecordDate`
(kaydın girildiği gün) hem `CancelDate` (iptal günü) tutar → modül Mizan / Fiş İcmali
kalıbıyla **Sedna'dan canlı sorgular** (model/migration/senkron yok, geçmişe dönük tam veri).

- **Gelen** = `RecordDate` o güne düşen TÜM kayıtlar (sonradan iptal edilmiş olsa bile o gün
  gelmiştir; detayda `is_cancelled` rozeti ile işaretlenir).
- **İptal** = `CancelDate` o güne düşen kayıtlar (`is_cancelled` = CancelDate dolu VEYA Status=-1
  — senkronun "aktif değil" tanımıyla birebir).
- Aynı gün gelip iptal edilen kayıt **iki sayıma da girer** (gün neti 0 — doğru davranış).
- Tutarlar `Contrack.Currency` para biriminden EUR'ya çevrilir — rezervasyon senkronuyla
  **aynı katsayılar** (`_currency_to_eur_factors`: son TCMB forex_selling). Kur yoksa yalnız
  EUR tutarlar alınır, TL/USD 0'lanır.
- pax tanımı `summary.py` ile aynı: yetişkin + ücretli çocuk + ücretsiz çocuk (**bebek hariç**).

## Dosya Haritası

| Katman | Dosya |
|---|---|
| Sedna sorgusu | `backend/app/utils/sedna_client.py` → `_RESERVATION_ACTIVITY_QUERY` + `fetch_reservation_activity(start, end_next)` |
| Router | `backend/app/routers/sales/reservations/daily_activity.py` |
| Router kaydı | `backend/app/routers/sales/__init__.py` (`prefix="/daily-activity"`) |
| Migration | `backend/alembic/versions/a7c4e2b9d1f3_add_daily_reservations_module.py` (yalnız modül + Admin izni; tablo yok) |
| Frontend | `frontend/src/routes/dashboard/satis/gunluk-hareketler/+page.svelte` |
| Navigasyon | `frontend/src/lib/config/navigation.ts` (sales grubu, calendarDays ikonu) |
| Test | `backend/tests/test_daily_activity.py` (16 test — fetch mock'lanır) |

## Veritabanı Şeması

**Yerel tablo yok.** Sedna `Reservation` + `Agency` (acente adı) + `Contrack` (para birimi)
join'i; `RecordDate`/`CancelDate` datetime olduğundan yarı açık aralık `[start, end_next)`
ile gün sınırı güvenli kesilir. Tarih literal'leri ISO doğrulamasından geçer (`date.fromisoformat`),
sorgu pymssql %-tuzağına karşı parametresiz `format()` ile kurulur (diğer Sedna sorgularıyla aynı kalıp).

## API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/api/sales/daily-activity/summary?start_date&end_date` | view | Gün gün gelen/iptal özeti (count, nights, pax, eur) + dönem toplamları + `cancel_rate`. Hareketsiz günler 0'larla döner, en yeni gün üstte. Aralık ≤ 92 gün. |
| GET | `/api/sales/daily-activity/details?activity_date&type=new\|cancelled` | view | Drill-down: günün rezervasyon satırları (misafir adı YOK — bkz. kişisel veri kararı). `new`'de `is_cancelled` sonradan-iptal işareti; `cancelled`'da `record_date` ile "girişe X gün kala iptal" hesaplanabilir. |
| GET | `/api/sales/daily-activity/status` | login | `{configured}` — Sedna etkin mi (sayfa gösterimi) |

- Tünel kapalı / `SEDNA_PASSWORD` boş → **503** (frontend EmptyState gösterir).
- **60sn TTL süreç-içi cache** (aralık bazlı): özet + drill-down aynı fetch'i paylaşır; tarih
  gezinmeleri Sedna'yı tekrar yormaz. Mizan kalıbındaki gibi 32 girdi üstünde süresi dolanlar temizlenir.
- **Onay akışı kapsam dışı:** modül salt-okunur (yalnız GET) — `check_approval()` gerekmez.
- **Audit:** GET endpoint'leri audit'lenmez (sistem genel kuralı); mutasyon yok.

## Frontend UI Yapısı

Kanonik liste iskeleti (tasarım sistemi): PageHeader → StatCard×4 → filtre barı → içerik → modal.

- **PageHeader** + actions: Yenile (`Button variant="secondary"` + RefreshCw, `loading`)
- **StatCard'lar:** Gelen Rezervasyon (teal, gece·misafir hint) · İptal (red, ciro + oran hint) ·
  Net Rezervasyon (blue) · Net Ciro Etkisi (emerald, negatifse red)
- **Filtre barı:** hızlı dönem chip'leri (Son 7/14/30 Gün, Bu Ay — teal-700 aktif) + custom
  `start → end` date input (değişince `quick='custom'`); sağda gün + hareket sayısı
- **Desktop tablo:** iki seviyeli başlık — "Gelen Rezervasyonlar" (teal-50 zemin) 4 kolon
  (Adet/Gece/Misafir/Ciro €), "İptaller" (red-50) 4 kolon, "Net" 2 kolon. Adet hücreleri
  tıklanır → drill-down modal. Bugün satırı `bg-teal-50/40` + "Bugün" rozeti. tfoot dönem toplamı.
- **Mobil (`<md`):** tablo → günlük kartlar (yalnız hareketli günler); Gelen/İptal kutuları tıklanır
- **Drill-down modal** (`max-w-4xl`): "Gelenler (n)" / "İptaller (m)" sekme toggle'ı; tablo:
  Voucher · Acente (sonradan-iptal rozeti burada) · Ülke · Oda · Pansiyon · Konaklama
  (giriş→çıkış, gece; iptallerde "Kayıt: … · girişe X gün kala iptal") · Pax · Tutar €
  (EUR-dışı ham tutar alt satırda) — misafir adı kolonu bilinçli olarak yoktur
- **Durumlar:** loading `TableSkeleton` · Sedna yok / hareket yok `EmptyState` · hata `console.error` + toast
- Tutar formatı: tabloda `Intl` EUR 0 hane (`tabular-nums`), modalda 2 hane

## Geliştirme Kuralları

1. **Yerel tabloya yazma ekleme** — modülün varlık nedeni canlı kaynak; senkron/iptal-log tablosu
   eklenecekse önce `occupancy_metrics` aktif-yalnız değişmezliği gözden geçirilmeli.
2. Aralık sınırı 92 gün (`_MAX_RANGE_DAYS`) — Sedna sorgu yükünü sınırlar; genişletmeden önce
   `Reservation` satır hacmi değerlendirilmeli.
3. Yeni alan eklerken `_RESERVATION_ACTIVITY_QUERY` + `_fetch_rows` normalize sözlüğü +
   frontend modal tablosu birlikte güncellenir.
4. EUR çevrimi rezervasyon senkronuyla ortak (`sedna_import._currency_to_eur_factors`) —
   ayrı katsayı mantığı YAZILMAZ (iki modül farklı ciro gösterir).
5. **Misafir adı eklenmez** — `Guests` kolonu kişisel veri olduğundan sorgudan/yanıttan/UI'dan
   bilinçli çıkarıldı (2026-06-10); `test_details_no_guest_names` bunu korur.
5. Polling yok: sayfa yüklemede fetch + elle Yenile. (Veri Sedna'da değiştiği için WS event'i
   da yok; kullanıcı tazeliği Yenile ile alır, backend cache 60sn.)
