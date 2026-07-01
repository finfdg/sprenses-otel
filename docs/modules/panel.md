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
| Layout | `frontend/src/routes/dashboard/+layout.svelte` — sidebar + topbar + route guard |
| Backend | Özel router **yok** — panel, modül-bazlı mevcut `*/summary` / dashboard endpoint'lerini okur |

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
