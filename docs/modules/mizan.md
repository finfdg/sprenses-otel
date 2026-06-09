# Mizan (Geçici Mizan / Trial Balance)

## Genel Bilgi
- **Modül kodu:** `accounting.mizan` (Muhasebe altı)
- **Frontend rota:** `/dashboard/muhasebe/mizan`
- **Backend prefix:** `/api/accounting/mizan`
- **İzin:** `accounting.mizan` view
- **Kaynak:** Sedna muhasebe DB'si — **canlı** sorgu (yerel saklama/model/migration YOK)

Sedna muhasebe hesaplarının dönem **borç / alacak / bakiye** özetini hesap planı kademeleri
(ana hesap → alt hesap → ... → leaf) bazında gösterir. Ana hesaptan başlanır, satır açılarak
alt hesaplara, oradan hesabın **hareketlerine (defter)** kadar inilir. Çift taraflı kayıt
gereği **toplam borç = toplam alacak** olmalı (denge kontrolü panoda gösterilir).

## Veri Kaynağı (Sedna)
- **`AccountingTrans`** = muhasebe fişi satırları (`AccountingCode` NOKTALI = leaf hesap, `Debit`,
  `Credit`, `AccOwnerId`). **`AccountingOwner`** = fiş başlığı (`FicheDate` = muhasebe tarihi).
  **`Accounting`** = hesap planı (`Code` → `Remark` ad; ana + alt + leaf tüm hesaplar, ~9.5K).
- **Mizan = leaf hesap bazında `SUM(Debit)` / `SUM(Credit)`** (FicheDate aralığı). Leaf satırları
  (~2.2K) bir kez çekilir; **KADEME aggregasyonu** (ana/alt hesap) router'da Python'da yapılır →
  tek mizan fetch tüm kademeleri + drill-down'ı besler.
- `sedna_client.py`: `fetch_mizan(start, end)` (leaf GROUP BY), `fetch_account_names()` (Code→Remark
  haritası, prefix adlarını çözmek için), `fetch_account_transactions(code, start, end, limit)`
  (bir hesabın + alt hesaplarının hareketleri; `code` `[A-Za-z0-9.]` doğrulanmış → güvenli gömülü).
