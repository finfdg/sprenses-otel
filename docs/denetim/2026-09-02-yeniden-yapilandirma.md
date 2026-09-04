# 2026-09-02 — Kod Tabanı Yeniden Yapılandırması (davranış korunumlu)

**İstek:** "tüm kod tabanını yeniden yapılandır". **Yaklaşım:** CLAUDE.md'nin kendi mimari kurallarını
(router → service → model; utils = teknik / services = domain; tasarım-sistemi bileşen taksonomisi) fiziksel
yapıya işlemek — **API yolu, DB şeması, UI davranışı ve hiçbir finansal sayı değişmeden.** İzole worktree
(`restructure/2026-09-02`), her faz ayrı commit, her faz test-yeşil.

## Doğrulama kapıları

| Kapı | Sonuç |
|---|---|
| pytest (2 050+ test) | kırmızı kümesi master taban çizgisiyle **birebir aynı** (15 önceden-var-olan + 2 worktree-ortam), yeni kırmızı **0** |
| Rota manifesti (`tests/test_route_manifest.py`, 465 rota: yol+metot+endpoint+etiket) | değişmedi |
| svelte-check / vitest | 0 hata / 363 (+yeni) yeşil |
| Finansal parmak izi (`denetim_finans_parmak_izi.py`, 41 değişmez, canlı DB, A=master/B=branch/A2) | **41/41 birebir** (2026-09-02 13:01 Faz 0–2b sonrası **ve** 2026-09-04 13:08 Faz 4c sonrası — her ikisi 41/41) |
| Katman bekçisi (`tests/test_layering.py`, AST) | ihlal 0, istisna listesi BOŞ (`audit_finance_invariants.py` Faz 4c'de servisleri çağırır hâle geldi) |

## Fazlar

| Faz | Commit | İçerik |
|---|---|---|
| 0 | `2866ef4` | `app/paths.py` merkezi yol sabitleri (15 modüldeki `__file__` derinliği hesabı kaldırıldı) + `tests/test_paths.py` + rota manifesti |
| 1 | `4bfe010` | `app/utils` bölündü: 10 domain modülü → `services/`, onay motoru → `approval/`, 8 dış istemci → `integrations/`, 6 parser → `parsers/`, 4 yayın modülü → `realtime/`; 178 dosya, shim yok; `tests/test_layering.py` |
| 2a | `a29aebe` | `bank_statement_import` / `check_import` (router kılığındaki servisler) → `services/*_service.py` |
| 2b | `1481506` | `source_type` sabitleri tek kaynak (`constants.py` literal'leri `finance_event` re-export'una çevrildi) + `tests/test_constants.py` |
| 2c | `3533c7f` | Doğrulanmış ölü kod: 8 şema sınıfı, `schemas/pagination.py`, 7 `cash_flow/_helpers` builder'ı, `krediler/__init__` bayat re-export, `pj.txt` |
| 3a | `9313b7d` | Frontend `lib/components` → `ui/ layout/ dashboard/ ai/ scheduled/ finance/cash-flow/`; 456 import, 11 doküman |
| 3b | `3947d27` | Üst-düzey router'lar paketlere: `system/ core/ ai/ common/ hr/` (+shifts/shift_schedule); `main.py` 13 include; etiket/önek birebir |
| 3c | `88a7896` | Frontend `stores/messaging/` (4 utils özellik modülü + store) ve `stores/cashflow/` (cache + runway) |
| 3d | `e4279a5` | Frontend tek-kaynak sabitler (`TRANSFER_CATEGORIES`), `SOURCE_CASH_FLOW` ve `requiredModuleForPath` ölü kod |
| 4a | `822d794` | Depo kökü hijyeni: **public'e sızan** `frontend/static/borcluluk_varlik_raporu_22052026.pdf` ve `incoming/*.xlsx` git'ten kaldırıldı; 3 kök zip → `docs/tasarim/`; `.gitignore` veri bloğu |
| 4b | `d1ebeb2` · 4c `2cd42ca` | Finans router çekirdekleri → `services/` (t_account, runway, bank_snapshot, eur_balances, aging, credit summary/list, checks summary, vendors summary/detail/analytics, payment_schedule, mutabakat/sales/advances summary) — verbatim, router re-export; `audit_finance_invariants.py` import'ları servislere çevrildi |
| 5 | `4940079` · 5b `8f21cc9` | Dokümantasyon: CLAUDE.md Proje Yapısı + Katman yönü, `docs/proje-yapisi.md`, `docs/README.md`, `README.md`, `docs/denetim/README.md`, kısa-biçim bayat yollar |

## Eski → yeni yol tablosu

Bkz. [`docs/denetim/README.md`](README.md) (özet tablo) ve [`docs/proje-yapisi.md`](../proje-yapisi.md).
Tam dosya-düzeyi harita: `git log --diff-filter=R --summary master..restructure/2026-09-02` (tüm taşımalar `git mv` ile, geçmiş korunur).

## Bilinçli olarak YAPILMAYANLAR (davranış/ops riski → sahibinin kararı)

- **cron script'leri `backend/jobs/` paketine taşınmadı** — 5 canlı systemd birimi (4'ü /etc'de, git'te DEĞİL) dosya adlarını sabitliyor; `cron_denetim_auto.py` DEPLOY_BLOCKERS kendi yolunu sayıyor. Taşıma yalnız shim + `sudo` birim güncellemesiyle mümkün.
- **`tests/` alt klasörlere gruplanmadı** — pytest node id'leri ~30 dokümanda; değer/çürütme oranı düşük.
- **Frontend dev sayfa ayrıştırmaları** (cariler 2211, ReservationsPanel 2071, mutabakat 1726, krediler 1469, KontratlarPanel, ScheduledModule, onay-akisi, bankalar, nakit-akim, devam-takip, denetim, butce) — davranış taşıyan (EUR konsolidasyon, echo-guard, $effect izleme) çıkarımlar; golden-test'li ayrı iş olarak `docs/denetim/2026-09-02-yeniden-yapilandirma.md` §Takip'te.
- **Türkçe modül adları** (butce, departmanlar, onay, hakedis, cariler, krediler) İngilizce'ye çevrilmedi — URL önekleri zaten donmuş, ~150 doküman/whitelist düzenlemesi sıfır çalışma-zamanı fayda.
- **İki `_event_eur` çekirdeği (t_account vs runway) birleştirilmedi** — farklı guard semantiği (None vs `<= 1.0`), parmak-izi değişmezi; birleştirme ayrı kapılı karar.
- **`finance/CLAUDE.md` (2 904 satır) changelog'a bölünmedi** — sahibinin kararı.
- **Stop-hook auto-commit daraltılmadı** (`git add -A` + push) — her kök belgeyi GitHub'a taşıyan kök neden; policy kararı.

