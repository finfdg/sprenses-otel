# Bankalar Modülü

## Genel Bilgi

| Alan | Değer |
|---|---|
| **Modül kodu** | `finance.banks` |
| **Üst modül** | Finans (`finance`) |
| **Frontend rota** | `/dashboard/finans/bankalar` |
| **Backend prefix** | `/api/finance/banks` |
| **İzin kodu** | `finance.banks` |
| **İzin seviyeleri** | `can_view` (görme), `can_use` (yükleme + düzenleme + silme) |

---

## Dosya Haritası

### Backend
| Dosya | Açıklama |
|---|---|
| `app/routers/finance/banks.py` | Ana router — hesap CRUD, ekstre yükleme, işlem listesi, ekstre/işlem silme |
| `app/services/bank_account_service.py` | Hesap CRUD servisi (router + onay executor ORTAK) |
| `app/services/bank_release_service.py` | **Banka verisi silme öncesi eşleşme çözme — TEK kaynak** (Faz 3, 2026-07-12) |
| `app/models/bank_account.py` | `BankAccount` modeli |
| `app/models/bank_transaction.py` | `BankTransaction` modeli |
| `app/models/bank_statement.py` | `BankStatement` modeli |
| `app/utils/bank_parser.py` | Excel/PDF ekstre ayrıştırıcı |

### Frontend
| Dosya | Açıklama |
|---|---|
| `src/routes/dashboard/finans/bankalar/+page.svelte` | Ana sayfa — hesap kartları, işlem tablosu |

---

## Veritabanı Şeması

### `bank_accounts`
| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | integer PK | |
| `bank_name` | varchar(100) | Banka adı |
| `branch_name` | varchar(200) | Şube adı |
| `account_no` | varchar(50) | Hesap no |
| `iban` | varchar(34) | IBAN (unique) |
| `currency` | varchar(3) | Para birimi (TRY, USD, EUR) |
| `holder_name` | varchar(300) | Hesap sahibi |
| `blocked_amount` | numeric(15,2) | Bloke tutar |
| `is_active` | boolean | Aktif/pasif |
| `created_by` | integer FK → users | Oluşturan |
| `created_at` | timestamptz | Oluşturma zamanı |

> **Not:** `bank_accounts`'ta ayrı `balance` kolonu **yoktur** — güncel bakiye hesabın son `bank_transactions.balance` değerinden türetilir.

### `bank_transactions`
| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | integer PK | |
| `account_id` | integer FK → bank_accounts | |
| `statement_id` | integer FK → bank_statements | |
| `date` | date | İşlem tarihi |
| `description` | text | Açıklama |
| `amount` | numeric(15,2) | İşlem tutarı (+ giriş, - çıkış) |
| `balance` | numeric(15,2) | İşlem sonrası bakiye |
| `receipt_no` | varchar(50) | Fiş/dekont no |
| `payment_method` | varchar(20) | Ödeme yöntemi (eft, havale, pos, atm) |
| `category_id` | integer FK → transaction_categories | Etiket kategorisi |
| `tag_note` | text | Etiket notu |
| `match_number` | varchar(50) | Eşleştirme numarası |
| `created_at` | timestamptz | |

### `bank_statements`
| Kolon | Tip | Açıklama |
|---|---|---|
| `id` | integer PK | |
| `account_id` | integer FK | |
| `file_name` | varchar(255) | Orijinal dosya adı |
| `file_url` | varchar(500) | Sunucu dosya yolu |
| `period_start` | date | Dönem başlangıç |
| `period_end` | date | Dönem bitiş |
| `total_transactions` | integer | Toplam işlem sayısı |
| `new_transactions` | integer | Yeni eklenen |
| `skipped_transactions` | integer | Mükerrer (atlandı) |
| `uploaded_by` | integer FK → users | |
| `uploaded_at` | timestamptz | |

**İndeksler:** `ix_bank_tx_account_date`, `ix_bank_tx_statement`, `ix_bank_tx_tag_category`

---

