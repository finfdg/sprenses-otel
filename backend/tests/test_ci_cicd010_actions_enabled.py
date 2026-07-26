"""CI'nın fiilen koşuyor olması — CICD-010 (v4 denetim, Boyut 11 — CI/CD).

Bulgu: CI 2026-06-02'den beri **hiç çalışmadı** — GitHub Actions depo düzeyinde
KAPALI (`actions/permissions` → `{"enabled": false}`, `ci.yml/runs` → 0 koşu).
451 commit test edilmeden master'a gitti; 1.900+ testlik takım ve
`--cov-fail-under=60` eşiği fiilen dekoratifti.

Kapanış kriteri: `actions/permissions` → `enabled: true` **ve** en son `ci.yml`
koşusunun conclusion'ı `success`.

Bu dosya iki katmanlı koruma kurar — çünkü bulgunun kökü iki farklı yerde geri
gelebilir:

1. **Yapısal katman (her yerde koşar):** `ci.yml` master'a push ve pull request
   üzerinde tetikleniyor mu, işler `if: false` gibi bir anahtarla susturulmuş mı.
   Tetikleyici kaldırılırsa Actions açık olsa bile CI bir daha koşmaz — bu
   tam olarak CICD-010'un "CI dekoratif" durumudur.
2. **Canlı katman (`gh` kimlik doğrulanmışsa koşar):** depoda Actions gerçekten
   etkin mi ve `ci.yml`'ın en az bir koşusu var mı. `gh` yoksa/kimliksizse test
   ATLANIR (skip) — sessizce yeşile dönmez, atlandığı raporda görünür. GitHub
   runner'ının içinde `gh` bu depoya kimliksizdir; orada kontrol zaten totolojik
   olurdu (iş akışı koşuyorsa Actions açıktır).

Sahte-yeşil değildir: Actions kapatılırsa canlı test, tetikleyici kaldırılırsa
yapısal test KIRMIZI'ya döner (ikisi de fiilen doğrulandı — bkz. denetim raporu).
"""

import json
import os
import re
import shutil
import subprocess

import pytest

# backend/tests/ -> proje kökü (iki üst) -> .github/workflows/ci.yml
CI_YML = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", ".github", "workflows", "ci.yml"
    )
)

CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
GH_TIMEOUT_SEC = 30


def _ci_text() -> str:
    assert os.path.exists(CI_YML), f"CI iş akışı bulunamadı: {CI_YML}"
    return open(CI_YML, encoding="utf-8").read()


def _trigger_block(text: str) -> str:
    """`on:` bloğunu (ilk üst-düzey `on:` anahtarından sonraki girintili gövde) döndürür."""
    m = re.search(r"^on:\n(.*?)(?=^\S)", text, re.MULTILINE | re.DOTALL)
    return m.group(1) if m else ""


def _gh_json(endpoint: str):
    """`gh api <endpoint>` çıktısını JSON olarak döndürür; kullanılamıyorsa testi atlar."""
    if shutil.which("gh") is None:
        pytest.skip("`gh` CLI kurulu değil — canlı Actions kontrolü atlandı.")
    auth = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT_SEC,
    )
    if auth.returncode != 0:
        pytest.skip("`gh` kimlik doğrulanmamış — canlı Actions kontrolü atlandı.")
    proc = subprocess.run(
        ["gh", "api", endpoint],
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT_SEC,
    )
    if proc.returncode != 0:
        pytest.skip(
            "GitHub API'ye ulaşılamadı (ağ/izin) — canlı Actions kontrolü atlandı: "
            + proc.stderr.strip()[:200]
        )
    return json.loads(proc.stdout)


