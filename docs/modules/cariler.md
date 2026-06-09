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
| GET | `/payment-instructions/{id}/export/excel` | view | Excel dökümü (okunur liste, teal başlık + toplam) |
| GET | `/payment-instructions/{id}/export/pdf` | view | PDF dökümü (reportlab + Vera font) |
| GET | `/payment-instructions/{id}/export/ykb-excel?debtor_account=` | view | **Yapı Kredi toplu ödeme** Excel'i (banka portalına yüklenir) |

### Banka-Özel Toplu Ödeme Excel'i — Yapı Kredi (2026-06-09)

Bankaların toplu ödeme yükleme şablonu okunur listeden **farklıdır** (sabit kolon sırası, başlık/toplam
satırı yok, IBAN boşluksuz, tutar düz ondalık). Yapı Kredi için (`export_ykb_excel`, `_YKB_HEADERS`):
- **Sayfa adı `ykb excel`** · 1. satır = bankanın 11 başlığı **birebir** (metinler dahil; "ALICI SUBE
  KODU" Ş'siz aynen) · 2. satırdan veri (başlık/toplam satırı yok).
- **Kolonlar:** A İŞLEM TARİHİ (bugün, DD.MM.YYYY) · B BORÇLU HESAP (`debtor_account` param = ödenen YKB
  hesap no) · C/D boş (IBAN varsa banka/şube kodu gereksiz) · E ALICI HESAP/IBAN (**boşluksuz**, `_norm_iban`)
  · F ALICI ADI · G TUTAR (**`0.00` düz ondalık, binlik ayraç yok**) · H DÖVİZ=TL · I AÇIKLAMA (kalem notu
  veya "Cari ödeme") · J VKN/TCKN + K ÖDEME TÜRÜ boş (cari VKN saklanmıyor; opsiyonel).
- **Frontend:** Ödeme Talimatı'nda **"Excel (Yapı Kredi)"** butonu → BORÇLU HESAP soran modal (localStorage'da
  hatırlanır) → indirir. Mevcut okunur Excel + PDF korunur.
- **Genişletme:** Başka banka = yeni `_XXX_HEADERS` + `export_xxx_excel` + frontend buton. Her bankanın
  şablonu paylaşılınca eklenir. Test: `tests/test_payment_instructions.py::test_ykb_export_format`.

