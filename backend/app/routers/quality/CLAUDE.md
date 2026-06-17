# Kalite Modülü

## Genel Bakış

Otel teknik servisinde kullanılan günlük/haftalık/aylık kontrol çizelgelerini dijitalleştiren modül. Şablon modülünde form yapıları tasarlanır, Formlar modülünde bu şablonlardan otomatik oluşan form örnekleri doldurulur ve onaylanır.

## Dosya Yapısı (Backend)

```
app/routers/quality/
├── __init__.py            # Alt router'ları birleştirir
├── templates.py           # Şablon CRUD
├── scheduler.py           # Otomatik form üretimi + _get_period_date helper
└── forms/                  # Form CRUD/doldurma/PDF paketi (önceki tek dosya 1016 satıra ulaşmıştı)
    ├── __init__.py         # Alt router'ları birleştirir (prefix yok; her endpoint /forms/... ile başlar)
    ├── crud.py             # Form CRUD — GET/POST /forms/, GET /forms/{id}, DELETE /forms/{id}
    ├── fill_submit.py      # PATCH /forms/{id}/fill, POST /forms/{id}/submit | review | reopen
    ├── pdf.py              # GET /forms/{id}/pdf
    └── _helpers.py         # _build_form_detail, _check_filler, _check_approver, _notify_quality_event, karşılaştırma + sayaç tüketim hesabı
```

## RBAC Modül Hiyerarşisi

```
Kalite (quality)                    ← ana modül, code: quality
├── Şablonlar (quality.templates)   ← form şablonlarını yönet
└── Formlar (quality.forms)         ← oluşan formları doldur/onayla
```

## İsterler

### 1. Konaklayan Kişi Sayısı
- Her formda `is_guest_count: true` olan bir alan bulunur
- Bu alan günlük konaklayan kişi sayısını tutar
- Kişi başı hesaplamalar bu değere bölünerek yapılır

### 2. Kişi Başı Tüketim Hesaplama
- `is_resource: true` işaretli alanlar (elektrik kWh, su m³, LNG kg) için kişi başı tüketim hesaplanır
- Hesaplama: `alan_değeri / konaklayan_kişi_sayısı`
- Hesaplama client-side yapılır, DB'de saklanmaz (denormalizasyon riski)
- FormRenderer.svelte bileşeninde `$derived` ile anlık güncellenir

### 3. %10 Sapma Uyarısı
- Her kişi başı değer, bir önceki günün kişi başı değeriyle karşılaştırılır
- API önceki formun değerlerini `previous_values` olarak döner
- Artış > %10 → kırmızı uyarı rozeti (↑ %X artış)
- Azalış > %10 → yeşil gösterge rozeti (↓ %X azalış)
- ThresholdIndicator.svelte bileşeni ile gösterilir

### 4. Düzeltici Faaliyet
- Evet/Hayır alanlarında "Hayır" seçildiğinde o sorunun altında düzeltici faaliyet metin alanı açılır
- `quality_form_values.corrective_action` alanında saklanır
- Alan bazlı — her soru için ayrı düzeltme kaydı tutulur

### 5. Açıklama Alanı
- Her formun sonunda genel açıklama alanı bulunur
- `quality_forms.notes` alanında saklanır
- Sorularda olmayan veya o gün için gelişen ekstrem olaylar yazılır

## Veritabanı Tabloları

| Tablo | Açıklama |
|-------|----------|
| `quality_templates` | Şablon tanımları (ad, sıklık, aktiflik) |
| `quality_template_sections` | Şablon bölümleri |
| `quality_template_fields` | Bölüm alanları (tip, birim, kaynak/kişi sayısı işaretleri) |
| `quality_template_assignees` | Dolduran/onaylayan atamaları (kullanıcı veya rol) |
| `quality_forms` | Form örnekleri (tarih, durum, dolduran, onaylayan) |
| `quality_form_values` | Doldurulmuş alan değerleri + düzeltici faaliyet |

## API Endpoints

### Şablonlar (`/api/quality/templates/`)
- `GET /` — Şablon listesi (paginated)
- `POST /` — Yeni şablon (bölüm+alan+atama dahil)
- `GET /{id}` — Şablon detay
- `PATCH /{id}` — Güncelle
- `DELETE /{id}` — Sil (form yoksa)

