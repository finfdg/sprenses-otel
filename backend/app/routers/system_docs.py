"""Sistem — Dokümanlar: proje .md dokümanlarını listele / görüntüle / indir (salt-okunur).

Kapsam: kök CLAUDE.md + docs/**/*.md + backend/app|frontend/src altındaki CLAUDE.md rehberleri.
Güvenlik: yol kullanıcı girdisiyle ASLA birleştirilip resolve edilmez — istenen `path` yalnızca
sunucu-tarafı izinli kümeyle BİREBİR eşleşirse servis edilir (path traversal imkânsız).
İzin: system.docs view. Salt-okunur → onay/audit kapsam dışı.
"""
import io
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from app.middleware.auth import require_permission
from app.models.user import User
from app.utils.md_docx import build_docs_docx

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # otel/ (proje kökü)
_EXCLUDE = {"node_modules", "venv", ".git", "build", ".svelte-kit", ".claude",
            ".pytest_cache", "__pycache__", "htmlcov"}

router = APIRouter()


def _category(rel: str) -> str:
    if rel.startswith("docs/modules/"):
        return "Modül Dokümanları"
    # Teknik denetim raporları + soru setleri → kendi grubu (keşfedilebilirlik)
    if rel.startswith("docs/denetim/"):
        return "Denetim Raporları"
    # Kök CLAUDE.md + docs/ kökündeki genel rehberler (ui-kurallari, modulerlik vb.) → tek grup
    if rel == "CLAUDE.md" or rel.startswith("docs/"):
        return "Genel Dokümanlar"
    if rel.endswith("CLAUDE.md"):
        return "Geliştirici Rehberleri"
    return "Diğer"


def _title(abspath: Path, rel: str) -> str:
    try:
        with abspath.open(encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("# "):
                    return s[2:].strip()
                if s and not s.startswith("#"):
                    break
    except Exception:
        pass
    return rel


# Modül kodu satırından (ör. "- **Modül kodu:** `finance.banks`") ilk backtick'li kodu çıkarır.
_CODE_RE = re.compile(r"`([a-z][a-z0-9_.]*)`")


def _module_code(abspath: Path):
    """Doküman başlığındaki modül kodunu çıkar (yoksa None).

    Öncelik: 'Modül kodu' satırı → yoksa 'Üst modül' (grup kodu) → yoksa 'Alt modüller'/'Modüller'
    satırının ilk kodu. Böylece Stok (Üst modül `stok`) / Yönetim Paneli (`yonetim`) gibi çok-modüllü
    dokümanlar da kod gösterir. Hepsinde ilk backtick'li token alınır (büyük/küçük harf duyarsız).
    """
    primary = parent = group = None
    try:
        with abspath.open(encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i > 150:
                    break
                low = line.lower()
                if primary is None and "modül kod" in low:
                    m = _CODE_RE.search(line)
                    if m:
                        primary = m.group(1)
                elif parent is None and "üst modül" in low:
                    m = _CODE_RE.search(line)
                    if m:
                        parent = m.group(1)
                elif group is None and ("alt modül" in low or "modüller" in low):
                    m = _CODE_RE.search(line)
                    if m:
                        group = m.group(1)
    except Exception:
        pass
    return primary or parent or group


def _walk():
    """İzinli .md dosyaları: (relpath, abspath) — sıralı, tekilleştirilmiş."""
    found: dict = {}
    root_claude = ROOT / "CLAUDE.md"
    if root_claude.is_file():
        found["CLAUDE.md"] = root_claude
    docs = ROOT / "docs"
    if docs.is_dir():
        for p in docs.rglob("*.md"):
            if any(part in _EXCLUDE for part in p.parts):
                continue
            found[str(p.relative_to(ROOT))] = p
    for base in ("backend/app", "frontend/src"):
        bp = ROOT / base
        if bp.is_dir():
            for p in bp.rglob("CLAUDE.md"):
                if any(part in _EXCLUDE for part in p.parts):
                    continue
                found[str(p.relative_to(ROOT))] = p
    return sorted(found.items())


def _resolve(path: str):
    """İstenen relpath izinli kümede mi → abspath; değilse None (traversal koruması)."""
    return dict(_walk()).get(path)


@router.get("/")
def list_documents(_: User = Depends(require_permission("system.docs", "view"))):
    items = []
    for rel, p in _walk():
        try:
            st = p.stat()
        except OSError:
            continue
        items.append({
            "path": rel,
            "title": _title(p, rel),
            "module_code": _module_code(p),
            "category": _category(rel),
            "size": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        })
    return {"items": items, "total": len(items)}


@router.get("/raw")
def doc_raw(path: str = Query(..., max_length=300),
            _: User = Depends(require_permission("system.docs", "view"))):
    p = _resolve(path)
    if not p or not p.is_file():
        raise HTTPException(status_code=404, detail="Doküman bulunamadı")
    return {"path": path, "title": _title(p, path), "content": p.read_text(encoding="utf-8")}


@router.get("/download")
def doc_download(path: str = Query(..., max_length=300),
                _: User = Depends(require_permission("system.docs", "view"))):
    p = _resolve(path)
    if not p or not p.is_file():
        raise HTTPException(status_code=404, detail="Doküman bulunamadı")
    fname = path.replace("/", "_")
    return FileResponse(
        str(p), media_type="text/markdown; charset=utf-8", filename=fname,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/export/word")
def doc_export_word(_: User = Depends(require_permission("system.docs", "view"))):
    files = [(rel, p.read_text(encoding="utf-8")) for rel, p in _walk()]
    buf = build_docs_docx(files)
    return StreamingResponse(
        io.BytesIO(buf),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="Sprenses-Dokumanlar.docx"'},
    )
