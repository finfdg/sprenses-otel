# Çekler Modülü

## Genel Bilgi

| Alan | Değer |
|---|---|
| **Modül kodu** | `finance.checks` |
| **Üst modül** | Finans (`finance`) |
| **Frontend rota** | `/dashboard/finans/cekler` |
| **Backend prefix** | `/api/finance/checks` |
| **İzin kodu** | `finance.checks` |
| **İzin seviyeleri** | `can_view` (görme), `can_use` (yükleme + durum güncelleme + silme) |

---

## Dosya Haritası

### Backend
| Dosya | Açıklama |
|---|---|
| `app/routers/finance/checks.py` | Ana router — yükleme, listeleme, durum güncelleme, banka eşleştirme |
| `app/models/check.py` | `Check`, `CheckUpload` modelleri |
| `app/utils/check_parser.py` | Excel çek dosyası ayrıştırıcı |
| `app/schemas/check.py` | Pydantic şemalar |

### Frontend
| Dosya | Açıklama |
|---|---|
| `src/routes/dashboard/finans/cekler/+page.svelte` | Ana sayfa — çek tablosu, yükleme, durum güncelleme |

---

## Veritabanı Şeması

### `checks`
| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | integer PK | |
| `upload_id` | integer FK → check_uploads | Hangi yüklemeden geldi |
| `check_type` | varchar(20) | Çek türü (verilecek, alınacak) |
| `sequence_no` | varchar(50) | Sıra numarası |
| `check_no` | varchar(50) | Çek numarası |
| `vendor_code` | varchar(50) | Cari kodu |
| `vendor_name` | varchar(200) | Cari adı |
| `description` | text | Açıklama / serbest not |
| `bank_name` | varchar(100) | Çekin ödeneceği banka (Sedna `AccCheck.Bank`) — Nakit Akım + Çekler'de gösterilir |
| `bank_name_inferred` | boolean | True → `bank_name` komşu çek-no'larından TAHMİN (UI'da "~banka" soluk rozet); False → kesin (Sedna) |
| `city` | varchar(100) | Şehir |
| `due_date` | date | Vade tarihi |
| `amount_tl` | numeric(15,2) | TL tutarı |
| `currency` | varchar(3) | Döviz kodu |
| `amount_currency` | numeric(15,2) | Döviz tutarı |
| `transaction_type` | varchar(50) | İşlem tipi |
| `status` | varchar(20) | Durum: pending, cashed, returned, cancelled |
| `bank_transaction_id` | integer FK → bank_transactions | Banka eşleşmesi |
| `created_at` | timestamptz | |

### `check_uploads`
| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | integer PK | |
| `file_name` | varchar(255) | Orijinal dosya adı |
| `file_url` | varchar(500) | Sunucu dosya yolu |
| `total_checks` | integer | Toplam çek sayısı |
| `new_checks` | integer | Yeni eklenen |
| `skipped_checks` | integer | Mükerrer (atlandı) |
| `uploaded_by` | integer FK → users | |
| `uploaded_at` | timestamptz | |

**İndeksler:** `ix_check_due_date`, `ix_check_vendor`, `ix_check_status`, unique `(check_no, vendor_code, due_date)`

---

## API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| `POST` | `/checks/upload` | use | Excel çek dosyası yükle |
| `POST` | `/checks/sedna-import` | use | Sedna'dan verilen çekleri içe aktar (aşağıda) |
| `GET` | `/checks/sedna-status` | view | Sedna içe aktarma etkin mi (`{configured}`) |
| `GET` | `/checks/uploads` | view | Yükleme geçmişi |
| `DELETE` | `/checks/uploads/{id}` | use | Yükleme sil (çekler geri alınır) |
| `GET` | `/checks/` | view | Çek listesi (paginated, durum/tarih filtresi) |
| `GET` | `/checks/summary` | view | Özet (toplam tutar, durum bazlı) |
| `PATCH` | `/checks/{id}/status` | use | Durum güncelle (cashed, returned, cancelled) |
| `POST` | `/checks/match-bank` | use | Banka işlemleriyle otomatik eşleştir |

---

## Dosya Yükleme Güvenliği

