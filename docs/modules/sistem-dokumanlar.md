# Sistem — Dokümanlar Modülü

Proje dokümantasyonunu (`.md` dosyaları) panel içinden **görüntüleme ve indirme** modülü. Salt-okunur.

## Genel Bilgi
- **Modül kodu:** `system.docs` (üst modül: `system`)
- **Frontend rota:** `/dashboard/sistem/dokumanlar`
- **Backend prefix:** `/api/system/docs`
- **İzin:** `system.docs` view (salt-okunur; `use` yok). Migration, `system.users`'ı görebilen rollere otomatik view verir.
- **Onay/Audit:** kapsam dışı (salt-okunur, mutasyon yok).

## Kapsam (hangi dosyalar)
**Dokümanlar** (`system_docs.py:_walk`): kök `CLAUDE.md` + `docs/**/*.md` + `backend/app|frontend/src`'teki `CLAUDE.md` rehberleri.
**Kaynak kod** (`_walk_source`): `backend/app/**/*.py` + `frontend/src/**/*.{svelte,ts,js}` (231 backend + 168 frontend ≈ 399 dosya).
- Hariç: `node_modules`, `venv`, `.git`, `build`, `.svelte-kit`, `.claude`, `.pytest_cache`, `__pycache__`, `htmlcov`
- **`.env` ASLA dahil değil** (uzantı kümesinde yok + `app/` altında değil); `_resolve` yalnız allowlist'le birebir eşleşeni servis eder → traversal/sızma imkânsız. Sır yok (config `.env`'den okur).

Kategoriler: **Genel Dokümanlar** (kök `CLAUDE.md` + `docs/` kökü), **Modül Dokümanları** (`docs/modules/`), **Denetim Raporları** (`docs/denetim/`), **Geliştirici Rehberleri** (`CLAUDE.md` rehberleri), **Kaynak — Backend** (`.py`), **Kaynak — Frontend** (`.svelte`/`.ts`/`.js`). Kaynak dosyalarda başlık = dosya adı, modül kodu yok; `export/word` yalnız dokümanları (`_walk`) kapsar — kaynak kod docx'e girmez.

## API Endpoint'leri
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/api/system/docs/` | view | Doküman listesi (path, title, **module_codes[]**, category, size, modified) |
| GET | `/api/system/docs/raw?path=` | view | Tek dokümanın ham markdown içeriği (panelde render için) |
| GET | `/api/system/docs/download?path=` | view | Tek dokümanı `.md` olarak indir (attachment) |
| GET | `/api/system/docs/export/word` | view | **Tüm dokümanları tek `.docx`** olarak üret + indir |

## Güvenlik
- **Path traversal imkânsız:** istenen `path`, kullanıcı girdisiyle birleştirilip `resolve` EDİLMEZ; yalnız sunucu-tarafı izinli kümeyle (`_walk`) **birebir eşleşirse** servis edilir. Eşleşmeyen/traversal yolu → 404. (`.env` vb. asla sızmaz.)
- Tüm endpoint'ler `require_permission("system.docs", "view")`.

## Frontend
- **Dosyalar:** `routes/dashboard/sistem/dokumanlar/+page.svelte`.
- Tasarım sistemi: `PageHeader` (+ "Word olarak indir" aksiyonu), `StatCard` (toplam/kategori), `SegmentedControl` (kategori filtresi), `Input` (arama, `icon`+`clearable`), `Modal` (görüntüleyici), `EmptyState`, `TableSkeleton`, `Button`, Lucide ikonlar.
- **Modül kodu rozetleri (çoklu):** Liste, başlığın yanında dokümanın **tüm modül kodlarını** teal rozetlerle gösterir. `system_docs.py:_module_codes` çıkarır (ilk 150 satır, büyük/küçük duyarsız, max 6): "Modül kodu/Kodu" satırından birincil kod + **kalın etiketli** "Üst modül"/"Alt modüller"/"Modüller" satırlarından o satırdaki tüm backtick kodlar. Böylece **Stok → `stok` + `stok.maliyet`/`stok.urunler`/`stok.hareketler`/`stok.depolar`** (5 rozet), muhasebe-ik → 6, yonetim-paneli → 3. **Yanlış-pozitif koruması:** yalnız `**`-kalın etiket satırı (prose "tüm modüller"/"alt modüllere" değil); örnek liste ("… vb./gibi/örnek") atlanır (sistem-moduller'in `finance.cash_flow` vb. örnekleri rozet olmaz). 33/38 modül dokümanında kod çıkar; tekil kodu olmayan altyapı/mimari dokümanlarında (finans-mimarisi, nakit-akim-is-akisi, push-bildirim, ssh-tunel, websocket) yoktur → rozet gizli. transaction-tags → `finance.banks` (doküman "bankalar modülünün parçası" der; doğru). Arama tüm kodları kapsar.
- **Görüntüleme:** `.md` → `marked` ile HTML. **Kaynak kod (.py/.svelte/.ts/.js)** → **`highlight.js`** (lib/core + python/typescript/javascript/xml/css/json/bash) ile syntax-highlight (`.svelte`/`.html` → `xml` dili). hljs çıktısı HTML-escape'li (XSS güvenli) + içerik güvenilir (kendi repo, admin-only). Token renkleri `.doc-content :global(.hljs-*)` ile (mevcut `pre` kutu stili korunur). Render stilleri `.doc-content :global(...)`.
- **İndirme:** `api.fetchRaw` (cookie auth) → blob → tarayıcı indirmesi. Tekil `.md` veya birleşik `.docx`.

## Backend Dosyaları
- `app/routers/system_docs.py` — list/raw/download/export-word + `_walk`/`_resolve` (allowlist).
- `app/utils/md_docx.py` — `build_docs_docx(files)`: python-docx ile birleşik Word (kapak + dosya başına H1 + pragmatik markdown render: başlık/paragraf/liste/kod/tablo).
- Migration `e3b7c9d1f2a4` — modül + admin izni. CI/test seed: `tests/ci/02_seed.sql` (id 914).
- Test: `tests/test_system_docs.py` (liste/içerik/indir/Word/traversal-engeli/izin-403).
