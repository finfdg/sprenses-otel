# Sistem — Roller

## Genel Bilgi
- **Modül kodu:** `system.roles`
- **Üst modül:** `system`
- **Frontend rota:** `/dashboard/sistem/roller`
- **Backend prefix:** `/api/system/roles`
- **İzin kodu:** `system.roles` — `can_view` / `can_use`

## Dosya Haritası
| Katman | Dosya |
|---|---|
| Router | `backend/app/routers/system_roles.py` |
| Schema | `backend/app/schemas/role.py` |
| Model | `backend/app/models/role.py`, `role_module_permission.py` |
| Response builder | `backend/app/utils/response_builders.py` — `build_role_responses_batch()` |
| Frontend | `frontend/src/routes/dashboard/sistem/roller/+page.svelte` |

## Veri Modeli
- **`roles`**: id, name, description, created_at
- **`role_module_permissions`**: role_id, module_id, can_view, can_use
  - İzin matrisi: her (rol, modül) çifti için tek satır
  - 2 seviye: `can_view` (görme) + `can_use` (ekle/düzenle/sil)

## API Endpoint'leri
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/api/system/roles/` | `system.roles:view` | Paginated, izin matrisi dahil |
| POST | `/api/system/roles/` | `system.roles:use` | Yeni rol (onay akışı) |
| PATCH | `/api/system/roles/{id}` | `system.roles:use` | Güncelle + izin matrisi (onay akışı) |
| DELETE | `/api/system/roles/{id}` | `system.roles:use` | Sil (atanmış kullanıcı varsa 400) |

## Performans
- **Batch izin yükleme:** `build_role_responses_batch()` rol listesini tek sorguda çeker, sonra tüm role_id'ler için izinleri tek sorguda getirir — N+1 yoktur
- **Module ağacı:** Rol detayında tüm modüller ağaç yapısında döner (`modules.tree`)

## Onay Akışı
POST/PATCH/DELETE `check_approval(db, "system.roles", ...)` çağrısından geçer.

## Audit Log
| Action | Entity Type |
|---|---|
| `create` | `role` |
| `update` | `role` (izin matrisi değişikliği dahil) |
| `delete` | `role` |

## Geliştirme Kuralları
- **Admin rol korumalı:** `name="Admin"` olan rol silinemez/düzenlenemez
- **İzin güncellenirken** mevcut satırlar upsert edilir, kaldırılan modüller tabloda silinir
- **Kullanıcılara atanmış rol silme yasağı:** Endpoint 400 döner
- **UI:** İzin matrisi checkbox grid, modül ağacı hiyerarşik render
- **Toplu izin işlemleri (2026-06-02):** Matris başlığında "Tümünü seç" (görme+kullanma), "Sadece görme", "Temizle" butonları → tüm modülleri tek tıkla ayarlar. Ana modül checkbox'ı **grup-toggle**'dır: alt modüllere yayılır (cascade) ve kısmi seçimde `indeterminate` (—) gösterir. Bireysel alt-modül checkbox'ları ince ayar için korunur. `görme→kullanma` eşlemesi (kullanma açılınca görme de açılır; görme kapanınca kullanma kapanır) toplu işlemlerde de geçerlidir.
