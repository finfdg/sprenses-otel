# Sistem — Sunucu İzleme

## Genel Bilgi
- **Modül kodu:** `system.server`
- **Üst modül:** `system`
- **Frontend rota:** `/dashboard/sistem/sunucu`
- **Backend prefix:** `/api/system/server`
- **İzin kodu:** `system.server` — `view` (izleme), `use` (servis yeniden başlatma)

## Dosya Haritası
| Katman | Dosya |
|---|---|
| Router | `backend/app/routers/system_server.py` |
| Frontend | `frontend/src/routes/dashboard/sistem/sunucu/+page.svelte` |
| Test | `backend/tests/test_system_server.py` |

## API Endpoint'leri
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/api/system/server/info` | view | CPU/RAM/disk metrikleri + servis durumları |
| POST | `/api/system/server/services/{service_name}/restart` | use | Whitelist'li servisi yeniden başlat |
| GET | `/api/system/server/services/{service_name}/logs` | view | Servis journald logları (son N satır) |

## Frontend UI Yapısı
- Tasarım sistemi: `PageHeader` + `StatCard` (CPU/RAM/disk) + servis durum listesi.
- **Polling istisnası:** Sistem metrikleri WS ile taşınmaz → 30 sn'lik `setInterval` ile `GET /server/info`
  fetch edilir. Sayfa kapanınca timer durur (`onDestroy`). Bu, CLAUDE.md "Polling yasak" kuralının
  **bilinçli sınırlı istisnasıdır** (başka sayfalarda polling yapılamaz).

## Audit Log Entegrasyonu
- `entity_type`: `server_service` — `action`: restart (servis yeniden başlatma kaydedilir)

## Geliştirme Kuralları
- **Servis whitelist:** Yalnız izin verilen servis adları (`sprenses-api`, `sprenses-frontend`, `nginx`,
  `postgresql` vb.) restart/log alabilir — keyfi servis adı reddedilir (komut enjeksiyonu/kapsam koruması).
- **sudo NOPASSWD:** `systemctl restart/status/logs` için `ec2-user`'a dar kapsamlı NOPASSWD sudoers kuralı
  gerekir; aksi halde restart endpoint'i çalışmaz.
- **Onay akışı istisnası:** Servis restart operasyonel/anlık bir bakım eylemidir; `check_approval`'dan
  geçmez (audit ile izlenir) — bilinçli muafiyet.