## Yan bulgular (yeniden yapılandırma DIŞI, aksiyon ister)

1. **FİNANSAL:** canlı `finance_events`'te 23 bayat TRY kaydı (₺2 238 007,97; hepsi açık → T-Hesap/runway/aging'e yansıyor) + 4 USD kayıt `amount_try` NULL (id 22944-22947). FIN-001 sınıfı 2026-07-25 düzeltmesinden sonra yeniden oluşmuş: `fix_stale_amount_try.py --apply` / `backfill_usd_amount_try.py --apply` kararı ve yazıcı yolunun (`finance_event_service._upsert`) düzeltilmesi.
2. **GÜVENLİK:** `borcluluk_varlik_raporu_22052026.pdf` 2026-06-02'den beri public repo + kimlik doğrulamasız URL'de; git geçmişinde hâlâ var → `git filter-repo` + force-push kararı (tüm hash'ler yine değişir).
3. **Çakışan WIP:** `.claude/worktrees/intelligent-sutherland-eaa958` içinde commit'lenmemiş KMH "canlı kalan" özelliği (krediler/_helpers.py, products.py, summary.py, credit_service.py, test_kmh.py — +282 satır) — Faz 4b aynı dosyaları servislere taşıdığı için o WIP yeni düzene yeniden uygulanmalı.
4. `cron_weekly_push.py` ve 3 banka API fetcher'ı zamanlanmamış (belgeler aksini söylüyor); `tesseract` kurulu değil (OCR dalı ölü, tessdata 8,6 MB); 8 eski Claude worktree'si + 6 `denetim/*` dalı temizlenebilir; `scratchpad/` (191 MB müşteri belgesi) repo dışına taşınmalı.
