"""CI lint/tip kapısı regresyon testi — QUAL-001 (v4 denetim, Boyut 2 — Kod Kalitesi).

Bulgu: Lint/tip denetimi hiçbir kapıda koşmuyordu — ruff/svelte-check CI'da yok.
Kapanış kriteri: CI'da lint/tip adımı koşuyor ve hata durumunda kırmızı veriyor.

Bu test, `.github/workflows/ci.yml` içinde bloklayıcı lint/tip kapısının
(backend ruff + frontend svelte-check) varlığını zorunlu kılar. Kapı silinirse
veya zayıflatılırsa (ör. `continue-on-error`, `|| true` ile hata yutulursa) test
KIRMIZI'ya döner. Böylece QUAL-001'in geri dönüşü yakalanır.
"""

import os
import re

# backend/tests/ -> proje kökü (iki üst) -> .github/workflows/ci.yml
CI_YML = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", ".github", "workflows", "ci.yml"
    )
)


def _ci_text() -> str:
    assert os.path.exists(CI_YML), f"CI iş akışı bulunamadı: {CI_YML}"
    return open(CI_YML, encoding="utf-8").read()


def test_ci_has_lint_job():
    """CI'da ayrı bir lint/tip işi tanımlı olmalı."""
    text = _ci_text()
    assert re.search(r"^\s{2}lint:", text, re.MULTILINE), (
        "ci.yml içinde 'lint:' işi yok — lint/tip kapısı kaldırılmış (QUAL-001 geri döndü)."
    )


def test_ci_runs_ruff_critical_gate():
    """Backend tarafı: ruff, kritik hata kurallarıyla koşmalı.

    'ruff check' + gerçek-hata select kümesi (E9/F63/F7/F82) aranır. Kural kümesi
    tümüyle silinirse ya da komut kaldırılırsa test kırmızıya döner.
    """
    text = _ci_text()
    assert re.search(r"ruff\s+check\b", text), (
        "ci.yml 'ruff check' adımını içermiyor — backend lint kapısı yok."
    )
    # Kritik gerçek-hata kuralları select edilmeli (E9 sözdizimi + F82 tanımsız ad
    # en az bunlar). Bunlar 'hata durumunda kırmızı'yı sağlayan çekirdek.
    for rule in ("E9", "F82"):
        assert re.search(rf"--select[^\n]*{rule}\b", text), (
            f"ruff kritik kural '{rule}' select edilmemiş — kapı gerçek hataları yakalamaz."
        )


def test_ci_runs_svelte_check():
    """Frontend tarafı: svelte-check tip denetimi koşmalı (ön koşulu sync ile).

    svelte-check '.svelte-kit/tsconfig.json' olmadan yanlış-kırmızı verir; bu yüzden
    'svelte-kit sync' ön adımı da zorunlu tutulur.
    """
    text = _ci_text()
    assert re.search(r"npm run check|svelte-check", text), (
        "ci.yml svelte-check (npm run check) adımını içermiyor — frontend tip kapısı yok."
    )
    assert re.search(r"svelte-kit sync", text), (
        "ci.yml 'svelte-kit sync' ön adımını içermiyor — svelte-check CI'da yanlış-kırmızı verir."
    )


def test_ci_lint_gate_is_blocking():
    """Lint kapısı hatayı yutmamalı: continue-on-error / '|| true' / '|| exit 0' yok.

    Kapanış kriteri 'hata durumunda kırmızı' demek. Hata yutulursa kapı sahte-yeşil olur.
    """
    text = _ci_text()
    # lint işinin gövdesini kabaca al (lint: ... bir sonraki üst-düzey işe kadar).
    m = re.search(r"^\s{2}lint:\n(.*?)(?=^\s{2}\w+:\n)", text, re.MULTILINE | re.DOTALL)
    lint_body = m.group(1) if m else text
    assert "continue-on-error" not in lint_body, (
        "lint işinde 'continue-on-error' var — kapı hatayı yutuyor (sahte-yeşil)."
    )
    assert not re.search(r"\|\|\s*(true|exit 0)", lint_body), (
        "lint işinde '|| true' / '|| exit 0' var — kapı hatayı yutuyor (sahte-yeşil)."
    )
