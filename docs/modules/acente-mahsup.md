# Acente Mahsup & Nakit Akım (sales.acente_mahsup)

## 1. Genel Bilgi

| Alan | Değer |
|---|---|
| **Modül kodu** | `sales.acente_mahsup` |
| **Üst modül** | Satış (`sales`) |
| **Frontend rota** | `/dashboard/satis/acente-mahsup` |
| **Backend prefix** | `/api/sales/acente-mahsup` |
| **İzin** | `sales.acente_mahsup` — **yalnız `view`** (salt-okuma pano) |
| **Onay akışı** | **Muaf** (mutasyon yok, GET-only — Yönetim Paneli deseni) |
| **Para birimi** | EUR |

**Amaç:** Rezervasyon → fatura → avans mahsubu → vadeli tahsilat zincirinin acente
bazlı **EUR projeksiyonu**, yıl sonu ciro hedefi senaryosuyla. "Acente Mahsup &
Nakit Akım" 5 sekmeli salt-okuma panodur: Genel Bakış, Alınan Avanslar,
Rezervasyon & Ciro, Satış Faturaları, Nakit Akım.

**Hak Ediş'ten (finance.hakedis) farkı:** Hak Ediş **gerçek** muhasebe faturalarının
(120, TL) yaşlandırmasıdır — bugüne kadar kesilmiş fatura + tahsilat. Bu modül ise
rezervasyon cirosundan üretilen **ileri projeksiyondur** (EUR) ve hedef + kickback
senaryo katmanı ekler. İki modül farklı sorulara cevap verir; birbirinin yerine geçmez.

## 2. Dosya Haritası

**Backend:**
- `app/models/agency_group.py` — `AgencyGroup` modeline `term_days` + `kickback_percent`
  kolonları eklendi (projeksiyon konfigü).
