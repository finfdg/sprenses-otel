# Sistem — Audit Log

## Genel Bilgi
- **Modül kodu:** `system.audit_logs`
- **Üst modül:** `system`
- **Frontend rota:** `/dashboard/sistem/audit-loglar`
- **Backend prefix:** `/api/system/audit-logs`
- **İzin kodu:** `system.audit_logs` — sadece `can_view` (kayıtlar değiştirilemez)

## Dosya Haritası
| Katman | Dosya |
|---|---|
| Router | `backend/app/routers/audit.py` |
| Model | `backend/app/models/audit_log.py` |
| Util | `backend/app/utils/audit.py` — `log_action()` helper |
| Frontend | `frontend/src/routes/dashboard/sistem/audit-loglar/+page.svelte` |

## Veri Modeli
**`audit_logs`** tablosu:
| Kolon | Açıklama |
|---|---|
| id | PK |
| user_id | İşlemi yapan (NULL olabilir — başarısız login) |
| action | login / logout / register / send_verification / verify_email / change_password / reset_password / create / update / delete |
| entity_type | user / role / module / vendor / check / credit / … |
| entity_id | Etkilenen kayıt ID |
| details | JSON — ek bilgi (değişen alanlar, IP, user-agent) |
| ip_address | Kaynak IP |
| created_at | Zaman (Europe/Istanbul) |

## API Endpoint'leri
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/api/system/audit-logs/` | `system.audit_logs:view` | Paginated + filtrelenebilir (action, entity_type, user_id) |

## Kullanım (Backend)
```python
from app.utils.audit import log_action

log_action(db, user_id=current_user.id, action="update",
           entity_type="vendor_transaction", entity_id=vtx.id,
           details={"amount": new_amount}, ip_address=request.client.host)
```

## Geliştirme Kuralları
- **Append-only:** Audit logları asla güncellenmez veya silinmez — sadece INSERT
- **Her CRUD endpoint'i** kendi `log_action()` çağrısını yapmalı
- **Auth event'leri:** `auth.py` içinde login/logout/register otomatik loglanır (başarısız login de log'lanır, user_id=NULL)
- **Performans:** `created_at` üzerinde index var (en yeniden eskiye sıralama)
- **Retention policy:** Şu an sınırsız — gelecekte 1 yıl üstü arşivlenebilir