- **MIME doğrulaması:** `app/utils/file_validation.py` ile magic bytes kontrolü
- **Boyut limiti:** Maksimum 10 MB
- **Uzantı kontrolü:** Yalnızca `.xlsx`, `.xls`
- **Mükerrer kontrolü:** `_check_dedup_key()` = `(check_no, vendor_code, currency, native tutar)` —
  vade anahtarda değil (vade değişimi mükerrer üretmez); döviz çekte kur-bağımsız yüz değer kullanılır

---

## Sedna (Muhasebe SQL Server) Doğrudan İçe Aktarma (2026-06-06)

Verilen çekler Excel'e ek olarak doğrudan Sedna muhasebe DB'sinden çekilir (ters SSH tüneli
`127.0.0.1:11433`) — cariler/IBAN ile aynı altyapı. `POST /checks/sedna-import` (finance.checks
use, onaydan muaf, audit'li).

- **Kaynak/eşleme:** `AccCheckTrans` (hareket) + `AccCheck` (çek kimliği: `CheckNo`/`Bank`/`City`)
  + `Accounting` (`Remark`=cari adı). Verilen çek **issuance** satırı = `CheckPosition=100` +
  `ActionType=2` (cari-tarafı borç, çek başına TEK). Join `AccountingCode` (virgüllü) →
  `Accounting.Code` (noktalı) `REPLACE(',','.')`. Filtre `Deleted=0` + `DueDate`/`CheckNo` dolu.
- **Kapsanan hesaplar — 320 + 159 + 335 (2026-06-09 genişletildi):** Verilen çek karşı-tarafı yalnız
  satıcı değildir. Üç prefix de "verilen çek"tir ve senkronlanır: **320** satıcı (`sedna_account_prefix`,
  config), **159** verilen sipariş avansı, **335** personel/ortak. `sedna_client._ISSUED_CHECK_PREFIXES_EXTRA
  = ("159","335")` → WHERE `(AccountingCode LIKE '320%' OR '159%' OR '335%')` (prefix'ler rakam → gömülü,
  `execute` parametresiz; pymssql %-tuzağı). **Neden:** 320-only import 159/335 çeklerini hiç güncellemiyordu
  → Sedna'da iptal/ödenir/vade değişse bile bizde "bekliyor" kalıyordu (canlı: çek 0353815 Necip Özden
  arazi avansı 159, Sedna'da pos=103 iptal ama bizde vadesi-geçen pending görünüyordu). İlk genişletmede
  Sedna'da 320=137 + 159=17 + 335=5 = **159 verilen çek**.
- **Durum (en kritik karar):** aynı `CheckId`'nin **EN YÜKSEK pozisyonu** (`AccCheckDef` legend'i,
  100-105 "Verilen Çek" doc grubu) → bizim duruma eşlenir:
  - `100` Verilen Çek / `104` Protesto / `105` Takipte → **pending**
  - `101` Bankadan Ödeme / `102` Kasadan Ödeme → **paid**
  - `103` Geri Al → **cancelled**
  - `sedna_client.fetch_issued_checks()` `max_pos` döner; `checks.py:_check_status_from_pos()` eşler.