- `app/services/agency_settlement_service.py` — `compute_settlement()` projeksiyon motoru
  (HTTP'siz, salt-okuma). Rezervasyon cirosu + konfig + avans + hedef → 5 sekmelik payload.
- `app/routers/sales/acente_mahsup.py` — GET endpoint (require_permission view, 60sn TTL cache).
- `app/routers/sales/__init__.py` — `/acente-mahsup` prefix ile bağlanır.
- `app/routers/sales/agency_groups.py` — CRUD şeması + PATCH/POST `term_days`/`kickback_percent`
  taşıyacak şekilde genişletildi (konfig düzenleme yüzeyi).
- `alembic/versions/e1a2c3d4f5b6_acente_mahsup_module.py` — kolonlar + modül + Admin RBAC.

**Frontend:**
- `src/routes/dashboard/satis/acente-mahsup/+page.svelte` — 5 sekmeli pano + senaryo
  girdileri + Acente Ayarları modalı.
- `src/lib/config/navigation.ts` — Satış grubuna NavItem (`I.scale` ikon).

**Test:** `backend/tests/test_acente_mahsup.py` (RBAC + shape + projeksiyon matematiği).

## 3. Veri Kaynakları (gerçek veri + senaryo)

| Girdi | Kaynak | Not |
|---|---|---|
| **Ciro (revenue)** | `reservations.eur_total` | Çıkış (checkout) ayında tanınır. Geçmiş ay = gerçekleşen, gelecek ay = mevcut ileri rezervasyon. |
| **Acenteler** | `agency_groups` (PMS üye adları, exact-strip eşleşme) | Grup dışı acenteler → **"Diğer"**. |
| **Vade** | `agency_groups.term_days` (konfig) | Nakit akımda ciro `round(vade/30)` ay ileri kaydırılır. Hak Ediş'in `receivable_terms`'inden **bağımsızdır**. |
| **Kickback** | `agency_groups.kickback_percent` (konfig) | Tutar = grup cirosu × oran. Sistemde daha önce yoktu — bu modülle geldi. |
| **Avanslar** | `receivable_service.compute_receivables` grup satırları (340) | `advance_received_tl`/`advance_consumed_tl` güncel TCMB kuruyla EUR'ya çevrilir. |
| **Yıl sonu hedefi + açılış nakit** | Endpoint query param (frontend'de localStorage) | Senaryo girdisi. Hedef boşsa gerçek ciro (forecast = 0). |

## 4. İş Kuralları (projeksiyon matematiği)

- **Ciro tanıma:** eur_total, rezervasyonun **çıkış ayına** yazılır ("fatura check-out'ta kesilir").
- **Gerçekleşen/İleri:** ay `(year, month) < (today.year, today.month)` ise gerçekleşen.
- **Hedef dağıtımı:** `additional = max(0, target − gerçek_toplam)`. Ek tahmin, İLERİ aylara
  **mevcut ileri rezervasyon ağırlığıyla** dağıtılır (ileri booking'i olmayan acente ek almaz;
  ileri booking yoksa ileri aylara eşit). → Forecast, gelecekte iş getirecek acentelere atfedilir.
- **Avans mahsubu (matris, grup × ay):** GERÇEKLEŞEN aylar gerçek `consumed` ile, İLERİ aylar
  `remaining = received − consumed` ile FIFO (erken ay önce) mahsup edilir. Mahsup edilen kısım
  vadede **tekrar tahsil edilmez** (avans zaten nakde alınmış, açılışa dahil).
- **Nakit akım:** her ay cirosu (mahsup düşülmüş) vadesine göre `m + round(vade/30)` ayına
  tahsilat olarak yazılır. Yıl dışına taşan tahsilat "ertesi yıla devreden". Kickback **Aralık**'ta düşülür.
- **Reconciliation:** `fatura toplamı = net + mahsup`; `funnel.net_collection = invoiced − advance_offset`.

## 5. API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/api/sales/acente-mahsup/` | `sales.acente_mahsup` view | Projeksiyon payload'ı. Query: `year`, `year_target` (EUR, boş=gerçek), `opening_cash` (EUR). 60sn TTL cache. |

Konfig düzenleme (vade/kickback) mevcut acente-grup endpoint'iyle yapılır:
`PATCH /api/sales/agency-groups/{id}` (izin: `sales.hotel_reservation` use) —
`term_days` (0-365) ve `kickback_percent` (0-100) alanları eklendi.

## 6. Frontend UI Yapısı

- **Tasarım kaynağı:** `scratchpad/tasarimlar/Sprenses Tasarımlar/Acente Mahsup & Nakit Akım.dc.html`.
- **Bileşenler:** PageHeader, StatCard (KPI), SegmentedControl (5 sekme), MoneyInput (senaryo/kickback),
  Modal + Button (Acente Ayarları), EmptyState, TableSkeleton. Runway grafiği inline SVG (data-viz).
- **Tema:** lacivert/altın — `teal-700`=lacivert #1b2b45, `brass`=altın #bd9a45 (tema token eşlemesi).
  Tüm tutarlar `tabular-nums`.
- **Senaryo:** Yıl (select) + Yıl Sonu Hedefi + Açılış Nakit (MoneyInput EUR) → değişince debounce ile
  yeniden yüklenir, localStorage'a yazılır.

## 7. Audit Log Entegrasyonu

- Panonun kendisi salt-okuma → audit yok.
- Vade/kickback düzenleme `agency_groups` PATCH üzerinden → `entity_type=agency_group`, action `update`
  (mevcut audit ile kaydedilir).

## 8. Geliştirme Kuralları / Notlar

- **Salt-okuma:** yeni mutasyon endpoint'i eklenmedi → onay/executor handler gerekmez. Vade/kickback
  düzenleme bilinçli olarak mevcut (onaysız) `agency_groups` CRUD'una bağlandı.
- **"Diğer" oranı yüksekse** kullanıcı Acente Ayarları/Otel Rezervasyon gruplamasından acente ekleyerek
  düzeltir — pano grup dışı ciroyu şeffaf gösterir.
- **Avans yaklaşıklığı:** `advance_received` tüm-zamanlı 340 bakiyesidir (tek yıla değil); EUR'ya güncel
  kurla çevrilir. Projeksiyon için kabul edilebilir; kesin muhasebe için Satış Faturaları/Hak Ediş'e bakılır.
