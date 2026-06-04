# Modülerlik İyileştirmeleri (2026-06-04)

Tasarımcı/mimari denetiminde tespit edilen zayıf yönlerin giderilmesi. Bu doküman
**ne yapıldı, neden, nasıl kullanılır** sorularını yanıtlar. Kapsam: #1 sihirli
string'ler, #2 route guard, #4 veri-tabanlı sidebar, #3 jenerik ListPage.

> İlgili bağlam: kök `CLAUDE.md` ("Kod Kalitesi" + "UI Tasarım Kuralları" bölümleri).
> Atlanan madde (#5 response_builders DTO): bu kod tabanı için fazla mühendislik
> olarak değerlendirildi, bilinçli olarak yapılmadı.

---

## #1 — Sihirli String'ler → Merkezi Sabitler

**Sorun:** WS event tipleri, broadcast modül adları ve `source_type` değerleri kod
boyunca düz string olarak dağılmıştı. Bir typo (ör. frontend'in dinlemediği bir event
tipi yayınlamak, sorguda eşleşmeyen bir `source_type`) sessizce kırılıyordu.

**Çözüm — tek doğruluk kaynağı:**

| Katman | Dosya | İçerik |
|---|---|---|
| Backend | [`app/constants.py`](../backend/app/constants.py) | `WSEvent`, `BroadcastModule`, `SourceType` |
| Frontend | [`src/lib/constants/realtime.ts`](../frontend/src/lib/constants/realtime.ts) | `WS_EVENT`, `BROADCAST_MODULE`, `WsEventType` union |

**Önemli ilkeler:**
- **Tek kaynak, çift değil:** Finans hareketi `source_type`'ları zaten
  `models/finance_event.py` (`SOURCE_BANK` vb.) içinde tanımlıydı; `constants.py`
  bunları **re-export** eder, yeniden tanımlamaz. Yalnızca evi olmayan değerler
  (scheduled `source_type`, WS event, broadcast modül) burada yeni tanımlandı.
- **DB-saklı değerler değiştirilemez:** `source_type` string'leri
  `finance_events`/`scheduled_definitions` tablolarında saklanır. Sabitler yalnızca
  literal yerine **isimli referans** sağlar; değer aynı kalır. Yeni değer = migration.
- **Diller-arası senkron elle:** Python ↔ TS arası otomatik senkron yoktur. Bir WS
  event tipi/broadcast modül adı değişirse `constants.py` **ve** `realtime.ts` birlikte
  güncellenir (iki dosyanın başındaki uyarı notları bunu hatırlatır).
- **TS tip güvenliği:** `onWsEvent(type: WsEventType, ...)` ve `emitLocal` union ile
  tiplenmiştir → kataloğda olmayan bir event adı **derleme hatası** verir. Çağrı
  noktaları string literal kullanmaya devam edebilir (union tipi typo'yu yakalar).

**Yeni event/modül/source eklerken:** önce ilgili sabit dosyasına ekle, sonra kullan.

---

## #2 — Frontend Route Guard

**Sorun:** Giriş yapmış ama bir modüle `view` izni olmayan kullanıcı, o modülün
sayfasına URL ile gidince sayfa mount oluyor ve veri çekmeye çalışıyordu (backend
403'lüyor ama frontend yine de deniyordu).

**Çözüm:** [`dashboard/+layout.svelte`](../frontend/src/routes/dashboard/+layout.svelte)
içinde reaktif `$effect` guard'ı. Mevcut rotanın gerektirdiği modül izni
[`lib/config/navigation.ts`](../frontend/src/lib/config/navigation.ts) →
`requiredModuleForPath(pathname)` ile bulunur; `hasPermission(code, 'view')` yoksa
toast + panele yönlendirme.

**Tasarım notları:**
- **Asıl kapı backend'dir.** Her endpoint `require_permission` ile korunur; bu guard
  **derinlemesine savunma + temiz UX**'tir, tek başına güvenlik sınırı değildir.
- **Tek route→modül haritası:** `requiredModuleForPath` aynı `navigation.ts` konfigini
  kullanır (sidebar ile ortak). En uzun eşleşen href kazanır (iç içe rotalar:
  `bankalar/talimatlar`, `formlar/[id]`).
- **Yönlendirme döngüsü yok:** Hedef `/dashboard` (Panel) izin gerektirmez.
- **İzin değişimine duyarlı:** `authState.user` güncellenince (ör. `permission_changed`
  WS event'i `refreshAuth` tetikler) effect yeniden çalışır → anlık geri alınan izinde
  kullanıcı sayfadan çıkarılır.

---

## #4 — Veri-Tabanlı Sidebar

**Sorun:** [`Sidebar.svelte`](../frontend/src/lib/components/Sidebar.svelte) 781 satırdı;
~40 link bloğu (href + izin kodu + etiket + ikon) elle, tekrar tekrar yazılmıştı. Yeni
modül = 15+ satır kopyala-yapıştır + ayrı route guard.

**Çözüm:** Menü yapısı tek konfigte: [`lib/config/navigation.ts`](../frontend/src/lib/config/navigation.ts)
→ `NAV_GROUPS` (gruplar → `{code, label, href, icon}`). Sidebar bu konfigi `{#each}`
ile render eder (~330 satıra indi). Aynı konfig route guard'ı (#2) besler.

**Korunan davranış:** Mesajlaşma okunmamış badge'i + WS mantığı, collapse/expand,
otomatik grup açılma, aktif vurgu, mobil davranış, ikonlar (Heroicons path'leri konfigte).

**Bonus düzeltme:** Eski grup-görünürlük kontrolü bazı alt sayfaların iznini atlıyordu
(ör. yalnızca `finance.krediler` ya da `system.server` izni olan kullanıcı grubu
göremiyordu). Yeni `groupVisible()` "grubun **herhangi** bir öğesine izin" mantığı bu
gizli hatayı giderir.

**Yeni modül/sayfa eklerken:** `NAV_GROUPS`'a ilgili gruba bir `NavItem` ekle —
sidebar linki **ve** route koruması otomatik gelir. (Alt rotalı sayfa: `prefixActive: true`.)

---

## #3 — Jenerik ListPage Bileşeni (PoC)

**Sorun:** Bespoke liste sayfaları aynı iskeleti (başlık, filtre barı kartı,
loading/empty durumları, pagination) tekrar tekrar elle yazıyordu. Bazıları
`PageHeader` bile kullanmıyordu (denetim sapması).

**Çözüm:** [`lib/components/ListPage.svelte`](../frontend/src/lib/components/ListPage.svelte)
— kanonik iskeleti (PageHeader → Stat kartları → Filtre barı → İçerik[loading/empty/
children] → Pagination) tek yerde toplar. Sayfa yalnızca kendine özel içeriği (tablo,
modallar) snippet olarak verir.

**PoC:** [`sistem/audit-loglar`](../frontend/src/routes/dashboard/sistem/audit-loglar/+page.svelte)
ListPage'e taşındı — bespoke başlık + filtre kartı + pagination kaldırıldı, davranış
birebir korundu, ayrıca eksik olan `PageHeader` kazandırıldı.

**API özeti:**
```
<ListPage title description {loading} isEmpty emptyIcon emptyTitle
          page pages total pageSize onPageChange
          search? onSearch?>      <!-- search+onSearch verilirse debounce'lu arama kutusu -->
  {#snippet actions()}...{/snippet}   {#snippet stats()}...{/snippet}
  {#snippet filters()}...{/snippet}
  ...children (tablo/liste)...
</ListPage>
```

**Taşınan sayfalar (2026-06-04):** Gerçekten bespoke iskeleti olan (ham `<h1>`, elle
yazılmış filtre barı / loading / pagination) **4 sayfa** ListPage'e taşındı:
`sistem/audit-loglar`, `sistem/hata-loglar`, `satis/oda-tipleri`, `finans/onay`.
Bu taşımalarda ListPage'e şu yeniden-kullanılabilir prop'lar eklendi: yerleşik
debounce'lu arama, `emptyCtaText`/`onEmptyCta` (boş durumda CTA), `card` (kart-listesi
sayfaları için beyaz sarmalayıcıyı atlar), `maxWidth` (sayfa genişliği).

**Bilinçli taşınMAYAN sayfalar — gerekçe:** `finans/avanslar`, `finans/cekler`,
`sistem/roller`, `sistem/kullanicilar`, `kalite/sablonlar` **zaten kanonik**
(PageHeader + StatCard/EmptyState/Pagination/Modal vb. tasarım sistemi bileşenlerini
doğru kullanıyorlar). Bespoke-iskelet sorunları yok, dolayısıyla ListPage onlara değer
katmaz — hatta `avanslar`'ı taşımak gelişmiş `Pagination` bileşenini ListPage'in basit
Önceki/Sonraki'sine **düşürürdü** (regresyon). `cekler` ayrıca aylık-akordeon + yükleme
alanı yapısıyla ListPage'in düz-tablo modeline uymaz (nakit-akım akordeonu gibi bilinçli
istisna). `cariler`/`krediler`/`bankalar`/`butce`/`onay-akisi` çok karmaşık (sekme,
ızgara, 1000+ satır) — taşınmadı.

**İlke:** ListPage yalnızca **bespoke iskeleti olan** sayfalara uygulanır. Zaten
PageHeader + tasarım sistemi kullanan sayfalar olduğu gibi bırakılır (zorlamak
risk-without-reward). Yeni liste sayfaları doğrudan ListPage ile kurulmalıdır.

---

## Doğrulama

- Backend: `python -c "import app.main"` + `pytest` (sabit değerleri korundu, import temiz).
- Frontend: `svelte-check` **0 hata**, `vitest` **274 test geçti**, `npm run build` başarılı.
- Davranış değişmedi (sabitler aynı değer; sidebar/guard mevcut izin matrisine sadık).
