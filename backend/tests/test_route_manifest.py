"""API rota kümesi dondurma testi — yeniden yapılandırma (2026-09-02) davranış bekçisi.

`tests/fixtures/route_manifest.json` her rotanın (path, HTTP metotları, endpoint fonksiyon adı,
OpenAPI etiketleri) dörtlüsünü tutar. Router dosyaları paketlere taşınırken / bölünürken
HİÇBİR public API yolu, metodu ya da endpoint adı değişmemelidir; bu test onu ispatlar.

Bilinçli bir API değişikliğinde manifest yeniden üretilir:
    cd backend && venv/bin/python -m tests.test_route_manifest --regenerate
"""
import json
import sys
from pathlib import Path

MANIFEST = Path(__file__).parent / "fixtures" / "route_manifest.json"


def _current_manifest():
    from app.main import app

    rows = []
    for r in app.routes:
        path = getattr(r, "path", None)
        if path is None:
            continue
        methods = sorted(m for m in (getattr(r, "methods", None) or []) if m not in ("HEAD", "OPTIONS"))
        ep = getattr(r, "endpoint", None)
        name = getattr(ep, "__name__", r.__class__.__name__)
        tags = sorted(getattr(r, "tags", None) or [])
        rows.append({"path": path, "methods": methods, "endpoint": name, "tags": tags})
    rows.sort(key=lambda x: (x["path"], x["methods"], x["endpoint"]))
    return rows


def test_route_manifest_is_frozen():
    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))
    actual = _current_manifest()
    exp_keys = {(r["path"], tuple(r["methods"]), r["endpoint"]) for r in expected}
    act_keys = {(r["path"], tuple(r["methods"]), r["endpoint"]) for r in actual}
    missing = sorted(exp_keys - act_keys)
    extra = sorted(act_keys - exp_keys)
    assert not missing and not extra, (
        f"Rota kümesi değişti — kayıp: {missing[:10]} · yeni: {extra[:10]}. "
        "Bilinçli değişiklikse manifesti yeniden üret (modül docstring'i)."
    )
    exp_tags = {(r["path"], tuple(r["methods"])): r["tags"] for r in expected}
    act_tags = {(r["path"], tuple(r["methods"])): r["tags"] for r in actual}
    drift = [(k, exp_tags[k], act_tags[k]) for k in exp_tags if exp_tags[k] != act_tags.get(k)]
    assert not drift, f"OpenAPI etiketleri değişti: {drift[:10]}"


def test_route_manifest_has_no_duplicate_paths():
    from collections import Counter

    c = Counter((r["path"], tuple(r["methods"])) for r in _current_manifest())
    dups = [k for k, v in c.items() if v > 1]
    assert not dups, f"Aynı (path, metot) birden fazla kez kayıtlı: {dups[:10]}"


if __name__ == "__main__" and "--regenerate" in sys.argv:
    MANIFEST.write_text(json.dumps(_current_manifest(), ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"manifest yeniden üretildi: {MANIFEST}")