def test_ci_workflow_triggers_on_master_push():
    """Yapısal kapı: `ci.yml` master'a push ve pull request'te tetiklenmeli.

    Tetikleyiciler daraltılır/kaldırılırsa (ör. yalnız `workflow_dispatch`
    bırakılırsa) CI, Actions açık olsa bile kendiliğinden koşmaz — CICD-010'un
    "commit'ler test edilmeden geçiyor" durumu geri döner.
    """
    triggers = _trigger_block(_ci_text())
    assert triggers, (
        "ci.yml içinde `on:` tetikleyici bloğu bulunamadı — iş akışı hiç koşmaz (CICD-010)."
    )
    assert re.search(r"^\s{2}push:", triggers, re.MULTILINE), (
        "ci.yml'da `push:` tetikleyicisi yok — commit'ler test edilmeden geçer (CICD-010)."
    )
    branch_line = re.search(r"^\s+branches:\s*\[(.*?)\]", triggers, re.MULTILINE)
    assert branch_line, "ci.yml push tetikleyicisinde `branches:` listesi yok."
    branches = {b.strip().strip("\"'") for b in branch_line.group(1).split(",")}
    assert "master" in branches, (
        f"ci.yml push tetikleyicisi master'ı kapsamıyor ({sorted(branches)}) — "
        "ana dal test edilmeden ilerler (CICD-010)."
    )
    assert re.search(r"^\s{2}pull_request:", triggers, re.MULTILINE), (
        "ci.yml'da `pull_request:` tetikleyicisi yok — PR'lar test edilmeden açılır."
    )


def test_ci_jobs_not_disabled():
    """Yapısal kapı: hiçbir iş `if: false` benzeri bir anahtarla susturulmamalı.

    Bir işi devre dışı bırakmak, iş akışını silmeden CI'yı dekoratif hâle
    getirmenin en sessiz yoludur — CICD-010'un aynı sonucu.
    """
    text = _ci_text()
    assert not re.search(r"^\s*if:\s*false\b", text, re.MULTILINE | re.IGNORECASE), (
        "ci.yml'da `if: false` var — bir iş sessizce devre dışı bırakılmış (CICD-010)."
    )
    for job in ("lint", "backend", "frontend"):
        assert re.search(rf"^\s{{2}}{job}:", text, re.MULTILINE), (
            f"ci.yml içinde '{job}:' işi yok — kapının bir bacağı kaldırılmış (CICD-010)."
        )


def test_github_actions_enabled_on_repo():
    """Canlı kapı: depoda GitHub Actions etkin olmalı (CICD-010 kapanış kriteri).

    Bulgunun tam hâli buydu: `actions/permissions` → `{"enabled": false}`. Ayar
    geri alınırsa bu test KIRMIZI'ya döner. `gh` yoksa/kimliksizse ATLANIR.
    """
    perms = _gh_json("repos/:owner/:repo/actions/permissions")
    assert perms.get("enabled") is True, (
        "GitHub Actions depo düzeyinde KAPALI — CI hiç koşmaz (CICD-010 geri döndü). "
        f"actions/permissions = {perms}"
    )


def test_ci_workflow_has_at_least_one_run():
    """Canlı kapı: `ci.yml`'ın en az bir koşusu olmalı.

    Actions açık olsa bile hiç koşu yoksa kapı fiilen dekoratiftir — denetimde
    ölçülen `total_count: 0` durumu. Bu test o durumu yakalar.
    """
    workflows = _gh_json("repos/:owner/:repo/actions/workflows")
    ci = next(
        (w for w in workflows.get("workflows", []) if w.get("path") == CI_WORKFLOW_PATH),
        None,
    )
    assert ci is not None, (
        f"GitHub'da '{CI_WORKFLOW_PATH}' iş akışı kayıtlı değil — CI tanınmıyor."
    )
    assert ci.get("state") == "active", (
        f"'{CI_WORKFLOW_PATH}' iş akışı '{ci.get('state')}' durumunda (aktif değil) — "
        "elle devre dışı bırakılmış (CICD-010)."
    )
    runs = _gh_json(f"repos/:owner/:repo/actions/workflows/{ci['id']}/runs?per_page=1")
    assert runs.get("total_count", 0) > 0, (
        "ci.yml'ın hiç koşusu yok (total_count=0) — test takımı fiilen dekoratif (CICD-010)."
    )