- **Dedup + senkron (2026-06-08 düzeltildi — vade DEĞİL tutar):** `_check_dedup_key()` =
  `(check_no, vendor_code, currency, NATIVE tutar)` — Excel ile aynı. **`due_date` ANAHTARDA YOK.**
  Eşleşmemiş çek (`bank_transaction_id IS NULL AND match_number IS NULL`) için **vade + durum** Sedna'dan
  güncellenir; eşleşmişe **dokunulmaz**. İdempotent.
  - **Neden vade anahtardan çıktı:** Eski key `(…, due_date)` idi; Sedna'da çekin vadesi değişince
    (yeniden vadelendirme) yeni key → **mükerrer kayıt** — eski vade tablo'da "GEÇMİŞ" hayalet kalıyordu
    (canlı örnek: çek 9498648 ERSA, 02.06→31.07; eski 02.06 kaydı silinmeden duruyordu). Vade anahtarda
    olmayınca vade değişince **mevcut kayıt güncellenir**, mükerrer olmaz.
  - **NATIVE tutar (kur-bağımsız):** TL çek → `amount_tl`; döviz çek → **`amount_currency`** (EUR/USD yüz
    değeri). `amount_tl` döviz çekte TL değerlemesidir, **kurla değişir** → anahtarda olursa her kur
    hareketinde "yeni çek" sanılır. Tutar, aynı no'lu **farklı** çekleri de ayırır (4149098: 900K vs 969K).
  - **Mükerrer temizliği:** Yükleme başında vade-değişiminden kalan **eşleşmemiş** mükerrerler silinir
    (eşleşmiş çeklere dokunulmaz; FE de invalidate). Sonuç `removed_dupes` döner.
  - **Dayanıklılık:** Her satır kendi `begin_nested()` SAVEPOINT'inde → eski hatalı-tutarlı kayıtların
    `UNIQUE(check_no,vendor_code,due_date)` çakışması tüm içe aktarmayı düşürmez, o satır atlanır.
  - **Tutar-kayması iyileştirmesi (2026-06-09):** Dedup-key bulunamayıp aynı `(check_no, vendor_code,
    due_date)` UNIQUE üçlüsünde **eşleşmemiş** bir kayıt varsa (tutar/para birimi bizde bozuk), import
    INSERT yerine kaydı **Sedna'ya hizalar** (UPDATE: `amount_tl`/`amount_currency`/`currency`/`status` +
    `upsert_check`). Eskiden bu satır UNIQUE çakışıp **sessizce atlanıyor, yanlış tutar kalıcı oluyordu**
    → nakit akım eksik. Canlı örnek: **PEKSAN 0353816** bizde 30.000 TL / 563,65 € sanılmış, Sedna'da
    **30.000 € = 1.596.726 TL** (1,56M TL eksik borç) → import bunu otomatik düzeltti. **Eşleşmiş** kayda
    (banka kanıtı) DOKUNULMAZ — mutabık verimiz korunur (ör. 714659 paid+banka-eşleşmiş EUR/TL etiketi atlanır).