## API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| `GET` | `/banks/accounts/` | view | Hesap listesi (bakiye özeti dahil) |
| `POST` | `/banks/accounts/` | use | Yeni hesap oluştur |
| `PATCH` | `/banks/accounts/{id}` | use | Hesap güncelle |
| `DELETE` | `/banks/accounts/{id}` | use | Hesap sil — işlemlerinin **tüm eşleşme/FE temizliğiyle** (`bank_release_service.delete_account_with_cleanup`; aşağıdaki Faz 3 bölümüne bkz.) |
| `POST` | `/banks/upload` | use | Ekstre yükle — banka otomatik algıla (IBAN'dan hesap bulunur) |
| `POST` | `/banks/accounts/{id}/upload` | use | Belirli hesaba ekstre yükle — **başlık IBAN/para-birimi doğrulaması** (Faz 3 #22b; uyuşmazsa 400) |
| `POST` | `/banks/accounts/{id}/manual-transaction` | use | **Ekstre-dışı (manuel) hareket** — ekstresi gelmemiş işlemi yansıtır; ekstre yüklenince o tarih aralığında **otomatik silinir** (çift kayıt yok). `source='manual'`, audit'li |
| `GET` | `/banks/accounts/{id}/transactions` | view | İşlem listesi (paginated; yanıt `source`: statement/manual) |
| `GET` | `/banks/accounts/{id}/statements` | view | Ekstre yükleme geçmişi |
| `DELETE` | `/banks/statements/{id}` | use | Ekstreyi ve TÜM işlemlerini sil — bağlı eşleşmeler çözülür, FE'ler temizlenir. **Onaya TABİ** (Faz 3 #22c) |
| `DELETE` | `/banks/transactions/{id}` | use | Tekil işlemi sil — **yalnız eşleşmemiş satır** (eşleşmişse 400). **Onaya TABİ** (Faz 3 #22c) |

---

## Dosya Yükleme Güvenliği

- **MIME doğrulaması:** `app/utils/file_validation.py` ile Excel magic bytes kontrolü (`\x50\x4B\x03\x04` xlsx, `\xD0\xCF\x11\xE0` xls)
- **Boyut limiti:** Maksimum 10 MB (Excel)
- **Uzantı kontrolü:** Yalnızca `.xlsx`, `.xls`
- **Mükerrer kontrolü:** `(account_id, transaction_date, amount, receipt_no)` üçlü unique kontrolü

---

## Çek / Kredi / Kredi Kartı / Avans Eşleştirmesi

Ekstre yüklenince otomatik eşleştirme tetiklenir (tümü `app/utils/matching_service.py`):

```python
# bank_statement_import.py → _post_upload_processing (her biri SAVEPOINT ile izole)
_match_checks_to_bank(db)    # bekleyen çekler (gider)
_match_credits_to_bank(db)   # ödenmemiş kredi taksitleri (gider)
_match_cc_to_bank(db)        # ödenmemiş KK ekstreleri (gider)
_match_advances_to_bank(db)  # bekleyen avanslar (GELİR; tutar+döviz birebir, gecikme isimli 60g / kör 10g, erken ≤10g)
```

Eşleştirme sonucu `finance_events` tablosunda `is_matched=True` olarak işaretlenir.
Eşleşen işlemler nakit akımda çift sayılmaz (birisi gizlenir).

---

## finance_events Entegrasyonu

Yeni banka işlemi eklendiğinde:

```python
finance_event_svc.upsert_bank_tx(db, db_tx, account)
```

| finance_events alanı | Değer |
|---|---|
| `source_type` | `"bank"` |
| `source_id` | `bank_transaction.id` |
| `direction` | `+1` (giriş) veya `-1` (çıkış) |
| `amount` | İşlem tutarı |
| `currency` | Hesap para birimi |
| `amount_try` | TL karşılığı (günlük kurdan hesaplanır) |
| `bank_name` | Hesabın banka adı |
| `bank_account_id` | Hesap ID |
| `iban` | Hesap IBAN |

---

## Audit Log Entegrasyonu

| entity_type | Kaydedilen eylem |
|---|---|
| `bank_account` | create, update, delete |
| `bank_statement` | create (yükleme), delete (çözülen eşleşme sayaçlarıyla) |
| `bank_transaction` | create (manuel hareket), delete (tekil silme) |

---

## Geliştirme Kuralları

1. **Bakiye:** `bank_accounts.balance` her zaman son banka ekstresindeki kapanış bakiyesidir — işlemlerden hesaplanmaz
2. **Para birimi:** Hesap para birimi değiştirilemez (işlem varsa)
3. **Ekstre silme:** İlgili tüm `bank_transactions` silinir, `finance_events` invalidate edilir — **silme öncesi her işlemin eşleşmeleri `bank_release_service` ile çözülür** (aşağıdaki Faz 3 bölümü)
4. **WS broadcast:** `broadcast_finance_update(background_tasks, "banks", "upload")` her yüklemede tetiklenir
5. **Eşleştirme:** Banka ID'si IBAN'dan çözümlenir — ekstre dosyasında IBAN yoksa manuel seçim gerekir
6. **TEK-kaynak silme kuralı (Faz 3, 2026-07-12):** Banka verisi (hesap/ekstre/işlem) silen **HER yol** `app/services/bank_release_service.py` fonksiyonlarını kullanmalıdır — elle `db.delete` yazılmaz (bkz. aşağıdaki bölüm)

---

## Aynı Gün İçi İşlem Sıralama (2026-04-15 Düzeltmesi)

### Sorun
TEB PDF ekstreleri işlemleri **ters kronolojik** sırada listeler (yeni → eski). `_ensure_chronological_order` fonksiyonu çok günlü ekstrelerde `first_date > last_date` kontrolü ile doğru sıralıyordu. Ancak **aynı güne ait tüm işlemler** olduğunda bakiye zinciri her iki yönde de eşit puan alıyordu → sıra değişmiyordu → son bakiye yanlış görünüyordu.

**Örnek:** TEB EUR hesabı 15/04/2026 — 16:10'da havale (+70.000), 16:12'de çek ödemesi (-70.000). PDF ters sırada listeliyor → parser son bakiyeyi 70.003,86 olarak kaydediyordu (gerçekte 3,86).

### Çözüm
`ParsedTransaction` modeline `time: Optional[str]` alanı eklendi. `_detect_columns` "saat" kolonunu algılıyor, `_try_parse_mapped_row` saat bilgisini çıkarıyor.

`_ensure_chronological_order`'a 3 seviyeli tiebreaker eklendi:
1. **Bakiye zinciri puanı** (mevcut — `_balance_chain_score`)
2. **Saat bilgisi** — ilk işlemin saati > son işlemin saatiyse → ters sıra → reverse
3. **Dekont numarası** — ilk dekont > son dekont ise → ters sıra → reverse

Bu düzeltme tüm banka formatlarını etkiler ama sadece saat veya dekont bilgisi olan bankalar (TEB vb.) için aktif olur.

---

## Faz 3 (2026-07-12) — Banka Kopyası Tamlığı + Temizlikli Silme

Eşleştirme denetiminin (`docs/denetim/2026-07-11-nakit-akim-eslestirme-denetimi.md` §6)
banka dilimi: **#22** (a/b/c) + **#24** (denetim C5). "Banka verisi otorite" ilkesinin ön
koşulu banka KOPYAMIZIN tam ve temiz olmasıdır — bu paket kopyanın bütünlüğünü denetler ve
silme yollarını güvenli hale getirir.

### (a) Bakiye-zinciri süreklilik kontrolü (#22a)

`sedna_recon_service.check_balance_chains(db, window_days=90)` — hesap başına, iki bakiyeli
satır arasındaki Σtutar ≈ bakiye farkı kontrolü (NULL-bakiye manuel satırlar köprü sayılır;
tolerans `BALANCE_CHAIN_TOLERANCE` = 0.02). Mutabakat koşusunun özetine
`balance_chain_breaks` olarak eklenir + kırılma varsa **"Ekstre bakiye zinciri kırık"**
bildirimi. Detay: `docs/modules/sedna-mutabakat.md` "Bakiye-zinciri kontrolü".

### (b) Hesaba-özel upload'da başlık doğrulaması (#22b)

`POST /banks/accounts/{id}/upload` artık ekstre başlığındaki **IBAN'ı** (boşluk-duyarsız,
büyük harf normalize) ve **para birimini** ("TL"→TRY eşlenir) seçili hesapla karşılaştırır —
uyuşmazlıkta **400** döner. Eskiden yanlış hesaba (hatta yanlış para biriminde) yükleme
sessizce kabul ediliyordu; dedup hesap-bazlı olduğundan mükerrer de engellenmiyordu.
Başlıkta IBAN/para birimi YOKSA doğrulama atlanır (eski davranış korunur). Otomatik-algılamalı
`POST /banks/upload` zaten IBAN'dan hesabı bulduğu için etkilenmez.

### (c) Ekstre / tekil işlem silme uçları (#22c — denetim C7)

Hatalı/yanlış hesaba yüklenmiş ekstrenin **geri alma yolu** (eskiden tek yol hesabı komple
silmekti):

- `DELETE /banks/statements/{id}` — ekstre + TÜM işlemleri; her işlem için eşleşme çözümü +
  FE invalidate (`bank_release_service.delete_bank_statement`). Yanıt çözülen eşleşme
  sayaçlarını döner (çek/kredi/avans/KK/cari); audit detayına da yazılır.
- `DELETE /banks/transactions/{id}` — tekil işlem; **YALNIZ eşleşmemiş satır** silinebilir
  (eşleşmiş satır banka kanıtıdır → 400 "önce eşleşmeyi geri alın" — **bilinçli sürtünme**).
  Öneri izleri (`method='suggestion'`) temizlenir.
- **İkisi de onay akışına TABİ** (`check_approval` op=`delete_statement`/`delete_transaction`) —
  bunlar eşleştirme-muafiyeti sınıfı DEĞİL, **gerçek veri silme**dir (bkz.
  `docs/modules/onay-akisi.md`). `finance.banks` use + audit + `BANKS` WS yayını.

### (#24, denetim C5) Hesap silme = temizlikli silme

`bank_account_service.delete_account` artık `bank_release_service.delete_account_with_cleanup`
çağırır. Eskiden yalnız `db.delete(acc)` yapılıyordu: cascade işlemleri silerken kaynak
kayıtlar "bankasız ödendi" kalıyor, `source_type='bank'` FE'leri orphan kalıyordu.

### `bank_release_service.py` — TEK kaynak (D1-2 deseni)

**KURAL: Banka verisi (hesap / ekstre / tekil işlem) silen HER yol bu servisi kullanmalı.**
Çekirdek `release_bank_transaction(db, tx)` bir banka hareketine bağlı TÜM eşleşmeleri çözer:

| Bağlı varlık | Serbest bırakma davranışı |
|---|---|
| Çek | `bank_transaction_id=None`; `paid` → **`pending`**; FE unmatch + `upsert_check` |
| Kredi taksiti | `is_paid=False` + `paid_date`/FK temizliği + **anapara `remaining_amount`'a iade**; N-1 grubun DİĞER banka satırlarındaki ortak `match_number` izi temizlenir (cari eşleşme numarasına dokunulmaz); FE unmatch + upsert |
| Avans | `received` → **`pending`** (+ `received_date`/`received_amount` temizliği); FE unmatch + upsert |
| KK ekstresi | `paid_amount` işlem tutarı kadar geri düşer (0 tabanı); `is_paid` açılır; FE unmatch + upsert (bağ `event_matches` izinden — stmt'de btx FK yok) |
| Cari çifti | `match_number` çiftindeki `VendorTransaction` satırları serbest (`match_number`/`payment_method` NULL) → dönüşte `needs_vendor_sync=True`; çağıran işlem sonunda **BİR KEZ** `sync_vendor_finance_events` koşar |
| `event_matches` | Banka bacağının kalan tüm izleri (öneriler dahil) silinir |

Üst fonksiyonlar: `delete_bank_statement` (ekstre; işlem başına release + FE invalidate,
cascade sil) · `delete_bank_transaction` (tekil; eşleşmişse `ValueError` → 400) ·
`delete_account_with_cleanup` (hesap; tüm işlemler release + invalidate). **Router + onay
executor ORTAK** — executor `_handle_finance_banks` aynı servis fonksiyonlarını çağırır
(`payload["op"]` ile ayrışır; op yoksa hesap CRUD). Bu yüzden `finance.banks` simple-crud
executor fabrikasından ÇIKARILDI (açık handler).