**Veritabanı:**
- `payment_instruction_lists` — başlık (ad, açıklama, status=draft/completed, created_by)
- `payment_instruction_items` — kalemler (list_id CASCADE, vendor_id SET NULL, `hesap_kodu`/`hesap_adi` snapshot, `amount`, `balance_snapshot`, `notes`, `sort_order`, **`bank_name`/`iban`** seçili banka snapshot'ı)

### Cari Banka / IBAN (`vendor_bank_accounts`) — Ödeme Talimatı için (2026-06-06)

IBAN'lar büyük ölçüde **Sedna'nın `dbo.Bank` tablosundan otomatik çekilir** (aşağıdaki içe aktarım);
elle ekleme/düzenleme Sedna'da olmayan cariler / düzeltmeler içindir.
Bir cari → **0..N** banka hesabı (`bank_name`, `iban`, `account_holder`, `is_default`, `sort_order`).

> **Not (2026-06-06 düzeltme):** Önceki tasarım "Sedna'da cari IBAN'ı yok" varsayımına dayanıyordu —
> bu yanlıştı. `Accounting.BankIbanNo` boş olsa da asıl kaynak **`dbo.Bank`** (cari koduna bağlı,
> firma başına çok IBAN). Canlı: 320'li **763 firma / 821 IBAN**.

**Sedna IBAN içe aktarımı — `POST /cariler/sedna-import-ibans`** (finance.cariler use, onaydan muaf, audit'li):
- Kaynak: `dbo.Bank` JOIN `dbo.Accounting` (`AccountingCode` virgüllü → `Code` noktalı, `REPLACE(',','.')`); filtre 320 + IBAN dolu.
- **Yalnız MEVCUT carilere** işler (önce hareket import'u); `dbo.Bank`'ta IBAN'ı olup bizde hareketi olmayan firmalar atlanır (`skipped_no_vendor`).
- Dedup (cari + normalize IBAN); caride hiç hesap yoksa **ilk IBAN varsayılan**; mevcut IBAN'ın **banka adı boşsa** Sedna'dan doldurulur (varsayılan/elle eklenenler **korunur**) — idempotent.
- Yanıt: `{total_fetched, vendors_matched, new_ibans, updated, skipped_existing, skipped_no_vendor}`. İlk canlı: 821 çekildi → 221 cari → 248 yeni IBAN.
- **Frontend:** Cariler → "Dosya Yükle" sekmesindeki Sedna kutusunda **"IBAN Çek"** butonu.

- **CRUD (elle):** `GET/POST/PATCH/DELETE /cariler/vendors/{id}/bank-accounts[/{ba_id}]` (finance.cariler use, audit'li, onaydan muaf — master veri).
  IBAN **normalize** (büyük harf, boşluksuz), **mükerrer 409**, **ilk hesap otomatik varsayılan**, varsayılan değiştirme, **varsayılan silinince devir**.
- **Frontend:** Cari detayında "Banka / IBAN" bölümü (listele + ekle + varsayılan ★ + sil).
- **Ödeme talimatı entegrasyonu:** Cari kalem eklenince **varsayılan banka/IBAN otomatik** gelir; kalemdeki **"Banka / IBAN" sütunundan** carinin IBAN'ları arasında seçim yapılabilir (`PATCH .../items/{id}` `bank_name`+`iban`). **PDF/Excel dökümünde Banka + IBAN sütunları** (IBAN 4'erli gruplu). Tek IBAN → otomatik; çok IBAN → seçim; yok → boş.
- **Test:** `tests/test_vendor_bank_ibans.py` (ilk-varsayılan/normalize/mükerrer/devir/PI-otomatik/export).
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

## Bakiye Mutabakatı — Excel-Kaynaklı Hayalet Kayıtlar (2026-06-09)

**Bulgu:** Eski cari **Excel** yüklemeleri (`cariler.xls`), `tx_hash` dedup'unun **yakalayamadığı**
bozuk kayıtlar bırakabiliyor — çünkü hash `(tarih, evrak, tutar, açıklama)`'dan üretilir; aynı işlem
**farklı tarih/işaret/açıklama** ile tekrar girilince hash farklı olur → ikinci kez eklenir. Tespit:
**cari bazında DB bakiyesi ↔ Sedna bakiyesi** karşılaştırması (borç tarafı genelde birebir tutar, fark
**alacak**ta birikir). Canlı tarama (293 cari): 5 cari sapmalı, ~4,13M ₺ hayalet bakiye temizlendi:
- **PEKSAN** (P033): aynı verilen çek (7146592/7146593) **iki kez** (gerçek 31.03/20.04 + Excel kopyası
  13.05) → 3,65M fazla. Bakiye -6,68M → **-3,03M**.
- **SALİM DALGIÇ** (B091): voucher 1164 hem Alacak (Excel upload 36) hem Borç (upload 54); Sedna'da Borç →
  yanlış-işaretli Alacak silindi. -237K → **-118,8K**.
- **GÜVEN MUTFAK** (G057) + **ALİ ÇITIR** (A228): Sedna'da **hiç olmayan** tekil Excel muhasebe fişleri
  (330K + 32K) → stale, silindi (kullanıcı onayıyla).
- **METEK** (M157): sapma değil — Sedna'da o gün girilen hareket henüz çekilmemiş (sonraki sync'te gelir).

**Önlem:** Cariler artık **doğrudan Sedna sync** ile besleniyor (Excel'e gerek yok) → yeni hayalet kayıt
birikmez. Mevcut sapmalar `finance_event_svc.invalidate` + `db.delete` + audit ile temizlendi (bakiye
Sedna ile birebir). İleride periyodik DB↔Sedna bakiye mutabakatı bu sınıf hatayı tek bakışta yakalar.

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
