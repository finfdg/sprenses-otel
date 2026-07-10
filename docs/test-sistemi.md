# Test Sistemi

> CLAUDE.md kökünden taşındı (2026-07-10, bağlam inceltme). Çalıştırma komutlarının özeti kökte;
> kurulum, altyapı notları ve test envanteri burada tutulur. `/test` slash komutu doğru akışı bilir.

## Backend (pytest)

```bash
# DATABASE_URL TEST DB'sine işaret etmeli — adı '_test' içermeli (örn: sprenses_test)
cd backend && source venv/bin/activate
export DATABASE_URL=postgresql://sprenses:PASS@127.0.0.1:5432/sprenses_test
python -m pytest tests/ -v

# Coverage raporu (pytest-cov):
python -m pytest tests/ --cov=app --cov-report=term --cov-report=html
# → htmlcov/index.html — dosya bazlı satır kapsamı
```

**Test DB kurulumu (ilk kullanım):**
```bash
sudo -u postgres psql -c "CREATE DATABASE sprenses_test OWNER sprenses;"
PGPASSWORD=PASS pg_dump -h 127.0.0.1 -U sprenses --schema-only sprenses \
  | PGPASSWORD=PASS psql -h 127.0.0.1 -U sprenses -d sprenses_test
PGPASSWORD=PASS pg_dump -h 127.0.0.1 -U sprenses --data-only \
  --table=users --table=roles --table=modules --table=role_module_permissions \
  --table=departments --table=transaction_categories sprenses \
  | PGPASSWORD=PASS psql -h 127.0.0.1 -U sprenses -d sprenses_test
```

**Test altyapı notları:**
- Token çıkarma: `conftest.py` içindeki `extract_token(response)` helper'ı HttpOnly cookie'den token alır
- Test ortamında `CORS_ORIGINS=http://testserver` set edilir → `secure=False` cookie → TestClient cookie geri döner
- Rate limiter'lar her test öncesi otomatik sıfırlanır (`autouse` fixture)
- **Test DB izolasyonu zorunlu:** `conftest.py` `DATABASE_URL` set edilmemişse veya adı `_test` içermiyorsa testleri durdurur. Bilerek prod-benzeri DB kullanılacaksa `ALLOW_PROD_DB_TESTS=1` ile bypass edilir (önerilmez).
- **Onay akışı sigortası:** `_disable_admin_approval_workflows` autouse fixture'ı her test başında admin rolünün requestor olduğu aktif workflow'ları SAVEPOINT içinde deaktive eder — CRUD testlerinin onay akışı yüzünden sessizce 202'ye düşmesini engeller. Onay akışını test edenler kendi workflow'larını yarattığı için etkilenmez.
- **Non-admin test fixture'ları:** `viewer_user_headers` (sadece `can_view`), `use_user_headers` (`can_view+can_use`), `no_perm_user_headers` (hiç izin yok), `make_user_with_perms({module: {view, use}})` factory — admin-dışı izin matrisi davranışını test etmek için. Her fixture yeni `Role` + `User` oluşturup login ederek auth header döner; test bitince SAVEPOINT rollback'i ile temizlenir.
- **pg_hba.conf:** `sprenses_test` DB için ayrı bir `host ... md5` satırı `/var/lib/pgsql/data/pg_hba.conf`'ta tanımlıdır (yoksa ident auth'a düşer, fail eder).

## Frontend (Vitest)

```bash
cd frontend && npx vitest run
```

**Test dosyaları (329 test, 25 dosya — `npx vitest run` koşusuyla doğrulandı, 2026-07-10):**

*API & utils:*
- `src/lib/api.test.ts` — API wrapper (GET/POST/PATCH/DELETE, upload, hata yönetimi, 401/403, signal, fetchRaw) (22 test)
- `src/lib/utils/finance.test.ts` — formatCurrency, formatCompact, groupByMonth, getTodayKeys, monthKeysToDateRange, transfer hariç tutma (48 test)
- `src/lib/utils/cashflow.test.ts` — aggregateRows (kredi/çek ayrı · cari firma-bazlı toplu · members bekletme kimliği), daySourceRank gün içi öncelik, AGGREGATE_LABELS (15 test)
- `src/lib/utils/paymentMethods.test.ts` — PAYMENT_METHODS, SELECTABLE, CATEGORIES, getPaymentMethod fallback (16 test)
- `src/lib/utils/colorMap.test.ts` — categoryColorMap, filterColorMap, availableColors, getColor fallback (16 test)
- `src/lib/utils/validation.test.ts` — validateEmail, validatePassword, validateRequired, validateModuleCode (12 test)
- `src/lib/utils/push.test.ts` — isPushSupported, getPushPermissionState (6 test)
- `src/lib/utils/lazy-mount.test.ts` — tembel mount görünürlük gözlemcisi (7 test)
- `src/lib/constants/finance.test.ts` — Kaynak tipleri, ödeme yöntemleri, kredi tipleri, para birimleri, sabit tutarlılığı (17 test)

*Store'lar:*
- `src/lib/stores/auth.test.ts` — setAuth, loadAuth, hasPermission (izin matrisi) (15 test)
- `src/lib/stores/toast.test.ts` — showToast, removeToast, otomatik kaldırma (12 test)
- `src/lib/stores/notification.test.ts` — setMutedConversations, updateMutedConversation, isConversationMuted, toggleSound (11 test)
- `src/lib/stores/ui.test.ts` — sidebar state, toggleSidebar, closeSidebar (6 test)
- `src/lib/stores/cashflow.test.ts` — isEurBalancesStale, finance_updated geçersizlemesi, invalidateCashFlowCache (7 test)

*Bileşenler:*
- `src/lib/components/MoneyInput.test.ts` — formatTR/parseTR/formatLiveTR/round-trip + imleç/highlight (33 test)
- `src/lib/components/Pagination.test.ts` — getPageNumbers (windowed), sayfa boyutu (16 test)
- `src/lib/components/FileDropzone.test.ts` — drag-drop, MIME/boyut doğrulama, çoklu dosya (14 test)
- `src/lib/components/SortableHeader.test.ts` — sıralama yönü/ikon (11 test)
- `src/lib/components/EmptyState.test.ts` — ikon/başlık/açıklama/CTA (9 test)
- `src/lib/components/StatusBadge.test.ts` — semantik durum renkleri (8 test)
- `src/lib/components/Breadcrumb.test.ts` — kırılım üretimi (6 test)
- `src/lib/components/TableSkeleton.test.ts` — satır/kolon iskeleti (6 test)
- `src/lib/components/FormSkeleton.test.ts` — form iskeleti (5 test)
- `src/lib/components/BulkActionsBar.test.ts` — toplu seçim/aksiyon barı (5 test)
- `src/lib/components/PdfPreviewModal.test.ts` — iOS Safari uyumlu PDF önizleme modalı (açma/kapama, blob URL yaşam döngüsü, Esc, backdrop) (6 test)
