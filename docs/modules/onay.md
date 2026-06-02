# Onay Modülü (Departman Onay İş Akışı)

## Genel Bilgi

| Alan | Değer |
|---|---|
| Modül kodu | `finance.onay` |
| Üst modül | `finance` |
| Frontend rota | `/dashboard/finans/onay` |
| Backend prefix | `/api/finance/onay` |
| İzin kodu | `finance.onay` (view/use) |

## Konsept

Cari hesaplardaki (vendor_transactions) mevcut fatura kayıtlarına departman ataması yapılır.
Bu atama ilgili departman müdürünün onayına düşer. **Ayrı bir fatura tablosu yoktur** —
vendor_transactions tablosundaki kayıtlar doğrudan kullanılır.

## İş Akışı

1. Finans kullanıcısı cariler sayfasında bir alacak kaydına departman atar (`POST /assign/{vtx_id}`)
2. İlgili departman müdürüne bildirim gönderilir
3. Departman müdürü Onay Kutusu sayfasından onaylar veya reddeder
4. Onaylanan kayıtlar bütçeye yansır (`actual_amount` güncellenir)
5. Reddedilen kayıtlara gerekçe yazılır, atamayı yapan kişiye bildirim gönderilir

## Durum Geçişleri (dept_status)

```
NULL (atanmamış) → pending (onay bekliyor)
pending → approved (onaylandı) / rejected (reddedildi)
rejected → NULL (atama kaldırıldı, yeniden atanabilir)
approved → (kalıcı, kaldırılamaz)
```

## Dosya Haritası

### Backend
| Dosya | Açıklama |
|---|---|
| `app/routers/finance/onay.py` | Atama, onay, ret, kaldırma endpoint'leri |
| `app/models/vendor_transaction.py` | dept_* alanları (department_id, dept_status, vb.) |

### Frontend
| Dosya | Açıklama |
|---|---|
| `routes/dashboard/finans/onay/+page.svelte` | Onay kutusu sayfası |
| `routes/dashboard/finans/cariler/+page.svelte` | Departman atama UI (Ata butonu + modal) |

## vendor_transactions Ek Alanları

| Kolon | Tip | Açıklama |
|---|---|---|
| department_id | int (FK) | Atanan departman |
| budget_category_id | int (FK) | Bütçe kategorisi |
| dept_status | varchar(20) | NULL, pending, approved, rejected |
| dept_assigned_by | int (FK) | Atamayı yapan kullanıcı |
| dept_assigned_at | timestamptz | Atama zamanı |
| dept_approved_by | int (FK) | Onaylayan/reddeden müdür |
| dept_approved_at | timestamptz | Onay/ret zamanı |
| dept_rejection_note | text | Red gerekçesi |

## API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| POST | /assign/{vtx_id} | finance.cariler use | Departman ata (onaya gönder) |
| GET | /my-approvals | finance.onay view | Kullanıcının onay bekleyen kayıtları |
| GET | /pending-count | finance.onay view | Sidebar badge sayısı |
| POST | /approve/{vtx_id} | finance.onay use | Onayla (bütçeye yansır) |
| POST | /reject/{vtx_id} | finance.onay use | Reddet (gerekçe zorunlu) |
| POST | /remove/{vtx_id} | finance.cariler use | Atamayı kaldır (pending/rejected) |

## Yetki Kontrolü

- **Atama:** `finance.cariler` use yetkisi (finans personeli)
- **Onay/Ret:** `finance.onay` use yetkisi + departman müdürü kontrolü (manager_id == current_user.id)
- **Kaldırma:** `finance.cariler` use yetkisi, sadece pending veya rejected durumda

## Bütçe Entegrasyonu

Onay verildiğinde, eğer `budget_category_id` atanmışsa:
- `Budget(department_id, category_id, year, month)` kaydının `actual_amount`'ı güncellenir
- Kayıt yoksa otomatik oluşturulur (`planned_amount=0`, `actual_amount=tutar`)

## Bildirimler

| Olay | Alıcı | Tip |
|---|---|---|
| Atama yapıldı | Departman müdürü | `dept_approval_needed` |
| Onaylandı | Atamayı yapan | `dept_approved` |
| Reddedildi | Atamayı yapan | `dept_rejected` |

## Cariler Sayfası Entegrasyonu

- Cari işlemler tablosuna "Departman" sütunu eklendi
- Alacak kayıtları (faturalar) için "Ata" butonu gösterilir
- Departman durumu badge ile gösterilir:
  - Yeşil: Onaylandı ✓
  - Sarı: Onay bekliyor (animasyonlu)
  - Kırmızı: Reddedildi ✕ (kaldırma butonu ile)
- Departman atama modalı: departman seçimi + opsiyonel bütçe kategorisi

## Geliştirme Kuralları

- Sadece `alacak > 0` olan kayıtlara (faturalar) departman atanabilir
- Onaylanmış atama kaldırılamaz
- Red gerekçesi zorunludur
- Aynı kayda farklı departman atamak için önce mevcut atama kaldırılmalı
