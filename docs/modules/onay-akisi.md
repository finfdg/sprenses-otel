# Onay Akışı Modülü (Modül Bazlı, Rol Tabanlı Onay Sistemi)

## Genel Bilgi

| Alan | Değer |
|---|---|
| Modül kodu | `system.approval` |
| Üst modül | `system` |
| Frontend rota | `/dashboard/sistem/onay-akisi` |
| Backend prefix | `/api/system/approval` |
| İzin kodu | `system.approval` (view/use) |

## Konsept

Modül bazlı, rol tabanlı, tek adımlı onay sistemi. Admin bir onay tanımı oluşturur:
1. **Onay adı** — tanımlayıcı isim
2. **Modül seçimi** — hangi modülde onay gerekecek
3. **Talep eden roller** — bu rollerdeki kullanıcıların CRUD işlemleri onaya tabi
4. **Onay veren roller** — bu rollerdeki kullanıcılar onay/red verebilir

Değişiklikler onaylanana kadar bekletilir (payload_json olarak saklanır). POST, PATCH ve DELETE işlemleri onaya tabi olabilir.

### Mevcut Departman Onayı ile İlişki

`finance/onay.py` ile çakışmaz — birlikte çalışır. Departman onayı sadece `vendor_transactions.dept_status` alanlarını kullanır. Bu modül ise `approval_requests` tablosunu kullanır ve herhangi bir modüle uygulanabilir.

## İş Akışı

```
1. Admin → Onay Akışı sayfasında onay tanımı oluşturur
   (Modül seç, talep eden roller seç, onay veren roller seç)
2. Talep eden roldeki kullanıcı → İlgili modülde kayıt oluşturur/günceller/siler
3. Sistem → Eşleşen onay tanımı bulur, değişikliği payload_json'da saklar
4. Onay veren rollerdeki kullanıcılara bildirim gider
5. Onaycı → Onaylar / Reddeder / İade eder
6. Onay → Payload uygulanır (değişiklik gerçekleşir)
7. Red → Talep sahibine bildirim, değişiklik uygulanmaz
8. İade → Talep sahibi düzeltip yeniden gönderebilir
9. İptal → Talep sahibi bekleyen/iade durumda iptal edebilir
```

## Durum Geçişleri

```
pending (bekliyor)
  → approved  (onaylandı, payload uygulanır)
  → rejected  (reddedildi, değişiklik çöpe gider)
  → returned  (düzeltme için iade edildi)
  → cancelled (talep sahibi iptal etti)

returned → pending (yeniden gönderildi)
```

## Veritabanı Şeması

### approval_workflows (Onay tanımları)

| Kolon | Tip | Açıklama |
|---|---|---|
| id | SERIAL PK | |
| name | VARCHAR(200) | Onay adı (unique) |
| module_id | FK modules | Hangi modül |
| entity_type | VARCHAR(50) | Geriye uyumluluk (module.code) |
| description | TEXT | Açıklama |
| is_active | BOOLEAN | Aktif mi? |
| conditions_json | TEXT | JSON koşullar (opsiyonel) |
| created_by | FK users | Oluşturan |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

### approval_workflow_requestor_roles (Talep eden roller)

| Kolon | Tip | Açıklama |
|---|---|---|
| id | SERIAL PK | |
| workflow_id | FK workflows | Onay tanımı |
| role_id | FK roles | Talep eden rol |

### approval_workflow_approver_roles (Onay veren roller)

| Kolon | Tip | Açıklama |
|---|---|---|
| id | SERIAL PK | |
| workflow_id | FK workflows | Onay tanımı |
| role_id | FK roles | Onay veren rol |

### approval_requests (Onay talepleri)

| Kolon | Tip | Açıklama |
|---|---|---|
| id | SERIAL PK | |
| workflow_id | FK workflows | Hangi onay tanımı |
| entity_type | VARCHAR(50) | Modül kodu |
| entity_id | INTEGER | Etkilenen kayıt ID |
| module_code | VARCHAR(50) | Modül kodu (explicit) |
| action_type | VARCHAR(10) | create / update / delete |
| payload_json | TEXT | Bekletilen değişiklik verisi (JSON) |
| status | VARCHAR(20) | pending/approved/rejected/returned/cancelled |
| current_step | SMALLINT | 1 (tek adım) |
| total_steps | SMALLINT | 1 (tek adım) |
| requested_by | FK users | Talep sahibi |
| requested_at | TIMESTAMPTZ | |
| completed_at | TIMESTAMPTZ | |
| completed_by | FK users | |