- **Alan eşleme:** `amount_tl`=Debit (TL); EUR çekte `currency`=EUR + `amount_currency`=CurrDebit;
  **`bank_name`=banka adı** (Sedna `AccCheck.Bank`; 2026-06-20'den önce `description`'a yazılıyordu, artık ayrı kolon → Nakit Akım/Çekler'de banka rozeti); `transaction_type`="Verilen Çek".
- **finance_events:** `upsert_check` `status`'a göre `is_realized` (paid→True) ayarlar → nakit akımda
  doğru görünür. Banka eşleşmesi sonradan `match()` ile çift sayımı engeller.
- **İptal çek düzeltmesi (2026-06-06):** `upsert_check` artık **cancelled** çekte FE **invalidate**
  eder (oluşturmaz) → iptal çek nakit akım listesinde **hayalet bekleyen gider** olarak görünmez.
  Tüm yolları kapsar (Excel/PATCH/Sedna). Önceki davranışta iptal çekler `is_realized=False` FE ile
  listede görünüyordu; düzeltme + mevcut iptal-çek FE'lerinin tek seferlik temizliği yapıldı.
- **Frontend:** Çekler sayfasında Sedna kutusu + **"Sedna'dan Çek Çek"** butonu (sedna-status ile gösterilir).
- **İlk canlı (320):** 135 verilen çek çekildi → 6 yeni, 1 durum güncel, 128 mevcut (Excel ile çakışmadan).
- **159/335 genişletme canlı (2026-06-09):** 159 verilen çek (320=137+159=17+335=5). Bir veri düzeltmesi
  gerekti: çekler 7146590-93 Excel'de yanlışlıkla **159 PEKSAN (0089)**'a yazılmış; Sedna issuance'ı
  **159 HANYAPIT (0088)** → 4 çek yeniden etiketlendi (banka eşleşmesi korunarak), sonra import temiz
  senkron oldu (0 mükerrer). PEKSAN 0353816 tutar-kayması da iyileşti (yukarı).
- **Test:** `tests/test_checks.py::TestSednaCheckImport` (durum eşleme + dedup + durum senkron + vade≠mükerrer +
  aynı-no-farklı-tutar + mükerrer iyileştirme + **tutar-kayması heal (eşleşmemiş) / matched-skip** +
  **159/335 prefix import** + **fetch SQL 320+159+335 kapsamı** + izin/503).

---

## Nakit Akım Entegrasyonu

Çekler, vade tarihlerinde nakit akımda gösterilir:

- **Verilen çek** → `direction = -1` (gider), `event_date = due_date`
- **Alınan çek** → `direction = +1` (gelir), `event_date = due_date`
- `is_realized = False` — henüz gerçekleşmemiş (ilerideki nakit çıkışı)
- Banka eşleşmesi sonrası `is_realized = True` olarak güncellenir

---

## Banka Eşleştirme Algoritması

`_match_checks_to_bank(db)` fonksiyonu (checks.py):

1. `status = "pending"` ve `bank_transaction_id IS NULL` olan çekleri al
2. Her çek için, banka işlemleri arasında:
   - Tarih farkı ≤ 5 gün
   - Tutar farkı ≤ %2 (veya 100 TL)
   olan en yakın işlemi bul
3. Eşleşme bulunursa:
   - `check.bank_transaction_id = best_match.id`
   - `check.status = "cashed"`
   - `finance_event_svc.match(db, "bank", btx_id, "check", check_id)` çağrılır

### Ne zaman çalışır — boşluk düzeltmesi (2026-06-06)

Eskiden `_match_checks_to_bank` **yalnızca** (1) banka ekstresi yüklemede ve (2) elle
`POST /checks/match-bank` ile çalışıyordu. Bu yüzden **ekstre önce yüklenip çek sonra**
eklenirse (Excel veya Sedna) çek eşleşmeden "bekliyor" kalıyordu — fiziksel ödeme bankada
görünse bile. **Düzeltme:** matcher artık **çek Excel yüklemesi** ve **Sedna içe aktarma**
sonunda da çağrılır → yeni/güncellenen çekler mevcut banka hareketleriyle anında eşleşir.

- **İkili fayda:** Sedna "Verilen Çek" (pending) dese bile, bankada ödeme kanıtı (örn.
  `"ÇEK : 4355461"` açıklamalı hareket) varsa çek **paid** olur — Sedna muhasebe gecikmesini de telafi eder.
- **Eşleşme gücü:** çek no banka açıklamasında geçiyorsa skor 99 (kesin); yoksa tutar+tarih(±10g)+çek-ödeme ifadesi.
- Sedna import yanıtı `matched_to_bank` sayısını döner; frontend toast'ta gösterilir.
- **Gerçek vaka:** çek 4355461 (GÜVEN MUTFAK, ₺330.000) Halkbank'tan 01.06.2026'da ödenmiş
  (`tx#5357 "ÇEK : 4355461 ALİ SAZAN"`) ama çek Excel'den ekstreden sonra geldiği için eşleşmemişti
  → match-bank ile çözüldü; bu düzeltme tekrarını önler.

---

## finance_events Entegrasyonu

```python
finance_event_svc.upsert_check(db, check, bank_tx=None)
```

| finance_events alanı | Değer |
|---|---|
| `source_type` | `"check"` |
| `source_id` | `check.id` |
| `direction` | `-1` (verilen çek = gider) |
| `amount` | `check.amount_tl` |
| `currency` | `check.currency` |
| `event_date` | `check.due_date` |
| `event_status` | `check.status` |
| `vendor_code` | `check.vendor_code` |
| `check_no` | `check.check_no` |
| `is_realized` | `True` (cashed/returned) veya `False` (pending) |
| `is_matched` | `True` (banka eşleşmesi varsa) |

---

## Durum Geçişleri

```
pending → cashed    (banka işlemi eşleşti)
pending → returned  (çek iade edildi)
pending → cancelled (iptal edildi)
cashed  → (nihai durum)
```

Durum değişikliğinde `finance_event_svc.upsert_check(db, check)` yeniden çağrılır.

---

## Audit Log Entegrasyonu

| entity_type | Kaydedilen eylem |
|---|---|
| `check_upload` | create (yükleme), delete |
| `check` | update (durum değişikliği) |

---

## Geliştirme Kuralları

1. **Silme:** Çek silmek yerine `cancelled` durumuna getir — geçmişi korur
2. **Para birimi:** Dövizli çeklerde `amount_tl` zorunludur (yükleme anında hesaplanmış olmalı)
3. **Mükerrer:** `(check_no, vendor_code, due_date)` kombinasyonu unique — aynı çek iki kez yüklenemez
4. **WS broadcast:** `broadcast_finance_update(background_tasks, "checks", "upload"/"update")`
5. **Eşleştirme toleransı:** Tarih ±5 gün, tutar ±%2 (banka değerleme farkları için)