- **60sn TTL cache** (`mizan.py:_cached`): aynı dönemde kademe değiştirme / alt hesap açma Sedna'yı
  tekrar yormaz (mizan ~60sn'de değişmez). Ad haritası da cache'lenir. Tünel kapalıysa 503.

## API
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/accounting/mizan/status` | login | Sedna etkin mi (`{configured}`) |
| GET | `/accounting/mizan/summary` | accounting.mizan view | Kademe bazında mizan + denge |
| GET | `/accounting/mizan/transactions` | accounting.mizan view | **Drill-down:** hesabın hareketleri (defter) + yürüyen bakiye |

**`/summary` parametreleri:** `start_date`, `end_date` (YYYY-AA-GG, **dahil**; aralık ≤ 800 gün),
`level` (kademe: 1=ana hesap, 2=alt hesap, ...; varsayılan 1), `parent` (drill-down: bu hesabın
**doğrudan alt** hesapları → `level` = parent segment sayısı + 1), `search` (kod/ad araması,
**Türkçe-duyarsız**). Yanıt: `rows[{code, name, borc, alacak, borc_bakiye, alacak_bakiye, bakiye,
has_children}]`, `total_borc/total_alacak` (görünen), `grand_total_borc/grand_total_alacak`
(TÜM mizan), `balanced` (|fark| < 0.01), `account_count`, `level`, `parent`, tarihler.

**`/transactions` parametreleri:** `code` (`[A-Za-z0-9.]`, tam leaf ya da prefix → alt hesaplar
dahil), `start_date`, `end_date`. Yanıt: `transactions[{fiche_date, voucher, code, account_name,
remark, debit, credit, balance(yürüyen)}]`, `total_debit/credit`, `balance`, `count`, `truncated`
(ilk 1000). 

## Frontend
- **Filtre barı:** Yıl seçici (◀ ▶ önceki/sonraki) · **Türkçe-duyarsız arama** (kod/ad, 300ms
  debounce + ✕) · Yenile.
- **Özet kartlar:** Toplam Borç · Toplam Alacak · **Denge** (Dengeli/Dengesiz — yeşil/kırmızı +
  fark) · Hesap sayısı.
- **Mizan tablosu (ağaç):** satır = hesap, sütunlar Hesap (kod + ad) · Borç · Alacak · Borç Bakiye
  · Alacak Bakiye. Ana hesabın yanındaki **›** ile alt hesaplar **satır içinde açılır** (lazy-load,
  girinti ile kademe gösterimi); tekrar tıkla → daralır. Her satırda **📖** → hesabın hareketleri
  (defter) modal'ı (tarih/fiş/açıklama/borç/alacak/**yürüyen bakiye**).
- **Arama modu:** arama yazınca leaf düzeyinde (kademe 6) düz sonuç gösterilir (ağaç yerine).
- Tasarım sistemi: PageHeader, StatCard, EmptyState, Modal, Lucide. Tablo yatay kayar (`overflow-x`).

## Kademe (Hesap Planı Hiyerarşisi)
Hesap kodu nokta-segmentlidir: `320.01.01.P033` = `[320, 01, 01, P033]`.
- **Kademe 1** = ana hesap (`320` SATICILAR) — Tek Düzen Hesap Planı 3-haneli ana hesabı.
- **Kademe 2** = `320.01` (İŞLETME SATICILAR), **Kademe 3** = `320.01.01`, **leaf** = `320.01.01.P033`.
- `_prefix(code, level)` ilk `level` segmenti birleştirir; `_aggregate` leaf borç/alacağı bu prefix'te
  toplar. `has_children` = bu prefix altında daha derin leaf var mı (› gösterimi).

## Borç / Alacak Bakiye
- `bakiye = borç − alacak`. **Borç Bakiye** = `bakiye > 0 ? bakiye : 0` (borç kalanı),
  **Alacak Bakiye** = `bakiye < 0 ? −bakiye : 0` (alacak kalanı) — standart mizan iki-kolon gösterimi.
- **Denge:** `grand_total_borc == grand_total_alacak` (çift taraflı kayıt) — TÜM mizan üzerinden,
  parent/search filtresinden bağımsız. Tutmuyorsa panoda kırmızı "Dengesiz + fark" uyarısı.

## Türkçe-Duyarsız Arama (KRİTİK)
Python `str.lower()` **Türkçe casing yapmaz**: 'SATIŞLAR'.lower() noktalı `i` üretir, kullanıcı
'satış' yazınca noktasız `ı` gönderir → eşleşmez (klasik Türkçe-I sorunu). `_search_norm()` küçük
harf + NFKD + birleşik-işaret atımı + `I/ı/İ/i → i` ile **hem büyük/küçük hem aksan duyarsız**
karşılaştırma yapar ('satis' ↔ 'SATIŞLAR', 'peksan' ↔ 'PEKSAN' eşleşir).

## Tasarım Kararları
- **Canlı sorgu, import yok:** Mizan rapor niteliğinde + Sedna source-of-truth → yerel model/
  migration/sync adımı yok (fiş icmali gibi). Her sorgu Sedna'ya gider; 60sn TTL cache drill/kademe
  gezintisini hızlandırır. Tünel kapalı → 503, uygulama etkilenmez.
- **Salt-okunur:** audit/finance_event/broadcast yok (mutasyon yok).
- **Tarih = FicheDate (muhasebe tarihi):** mizan dönem aidiyeti fiş tarihine göredir (RecordDate
  = ne zaman girildi, fiş icmalinde kullanılır; mizanda anlamsız).
- **SQL gömme güvenliği:** `code`/`parent` `[A-Za-z0-9.]{1,40}` doğrulanır (pymssql %-tuzağı için
  LIKE'lı sorgular parametresiz; tarihler ISO-doğrulanmış gömülü).

## Test
`tests/test_mizan.py` (13 test): kademe-1 aggregasyon + denge · parent drill (kademe 2) · dengesiz
bayrağı · Türkçe-duyarsız arama · 503 · geçersiz tarih/kod (422, SQL-gömme koruması) · aralık aşımı ·
hareketler + yürüyen bakiye · izin (403). `fetch_*` mock'lanır (CI'da tünel yok); autouse fixture
TTL cache'i temizler (test izolasyonu).

Canlı (9 Haz 2026, 2026 dönemi): 54 ana hesap · denge ✓ (borç=alacak=3,11 milyar ₺) · 2.232 leaf
hesap · 320.01.01.P033 PEKSAN bakiye −3,03M ₺ (16 hareket).
