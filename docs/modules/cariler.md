# Cariler Modülü

## Genel Bilgi

| Özellik | Değer |
|---|---|
| **Modül Kodu** | `finance.cariler` |
| **Üst Modül** | `finance` (Finans) |
| **Frontend Rota** | `/dashboard/finans/cariler` |
| **Backend Prefix** | `/api/finance/cariler/` |
| **İzin** | `finance.cariler` → `can_view` / `can_use` |

## Dosya Haritası

### Backend
| Dosya | Açıklama |
|---|---|
| `backend/app/models/vendor.py` | `Vendor` SQLAlchemy modeli |
| `backend/app/models/vendor_upload.py` | `VendorUpload` SQLAlchemy modeli |
| `backend/app/models/vendor_transaction.py` | `VendorTransaction` SQLAlchemy modeli |
| `backend/app/schemas/vendor.py` | Pydantic şemaları |
| `backend/app/routers/finance/cariler.py` | API endpoint'leri |
| `backend/app/utils/vendor_parser.py` | Excel ayrıştırma mantığı |

### Frontend
| Dosya | Açıklama |
|---|---|
| `frontend/src/routes/dashboard/finans/cariler/+page.svelte` | Cariler ana sayfa |
| `frontend/src/lib/types/vendor.ts` | TypeScript tipleri |

## Veritabanı Şeması

### vendors
| Kolon | Tip | Açıklama |
|---|---|---|
| id | SERIAL PK | |
| hesap_kodu | VARCHAR(50) UNIQUE | Muhasebe hesap kodu (ör: 320.01.01.A009) |
| hesap_adi | VARCHAR(300) | Cari/firma adı |
| payment_days | INT DEFAULT 90 | Ödeme vade gün sayısı |
| status | VARCHAR(30) DEFAULT 'normal' | Firma durumu: `normal`, `odeme_yasaklisi` |
| created_at | TIMESTAMPTZ | Oluşturulma tarihi |

### vendor_uploads
| Kolon | Tip | Açıklama |
|---|---|---|
| id | SERIAL PK | |
| file_name | VARCHAR(255) | Orijinal dosya adı |
| file_url | VARCHAR(500) | Sunucu dosya yolu |
| total_vendors | INT | Dosyadaki cari sayısı |
| total_transactions | INT | Toplam işlem sayısı |
| new_transactions | INT | Yeni eklenen işlem sayısı |
| skipped_transactions | INT | Mükerrer atlanan işlem sayısı |
| uploaded_by | INT FK(users) | Yükleyen kullanıcı |
| uploaded_at | TIMESTAMPTZ | Yükleme tarihi |

### vendor_transactions
| Kolon | Tip | Açıklama |
|---|---|---|
| id | SERIAL PK | |
| vendor_id | INT FK(vendors) CASCADE | Bağlı cari |
| upload_id | INT FK(vendor_uploads) CASCADE | Bağlı yükleme |
| date | DATE | İşlem tarihi |
| evrak_no | VARCHAR(100) | Evrak/fatura numarası |
| transaction_type | VARCHAR(100) | İşlem tipi (Mal Alış Faturası vb.) |
| fis_no | VARCHAR(50) | Fiş numarası |
| description | TEXT | Açıklama |
| borc | NUMERIC(15,2) | Borç tutarı |
| alacak | NUMERIC(15,2) | Alacak tutarı |
| bakiye | NUMERIC(15,2) | Kalan bakiye |
| tx_hash | VARCHAR(64) | Mükerrer tespit hash'i |
| payment_due_date | DATE | Hesaplanan ödeme tarihi (faturalar için) |
| created_at | TIMESTAMPTZ | Oluşturulma tarihi |

**Unique Constraint:** `(vendor_id, tx_hash)`

