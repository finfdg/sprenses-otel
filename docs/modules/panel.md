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
3. **Nakit Akım · T Hesap Cetveli** (`CashFlowTAccount`) — `GET /finance/cash-flow/t-account?period=&offset=`; Giriş/Çıkış açılır grupları, net bant. Mobilde kapalı özet kartı (Bugün Giriş/Çıkış/Net) → dokununca tam görünüm.
4. **Nakit Koruma · Ödeme Erteleme** (`NakitKoruma`) — `GET /finance/cash-flow/runway`; bankadaki nakitten ay-sonuna gün gün projeksiyon (SVG eğri + sıfır çizgisi + en düşük nokta), bakiyenin negatife düştüğü gün uyarısı. Kullanıcı en büyük ödemeleri (top 12; küçükler projeksiyonda ama listede özetlenir) tarih seçiciyle **erteleyerek** eğriyi canlı günceller. **Erteleme yalnız projeksiyon (what-if)** — kalıcı değil (projeksiyon matematiği: `finance.ts::projectRunway`, testli). Tahsilat tarafı yalnız kayıtlı beklenen girişleri içerir (oda geliri hariç → follow-up: hak ediş vadelerini ekle).
5. **Son Hareketler** (son 5 gerçekleşmiş, `end_date=bugün`).
6. **Bekleyen Onay** lacivert kartı → `GET /approval/requests/pending` → Onay Kutusu modalı.

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
