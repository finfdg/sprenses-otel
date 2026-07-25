"""CI kalite kapısı regresyon testi — CICD-013 (v4 denetim, Boyut 11 — CI/CD).

Bulgu: CI kalite kapısı eksik — svelte-check ve kapsam eşiği gate'e bağlı değil.
Kapanış kriteri: CI'da svelte-check koşuyor ve hata durumunda iş KIRMIZI.

Bu bulgunun svelte-check bacağı QUAL-001 (Boyut 2) ile fiilen kapatıldı:
`.github/workflows/ci.yml` içine bloklayıcı `lint` işi eklendi (svelte-kit sync →
`npm run check`). CICD-013 çerçevesi ayrıca **kapsam eşiğini** de ("kapsam eşiği
gate'e bağlı değil") adlandırır; `--cov-fail-under=60` backend işinde mevcut ama
QUAL-001 testi bunu KORUMUYORDU. Bu test o boşluğu kapatır ve CICD-013'ün kapanış
kriterini (svelte-check bloklayıcı) ayrıca zorunlu tutar.

Kapı zayıflatılırsa (svelte-check kaldırılır/yutulur ya da `--cov-fail-under`
silinir/0'a düşürülür) test KIRMIZI'ya döner — CICD-013'ün geri dönüşü yakalanır.
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


def _job_body(text: str, job: str) -> str:
    """`  <job>:` başlığından bir sonraki üst-düzey işe kadarki gövdeyi döndürür."""
    m = re.search(
        rf"^\s{{2}}{job}:\n(.*?)(?=^\s{{2}}\w+:\n|\Z)", text, re.MULTILINE | re.DOTALL
    )
    return m.group(1) if m else ""


def test_ci_runs_svelte_check_blocking():
    """CICD-013 kapanış kriteri: svelte-check CI'da koşar ve bloklayıcıdır.

    'npm run check' / 'svelte-check' adımı bulunmalı, ön koşul 'svelte-kit sync'
    olmalı ve lint işi hatayı yutmamalı (continue-on-error / '|| true' / '|| exit 0'
    yok). Aksi hâlde kapı sahte-yeşil olur.
    """
    text = _ci_text()
    assert re.search(r"npm run check|svelte-check", text), (
        "ci.yml svelte-check (npm run check) adımını içermiyor — CICD-013 geri döndü."
    )
    assert re.search(r"svelte-kit sync", text), (
        "ci.yml 'svelte-kit sync' ön adımı yok — svelte-check yanlış-kırmızı verir."
    )
    lint_body = _job_body(text, "lint")
    assert lint_body, "ci.yml içinde 'lint:' işi yok — svelte-check kapısı kaldırılmış."
    assert "continue-on-error" not in lint_body, (
        "lint işinde 'continue-on-error' var — svelte-check hatası yutuluyor (sahte-yeşil)."
    )
    assert not re.search(r"\|\|\s*(true|exit 0)", lint_body), (
        "lint işinde '|| true' / '|| exit 0' var — kapı hatayı yutuyor (sahte-yeşil)."
    )


def test_ci_enforces_coverage_threshold():
    """CICD-013 kapsam bacağı: backend pytest kapsam eşiğini zorunlu kılar.

    `--cov-fail-under=<N>` bulunmalı ve N>0 olmalı (0 = eşik dekoratif → kapı yok).
    Eşik silinir ya da 0'a düşürülürse kapsam regresyonu görünmez kalır.
    """
    text = _ci_text()
    m = re.search(r"--cov-fail-under=(\d+)", text)
    assert m, (
        "ci.yml '--cov-fail-under' eşiğini içermiyor — kapsam kapısı gate'e bağlı değil (CICD-013)."
    )
    threshold = int(m.group(1))
    assert threshold > 0, (
        f"--cov-fail-under={threshold} — sıfır eşik dekoratif, kapsam regresyonunu yakalamaz."
    )
    # Eşik pytest adımında olmalı (backend işinde çalışan gerçek komutta).
    backend_body = _job_body(text, "backend")
    assert "--cov-fail-under=" in backend_body, (
        "'--cov-fail-under' backend pytest işinde değil — kapsam kapısı fiilen koşmuyor."
    )