### approval_request_logs (Geçmiş)

| Kolon | Tip | Açıklama |
|---|---|---|
| id | SERIAL PK | |
| request_id | FK requests | Talep |
| step_number | SMALLINT | 1 |
| action | VARCHAR(20) | submit/approve/reject/return/cancel/resubmit |
| actor_id | FK users | Aksiyonu yapan |
| note | TEXT | Not/gerekçe |
| created_at | TIMESTAMPTZ | |

## API Endpoint'leri

### Onay Tanımları

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | /modules-with-roles | view | Modüller ve can_use rolleri |
| GET | /workflows | view | Tanım listesi (paginated) |
| GET | /workflows/{id} | view | Tanım detayı |
| POST | /workflows | use | Yeni tanım oluştur |
| PATCH | /workflows/{id} | use | Tanım güncelle |
| DELETE | /workflows/{id} | use | Pasifleştir |

### Onay Talepleri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | /requests/pending | view | Bekleyen onaylarım |
| GET | /requests/pending/count | view | Bekleyen sayısı (badge) |
| GET | /requests/my-submissions | view | Gönderdiğim talepler |
| GET | /requests/history | view | Geçmiş |
| GET | /requests/{id} | view | Talep detayı + loglar |
| POST | /requests/{id}/approve | use | Onayla |
| POST | /requests/{id}/reject | use | Reddet (gerekçe zorunlu) |
| POST | /requests/{id}/return | use | İade et (gerekçe zorunlu) |
| POST | /requests/{id}/cancel | view | İptal et (sadece talep sahibi) |
| POST | /requests/{id}/resubmit | view | Yeniden gönder |
| POST | /trigger | view | Manuel onay tetikle |
| GET | /status/{entity_type}/{entity_id} | view | Onay durumu sorgula |

## Frontend Sayfası

3 sekmeli tek sayfa:

