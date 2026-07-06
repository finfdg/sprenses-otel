# Panel (Dashboard)

## Genel Bilgi
- **Modül kodu:** `dashboard`
- **Üst modül:** — (kök menü öğesi)
- **Frontend rota:** `/dashboard`
- **Backend prefix:** — (özel router yok; mevcut özet endpoint'lerinden beslenir)
- **İzin kodu:** `dashboard` — `can_view` (giriş yapan her kullanıcının varsayılan erişimi)

## Dosya Haritası
| Katman | Dosya |
|---|---|
| Frontend | `frontend/src/routes/dashboard/+page.svelte` — karşılama paneli |
| Bileşen | `frontend/src/lib/components/CashFlowTAccount.svelte` — Nakit Akım T hesap cetveli (sekmeli dönem + tarih gezgini + açılır gruplar; mobilde daralt/genişlet özet kartı) |
| Bileşen | `frontend/src/lib/components/NakitKoruma.svelte` — Nakit Koruma / runway projeksiyonu (ödeme erteleme what-if) |
| Layout | `frontend/src/routes/dashboard/+layout.svelte` — sidebar + topbar + route guard |
| Backend | `finance/cash-flow/t-account` (T hesap) + `finance/cash-flow/runway` (Nakit Koruma) dışında özel router **yok**; panel modül-bazlı `*/summary` endpoint'lerini okur |

## Panel Yeniden Tasarımı (2026-07-04, lacivert/altın)
`design_handoff_panel_redesign` paketiyle panel yeniden tasarlandı (tema kararı: **tüm-uygulama
lacivert/altın** — bkz. kök CLAUDE.md UI "TEMA" notu; token yeniden eşlemesiyle uygulandı). Panel bölümleri
yukarıdan aşağı:
1. **Karşılama** + tarih.
2. **KPI ızgarası** (6 kart, 2/3 sütun): Bankalar · Doluluk · Avanslar · Cariler (kırmızı) · Çekler · Krediler — gerçek `*/summary` endpoint'lerinden, EUR.
3. **Nakit Akım** (`CashFlowTAccount`) — `GET /finance/cash-flow/t-account?period=&offset=`; Giriş/Çıkış açılır grupları, net bant. Mobilde kapalı özet kartı (Bugün Giriş/Çıkış/Net) → dokununca tam görünüm. **Kart başlığı sadece "Nakit Akım"** (2026-07-06 — "T Hesap Cetveli" ibaresi kullanıcı isteğiyle kaldırıldı; içeride hâlâ T-hesap düzenidir). Mobilde kapalıyken **"detay için dokun ›" ipucu kartın sağ üst köşesinde**. **Bekleyen/Gerçekleşen segmenti + Tarih görünümü (2026-07-06, tasarım "Nakit Akım T-Hesap.dc.html"):** her sütunda iki-satırlı **segment** (✓ Gerçekleşen | Bekleyen — aynı liste yerinde değişir, varsayılan Bekleyen) + sütun başlığındaki **takvim ikonu** ile kategori↔gün gruplaması geçişi. Gelir yeşil (emerald), gider altın (brass). (Finansman rozeti + Faaliyet/Finansman neti çipleri 2026-07-06 gösterimden kaldırıldı; backend verisi durur.) Kolon toplamları/Net değişmez (detay: `backend/app/routers/finance/CLAUDE.md` T-Hesap bölümü).
   - **Nakit akışı grafiği + Vadesi Geçenler kartın İÇİNDE (2026-07-06, "Nakit Koruma" bileşeni kaldırıldı):** Başlığın hemen altında **`RunwayChart`**, kartın en altında **`OverdueList`**.
     - **`RunwayChart` — DÖNEM-DUYARLI kümülatif nakit akışı eğrisi:** Veri T-Hesap yanıtındaki **`curve`** alanından gelir (`data` prop olarak `CashFlowTAccount`'tan geçer) → **dönem sekmesi (günlük/haftalık/aylık/yıllık) ve ileri/geri gezinmeyle BİRLİKTE değişir** (kullanıcı bulgusu: eski runway sabit "bu ay" idi, grafik değişmiyordu). Eğri dönem başında 0'dan başlar, gün gün net (gelir−gider, EUR) birikir, dönem sonunda `net_eur`'a ulaşır (net bandıyla tutarlı) → SVG polyline + sıfır çizgisi + en düşük nokta + hover ipucu. Backend `t_account.py` `daily_net` biriktirir (TÜM dahil olaylardan, item-cap'ten bağımsız → doğru); T-Hesap'a girmeyen vadesi-geçmiş-ödenmemiş gider eğriye de girmez. Test: `TestTAccountCurve`.
     - **`OverdueList` — vadesi geçmiş ödenmemiş kalemler**, kaynak türüne göre gruplu; `finance.cash_flow` use → tarih seçerek KALICI öteleme (`POST /cash-flow/defer-batch`). Paylaşımlı **`lib/stores/runway.svelte.ts`** deposundan (`GET /finance/cash-flow/runway`) beslenir (ref-count'lu abonelik + WS tazeleme). Vadesi geçenler dönemden bağımsız "şu an geçmiş olanlar"dır → dönem sekmesiyle değişmez (bilinçli).
     - Eski `NakitKoruma`'nın "Ödeme Erteleme" planlama gövdesi (beklenen tahsilatlar / bu ay planlı ödemeler / ay sonu projeksiyon) **tamamen kaldırıldı** (kullanıcı isteği).
4. **Son Hareketler** (son 5 gerçekleşmiş, `end_date=bugün`).
5. **Bekleyen Onay** lacivert kartı → `GET /approval/requests/pending` → Onay Kutusu modalı.

## API Endpoint'leri
Bu modülün kendine ait mutasyon/CRUD endpoint'i **yoktur** (salt-okuma aggregator). Panel, kullanıcının
izinli olduğu modüllerin özet endpoint'lerini (ör. `finance/cash-flow/mobile-dashboard`,
`yonetim/dashboard`) çağırarak kartları doldurur.

## Frontend UI Yapısı
- Tasarım sistemi: `PageHeader` (karşılama) + `StatCard` kartları + hızlı erişim bağlantıları.
- Kartlar kullanıcının **izinli olduğu** modüllere göre koşullu render edilir (`hasPermission`).
- Salt-okuma → `EmptyState`/`ConfirmDialog` beklenmez; yükleme `TableSkeleton`/`FormSkeleton`.

## Audit Log Entegrasyonu
Yok — salt-okuma modülü, mutasyon üretmez.

## Geliştirme Kuralları
- **Salt-okuma:** Panel yeni yazma endpoint'i eklememelidir; veri hep ilgili modülün kaynağından okunur.
- **Onay akışı:** Uygulanamaz (mutasyon endpoint'i yok) — bilinçli muafiyet.
- **Not:** Bu modül, GM/Finans KPI panosu olan **Yönetim Paneli** (`yonetim.panel` → `yonetim-paneli.md`)
  ile **karıştırılmamalıdır**; ikisi ayrı modüldür.
