# Denetim Takip Modülü

## 1. Genel Bilgi

| Alan | Değer |
|---|---|
| **Modül kodu** | `system.denetim` |
| **Üst modül** | Sistem (`system`) |
| **Frontend rota** | `/dashboard/sistem/denetim` |
| **Backend prefix** | `/api/system/denetim` |
| **İzin kodu** | `system.denetim` — `view` (görüntüle) / `use` (durum değiştir, otomasyon yönet) |
| **Migration** | `c4d8e2f6a1b9` |
| **Oluşturulma** | 2026-07-25 |

**Neden var:** Kurumsal denetim raporları (`docs/denetim/*.md`) statik metindi. Bir bulgu
kapandığında rapor elle güncelleniyor, genel notun ne olduğu insan hesabına kalıyordu —
yani "hangi madde düzeldi, not kaça çıktı" sorusunun makine tarafından doğrulanabilir bir
cevabı yoktu. Bu modül raporu **veriye** çevirir: her bulgu bir satır, her boyut bir skor
taşıyıcı, her otomasyon koşusu denetlenebilir bir kayıt.

---

## 2. Dosya Haritası

### Backend
| Dosya | İçerik |
|---|---|
| `app/models/audit_tracker.py` | 5 model: `AuditReport`, `AuditDimension`, `AuditFinding`, `AuditFindingRun`, `AuditAutomationConfig` |
| `app/schemas/audit_tracker.py` | `FindingCreate/Update`, `AutomationConfigUpdate`, `FindingResponse`, `DimensionResponse`, `ScoreboardResponse`, `RunResponse` |
| `app/services/audit_tracker_service.py` | **Skor motoru + prompt üreteci + CRUD** — router, onay executor'ı ve cron ORTAK kullanır |
| `app/routers/system_denetim.py` | HTTP uçları (izin + onay + audit) |
| `app/utils/approval_executor.py` | `_handle_system_denetim` + `_HANDLERS["system.denetim"]` |
| `alembic/versions/c4d8e2f6a1b9_*.py` | 5 tablo + `system.denetim` modülü + Admin izni |
| `cron_denetim_auto.py` | 5 saatlik otomasyon (worktree → claude → test → deploy → geri alma) |
| `seed_denetim.py` + `seed_data/` | Rapor verisinin idempotent yüklenmesi |
| `tests/test_denetim.py` | 43 test (skor motoru, prompt, izin, onay regresyonu, koşu eşlemesi) |

### Frontend
| Dosya | İçerik |
|---|---|
| `routes/dashboard/sistem/denetim/+page.svelte` | 3 görünüm: Bulgular · Skor Panosu · Otomasyon Koşuları |
| `lib/config/navigation.ts` | `system.denetim` NavItem (sidebar + route guard tek kaynaktan) |

### Sistem
| Dosya | İçerik |
|---|---|
| `scripts/systemd/sprenses-denetim-auto.service` | oneshot birim (`TZ=Europe/Istanbul`, `OnFailure=` alarmı) |
| `scripts/systemd/sprenses-denetim-auto.timer` | `OnCalendar=*-*-* 00/2:40:00 Europe/Istanbul` (2 saatte bir, günde 12 koşu) |

> **Unit dosyaları git'te VAR ama `/etc/systemd/system/` git'te DEĞİL** — sunucu yeniden
> kurulursa `scripts/systemd/` içindekiler tekrar kopyalanmalıdır.

---

## 3. Veritabanı Şeması

### `audit_reports`
Bir denetim raporu. Yeni denetim yapıldığında yeni satır eklenir; `is_active` panoda
gösterileni belirler.

`key` (unique) · `title` · `report_date` · `doc_path` · `baseline_score` · `target_score` ·
`notes` · `is_active`

### `audit_dimensions`
23 skor boyutu. **`score_current` KOLONU YOKTUR** — bilinçli.

`report_id` · `no` (1-23) · `name` · `score_prev` (v3) · `score_baseline` (denetim anı) ·
`score_target` (90 gün) · `layer` (`cekirdek`/`operasyon`) · `reason`
UNIQUE(`report_id`, `no`)

### `audit_findings`
Tablonun satırı, otomasyonun iş kalemi.

