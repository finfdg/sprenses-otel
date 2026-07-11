"""AST BEKÇİSİ — yayınsız mutasyon endpoint'i sözleşmesi (Faz 2 #15, 2026-07-12).

Kural: `app/routers/{finance,sales,accounting,hr}` altındaki HER `@router.post/patch/
put/delete` endpoint'i şu ÜÇÜNDEN birini sağlamalıdır:

(a) Gövdesinde WS yayını çağrısı: `broadcast_finance_update` / `broadcast_sales_update` /
    `notify_finance_update_sync`.
(b) `finance_event_svc` kullanımı — kendisi veya çağırdığı AYNI DOSYADAKİ bir yardımcı
    (1 seviye). FE'ye yazan her yol after_commit YAYIN SİGORTASI ile otomatik yayınlar
    (finance_event_service._flush_ws_modules) → ayrıca elle broadcast şart değildir.
(c) Aşağıdaki WHITELIST'te bilinçli istisna olarak kayıtlıdır (tek satır gerekçeyle).

YENİ eklenen yayınsız mutasyon bu testi KIRAR — amaç, açık ekranların sessizce bayat
kalmasına yol açan "broadcast unutuldu" sınıfını kalıcı engellemektir. Whitelist'e girmeden
önce endpoint'in gerçekten yayın gerektirmediğinden (PDF/salt-doğrulama/metadata) veya
yayının ithal edilen domain modülünde yapıldığından emin ol.

Whitelist çift yönlü denetlenir: ihlal etmeyen (sonradan düzeltilen) girişler de testi
kırar → liste bayatlamaz.
"""
import ast
import os

BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "app", "routers")
PACKAGES = ("finance", "sales", "accounting", "hr")
MUTATION_METHODS = {"post", "patch", "put", "delete"}
BROADCAST_FUNCS = {
    "broadcast_finance_update",
    "broadcast_sales_update",
    "notify_finance_update_sync",
}

# ── WHITELIST — bilinçli istisnalar (dosya:fonksiyon → tek satır gerekçe) ──────────
# Her giriş tarama anındaki gerçek bir ihlale karşılık gelir; endpoint sonradan yayın
# kazanırsa giriş buradan SİLİNMELİDİR (test bunu da zorlar).
WHITELIST = {
    # PDF üretimi — DB'de finansal veri değişmez, yalnız talimat PDF'i döner
    "finance/bank_instructions.py:create_transfer_instruction":
        "PDF üretimi (talimat çıktısı; veri mutasyonu yok)",
    "finance/bank_instructions.py:create_currency_exchange_instruction":
        "PDF üretimi (talimat çıktısı; veri mutasyonu yok)",
    # Dosya yükleme — yayın + FE ithal edilen domain modülünde
    "finance/banks.py:upload_statement_auto":
        "yayın/FE bank_statement_import._post_upload_processing'te (paket-içi domain modülü)",
    "finance/banks.py:upload_statement":
        "yayın/FE bank_statement_import._post_upload_processing'te (paket-içi domain modülü)",
    # Departman metadata — FE yazmaz; onaylı değişiklik requests._EXECUTED_MODULE_EVENTS
    # (finance.departmanlar → BUTCE) ile yayınlanır, doğrudan CRUD yayın taşımaz (bilinçli)
    "finance/departmanlar.py:create_department":
        "service-katmanlı departman metadata CRUD (nakit akım/FE etkisi yok)",
    "finance/departmanlar.py:update_department":
        "service-katmanlı departman metadata CRUD (nakit akım/FE etkisi yok)",
    "finance/departmanlar.py:delete_department":
        "service-katmanlı departman metadata CRUD (nakit akım/FE etkisi yok)",
    # Ödeme talimatı çalışma listeleri — operasyonel liste/PDF hazırlığı; FE'ye yazmaz
    "finance/payment_instructions.py:create_instruction_list":
        "ödeme talimatı çalışma listesi (operasyonel; finance_events'e yazmaz)",
    "finance/payment_instructions.py:update_instruction_list":
        "ödeme talimatı çalışma listesi (operasyonel; finance_events'e yazmaz)",
    "finance/payment_instructions.py:delete_instruction_list":
        "ödeme talimatı çalışma listesi (operasyonel; finance_events'e yazmaz)",
    "finance/payment_instructions.py:add_items":
        "ödeme talimatı kalem yönetimi (operasyonel; finance_events'e yazmaz)",
    "finance/payment_instructions.py:update_item":
        "ödeme talimatı kalem yönetimi (operasyonel; finance_events'e yazmaz)",
    "finance/payment_instructions.py:delete_item":
        "ödeme talimatı kalem yönetimi (operasyonel; finance_events'e yazmaz)",
    # Merkezi Sedna senkronu — endpoint hemen döner; adım yayınları arka plan işinde
    # (run_sync_all_steps adım-anında notify_finance_update_sync çağırır — 2. seviye)
    "finance/sedna_sync.py:sedna_sync_all":
        "arka-plan job adım-anında yayınlar (run_sync_all_steps; 1-seviye kuralın dışında)",
    # Kategori metadata — kategori LİSTESİ değişimi; etiketleme yayını tag endpoint'lerinde
    "finance/transaction_tags.py:create_category":
        "kategori metadata oluşturma (nakit akım kalemi değişmez)",
    # FE senkronu ithal auto_tagger._sync_finance_events'te → after_commit sigortası yayınlar
    "finance/transaction_tags.py:run_auto_match_vendors":
        "FE senkronu utils/auto_tagger içinde (after_commit sigortası yayınlar)",
    # Salt doğrulama — token/hesap listesi testi, DB'ye yazmaz
    "finance/vakifbank.py:vakifbank_test_connection":
        "salt-doğrulama (VakıfBank token testi; DB mutasyonu yok)",
    # Cari IBAN defteri — talimat PDF verisi/metadata; nakit akım/FE etkisi yok
    "finance/cariler/bank_accounts.py:add_bank_account":
        "cari IBAN defteri metadata (nakit akım/FE etkisi yok)",
    "finance/cariler/bank_accounts.py:update_bank_account":
        "cari IBAN defteri metadata (nakit akım/FE etkisi yok)",
    "finance/cariler/bank_accounts.py:delete_bank_account":
        "cari IBAN defteri metadata (nakit akım/FE etkisi yok)",
}


