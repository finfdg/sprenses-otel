# Sistem — Dokümanlar Modülü

Proje dokümantasyonunu (`.md` dosyaları) panel içinden **görüntüleme ve indirme** modülü. Salt-okunur.

## Genel Bilgi
- **Modül kodu:** `system.docs` (üst modül: `system`)
- **Frontend rota:** `/dashboard/sistem/dokumanlar`
- **Backend prefix:** `/api/system/docs`
- **İzin:** `system.docs` view (salt-okunur; `use` yok). Migration, `system.users`'ı görebilen rollere otomatik view verir.
- **Onay/Audit:** kapsam dışı (salt-okunur, mutasyon yok).

## Kapsam (hangi dosyalar)
Sunucu-tarafı izinli küme (`system_docs.py:_walk`):
- Kök `CLAUDE.md`
- `docs/**/*.md` (modül dokümanları + genel dokümanlar)
- `backend/app/**/CLAUDE.md` ve `frontend/src/**/CLAUDE.md` (geliştirici rehberleri)
- Hariç: `node_modules`, `venv`, `.git`, `build`, `.svelte-kit`, `.claude`, `.pytest_cache`, `__pycache__`, `htmlcov`

Kategoriler: **Genel Dokümanlar** (kök `CLAUDE.md` + `docs/` kökü — ui-kurallari, modulerlik vb.), **Modül Dokümanları** (`docs/modules/`), **Denetim Raporları** (`docs/denetim/` — teknik denetim raporları + soru setleri), **Geliştirici Rehberleri** (router/component `CLAUDE.md`).

## API Endpoint'leri
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/api/system/docs/` | view | Doküman listesi (path, title, **module_code**, category, size, modified) |
| GET | `/api/system/docs/raw?path=` | view | Tek dokümanın ham markdown içeriği (panelde render için) |
| GET | `/api/system/docs/download?path=` | view | Tek dokümanı `.md` olarak indir (attachment) |
| GET | `/api/system/docs/export/word` | view | **Tüm dokümanları tek `.docx`** olarak üret + indir |

## Güvenlik
- **Path traversal imkânsız:** istenen `path`, kullanıcı girdisiyle birleştirilip `resolve` EDİLMEZ; yalnız sunucu-tarafı izinli kümeyle (`_walk`) **birebir eşleşirse** servis edilir. Eşleşmeyen/traversal yolu → 404. (`.env` vb. asla sızmaz.)
- Tüm endpoint'ler `require_permission("system.docs", "view")`.

## Frontend
- **Dosyalar:** `routes/dashboard/sistem/dokumanlar/+page.svelte`.
- Tasarım sistemi: `PageHeader` (+ "Word olarak indir" aksiyonu), `StatCard` (toplam/kategori), `SegmentedControl` (kategori filtresi), `Input` (arama, `icon`+`clearable`), `Modal` (görüntüleyici), `EmptyState`, `TableSkeleton`, `Button`, Lucide ikonlar.
- **Modül kodu rozeti:** Liste, başlığın yanında **modül kodunu** (ör. `finance.cariler`) teal rozetle gösterir. Kod, dokümandaki "Modül kodu/Kodu" satırından çıkarılır (`system_docs.py:_module_code` — ilk 150 satır, büyük/küçük harf duyarsız, ilk backtick'li token). 31/38 modül dokümanında çıkar; çok-modüllü/altyapı dokümanlarında (finans-mimarisi, stok [alt modüller], yonetim-paneli, ssh/websocket) yoktur → rozet gizli. Arama kodu da kapsar.
- **Görüntüleme:** `marked` ile markdown → HTML (`{@html}`); içerik güvenilir kaynak (kendi commit'li repo dokümanları + yalnız `system.docs` yetkili erişir). Render stilleri `.doc-content :global(...)` ile.
- **İndirme:** `api.fetchRaw` (cookie auth) → blob → tarayıcı indirmesi. Tekil `.md` veya birleşik `.docx`.

## Backend Dosyaları
- `app/routers/system_docs.py` — list/raw/download/export-word + `_walk`/`_resolve` (allowlist).
- `app/utils/md_docx.py` — `build_docs_docx(files)`: python-docx ile birleşik Word (kapak + dosya başına H1 + pragmatik markdown render: başlık/paragraf/liste/kod/tablo).
- Migration `e3b7c9d1f2a4` — modül + admin izni. CI/test seed: `tests/ci/02_seed.sql` (id 914).
- Test: `tests/test_system_docs.py` (liste/içerik/indir/Word/traversal-engeli/izin-403).
