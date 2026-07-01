# Kalite (Şablonlar + Formlar)

## Genel Bilgi
- **Modül kodu:** `quality` → alt: `quality.templates` (Şablonlar), `quality.forms` (Formlar)
- **Üst modül:** `quality`
- **Frontend rota:** `/dashboard/kalite/sablonlar`, `/dashboard/kalite/formlar`
- **Backend prefix:** `/api/quality`
- **İzin kodu:** `quality.templates` (view/use), `quality.forms` (view/use)

> **Ayrıntılı geliştirici rehberi:** `backend/app/routers/quality/CLAUDE.md` (iş kuralları, onay akışı
> istisnası, executor handler davranışı bu dosyada tutulur). Bu doküman `docs/modules/` şablon özetidir.

## Dosya Haritası
| Katman | Dosya |
|---|---|
| Router (şablon) | `backend/app/routers/quality/templates.py` |
| Router (form) | `backend/app/routers/quality/forms/` (`crud.py`, `fill_submit.py`, `pdf.py`, `_helpers.py`) |
| Zamanlayıcı | `backend/app/routers/quality/scheduler.py` (`cron_generate_forms.py` ile) |
| Model | `quality_template.py` (+ sections/fields/assignees), `quality_form.py` (+ form_values) |
| Servis | `backend/app/services/quality_service.py` (şablon bölüm/alan/atama kaydetme — router + executor ORTAK) |
| Frontend | `src/routes/dashboard/kalite/sablonlar/+page.svelte`, `.../formlar/+page.svelte`, `lib/components/quality/TemplateBuilder.svelte` |

## Veritabanı Şeması (özet)
- `quality_templates` (+ `quality_template_sections`, `quality_template_fields`, `quality_template_assignees`)
- `quality_forms` (+ `quality_form_values`) — durum: `draft` → `submitted` → `approved`/`rejected` (yeniden açılabilir)

## API Endpoint'leri
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET/POST/PATCH/DELETE | `/api/quality/templates/` | view/use | Şablon CRUD |
| POST/DELETE | `/api/quality/templates/{id}/logo` | use | Şablon logosu yükle/sil |
| GET/POST | `/api/quality/forms/` | view/use | Form listele/oluştur |
| GET/DELETE | `/api/quality/forms/{id}` | view/use | Form detay / sil |
| PATCH | `/api/quality/forms/{id}/fill` | use | Form doldur |
| POST | `/api/quality/forms/{id}/submit` | use | Form gönder |
| POST | `/api/quality/forms/{id}/review` | use | Onayla/reddet |
| POST | `/api/quality/forms/{id}/reopen` | use | Yeniden aç |
| GET | `/api/quality/forms/{id}/pdf` | view | Onaylı form PDF |

## Frontend UI Yapısı
Tasarım sistemi: `PageHeader` + filtre barı + liste + `Modal`/`TemplateBuilder`. Referans kanonik sayfa
kuralları için `docs/ui-kurallari.md`.

## Audit Log Entegrasyonu
- `entity_type`: `quality_template`, `quality_form`
- `action`: create, update, delete, download

## Geliştirme Kuralları
- **Onay akışı:** Şablon + form **create/delete** `check_approval`'dan geçer; form **durum geçişleri**
  (fill/submit/review/reopen) bilinçli olarak muaftır (formun kendi iş akışı; `review` zaten onaydır) —
  gerekçe `quality/CLAUDE.md`'de. Executor `_handle_quality_forms` yalnız create/delete işler.
- **Form silme:** yalnız `draft`; **PDF export:** yalnız `approved`.
- **Şablon yapısı:** Formu olan şablonun bölüm/alan yapısı değiştirilemez (orphan value riski).
