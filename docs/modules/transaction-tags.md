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

## Virman / Döviz Satım Karşı Bacak Eşleme — Kur-Duyarlı (2026-07-03 düzeltmesi)

`Virman` ve `Döviz Satım` etiketlerinde karşı banka bacağı otomatik bulunup aynı
`match_number` ile etiketlenir (`transaction_tags._find_pair_counterpart`):

- **Virman:** karşı bacak yalnız **AYNI para birimli** hesaplarda aranır — tutar
  birebir, yoksa ±%2 (en yakın tutarlı aday seçilir).
- **Döviz Satım:** bacaklar **FARKLI para birimli** hesaplardadır (ör. EUR çıkış ↔ TL
  giriş) — ham tutarlar karşılaştırılamaz. İki bacağın **TL değeri** (o günün TCMB
  `forex_selling` kuru; TL bacak ×1) **±%5** içinde eşleşmelidir; aynı birimdeki
  hareketler aday bile olamaz. Kur kaydı yoksa **eşleme yapılmaz** (yanlış eşlemektense
  yalnız seçilen işlem etiketlenir).
- **Neden (canlı hata, 02.07.2026):** eski mantık kur gözetmeden aynı tarihte ±%2 ham
  tutar arıyordu → €36.428,78 döviz satışına, gerçek TL bacağı (₺1.939.941,82) yerine
  aynı EUR hesaba aynı gün gelen €36.781,33'lük acente havalesi (TRAVE) eşlendi (#481).
  TL bacağı ham tutarda hiçbir zaman bulunamazdı. Yanlış kayıt elle düzeltildi (#482).
- Test: `test_transaction_tags.py` — `test_virman_pairs_same_currency_only`,
  `test_doviz_satim_pairs_cross_currency_leg` (canlı vakayı birebir üretir),
  `test_doviz_satim_without_rate_does_not_pair`.

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