## API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| POST | `/cariler/upload` | use | Excel dosya yükleme |
| POST | `/cariler/sedna-import` | use | **Sedna (muhasebe DB) doğrudan içe aktarma** — Excel ile aynı upsert/dedup |
| GET | `/cariler/sedna-status` | view | Sedna içe aktarma etkin mi (`{configured}`) |
| GET | `/cariler/uploads` | view | Yükleme geçmişi |
| DELETE | `/cariler/uploads/{id}` | use | Yükleme sil (CASCADE) |
| GET | `/cariler/vendors` | view | Cari listesi (paginated, arama) |
| GET | `/cariler/vendors/summary` | view | Cari özet bilgileri |
| GET | `/cariler/vendors/{id}` | view | Cari detay + işlemler |
| GET | `/cariler/vendors/{id}/bank-transactions` | view | Cariye ait banka işlemleri |
| PATCH | `/cariler/vendors/{id}/payment-days` | use | Vade günü güncelle (tüm alacaklar yeniden hesaplanır) |
| PATCH | `/cariler/vendors/{id}/status` | use | Firma durumu güncelle (normal / ödeme yasaklısı) |
| GET | `/cariler/payment-schedule` | view | Haftalık ödeme planı (FIFO net borç bazlı) |
| GET | `/cariler/export/vendors` | view | Cari listesi Excel export |
| GET | `/cariler/export/payment-schedule` | view | Ödeme planı Excel export |
| GET | `/cariler/transactions/{vtx_id}/candidate-checks` | view | Eşleşme adayı çekler |
| POST | `/cariler/transactions/{vtx_id}/match-check/{check_id}` | use | Çek ile eşleştir |
| DELETE | `/cariler/transactions/{vtx_id}/unmatch-check` | use | Çek eşleştirmesini kaldır |
| DELETE | `/cariler/transactions/{vtx_id}/unmatch` | use | Banka eşleştirmesini kaldır |
| PATCH | `/cariler/transactions/{vtx_id}/devir` | use | Devir/açılış olarak işaretle |
| POST | `/cariler/transactions/bulk-delete` | use | Toplu işlem silme — body: `{ids: [int]}`, en fazla 5000 |

### Ödeme Talimat Listeleri (`/payment-instructions`)

