# Sistem — Modüller

## Genel Bilgi
- **Modül kodu:** `system.modules`
- **Üst modül:** `system`
- **Frontend rota:** `/dashboard/sistem/moduller`
- **Backend prefix:** `/api/system/modules`
- **İzin kodu:** `system.modules` — `can_view` / `can_use`

## Dosya Haritası
| Katman | Dosya |
|---|---|
| Router | `backend/app/routers/system_modules.py` |
| Schema | `backend/app/schemas/module.py` |
| Model | `backend/app/models/module.py` |
| Frontend | `frontend/src/routes/dashboard/sistem/moduller/+page.svelte` |

## Veri Modeli
- **`modules`**: id, code (unique), name, parent_id (self-FK, hiyerarşi), icon, sort_order, is_active
- **Kök modüller:** `panel`, `messaging`, `finance`, `accounting`, `hr`, `quality`, `system`
- **Alt modüller:** `finance.cash_flow`, `finance.banks`, `accounting.taxes` vb.

## API Endpoint'leri
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/api/system/modules/` | `system.modules:view` | Paginated düz liste |
| GET | `/api/system/modules/tree` | `system.modules:view` | Hiyerarşik ağaç |
| POST | `/api/system/modules/` | `system.modules:use` | Yeni modül (onay akışı) |
| PATCH | `/api/system/modules/{id}` | `system.modules:use` | Güncelle (onay akışı) |
| DELETE | `/api/system/modules/{id}` | `system.modules:use` | Sil (alt modül/izin varsa 400) |

## Geliştirme Kuralları
- **`code` alanı değiştirilmemeli** — kod bazlı izin kontrolü yapıldığı için değişirse tüm izin matrisi bozulur
- **Ağaç yapısı:** `parent_id` self-FK, döngü oluşturulamaz (validasyonla)
- **Silme:** Alt modüller varsa cascade delete yok, 400 döner
- **`sort_order`:** UI'da menü sırası için kullanılır
- **Yeni modül ekleme:** Mutlaka `backend/app/routers/finance/CLAUDE.md` gibi router CLAUDE.md + `docs/modules/*.md` dosyası oluşturulmalı, ana `CLAUDE.md` API endpoint listesine eklenmeli

## Onay Akışı
POST/PATCH/DELETE `check_approval(db, "system.modules", ...)` ile geçer.

## Audit Log
| Action | Entity Type |
|---|---|
| `create` | `module` |
| `update` | `module` |
| `delete` | `module` |