# ── AST tarayıcı ───────────────────────────────────────────────────────────────────

def _decorated_mutation_method(fn):
    """@<router>.post/patch/put/delete dekoratörü varsa HTTP metodunu döndür."""
    for dec in fn.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and target.attr in MUTATION_METHODS:
            return target.attr
    return None


def _names_used(node):
    """Fonksiyon gövdesinde geçen çağrı/isim adları (Name + Attribute attr'ları)."""
    names = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            names.add(n.id)
        elif isinstance(n, ast.Attribute):
            names.add(n.attr)
    return names


def _satisfies_contract(names):
    """(a) broadcast çağrısı veya (b) finance_event_svc kullanımı var mı?"""
    return bool(names & BROADCAST_FUNCS) or "finance_event_svc" in names


def _scan_violations():
    """4 router paketindeki tüm yayınsız mutasyon endpoint'lerini bul."""
    violations = []
    for pkg in PACKAGES:
        pkg_dir = os.path.abspath(os.path.join(BASE_DIR, pkg))
        assert os.path.isdir(pkg_dir), f"router paketi bulunamadı: {pkg_dir}"
        for dirpath, _dirs, files in os.walk(pkg_dir):
            for fname in sorted(files):
                if not fname.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fname)
                rel = os.path.relpath(path, os.path.abspath(BASE_DIR)).replace(os.sep, "/")
                with open(path, encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=path)

                # Aynı dosyadaki TÜM fonksiyonlar (1-seviye yardımcı araması için)
                module_funcs = {}
                for n in ast.walk(tree):
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        module_funcs.setdefault(n.name, n)

                for n in ast.walk(tree):
                    if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    method = _decorated_mutation_method(n)
                    if method is None:
                        continue
                    names = _names_used(n)
                    ok = _satisfies_contract(names)
                    if not ok:
                        # 1 seviye: gövdede adı geçen aynı-dosya yardımcıları
                        for called in names:
                            helper = module_funcs.get(called)
                            if helper is not None and helper is not n:
                                if _satisfies_contract(_names_used(helper)):
                                    ok = True
                                    break
                    if not ok:
                        violations.append(f"{rel}:{n.name}")
    return sorted(set(violations))


# ── Testler ──────────────────────────────────────────────────────────────────────

def test_all_mutation_endpoints_broadcast_or_whitelisted():
    """Yeni yayınsız POST/PATCH/PUT/DELETE endpoint'i eklenemez (Faz 2 #15 sözleşmesi)."""
    violations = _scan_violations()
    unlisted = [v for v in violations if v not in WHITELIST]
    assert unlisted == [], (
        "Yayınsız mutasyon endpoint'i bulundu — ya broadcast_finance_update/"
        "broadcast_sales_update/notify_finance_update_sync çağır, ya finance_event_svc "
        "ile FE'ye yaz (after_commit sigortası yayınlar), ya da GERÇEK istisna ise "
        "tests/test_broadcast_guard.py WHITELIST'ine gerekçeli satır ekle:\n  - "
        + "\n  - ".join(unlisted)
    )


def test_whitelist_has_no_stale_entries():
    """Whitelist bayatlamaz: artık ihlal olmayan (yayın kazanan/silinen) giriş kaldırılmalı."""
    violations = set(_scan_violations())
    stale = [w for w in WHITELIST if w not in violations]
    assert stale == [], (
        "Whitelist girişleri artık ihlal değil (endpoint yayın kazandı veya kaldırıldı) — "
        "şu satırları WHITELIST'ten sil:\n  - " + "\n  - ".join(stale)
    )


def test_scanner_sees_known_broadcasting_endpoint():
    """Tarayıcı sağlık kontrolü: bilinen yayınlı endpoint ihlal DEĞİL, bilinen istisna
    whitelist kapsamında (tarayıcı bozulursa test sessizce her şeyi geçirmesin)."""
    violations = set(_scan_violations())
    # banks.py hesap CRUD'u broadcast_finance_update çağırır → ihlal listesinde olmamalı
    assert not any(v.startswith("finance/banks.py:create_account") for v in violations)
    # vakifbank test-connection bilinen istisna — tarayıcı onu görmeye devam etmeli
    assert "finance/vakifbank.py:vakifbank_test_connection" in violations