`report_id` · `code` · `title` · `dimension_no` · `risk` · `effort` · `category` · `status` ·
`evidence` · `solution` · `closure_criteria` · `source_section` · `score_impact` ·
`automatable` · `auto_enabled` · `prompt_override` · `auto_attempts` · `last_run_at` ·
`last_run_status` · `branch_name` · `closed_at` · `closed_by` · `closure_note` ·
`verification_output`
UNIQUE(`report_id`, `code`) · index: status, risk, (report_id, dimension_no)

### `audit_finding_runs`
Her otomasyon (veya elle) koşusunun izi — "otomasyon ne yaptı" sorusunun cevabı.

`finding_id` · `trigger` · `status` · `started_at` · `finished_at` · `duration_sec` ·
`branch` · `commit_sha` · `files_changed` · `tests_passed` · `tests_failed` · `deployed` ·
`rolled_back` · `model` · `cost_usd` · `summary` · `log_excerpt` · `error`

### `audit_automation_config`
Tek satır (`id=1`). `enabled` **acil durdurma anahtarıdır** — cron her koşuda önce buna
bakar, kapalıysa hiçbir şey yapmadan çıkar (systemd timer'ı durdurmaya gerek yok).

### DB'de saklanan sabit değerler — DEĞİŞTİRİLEMEZ
```
risk     : kritik | yuksek | orta | dusuk
effort   : S | M | L
category : kod | altyapi | surec | dokuman | test | guvenlik | veri
status   : acik | devam | inceleme | kismen | kapali | iptal
run.status: calisiyor | basarili | basarisiz | atlandi | geri_alindi
```

---

## 4. Skor Motoru — İş Kuralları

### Neden türetilmiş, neden saklanmıyor

```
boyut_güncel = score_baseline + Σ(bulgu.score_impact × durum_ağırlığı)
üst sınır    = min(score_target, 10)
genel not    = ortalama(boyut_güncel) × 10
```

`score_current` **hiçbir yerde saklanmaz**, her okumada yeniden hesaplanır.

Bu, doğrudan **FIN-001'in dersidir**: `finance_events.amount_try` saklanan bir türev
değerdi ve hiçbir yazıcı onu tazelemiyordu → yönetim raporlarında aylarca ₺696.190,94
hayalet para durdu. Aynı hata sınıfının bu modülde tekrarlaması **yapısal olarak
imkânsızdır**: saklanmayan bir değer bayatlayamaz.

### Durum → puan ağırlığı

| Durum | Ağırlık | Gerekçe |
|---|:--:|---|
| `kapali` | 1,0 | Kapanış kriteri sağlandı |
| `kismen` | 0,5 | DR-001 gibi "büyük ölçüde kapandı" maddeleri |
| `inceleme` | 0,0 | **Kod hazır ama canlıda değil → puan YOK** |
| `devam` · `acik` · `iptal` | 0,0 | — |

`inceleme`'nin puan vermemesi bilinçlidir: "yazıldı" ile "çalışıyor" arasındaki farkı
notun gizlememesi gerekir.

### Tavan kuralı

Bir boyutun skoru `score_target`'ı (rapordaki 90 gün hedefi) aşamaz. Aksi halde
`score_impact` değerlerinin toplamı notu şişirirdi. Sonuç: "tüm maddeler kapanırsa"
projeksiyonu raporun ilan ettiği hedefle tutarlı kalır.

### Bulgu başına puan (`applied_points` / `potential_points`)

Bir bulgunun genel nota katkısı `score_impact`'ten **doğrudan türetilmez** — boyut skoru
tavana dayanmışsa marjinal katkı sıfır olabilir. Bu yüzden puan, "bu bulgu olmasaydı boyut
skoru ne olurdu" farkından hesaplanır ve `10 / boyut_sayısı` çarpanıyla 100'lük ölçeğe
çevrilir (23 boyutta 1 boyut puanı ≈ 0,43 genel not puanı).

---

## 5. API Endpoint'leri

| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/scoreboard` | view | 23 boyut canlı skor + genel not + sayımlar |
| GET | `/findings` | view | Sayfalı liste (filtre: status/risk/category/dimension_no/automatable/search; sıralama whitelist'li) |
| GET | `/findings/{id}` | view | Tek bulgu + son 20 koşu |
| POST | `/findings` | use | Rapor dışı takip maddesi ekle (onay + audit) |
| PATCH | `/findings/{id}` | use | Durum/alan güncelle (onay + audit) — skoru değiştirir |
| DELETE | `/findings/{id}` | use | Sil (onay + audit) |
| GET | `/config` | view | Otomasyon ayarları + sıradaki aday |
| PATCH | `/config` | use | Ayar güncelle (onay `update_config` + audit) |
| POST | `/findings/{id}/run` | use | Otomasyonu şimdi başlat (alt süreç; `automatable` değilse 400) |
| GET | `/runs` | view | Tüm koşu geçmişi (sayfalı) |

Liste yanıtı standart sözleşmeye uyar: `{ items, total, page, page_size, pages }`.

---

## 6. Frontend UI Yapısı

`ListPage.svelte` iskeleti, üç görünüm `SegmentedControl` ile değişir:

1. **Bulgular** — masaüstü tablo + mobil kart. Kolonlar: Kod · Bulgu (+boyut/kategori) ·
   Risk · Efor · Durum · **Puan Etkisi** · Otomasyon · İşlem.
   Satır genişletilince: kanıt, çözüm, kapanış kriteri, **tam Claude Code komutu**,
   son koşu özeti ve durum değiştirme düğmeleri.
2. **Skor Panosu** — 23 boyut; her satırda denetim anı / şu an / hedef ve üç katmanlı
   ilerleme çubuğu (gri = denetim anı, lacivert = şu an, sarı çizgi = hedef).
3. **Otomasyon Koşuları** — başlangıç, bulgu, sonuç, süre, testler, deploy, maliyet, branch.

**Puan etkisi kolonu** kullanıcının sorduğu "düzeldi bilgisi"ni taşır: madde kapalıysa
yeşil `+X,XX puan` (nota hâlihazırda kattığı), açıksa gri `+X,XX kazanç` (kapanınca
kazanılacak).

Bileşenler: `ListPage`, `StatCard`, `StatusBadge`, `SegmentedControl`, `Button`, `Select`,
`Modal`, `ConfirmDialog`. İkonlar Lucide. Native `confirm()` kullanılmaz.

---

## 7. Otomasyon — Periyodik Koşu (2 saatte bir)

### Akış

```
flock  →  acil durdurma anahtarı  →  bellek bekçisi (MemAvailable+SwapFree ≥ 2500 MB)
   ↓
aday seç (risk → efor → skor etkisi)
   ↓
izole git worktree (/home/ec2-user/otel-denetim/<kod>, branch denetim/<kod>-<zaman>)
   ↓
claude -p --model opus --permission-mode bypassPermissions --output-format json
        --max-budget-usd N --setting-sources user --no-session-persistence
   ↓
sır bekçisi → commit → TÜM test takımı (sprenses_test)
   ↓
testler yeşil?  →  master'a merge  →  deploy  →  /api/health
                                                    ↓ 200 değilse
                                              OTOMATİK GERİ AL
   ↓
audit_finding_runs kaydı + bildirim (izinli kullanıcılara)
```

### Otomatik deploy'dan muaf değişiklikler — bilinçli

| Desen | Neden |
|---|---|
| `backend/alembic/versions/` | Üretim şeması gözetimsiz değiştirilmez (geri alınamaz) |
| `backend/cron_denetim_auto.py` | Otomasyon kendi ayağını kesemez |
| `scripts/systemd/` | Zamanlayıcı kendini bozamaz |
| `.env`, `.claude/settings.json`, `scripts/claude-guard-secrets.sh` | Güvenlik yapılandırması |

Bu durumlarda kod branch'te kalır, bulgu **`inceleme`** durumuna geçer, bildirim gider.
Puan verilmez (bkz. durum→ağırlık tablosu).

### `--setting-sources user` — neden ve bedeli

Proje `.claude/settings.json`'ındaki **Stop hook'u headless `-p` modunda da çalışır** ve
`cd /home/ec2-user/otel` sabit yoluyla **canlı çalışma ağacını** commit'leyip GitHub'a
push eder. Otomasyon worktree'de çalışırken bu istenmeyen bir yan etkidir (üstelik depo
public — SEC-001). `--setting-sources user` bunu kapatır (canlıda ölçüldü: hook sayısı
0'a düştü).

**Bedeli:** aynı bayrak `PreToolUse` gizli-dosya bekçisini de kapatır. Bu yüzden
`cron_denetim_auto.py` içinde `_looks_secret()` bekçisi vardır — `.env`/`.pem`/`.key`/
`credentials`/`secret` içeren bir yol değişmişse **commit reddedilir** ve koşu başarısız
sayılır. Test: `tests/test_denetim.py::TestCronHelpers`.

### Güvenlik ve dayanıklılık kuralları

- **Tek koşu:** `flock` (`/tmp/sprenses-denetim-auto.lock`) — timer + elle tetikleme çakışmaz.
- **Bellek:** `deploy-frontend.sh` ile aynı eşik. 2026-07-06 ve 07-18 donma olaylarının dersi.
- **Bütçe:** `--max-budget-usd` (varsayılan 8 USD) + `timeout_min` (varsayılan 45 dk).
- **Deneme sınırı:** bulgu başına `max_attempts` (varsayılan 2) — çözülemeyen madde sonsuz
  döngüye girmez.
- **Başarısız koşuda branch KALIR** — inceleme için; yalnız worktree dizini temizlenir.
- **Kendi hatasını `error_logs`'a yazar** (`source='cron:denetim-otomasyon'`) + `OnFailure=`
  alarmı.

### Bildirim

Alıcılar **izinden türetilir** (`user_can(db, u, "system.denetim", "view")`), rol adından
değil. Bu, DR-003'te yakalanan "rol adına bakan alarm sessizce kimseye ulaşmıyor"
hatasının tekrarını engeller. Kanal: uygulama içi bildirim + push + e-posta.

---

## 8. Audit Log Entegrasyonu

| entity_type | Eylemler |
|---|---|
| `audit_finding` | `create`, `update` (değişen alanlar eski/yeni ile), `delete`, `execute` (elle otomasyon başlatma) |
| `audit_automation_config` | `update` (değişen ayarlar) |

---

## 9. Geliştirme Kuralları

1. **Skoru saklama.** `score_current` kolonu eklemek bu modülün varlık sebebini yok eder.
   Yeni bir türev metrik gerekiyorsa serviste hesapla.
2. **Seed kullanıcı alanlarına dokunmaz.** `seed_denetim.py` yeniden koşturulduğunda
   yalnız rapor metni tazelenir; `status`, `auto_enabled`, `closure_note`,
   `verification_output`, `prompt_override` **korunur**. Aksi halde seed "düzeldi"
   bilgisini silerdi.
3. **Seed otomasyon kuyruğuna madde eklemez.** `auto_enabled` daima `False` başlar —
   istenmeyen otonom koşu olmasın. Kuyruğa alma kullanıcı kararıdır.
4. **`automatable=False` maddeler otomasyona verilmez.** GitHub depo ayarı (SEC-001,
   CICD-010), AWS provizyonu (DR-002), e-posta adresi düzeltmesi gibi repo dışı işler
   bu bayrakla ayrılır; API 400 döner.
5. **Yeni denetim raporu eklerken** yeni `audit_reports` satırı aç, eskisini
   `is_active=False` yap. Eski bulgular ve koşu geçmişi silinmez — tarihsel iz korunur.
6. **Prompt tek kaynaktır.** Kullanıcının kopyaladığı metin ile otomasyonun çalıştırdığı
   metin AYNI fonksiyondan (`build_prompt`) gelir; elle çalıştırma ile otomasyon birebir
   aynı işi yapar.

---

## 10. İlgili Dokümanlar

- Denetim raporu: [`docs/denetim/2026-07-25-v4-kurumsal-denetim.md`](../denetim/2026-07-25-v4-kurumsal-denetim.md)
- Restore tatbikatı: [`docs/denetim/2026-07-25-restore-tatbikati.md`](../denetim/2026-07-25-restore-tatbikati.md)
- Sunucu / bellek koruması: [`docs/modules/sunucu.md`](sunucu.md)
- Onay akışı: [`docs/modules/onay-akisi.md`](onay-akisi.md)