Cari ödemeleri için toplu talimat hazırlama — carileri seçip listeye ekle, tutarları
düzenle, Excel/PDF olarak dışa aktar. Listeler **kalıcıdır** (`finance.cariler` izniyle).

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/payment-instructions/` | view | Tüm listeler (özet — kalemsiz) |
| GET | `/payment-instructions/{id}` | view | Tek liste detayı (kalemler dahil) |
| POST | `/payment-instructions/` | use | Yeni liste (opsiyonel başlangıç kalemleriyle) |
| PATCH | `/payment-instructions/{id}` | use | Liste başlığı/durum güncelle |
| DELETE | `/payment-instructions/{id}` | use | Listeyi sil (kalemler CASCADE) |
| POST | `/payment-instructions/{id}/items` | use | Cari kalem(ler) ekle (mükerrer vendor atlanır) |
| PATCH | `/payment-instructions/{id}/items/{item_id}` | use | Kalem tutarı/notu güncelle |
| DELETE | `/payment-instructions/{id}/items/{item_id}` | use | Kalemi çıkar |
| GET | `/payment-instructions/{id}/export/excel` | view | Excel dökümü (teal başlık + toplam) |
| GET | `/payment-instructions/{id}/export/pdf` | view | PDF dökümü (reportlab + Vera font) |

**Veritabanı:**
- `payment_instruction_lists` — başlık (ad, açıklama, status=draft/completed, created_by)
- `payment_instruction_items` — kalemler (list_id CASCADE, vendor_id SET NULL, `hesap_kodu`/`hesap_adi` snapshot, `amount`, `balance_snapshot`, `notes`, `sort_order`)
- Migration: `d4e8f1a9c2b6_add_payment_instructions.py`

**İş kuralları:**
- Kalem eklerken tutar **carinin bakiyesinden** otomatik gelir: `bakiye < 0` ise `|bakiye|` (ödeyeceğimiz tutar), pozitifse 0. `balance_snapshot` eklendiği andaki bakiyeyi saklar (referans).
- Tutar **manuel düzenlenebilir** — frontend MoneyInput, blur'da debounce'lu PATCH.
- Aynı `vendor_id` listeye iki kez eklenmez (mükerrer atlanır, `added`/`skipped` raporlanır).
- `hesap_kodu`/`hesap_adi` snapshot tutulur — cari silinse bile kalem korunur (`vendor_id` SET NULL).
- Toplam tutar (`total_amount`) ve kalem sayısı (`item_count`) yanıtlarda kalemlerden hesaplanır (denormalize kolon yok → tutarsızlık riski yok).

**Frontend:**
- **"Ödeme Talimatı"** sekmesi (`lib/components/finance/PaymentInstructions.svelte`) — liste seç/oluştur/sil, cari ara+ekle, MoneyInput ile tutar düzenle, Excel/PDF indir.
- **Cari satırından hızlı ekleme:** Cariler tablosunda bakiye yanında (masaüstü hover'da "+" ikonu, mobilde "Talimat" butonu) → modal: mevcut listeye ekle veya yeni liste oluştur. Tutar carinin bakiyesinden otomatik gelir (`openAddToList`/`confirmAddToList`).

## Sedna (Muhasebe DB) Doğrudan İçe Aktarma (2026-06-06)

Cari hareketler Excel'e gerek kalmadan **doğrudan muhasebe programının (Sedna) SQL Server'ından**
çekilebilir. Excel yükleme aynen korunur — bu **additive** bir kaynaktır.

**Bağlantı (loose coupling):** Sedna ofis LAN'ında (`192.168.2.245`). EC2 oraya **ters SSH
tüneli** üzerinden erişir (`127.0.0.1:11433` → tünel → Ubuntu → SQL Server). Bağlantı **yalnızca
import tetiklenince** kurulur; uygulamanın normal işleyişi tünele bağlı **değildir** (tünel
kapalıysa import 503 verir, gerisi çalışır). `SEDNA_PASSWORD` boşsa özellik kapalı (buton gizli).

**Eşleme (Sedna → vendor_transactions):**
| Sprenses | Sedna |
|---|---|
| hesap_kodu | `AccountingTrans.AccountingCode` (string join) |
| hesap_adi | `Accounting.Remark` |
| date | `AccountingOwner.FicheDate` |
| evrak_no | `AccountingTrans.DocumentNo` |
| transaction_type | `AccDocumentType.DocumentRemark` (DocumentType lookup) |
| fis_no | `AccountingOwner.Voucher` |
| description | `AccountingTrans.Remark1` |
| borç / alacak | `Debit` / `Credit` |
| payment_days (yeni cari) | `Accounting.PayDay` (0 ise varsayılan 90) |
| tx_hash | `compute_vendor_tx_hash(...)` |

- **Filtre:** `AccountingCode LIKE '320%'` (satıcılar — mevcut kapsamla birebir) + `t.Deleted=0
  AND o.Deleted=0`. Kodlama **`charset='CP1254'`** (Türkçe İ/Ş/ğ doğru okunsun).
- **Mükerrer yok:** `tx_hash` Excel ile **aynı fonksiyondan** üretilir → Excel'den veya Sedna'dan
  gelen aynı işlem aynı hash'i alır. Üretimde 2236 hareketin 2077'si mevcut (Excel) ile eşleşip
  atlandı, 159'u yeni eklendi. Aynı upsert + payment_due + finance_events + **removal_candidates**.
- **Backend:** `utils/sedna_client.py` (pymssql, salt-okunur, prefix güvenli/parametresiz →
  `%`-tuzağı yok), `routers/finance/cariler/sedna_import.py` (`POST /sedna-import`, `GET
  /sedna-status`). Config: `config.py` `sedna_*` + `.env SEDNA_PASSWORD`. Onaydan muaf
  (operasyonel/içe-aktarma endpoint'i), audit'li, finance.cariler use.
- **Frontend:** Cariler → "Yükle" sekmesinde **"Sedna'dan İçe Aktar"** kartı (sednaConfigured ise).
  Sonuç + silme adayları Excel ile **aynı modalı** kullanır.
- **Test:** `tests/test_cariler_sedna.py` (fetch mock'lu): oluşturma + payment_due + **re-run dedup**
  (0 yeni) + izin + tünel-kapalı/yapılandırılmamış 503.
- **Güvenlik:** salt-okunur login (`prenses\btadmin` zaten db_datareader; ideali ayrı `dms_user`).
  Şifre yalnız `.env` (600, gitignore). Bağlantı kuran ters-SSH anahtarı EC2'de kısıtlı
  (`permitlisten=127.0.0.1:11433`, kabuk yok).

## Kaynakta Olmayan Kayıtların Tespiti (Removal Candidates)

Cari Excel yüklemesi insert-only çalışır — yüklenen dosyada bulunmayan eski kayıtlar otomatik silinmez. Eğer kullanıcı veri kaynağında (muhasebe programı) bir hareketi sildiyse, sistem ile Excel'in yürüyen bakiyesi uyuşmaz hale gelir.

**Akış:**
1. `POST /cariler/upload` yanıtı artık `removal_candidates: RemovalCandidate[]` alanı döner
2. Diff kapsamı **iki katmanlı** kısıttır:
   - **Vendor scope:** Sadece Excel'deki `hesap_kodu` listesi içindeki cariler
   - **Tarih scope:** Sadece Excel'in `min(date) ↔ max(date)` aralığındaki kayıtlar
3. Bu kapsamda olup Excel'de `(vendor_id, tx_hash)` eşleşmesi olmayan kayıtlar adaydır
4. **Korumalı kayıtlar otomatik atlanır** (manuel iş yapılmış kayıtlar):
   - `match_number IS NOT NULL` → banka/çek ile eşleşmiş
   - `dept_status IN ('assigned', 'approved')` → departmana atanmış / onaylanmış
   - `finance_events.is_matched = TRUE` → karşı tarafla bağlanmış
5. Frontend modal'ı checkbox ile gösterir; kullanıcı seçip `POST /cariler/transactions/bulk-delete` çağırır
6. Bulk-delete endpoint'i de aynı korumaları tekrar kontrol eder (race condition güvencesi) — yetkisiz silme yapmaz, atlanan kayıtlar `skipped_reasons` alanında raporlanır

**Neden manuel onay (otomatik silme değil)?**
Yanlış/eksik Excel yükleme tek bir hareketle kalıcı veri kaybına yol açabilir. Kullanıcının her aday için tek tıkla onaylaması zorunludur.

**Neden vendor + tarih scope (genel scope değil)?**
Kullanıcı tek bir cariyi yüklediğinde başka carilerin geçmiş kayıtlarına dokunulmaz. Excel kapsamı dışındaki dönemlerin (ör. Excel sadece son 3 ay) eski kayıtları korunur.

## Ödeme Hesaplama Mantığı

1. Fatura tipi işlemler tespit edilir (`transaction_type` içinde "Fatura" geçenler)
2. Fatura tarihine **90 gün** eklenir
3. Sonuç Cuma değilse **sonraki Cuma'ya** yuvarlanır
4. Ödeme planı bu Cuma tarihlerine göre haftalık gruplandırılır

## Audit Log Entegrasyonu

- **entity_type:** `vendor_upload`
  - **Eylemler:** `create` (dosya yükleme), `delete` (dosya silme)
  - Yükleme detayında `silme adayı` sayısı varsa `details` alanına eklenir
- **entity_type:** `vendor_transaction`
  - **Eylem:** `delete` (toplu silme — `entity_id=None`, `details` alanında silinen+atlanan sayılar)

## Firma Durumu (Vendor Status)

- **Değerler:** `normal` (varsayılan), `odeme_yasaklisi`
- Sabitler: `app/models/vendor.py` içinde `STATUS_NORMAL`, `STATUS_PAYMENT_BANNED`
- **Ödeme Yasaklısı** firmalar:
  - Ödeme planında (`payment-schedule`) yer almaz — `_get_vendor_net_debts()` bunları filtreler
  - `finance_events` tablosundaki `vendor_payment` kayıtları kaldırılır (`sync_vendor_finance_events`)
  - Nakit akımda görünmez
  - Cari listesinde kırmızı "Yasaklı" badge ile gösterilir, satır arka planı kırmızı
- Durum değişikliği:
  - `PATCH /cariler/vendors/{id}/status` endpoint'i ile yapılır
  - Onay kontrolünden geçer (`check_approval`)
  - Audit log kaydedilir
  - WS broadcast tetiklenir → tüm liste sayfaları anlık güncellenir
  - Durum değiştiğinde ödeme planı cache'i sıfırlanır

## Geliştirme Kuralları

- Mükerrer işlem tespiti `tx_hash` (SHA-256) ile yapılır
- Yükleme silindiğinde ilişkili işlemler CASCADE ile silinir
- İşlemi kalmayan cariler otomatik temizlenir
- Ödeme tarihi sadece alacak tutarı > 0 olan fatura işlemleri için hesaplanır

## Cari Detay — İşlem Sıralaması ve Pagination

- `GET /cariler/vendors/{id}` endpoint'i işlemleri **tarih DESC, id DESC** sırasında döner — en yeni kayıt 1. sayfanın başında görünür
- Varsayılan `page_size = 50`, üst sınır 500
- **Neden DESC?** Kullanıcı bir cariyi açtığında en çok "en son ne oldu?" sorusunu sorar; eski Excel yüklemelerinde 50+ işlem olan firmalarda ASC sıralama 1. sayfada eski kayıtları gösterip yeni kayıtların 2. sayfada kalmasına ve fark edilmemesine yol açıyordu (ör. Bens Pastacılık: 64 işlemden 14'ü 2. sayfada kalıyordu)
- Diğer finans modülleriyle (Nakit Akım, Banka İşlemleri, Çekler) tutarlı

## Cari Detay — Kümülatif Bakiye Hesabı

- `bakiye` alanı **Excel snapshot'ından değil**, PostgreSQL window function ile **sistemde hesaplanır**:
  ```sql
  SUM(borc - alacak) OVER (ORDER BY date ASC, id ASC)
  ```
- Sayfalama DESC sırada uygulansa da kümülatif hesap **tüm geçmiş üzerinden kronolojik** çalışır — sayfa 1'deki en yeni satırın bakiyesi tüm tarihçenin toplamıdır
- DB'deki `vendor_transactions.bakiye` kolonu Excel'den geldiği gibi saklanmaya devam eder (referans/denetim için), ancak API yanıtında **göstermeyiz** — kullanıcıya hep kümülatif değer döner
- **Neden gerekti?** Muhasebe programının Excel'e yazdığı bakiye kendi iç işlem sıralamasına göre yürür (belge no, kayıt zamanı vb.); bu sıra bizim `date + id` sıramızla aynı olmayabilir → arka arkaya iki satırın bakiye farkı tek bir işlemin etkisini doğru yansıtmıyordu. Ör. Bens Pastacılık 24.04.2026 çek 7823811: Excel -414.849,99 saklamış, gerçekte kronolojik -642.300,89 (önceki bakiye -1.212.300,89 + 570.000 borç)
- En yeni satırın kümülatif bakiyesi = cari toplam bakiyesi = `total_borc - total_alacak` (matematiksel tutarlılık garanti)
