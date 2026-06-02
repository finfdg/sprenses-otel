# İşlem Etiketleme Modülü

## Genel Bilgi

| Alan | Değer |
|---|---|
| **Modül kodu** | `finance.banks` (bankalar modülünün parçası) |
| **Frontend rota** | `/dashboard/finans/bankalar` → "Etiketleme" sekmesi |
| **Backend prefix** | `/api/finance` |
| **İzin kodu** | `finance.banks` |

Banka işlemlerini kategorilere ayırmaya ve cari kodlara eşleştirmeye yarayan modül.
Nakit akım analizinde masraf kategorisi gruplamalarına temel sağlar.

---

## Dosya Haritası

### Backend
| Dosya | Açıklama |
|---|---|
| `app/routers/finance/transaction_tags.py` | Kategori CRUD, etiketleme, otomatik eşleştirme |
| `app/models/transaction_category.py` | `TransactionCategory` modeli |
| `app/models/bank_transaction.py` | `tag_category_id`, `tag_note`, `match_number` alanları |

### Frontend
| Dosya | Açıklama |
|---|---|
| `src/routes/dashboard/finans/bankalar/+page.svelte` | Etiketleme arayüzü |

---

## Veritabanı Şeması

### `transaction_categories`
| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | integer PK | |
| `name` | varchar(100) | Kategori adı (ör. "Kira", "Maaş") |
| `color` | varchar(7) | HEX renk kodu (#4CAF50) |
| `parent_id` | integer FK → self | Üst kategori (hiyerarşik yapı) |
| `is_active` | boolean | |
| `created_at` | timestamptz | |

### `bank_transactions` — Etiket alanları
| Kolon | Tip | Açıklama |
|---|---|---|
| `tag_category_id` | integer FK → transaction_categories | Atanan kategori |
| `tag_note` | text | Serbest metin notu |
| `tag_source` | varchar(20) | `manual`, `auto`, `vendor` |
| `match_number` | varchar(50) | Harici eşleştirme referans numarası |
| `vendor_id` | integer FK → vendors | Eşleştirilen cari |

---

## API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| `GET` | `/tags/categories` | view | Kategori listesi (hiyerarşik) |
| `POST` | `/tags/categories` | use | Yeni kategori oluştur |
| `PATCH` | `/tags/categories/{id}` | use | Kategori güncelle |
| `DELETE` | `/tags/categories/{id}` | use | Kategori sil |
| `GET` | `/tags/untagged-count` | view | Etiketlenmemiş işlem sayısı |
| `PATCH` | `/tags/transactions/{tx_id}` | use | İşlemi etiketle (tekli) |
| `POST` | `/tags/transactions/bulk` | use | Toplu etiketleme |
| `POST` | `/tags/auto-tag` | use | Kurallara göre otomatik etiketle |
| `GET` | `/tags/payment-methods` | view | Ödeme yöntemi listesi |
| `POST` | `/tags/auto-match-vendors` | use | Açıklamadan otomatik cari eşleştir |

---

## Etiketleme Veri Akışı

```
Banka işlemi yüklenir
       ↓
tag_category_id = NULL (etiketlenmemiş)
       ↓
Manuel / otomatik etiketleme
       ↓
tag_category_id = kategori_id
tag_source = "manual" / "auto" / "vendor"
       ↓
finance_event_svc.sync_tag(db, tx_id, ...)
       ↓
finance_events tablosu güncellenir
(category_id, category_name, category_color, vendor_id, tag_note)
```

---

## finance_events Entegrasyonu

```python
finance_event_svc.sync_tag(db, tx_id, category_id, category_name, category_color, vendor_id, tag_note, tag_source)
```

`finance_events` tablosunda `bank` kayıtlarının kategori/cari bilgileri güncellenir.
Bu sayede nakit akım raporunda kategori bazlı gruplama yapılabilir.

---

## Otomatik Etiketleme Kuralları

`run_auto_tag()` fonksiyonu şu kurallara göre çalışır:

1. **Açıklama eşleşmesi:** İşlem açıklaması bilinen kategorilerle karşılaştırılır
2. **Ödeme yöntemi:** EFT/Havale transferleri vs. POS ödemeleri ayrımı
3. **Cari eşleştirme:** Açıklamadaki cari kodu/adı `vendors` tablosunda aranır

---

## Audit Log Entegrasyonu

| entity_type | Kaydedilen eylem |
|---|---|
| `transaction_tag` | update (tekli/toplu etiketleme) |
| `transaction_category` | create, update, delete |

---

## Geliştirme Kuralları

1. **Hiyerarşi:** Maksimum 2 seviye kategori hiyerarşisi (üst + alt)
2. **Etiket kaynağı:** `tag_source` alanı her zaman set edilmeli (`manual`/`auto`/`vendor`)
3. **Toplu işlem:** 1000+ işlemde toplu etiketleme endpoint'i kullanılmalı
4. **WS broadcast:** Etiketleme sonrası `broadcast_finance_update(background_tasks, "banks", "tag")` tetiklenir
5. **Renk kodu:** Kategoriler için HEX renk kodu zorunludur (frontend badge gösterimi için)
