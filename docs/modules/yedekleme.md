# Yedekleme Modülü

> ## ⚠️ İki ayrı yedek vardır — karıştırma
> - **KOD yedeği** (bu modül + Stop hook): kaynak kodu git/GitHub'a yedekler. **Veriyi (DB) YEDEKLEMEZ.**
> - **VERİTABANI yedeği** (aşağıdaki "Veritabanı Yedeği" bölümü): `pg_dump` ile finansal/cari/rezervasyon/PDKS verisini yedekler.
>
> Bu ayrım kritik: 2026-06-21 denetimi (D15-1, **tek Kritik bulgu**) bu modülün yalnız kodu yedeklediğini, DB için
> hiçbir otomatik yedek olmadığını saptadı → 2026-06-22'de DB yedeği eklendi (aşağıda).

## Veritabanı Yedeği (pg_dump) — 2026-06-22 (D15-1)

Otomatik günlük PostgreSQL yedeği. **Bu modülden (UI) bağımsız**, altyapı seviyesinde çalışır.

- **Script:** `scripts/db-backup.sh` — `pg_dump -Fc` (sıkıştırılmış custom format) → `/var/backups/sprenses-db/sprenses-<ts>.dump`. Atomik yazım (`.tmp`→`mv`), **bütünlük doğrulaması** (`pg_restore --list`), **rotasyon** (son `SPRENSES_BACKUP_KEEP`=30 yedek). DB şifresi `.env`'deki `DATABASE_URL`'den (argümanda parola yok, `PGPASSWORD`).
- **Zamanlama:** `sprenses-db-backup.timer` (systemd) — her gün **03:00 Europe/Istanbul**, `Persistent=true` (kaçan koşum açılışta çalışır). Servis: `sprenses-db-backup.service` (`User=ec2-user`, oneshot).
- **Geri yükleme / tatbikat:** `scripts/db-restore.sh`
  - `scripts/db-restore.sh` → en son yedeği **geçici DB'ye** yükler + kritik tablo satır sayılarını basar + geçici DB'yi siler (**restore tatbikatı** — "yedek var ≠ çalışıyor"). Çeyrekte bir çalıştırılmalı.
  - `scripts/db-restore.sh <dump> sprenses` → **ÜRETİME** geri yükler (elle `EVET` onayı; `--clean --if-exists`, owner=sprenses md5 ile).
- **Off-site (OPSİYONEL, henüz pasif):** `SPRENSES_BACKUP_S3=s3://bucket/prefix` set edilirse `aws s3 cp --sse AES256` ile yüklenir. **Şu an kapalı** — EC2'de IAM role / aws credential YOK. Tam felaket-kurtarma (instance/disk kaybı) için S3 bucket + IAM role kurulup bu değişken servise (`/etc/systemd/system/sprenses-db-backup.service` `Environment=`) eklenmeli. Yerel yedek; yanlış DROP/DELETE, app bug ve veri bozulmasına karşı korur ama tek-disk kaybına karşı KORUMAZ → off-site tamamlanmalı.
- **Not:** `archive_mode=off` (PITR yok); küçük DB (~44 MB) için günlük tam-dump yeterli. PITR/RDS orta-vade.

## Genel Bilgi
- **Modül kodu:** `system.backup` (üst modül: `system`)
- **Frontend rota:** `/dashboard/sistem/yedekleme`
- **Backend prefix:** `/api/system/backup`
- **İzin:** `system.backup` — view (durum izleme), use (yedek + geri yükleme). Admin-only (Sunucu modülüyle aynı rollere verilir).
- **DB tablosu yok** — veri kaynağı **git'in kendisidir** (Sunucu modülü gibi salt-operasyon).

## Amaç
Kodun GitHub'daki (`finfdg/sprenses-otel`, private) yedek durumunu uygulama içinden
izlemek, **manuel yedek** almak (commit + push) ve gerektiğinde **geri yüklemek**.
Otomatik yedek `.claude/settings.json` Stop hook'u ile zaten alınır; bu modül
**görünürlük + manuel kontrol** ekler.

## Dosya Haritası
- Backend: `backend/app/routers/system_backup.py` (main.py'de `/api/system` altına mount)
- Frontend: `frontend/src/routes/dashboard/sistem/yedekleme/+page.svelte`
- Navigasyon: `frontend/src/lib/config/navigation.ts` → system grubu → `system.backup`

## API Endpoint'leri
| Method | Path | İzin | Açıklama |
|---|---|---|---|
| GET | `/api/system/backup/status` | view | Son commit, bekleyen değişiklik, ahead/behind, senkron, uzak URL, son 30 commit |
| POST | `/api/system/backup/run` | use | Değişiklik varsa commit (`Manuel yedek: …`) + GitHub'a push |
| POST | `/api/system/backup/restore` | use | Seçilen commit'e güvenli geri yükleme (aşağıda) |

## Geri Yükleme — Güvenli "İleri-Commit" Semantiği
**Geçmiş asla yeniden yazılmaz, force-push yapılmaz, hiçbir şey kaybolmaz:**
1. Mevcut commit'lenmemiş değişiklik varsa → önce otomatik yedeklenir.
2. Hedef commit'in dosyaları çalışma ağacına + index'e getirilir (`git checkout <commit> -- .`).
3. Fark varsa **yeni bir commit** olarak kaydedilir (`Geri yükleme: <hash> durumuna dönüldü`).
4. Push edilir.
5. **Kod değiştiği için yeniden deploy gerekir** (backend restart + frontend build) — yanıtta `redeploy_needed` ile bildirilir.

> Not: Bu yöntem hedef commit'teki dosya **içeriklerini** geri getirir; hedeften sonra
> eklenmiş yepyeni dosyalar silinmez (güvenlik için bilinçli). Tam eşitlik gerekirse
> manuel müdahale gerekir.

## Güvenlik
- **subprocess list-arg** ile (shell yok) → komut enjeksiyonu imkânsız.
- `restore` commit hash'i **yalnızca hex** kabul eder (`; rm -rf /` gibi girdiler 400 ile reddedilir).
- `git push` backend'den (`ec2-user`, gh credential-helper) çalışır; **`.env`/sırlar gitignore ile dışlanır**, yedeğe gitmez.
- Tüm yazma işlemleri **audit log**'a yazılır (`backup`, `restore` eylemleri, entity_type=`system_backup`).
- Admin-only izin (Sunucu modülüyle aynı güven sınırı).

## Frontend UI
- `ListPage` iskeleti: PageHeader + StatCard'lar (Son Yedek / Senkron Durumu / Yedek Deposu) + "Şimdi Yedekle" butonu + commit geçmişi tablosu.
- Geri yükleme: tabloda satır başına "Geri Yükle" → **danger `ConfirmDialog`** (güçlü uyarı: yeniden deploy gerekir, geri alınabilir).
- Polling yok; durum mount'ta ve her işlemden sonra tazelenir.

## Audit Log
- entity_type: `system_backup`
- Eylemler: `backup` (manuel yedek), `restore` (geri yükleme).

## Geliştirme Kuralları
- Bu modül **onay akışından muaftır** (Sunucu restart gibi salt-operasyon endpoint'i).
- Geri yükleme sonrası deploy **otomatik yapılmaz** (çalışan backend'in kendini mid-request restart etmesi riskli) — kullanıcı/operatör elle deploy eder.