1. **Tanımlar**: Onay tanımı CRUD — modül + rol seçimi ile
2. **Bekleyen Onaylar**: Onaycının gelen kutusu (action_type badge'li kart görünümü)
3. **Gönderdiklerim**: Kullanıcının gönderdiği talepler + durum takibi

### Tanım Oluşturma Formu

1. **Onay Adı** — text input
2. **Modül** — dropdown (`/modules-with-roles` endpoint'inden)
3. **Talep Eden Roller** — checkbox list (seçilen modülün can_use rolleri)
4. **Onay Veren Roller** — checkbox list (aynı listeden)
5. **Açıklama** — textarea (opsiyonel)
6. **Koşullar JSON** — textarea (opsiyonel, gelişmiş)

## Dosya Haritası

### Backend
| Dosya | Açıklama |
|---|---|
| `app/models/approval.py` | 6 model (Workflow, Step, RequestorRole, ApproverRole, Request, Log) |
| `app/schemas/approval.py` | Pydantic şemaları (RoleSummary, ModuleWithRoles, Workflow*, Request*) |
| `app/routers/approval/__init__.py` | Router paketi |
| `app/routers/approval/workflows.py` | Tanım CRUD + modules-with-roles |
| `app/routers/approval/requests.py` | Onay talep işlemleri |
| `app/utils/approval_service.py` | Merkezi servis (tetikleme, çözümleme, işlem) |
| `app/utils/approval_check.py` | CRUD endpoint'leri için onay kontrol helper'ı |
| `app/utils/approval_executor.py` | Onaylanan taleplerin payload'larını uygulayan executor |

### Frontend
| Dosya | Açıklama |
|---|---|
| `routes/dashboard/sistem/onay-akisi/+page.svelte` | Onay Akışı sayfası |

## Entegrasyon Kılavuzu

### CRUD Endpoint'lerine Onay Ekleme (Zorunlu)

Tüm modüllerin POST/PATCH/DELETE endpoint'leri `check_approval()` çağrısı içermelidir:

```python
from app.utils.approval_check import check_approval

# ── POST (create) ──
@router.post("/", status_code=201)
def create_entity(data: EntityCreate, db=Depends(get_db), current_user=Depends(...)):
    approval_resp = check_approval(db, "module.code", 0, current_user.id, "create", data.model_dump())
    if approval_resp:
        return approval_resp
    # ... normal oluşturma işlemi

# ── PATCH (update) ──
@router.patch("/{entity_id}")
def update_entity(entity_id: int, data: EntityUpdate, db=Depends(get_db), current_user=Depends(...)):
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(404, "Bulunamadı")
    approval_resp = check_approval(db, "module.code", entity_id, current_user.id, "update", data.model_dump(exclude_unset=True))
    if approval_resp:
        return approval_resp
    # ... normal güncelleme işlemi

# ── DELETE ──
@router.delete("/{entity_id}")
def delete_entity(entity_id: int, db=Depends(get_db), current_user=Depends(...)):
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(404, "Bulunamadı")
    approval_resp = check_approval(db, "module.code", entity_id, current_user.id, "delete", {})
    if approval_resp:
        return approval_resp
    # ... normal silme işlemi
```

### Executor Handler Ekleme

Yeni modül için `app/utils/approval_executor.py`'ye handler eklenmeli:

```python
def _handle_my_module(db, action_type, entity_id, payload, actor_id):
    from app.models.my_model import MyModel

    if action_type == "create":
        obj = MyModel(**payload, created_by=actor_id)
        db.add(obj)
    elif action_type == "update":
        obj = db.query(MyModel).filter(MyModel.id == entity_id).first()
        if obj:
            for k, v in payload.items():
                if hasattr(obj, k):
                    setattr(obj, k, v)
    elif action_type == "delete":
        obj = db.query(MyModel).filter(MyModel.id == entity_id).first()
        if obj:
            db.delete(obj)

# _HANDLERS tablosuna ekle:
_HANDLERS["my.module_code"] = _handle_my_module
```

### Alt Kayıtlar İçin `_target` Pattern'ı

Aynı modül kodunu paylaşan farklı varlıklar (ör: bütçe + departman, kredi + ödeme):

```python
# Endpoint'te:
payload = {"_target": "payment", **data.model_dump(exclude_unset=True)}
approval_resp = check_approval(db, "finance.krediler", payment_id, current_user.id, "update", payload)

# Executor'da:
target = payload.pop("_target", "default")
if target == "payment":
    # Ödeme güncelleme mantığı
else:
    # Ana kayıt mantığı
```

## Entegre Modüller

Onay kontrolü entegre edilmiş modüller:

| Modül Kodu | Endpoint'ler |
|---|---|
| `system.users` | create, update, delete |
| `system.roles` | create, update, delete |
| `system.modules` | create, update, delete |
| `finance.banks` | create_account, update_account, delete_account |
| `finance.krediler` | create/update/delete product + update/delete payment |
| `finance.avanslar` | create, update, delete |
| `finance.butce` | category CRUD + budget upsert/delete + department CRUD |
| `finance.checks` | update_check_status |
| `finance.cariler` | update_vendor_payment_days |
| `accounting.taxes` | definition CRUD + entry update |
| `accounting.recurring` | definition CRUD + entry update |
| `accounting.rent_income` | definition CRUD + entry update |
| `accounting.rent_expense` | definition CRUD + entry update |
| `accounting.dividend` | definition CRUD + entry update |
| `hr.salary` | definition CRUD + entry update |
| `hr.withholding` | definition CRUD + entry update |
| `hr.sgk` | definition CRUD + entry update |
| `quality.templates` | create, update, delete |
| `quality.forms` | create, delete |

## Bildirim Entegrasyonu

Onay sürecinin her aşamasında ilgili kullanıcılara bildirim gönderilir (DB kayıt + WebSocket gerçek zamanlı):

| Olay | Bildirim Alan | Bildirim Türü | Kaynak |
|---|---|---|---|
| Onay talebi oluşturuldu (CRUD) | Onaycılar | `approval_needed` | `approval_check.py` (sync) |
| Onay talebi oluşturuldu (trigger) | Onaycılar | `approval_needed` | `requests.py` (async) |
| Onaylandı (son adım) | Talep sahibi | `approval_approved` | `requests.py` |
| Onaylandı (sonraki adım) | Sonraki onaycılar | `approval_needed` | `requests.py` |
| Reddedildi | Talep sahibi | `approval_rejected` | `requests.py` |
| İade edildi | Talep sahibi | `approval_returned` | `requests.py` |
| İptal edildi (sahip) | Onaycılar | `approval_cancelled` | `requests.py` |
| İptal edildi (onaycı) | Talep sahibi | `approval_cancelled` | `requests.py` |
| Yeniden gönderildi | Onaycılar | `approval_needed` | `requests.py` |

- CRUD endpoint'lerinden `check_approval()` ile oluşturulan talepler `create_and_send_notifications_sync()` kullanır (senkron)
- Diğer aksiyonlar `create_and_send_notifications()` (async) kullanır
- Tüm bildirimler `/dashboard/sistem/onay-akisi` sayfasına yönlendirir
- **Push bildirimleri:** Her iki fonksiyon da otomatik olarak web push gönderir (arka plan thread ile). Kullanıcı offline olsa bile telefona push bildirim gelir.

## Geliştirme Kuralları

- **Tüm yeni modüller onay sistemine tabi olmalıdır** — CRUD endpoint'lerine `check_approval()` zorunlu
- Modül seçimi zorunlu — entity_type artık kullanılmıyor
- Tek adımlı onay — çok adımlı yapı kaldırıldı (geriye uyumluluk korunuyor)
- Talep eden ve onay veren roller, seçilen modülde `can_use` yetkisi olan rollerden seçilir
- Aynı kayıt için aynı anda sadece 1 aktif (pending) talep olabilir
- Red gerekçesi zorunlu, onay notu opsiyonel
- İade edilen talep yeniden gönderildiğinde tekrar pending olur
- Onaylanan veya iptal edilen talepler değiştirilemez
- Değişiklikler onaylanana kadar `payload_json`'da bekletilir
- Onay talebi onaylandığında `execute_approved_payload()` otomatik çağrılır
- Yeni modül için `approval_executor.py`'ye handler eklenmeli

## Okuma Yetkilendirmesi ve Yük Gizliliği (Güvenlik — 2026-06-17)

**Sorun (kapatıldı):** Onay talebi *okuma* endpoint'leri yalnızca `system.approval:view` izniyle korunuyordu; sahiplik/onaycı kontrolü yoktu. Düşük yetkili bir kullanıcı `GET /requests/{id}`'i ID enumerate ederek **herhangi bir talebin `payload_json`'ını** okuyabiliyordu. `system.users` için aktif bir workflow varsa yük **düz-metin şifre** (`UserCreate.password`) içerdiğinden bu kritik bir sızıntıydı (IDOR/BOLA).

**Çözüm — iki katman:**

1. **Hassas-alan redaksiyonu (her zaman):** `_build_request_response()` artık `payload_json`'u `_redact_payload()` üzerinden geçirir. Anahtar adı `password/secret/token/pwd/hash/api_key` içeren tüm alanlar (özyinelemeli) `***` ile maskelenir. **Yürütmeyi etkilemez** — `execute_approved_payload()` yükü doğrudan DB kolonundan okur, redaksiyon yalnızca API yanıtına uygulanır.
2. **Sahip/onaycı kapsamlaması:** Tüm okuma endpoint'leri artık yalnızca **ilgili kullanıcıya** açık (`_user_can_view_request()` = talep sahibi **VEYA** loglarda işlem yapmış **VEYA** mevcut adım onaycısı):
   - `GET /requests/{id}` → ilgili değilse **403**
   - `GET /status/{entity_type}/{entity_id}` → ilgili değilse `status` döner ama `request` (yük) **null**
   - `GET /requests/history` → SQL-tarafı filtre ile yalnız sahip/işlem-yapan talepler (ölçeklenebilir, fetch-all yok; `ix_arl_actor` indeksli `actor_id` alt-sorgusu)
   - `/requests/pending` ve `/requests/my-submissions` zaten kapsamlıydı (değişmedi)

**Bilinçli tasarım kararı:** `history` artık **organizasyon-geneli denetim görünümü değil**, kişiye özel ("ilgili olduğum talepler"). Bu, mevcut `pending`/`my-submissions` kapsamlama desenine hizalıdır. İleride admin-geneli denetim görünümü istenirse ayrı bir yetki (ör. `system.approval` `can_use` veya özel "tümünü gör" bayrağı) ile additive olarak eklenmelidir — varsayılan güvenli kapsam korunmalı.

**Testler:** `tests/test_approval_system.py::TestApprovalReadAuthorization` (5 test) — yabancının detay 403'ü, geçmiş dışlaması, status yük gizliliği, kullanıcı-oluşturma şifre redaksiyonu (uçtan uca) ve `_redact_payload` birim testi. Regresyon: sahip+onaycı erişimi korunur.

**Not (altyapı doğrulaması):** Backend `--host 127.0.0.1` ile bağlıdır (port 8001 yalnız localhost dinler) → `X-Real-IP` rate-limit atlatma yüzeyi OS seviyesinde kapalı; backend portuna dışarıdan doğrudan erişilemez.