### Formlar (`/api/quality/forms/`)
- `GET /` — Form listesi (paginated, filtrelenebilir: status, template_id, date_from, date_to)
- `GET /{id}` — Form detay + şablon yapısı + önceki değerler
- `POST /` — Manuel form oluştur
- `PATCH /{id}/fill` — Değerleri kaydet (taslak)
- `POST /{id}/submit` — Formu gönder (zorunlu alan kontrolü) — WS bildirim gönderir
- `POST /{id}/review` — Onayla/Reddet — WS bildirim gönderir
- `POST /{id}/reopen` — Reddedileni yeniden aç — WS bildirim gönderir
- `DELETE /{id}` — Taslak formu sil (sadece draft durumunda)
- `GET /{id}/pdf` — Onaylı formu PDF olarak döndür

### Zamanlayıcı (`/api/quality/scheduler/`)
- `POST /generate` — Aktif şablonlara bugünün formlarını oluştur
- `GET /status` — Hangi şablonların bugün formu olduğunu kontrol et

## Form Durumları (Workflow)

```
draft → submitted → approved
                  → rejected → draft (reopen)
```

- **draft**: Taslak — dolduranlar düzenleyebilir
- **submitted**: Gönderildi — onaylayanlar inceleyebilir
- **approved**: Onaylandı — salt okunur
- **rejected**: Reddedildi — dolduranlar yeniden açabilir

## Atama Sistemi

- Dolduran/onaylayan atamaları kullanıcı (`user_id`) veya rol (`role_id`) bazlı yapılabilir
- Atama yoksa herkes o işlemi yapabilir
- CHECK constraint ile user_id XOR role_id zorunlu
- **Endpoint-bazlı yetki kontrolü:** `fill`/`submit` → `_check_filler`, `review` → `_check_approver`,
  `reopen` → **`_check_filler` VEYA `_check_approver`** (P1 güvenlik düzeltmesi, 2026-06-17). Eskiden
  `reopen`'ın tek kapısı `quality.forms:use` idi → atanmamış herhangi bir kullanıcı reddedilmiş formu
  yeniden açıp `reviewed_by/reviewed_at/review_comment` alanlarını silebiliyordu. Artık yalnız formun
  doldurucusu/onaylayanı yeniden açabilir. Test: `test_quality_module.py::TestReopenAuthorization`.

## Frontend Sayfaları

| Sayfa | Yol | Açıklama |
|-------|-----|----------|
| Şablonlar | `/dashboard/kalite/sablonlar` | Şablon CRUD (TemplateBuilder ile) |
| Formlar | `/dashboard/kalite/formlar` | Form listesi (filtrelenebilir) |
| Form Detay | `/dashboard/kalite/formlar/{id}` | Form doldurma/onaylama (FormRenderer ile) |

## Frontend Bileşenleri

| Bileşen | Yol | Açıklama |
|---------|-----|----------|
| FormRenderer | `lib/components/quality/FormRenderer.svelte` | Dinamik form renderlayıcı |
| TemplateBuilder | `lib/components/quality/TemplateBuilder.svelte` | Şablon oluşturucu (bölüm/alan/atama) |
| ThresholdIndicator | `lib/components/quality/ThresholdIndicator.svelte` | %10 sapma göstergesi |

## Sıklık Periyodları

- **daily**: Her gün, period_date = bugün
- **weekly**: Haftanın Pazartesi günü, period_date = Pazartesi tarihi
- **monthly**: Ayın 1'i, period_date = ayın 1'i

## WebSocket Bildirimleri

Form durumu değiştiğinde (submit/approve/reject/reopen) tüm bağlı kullanıcılara WS event gönderilir:
```json
{
  "type": "quality_form_update",
  "event": "submitted|approved|rejected|reopened",
  "form_id": 123,
  "template_name": "Günlük Kontrol",
  "period_date": "2026-03-05",
  "actor_name": "Admin"
}
```

## Kısıtlamalar

- **Şablon bölüm yapısı:** Formu olan şablonların bölüm/alan yapısı değiştirilemez (orphan value riski). Önce formlar silinmeli.
- **Form silme:** Sadece `draft` durumundaki formlar silinebilir.
- **PDF export:** Sadece `approved` durumundaki formlar PDF olarak dışa aktarılabilir.

## Audit Logging

Tüm CRUD işlemleri `audit_logs` tablosuna kaydedilir:
- `entity_type`: `quality_template` veya `quality_form`
- `action`: create, update, delete, download
