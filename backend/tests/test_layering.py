"""Katman yönü bekçisi — 2026-09-02 yeniden yapılandırmasının kalıcı kuralı (AST tabanlı).

İzin verilen bağımlılık yönü (CLAUDE.md "Katman yönü"):

    routers → approval → services → (integrations | parsers | realtime | utils) → models

- `app/services`, `app/utils`, `app/approval`, `app/integrations`, `app/parsers`, `app/realtime`
  hiçbir yerde (fonksiyon içi lazy import dahil) `app.routers` import ETMEZ.
- `app/utils`, `app/integrations`, `app/parsers` → `app.services` / `app.approval` import ETMEZ
  (teknik yardımcı ve dış istemciler domain mantığına bağımlı olamaz).
- Eski `app.utils.<taşınan-modül>` yolları depoda hiçbir yerde kalmaz (shim yok; taşınma kalıcı).

Bilinen ve İZİN VERİLEN istisnalar `_ALLOWED_ROUTER_IMPORTERS` içinde açıkça listelenir; bir istisna
kapanınca listeden düşülür (liste boşalınca bekçi tam güçtür).
"""
import ast
from pathlib import Path

from app import paths

APP = paths.APP_DIR
BACKEND = paths.BACKEND_DIR
REPO = paths.REPO_ROOT

# services→routers ihlali: finansal parmak-izi değişmez kaydı, router iç fonksiyonlarını ölçüm için
# çağırır. Kapanışı: o hesapların servislere çıkarılması (yeniden yapılandırma Faz 3, fingerprint-kapılı).
_ALLOWED_ROUTER_IMPORTERS = {
    "services/audit_finance_invariants.py",
}

# app/utils'ten taşınan modüller (2026-09-02) — eski yol hiçbir yerde kalmamalı
_MOVED_FROM_UTILS = {
    "matching_service", "finance_event_service", "auto_tagger", "vendor_fifo", "sync_vendor_fifo",
    "recurring_vendor_sync", "entry_generator", "kmh_calculator", "occupancy", "fx_rates",
    "approval_check", "approval_service", "approval_executor",
    "sedna_client", "tcmb", "amadeus_client", "garanti_api", "qnb_api", "yapikredi_api",
    "vakifbank_client", "mail",
    "bank_parser", "bank_parse_helpers", "cc_statement_parser", "check_parser",
    "reservation_parser", "vendor_parser",
    "finance_broadcast", "sales_broadcast", "notification", "push",
}


def _imports_of(py: Path):
    """Dosyadaki TÜM import hedeflerini (modül düzeyi + fonksiyon içi) noktalı ad olarak üret."""
    tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module, node.lineno


def _py_files(*subdirs):
    for d in subdirs:
        for py in (APP / d).rglob("*.py"):
            yield py


def _violations(subdirs, forbidden_prefixes, allowed=frozenset()):
    out = []
    for py in _py_files(*subdirs):
        rel = py.relative_to(APP).as_posix()
        if rel in allowed:
            continue
        for mod, line in _imports_of(py):
            if any(mod == p or mod.startswith(p + ".") for p in forbidden_prefixes):
                out.append(f"{rel}:{line} → {mod}")
    return out


def test_no_layer_imports_routers():
    """services/utils/approval/integrations/parsers/realtime hiçbir yerde app.routers import etmez."""
    bad = _violations(
        ("services", "utils", "approval", "integrations", "parsers", "realtime"),
        ("app.routers",),
        allowed=_ALLOWED_ROUTER_IMPORTERS,
    )
    assert not bad, "Katman ihlali (→ app.routers):\n  " + "\n  ".join(bad)


def test_allowed_router_importers_still_need_the_exception():
    """İstisna listesi bayatlamasın: listedeki dosya artık router import etmiyorsa listeden düş."""
    stale = []
    for rel in _ALLOWED_ROUTER_IMPORTERS:
        py = APP / rel
        assert py.is_file(), f"istisna listesindeki dosya yok: {rel}"
        if not any(m.startswith("app.routers") for m, _ in _imports_of(py)):
            stale.append(rel)
    assert not stale, f"İstisna artık gereksiz — listeden düş: {stale}"


def test_technical_layers_do_not_import_domain():
    """utils/integrations/parsers → services/approval bağımlılığı yok."""
    bad = _violations(("utils", "integrations", "parsers"), ("app.services", "app.approval"))
    assert not bad, "Teknik katman domain'e bağımlı olamaz:\n  " + "\n  ".join(bad)


def test_no_stale_app_utils_paths_anywhere():
    """Taşınan modüllerin eski `app.utils.<ad>` / `app/utils/<ad>` yolu depoda kalmadı (tarihsel raporlar hariç)."""
    roots = [BACKEND / "app", BACKEND / "tests", BACKEND, REPO / "scripts", REPO / "docs", REPO / "CLAUDE.md",
             REPO / ".claude" / "agents", REPO / ".claude" / "commands"]
    skip_parts = {"venv", "node_modules", "__pycache__", ".git", "worktrees", "denetim"}
    hits = []
    names = "|".join(sorted(_MOVED_FROM_UTILS))
    import re
    pat = re.compile(rf"app[./]utils[./](?:{names})\b")
    for root in roots:
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file() and p.suffix in (".py", ".md", ".sh", ".txt")]
        for f in files:
            if f.is_relative_to(BACKEND) and f.parent != BACKEND and not any(f.is_relative_to(BACKEND / d) for d in ("app", "tests")):
                continue
            if any(part in skip_parts for part in f.parts):
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if pat.search(line):
                    hits.append(f"{f.relative_to(REPO)}:{i}")
    assert not hits, "Eski app.utils yolu kaldı:\n  " + "\n  ".join(hits[:30])
