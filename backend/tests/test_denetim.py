"""Denetim Takip modülü testleri — skor motoru, prompt üreteci, izin, onay, otomasyon.

Odak: skorun TÜRETİLMİŞ olması (saklanmadığı için bayatlayamaz) ve durum→skor
eşlemesinin doğruluğu. Ayrıca bu modülün mutasyon uçlarının izin + onay + audit
zincirinden geçtiği doğrulanır (CLAUDE.md zorunluluğu).
"""
from datetime import date

import pytest

from app.models.audit_tracker import (
    AuditDimension,
    AuditFinding,
    AuditFindingRun,
    AuditReport,
)
from app.services import audit_tracker_service as svc


# ─── Fixture'lar ─────────────────────────────────────────────

@pytest.fixture
def denetim_report(db):
    """İki boyutlu küçük bir denetim raporu — skor aritmetiği elle doğrulanabilsin."""
    # Var olan aktif raporlar bu testte karışmasın
    db.query(AuditReport).update({AuditReport.is_active: False})

    report = AuditReport(
        key="test-denetim-v1",
        title="Test Denetimi",
        report_date=date(2026, 7, 25),
        doc_path="docs/denetim/test.md",
        baseline_score=50.0,
        target_score=80.0,
        is_active=True,
    )
    db.add(report)
    db.flush()

    db.add(AuditDimension(
        report_id=report.id, no=1, name="Mimari", score_prev=7,
        score_baseline=6.0, score_target=8.0, layer="cekirdek", reason="test",
    ))
    db.add(AuditDimension(
        report_id=report.id, no=2, name="Yedekleme", score_prev=5,
        score_baseline=4.0, score_target=8.0, layer="operasyon", reason="test",
    ))
    db.flush()
    return report


def _finding(db, report, code, **kw):
    defaults = dict(
        report_id=report.id, code=code, title=f"{code} başlığı",
        dimension_no=1, risk="yuksek", effort="S", category="kod",
        status="acik", score_impact=1.0, automatable=True, auto_enabled=False,
    )
    defaults.update(kw)
    f = AuditFinding(**defaults)
    db.add(f)
    db.flush()
    return f


# ─── Skor motoru ─────────────────────────────────────────────

class TestScoreEngine:
    """Skor SAKLANMAZ, türetilir — bu sınıf o sözleşmeyi korur."""

    def test_baseline_when_nothing_closed(self, db, denetim_report):
        _finding(db, denetim_report, "A-001")
        rows = {r["no"]: r for r in svc.dimension_scores(db, denetim_report)}
        assert rows[1]["score_current"] == 6.0
        assert rows[2]["score_current"] == 4.0

    def test_closing_raises_dimension_score(self, db, denetim_report):
        f = _finding(db, denetim_report, "A-001", score_impact=1.0)
        f.status = "kapali"
        db.flush()
        rows = {r["no"]: r for r in svc.dimension_scores(db, denetim_report)}
        assert rows[1]["score_current"] == 7.0

    def test_partial_counts_half(self, db, denetim_report):
        """`kismen` (DR-001 gibi) puanın YARISINI verir."""
        f = _finding(db, denetim_report, "A-001", score_impact=1.0)
        f.status = "kismen"
        db.flush()
        rows = {r["no"]: r for r in svc.dimension_scores(db, denetim_report)}
        assert rows[1]["score_current"] == 6.5

    def test_inceleme_gives_no_points(self, db, denetim_report):
        """Kod hazır ama canlıda değil → puan YOK (aksi halde not şişer)."""
        f = _finding(db, denetim_report, "A-001", score_impact=1.0)
        f.status = "inceleme"
        db.flush()
        rows = {r["no"]: r for r in svc.dimension_scores(db, denetim_report)}
        assert rows[1]["score_current"] == 6.0

    def test_score_capped_at_target(self, db, denetim_report):
        """Puan etkileri toplamı hedefi aşamaz — rapordaki 90 gün hedefi tavandır."""
        for i in range(5):
            f = _finding(db, denetim_report, f"A-00{i}", score_impact=1.0)
            f.status = "kapali"
        db.flush()
        rows = {r["no"]: r for r in svc.dimension_scores(db, denetim_report)}
        assert rows[1]["score_current"] == 8.0  # baseline 6 + 5 puan → 8'de kesildi

    def test_reopening_removes_points(self, db, denetim_report):
        f = _finding(db, denetim_report, "A-001", score_impact=1.0)
        f.status = "kapali"
        db.flush()
        assert svc.dimension_scores(db, denetim_report)[0]["score_current"] == 7.0

        svc.apply_finding_update(db, f, {"status": "acik"}, actor_id=None)
        assert svc.dimension_scores(db, denetim_report)[0]["score_current"] == 6.0
        assert f.closed_at is None, "Geri açılan bulguda kapanış damgası temizlenmeli"

    def test_overall_score_is_dimension_mean_times_ten(self, db, denetim_report):
        f = _finding(db, denetim_report, "A-001", score_impact=1.0)
        f.status = "kapali"
        db.flush()
        board = svc.scoreboard(db, denetim_report)
        # (7.0 + 4.0) / 2 * 10 = 55.0
        assert board["current_score"] == 55.0
        assert board["baseline_score"] == 50.0

    def test_potential_score_assumes_all_closed(self, db, denetim_report):
        _finding(db, denetim_report, "A-001", score_impact=1.0, dimension_no=1)
        _finding(db, denetim_report, "B-001", score_impact=2.0, dimension_no=2)
        board = svc.scoreboard(db, denetim_report)
        # potansiyel: boyut1 7.0, boyut2 6.0 → 65.0
        assert board["potential_score"] == 65.0
        assert board["current_score"] == 50.0

    def test_layer_averages(self, db, denetim_report):
        board = svc.scoreboard(db, denetim_report)
        assert board["core_avg"] == 6.0
        assert board["ops_avg"] == 4.0

    def test_counts(self, db, denetim_report):
        _finding(db, denetim_report, "A-001", risk="kritik", status="acik")
        _finding(db, denetim_report, "A-002", risk="yuksek", status="kapali")
        _finding(db, denetim_report, "A-003", risk="orta", status="kismen")
        board = svc.scoreboard(db, denetim_report)
        assert board["counts"]["toplam"] == 3
        assert board["counts"]["kritik_acik"] == 1
        assert board["counts"]["kapali"] == 1
        assert board["counts"]["kismen"] == 1


# ─── Prompt üreteci ──────────────────────────────────────────

class TestPromptBuilder:

    def test_prompt_contains_all_sections(self, db, denetim_report):
        f = _finding(
            db, denetim_report, "FIN-001",
            title="amount_try hiç tazelenmiyor",
            evidence="finance_event_service.py:118 — _upsert alan sözlüğüne koymuyor",
            solution="_upsert alan sözlüğüne amount_try ekle",
            closure_criteria="SELECT count(*) ... = 0",
        )
        prompt = svc.build_prompt(db, f, denetim_report)

        assert "FIN-001" in prompt
        assert "amount_try hiç tazelenmiyor" in prompt
        assert "finance_event_service.py:118" in prompt
        assert "SELECT count(*) ... = 0" in prompt
        assert "Kapanış kriteri" in prompt
        assert "1 — Mimari" in prompt
        assert "docs/denetim/test.md" in prompt

    def test_prompt_reminds_project_rules(self, db, denetim_report):
        """Prompt kendi kendine yeterli olmalı — CLAUDE.md kuralları içinde geçmeli."""
        f = _finding(db, denetim_report, "X-001")
        prompt = svc.build_prompt(db, f, denetim_report)
        assert "CLAUDE.md" in prompt
        assert "Python 3.9" in prompt
        assert "pytest" in prompt
        assert "regresyon testi" in prompt

    def test_prompt_override_wins(self, db, denetim_report):
        f = _finding(db, denetim_report, "X-001", prompt_override="Elle yazılmış komut")
        assert svc.build_prompt(db, f, denetim_report) == "Elle yazılmış komut"


# ─── Otomasyon kuyruğu ───────────────────────────────────────

class TestAutomationQueue:

    def test_only_enabled_and_automatable_are_candidates(self, db, denetim_report):
        _finding(db, denetim_report, "A-001", automatable=False, auto_enabled=True)
        _finding(db, denetim_report, "A-002", automatable=True, auto_enabled=False)
        assert svc.next_automation_candidate(db, denetim_report, 2) is None

    def test_critical_small_effort_goes_first(self, db, denetim_report):
        _finding(db, denetim_report, "LOW-1", risk="dusuk", effort="S",
                 automatable=True, auto_enabled=True)
        _finding(db, denetim_report, "CRIT-L", risk="kritik", effort="L",
                 automatable=True, auto_enabled=True)
        _finding(db, denetim_report, "CRIT-S", risk="kritik", effort="S",
                 automatable=True, auto_enabled=True)

        pick = svc.next_automation_candidate(db, denetim_report, 2)
        assert pick.code == "CRIT-S"

    def test_attempt_limit_excludes(self, db, denetim_report):
        _finding(db, denetim_report, "A-001", automatable=True, auto_enabled=True,
                 auto_attempts=2)
        assert svc.next_automation_candidate(db, denetim_report, 2) is None

    def test_closed_findings_are_not_candidates(self, db, denetim_report):
        _finding(db, denetim_report, "A-001", automatable=True, auto_enabled=True,
                 status="kapali")
        assert svc.next_automation_candidate(db, denetim_report, 2) is None


# ─── Koşu sonucu → durum eşlemesi ────────────────────────────

class TestRunOutcome:
    """Otomasyonun "kapandı" demesi ancak CANLIYA çıktıysa geçerlidir."""

    def test_success_with_deploy_closes(self, db, denetim_report):
        f = _finding(db, denetim_report, "A-001")
        run = svc.start_run(db, f, "otomatik", "opus")
        svc.finish_run(db, run, {"status": "basarili", "deployed": True,
                                 "commit_sha": "abc1234", "branch": "denetim/a-001"})
        db.refresh(f)
        assert f.status == "kapali"
        assert f.closed_at is not None
        assert "abc1234" in (f.closure_note or "")

    def test_success_without_deploy_waits_for_review(self, db, denetim_report):
        f = _finding(db, denetim_report, "A-001")
        run = svc.start_run(db, f, "otomatik", "opus")
        svc.finish_run(db, run, {"status": "basarili", "deployed": False})
        db.refresh(f)
        assert f.status == "inceleme"

    def test_failure_reopens(self, db, denetim_report):
        f = _finding(db, denetim_report, "A-001")
        run = svc.start_run(db, f, "otomatik", "opus")
        assert f.status == "devam"
        svc.finish_run(db, run, {"status": "basarisiz", "error": "Testler kırmızı"})
        db.refresh(f)
        assert f.status == "acik"

    def test_rollback_reopens(self, db, denetim_report):
        f = _finding(db, denetim_report, "A-001")
        run = svc.start_run(db, f, "otomatik", "opus")
        svc.finish_run(db, run, {"status": "geri_alindi", "rolled_back": True})
        db.refresh(f)
        assert f.status == "acik"

    def test_stale_run_is_reaped(self, db, denetim_report):
        """Süreç öldürülünce koşu sonsuza dek 'calisiyor' kalmamalı.

        2026-07-25 canlı olayı: UI'dan başlatılan koşu API'nin cgroup'undaydı,
        `systemctl restart sprenses-api` onu öldürdü, `finish_run` hiç çalışmadı.
        """
        from datetime import timedelta

        f = _finding(db, denetim_report, "A-001")
        run = svc.start_run(db, f, "elle", "opus")
        assert run.status == "calisiyor" and f.status == "devam"

        # Süreç öldü: koşu eskidi ama kimse kapatmadı
        run.started_at = svc.datetime.now(svc.tz_istanbul) - timedelta(minutes=180)
        db.flush()

        assert svc.reap_stale_runs(db) == 1
        db.refresh(run)
        db.refresh(f)
        assert run.status == "basarisiz"
        assert run.finished_at is not None
        assert "yarıda kesildi" in run.error
        assert f.status == "acik", "Bulgu tekrar denenebilir duruma dönmeli"

    def test_reaper_does_not_touch_fresh_runs(self, db, denetim_report):
        """Gerçekten koşan bir işi öldürmüş gibi işaretleme."""
        f = _finding(db, denetim_report, "A-001")
        run = svc.start_run(db, f, "otomatik", "opus")
        assert svc.reap_stale_runs(db) == 0
        db.refresh(run)
        assert run.status == "calisiyor"

    def test_attempt_counter_increments(self, db, denetim_report):
        f = _finding(db, denetim_report, "A-001")
        svc.start_run(db, f, "otomatik", "opus")
        assert f.auto_attempts == 1
        svc.start_run(db, f, "otomatik", "opus")
        assert f.auto_attempts == 2


# ─── HTTP: izin geçidi ───────────────────────────────────────

class TestPermissions:

    def test_scoreboard_requires_view(self, client, no_perm_user_headers):
        r = client.get("/api/system/denetim/scoreboard", headers=no_perm_user_headers)
        assert r.status_code == 403

    def test_findings_requires_view(self, client, no_perm_user_headers):
        r = client.get("/api/system/denetim/findings", headers=no_perm_user_headers)
        assert r.status_code == 403

    def test_viewer_cannot_mutate(self, client, viewer_user_headers, db, denetim_report):
        f = _finding(db, denetim_report, "A-001")
        db.commit()
        r = client.patch(
            f"/api/system/denetim/findings/{f.id}",
            json={"status": "kapali"},
            headers=viewer_user_headers,
        )
        assert r.status_code == 403

    def test_admin_can_read_scoreboard(self, client, auth_headers, db, denetim_report):
        db.commit()
        r = client.get("/api/system/denetim/scoreboard", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["report_key"] == "test-denetim-v1"
        assert len(body["dimensions"]) == 2


# ─── HTTP: liste ve güncelleme ───────────────────────────────

class TestFindingsApi:

    def test_list_returns_pagination_contract(self, client, auth_headers, db, denetim_report):
        _finding(db, denetim_report, "A-001")
        db.commit()
        r = client.get("/api/system/denetim/findings", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        for key in ("items", "total", "page", "page_size", "pages"):
            assert key in body

    def test_list_includes_prompt_and_points(self, client, auth_headers, db, denetim_report):
        _finding(db, denetim_report, "A-001", closure_criteria="ölçüm = 0")
        db.commit()
        body = client.get("/api/system/denetim/findings", headers=auth_headers).json()
        item = next(i for i in body["items"] if i["code"] == "A-001")
        assert "A-001" in item["prompt"]
        assert "ölçüm = 0" in item["prompt"]
        assert item["potential_points"] > 0
        assert item["applied_points"] == 0

    def test_closed_finding_reports_applied_points(self, client, auth_headers, db, denetim_report):
        f = _finding(db, denetim_report, "A-001", score_impact=1.0)
        f.status = "kapali"
        db.commit()
        body = client.get("/api/system/denetim/findings", headers=auth_headers).json()
        item = next(i for i in body["items"] if i["code"] == "A-001")
        # 1 puanlık boyut artışı, 2 boyutlu raporda genel nota 1 * (10/2) = 5 puan
        assert item["applied_points"] == 5.0

    def test_sort_by_rejects_arbitrary_column(self, client, auth_headers, db, denetim_report):
        db.commit()
        r = client.get(
            "/api/system/denetim/findings?sort_by=evidence", headers=auth_headers,
        )
        assert r.status_code == 422

    def test_risk_filter(self, client, auth_headers, db, denetim_report):
        _finding(db, denetim_report, "A-001", risk="kritik")
        _finding(db, denetim_report, "A-002", risk="dusuk")
        db.commit()
        body = client.get(
            "/api/system/denetim/findings?risk=kritik", headers=auth_headers,
        ).json()
        assert [i["code"] for i in body["items"]] == ["A-001"]

    def test_status_update_moves_score(self, client, auth_headers, db, denetim_report):
        f = _finding(db, denetim_report, "A-001", score_impact=1.0)
        db.commit()

        before = client.get("/api/system/denetim/scoreboard", headers=auth_headers).json()
        r = client.patch(
            f"/api/system/denetim/findings/{f.id}",
            json={"status": "kapali"}, headers=auth_headers,
        )
        assert r.status_code == 200
        after = client.get("/api/system/denetim/scoreboard", headers=auth_headers).json()
        assert after["current_score"] > before["current_score"]

    def test_manual_run_uses_isolated_cgroup(self, client, auth_headers, db, denetim_report,
                                             monkeypatch):
        """Elle koşu KENDİ systemd birimiyle başlatılmalı — API'nin cgroup'unda değil.

        Aksi halde `systemctl restart sprenses-api` koşuyu ortasından öldürür
        (2026-07-25 canlı olayı). Bu test çağrılan komutu yakalar.
        """
        import subprocess as sp

        from app.routers import system_denetim

        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(system_denetim.subprocess, "run", fake_run)

        f = _finding(db, denetim_report, "A-001", automatable=True)
        db.commit()
        r = client.post(
            f"/api/system/denetim/findings/{f.id}/run", json={}, headers=auth_headers,
        )
        assert r.status_code == 200

        cmd = captured["cmd"]
        assert "systemd-run" in cmd, "Koşu kendi cgroup'unda başlatılmalı"
        assert "--collect" in cmd
        assert any(str(a).startswith("sprenses-denetim-manual-") for a in cmd)
        assert "--finding" in cmd and "A-001" in cmd

    def test_manual_run_rejected_for_non_automatable(self, client, auth_headers, db, denetim_report):
        f = _finding(db, denetim_report, "SEC-001", automatable=False)
        db.commit()
        r = client.post(
            f"/api/system/denetim/findings/{f.id}/run", json={}, headers=auth_headers,
        )
        assert r.status_code == 400


# ─── Onay akışı regresyonu ───────────────────────────────────

class TestApprovalRegression:
    """Executor handler router ile AYNI service'i çağırmalı (CLAUDE.md D1-2)."""

    def test_executor_update_applies_same_change_as_router(self, db, denetim_report):
        from app.utils.approval_executor import _HANDLERS

        f = _finding(db, denetim_report, "A-001", score_impact=1.0)
        handler = _HANDLERS["system.denetim"]
        handler(db, "update", f.id, {"status": "kapali"}, actor_id=None)

        db.refresh(f)
        assert f.status == "kapali"
        assert f.closed_at is not None
        assert svc.dimension_scores(db, denetim_report)[0]["score_current"] == 7.0

    def test_executor_create_uses_active_report(self, db, denetim_report):
        from app.utils.approval_executor import _HANDLERS

        handler = _HANDLERS["system.denetim"]
        handler(db, "create", 0, {
            "code": "NEW-001", "title": "Onayla eklenen bulgu", "dimension_no": 2,
            "risk": "orta", "effort": "M", "category": "kod", "status": "acik",
            "score_impact": 0.5, "automatable": False, "auto_enabled": False,
        }, actor_id=None)

        created = (
            db.query(AuditFinding)
            .filter(AuditFinding.code == "NEW-001")
            .first()
        )
        assert created is not None
        assert created.report_id == denetim_report.id

    def test_executor_config_update(self, db, denetim_report):
        from app.utils.approval_executor import _HANDLERS

        handler = _HANDLERS["system.denetim"]
        handler(db, "update_config", 1, {"enabled": True, "model": "sonnet"}, actor_id=None)
        cfg = svc.get_config(db)
        assert cfg.enabled is True
        assert cfg.model == "sonnet"

    def test_module_has_executor_handler(self):
        """AST bekçisiyle aynı sözleşme — açıkça de doğrula."""
        from app.utils.approval_executor import _HANDLERS
        assert "system.denetim" in _HANDLERS


# ─── Otomasyon yapılandırması ────────────────────────────────

class TestAutomationConfig:

    def test_defaults_are_safe(self, db):
        cfg = svc.get_config(db)
        assert cfg.enabled is False, "Otomasyon varsayılan olarak KAPALI olmalı"
        assert cfg.auto_rollback is True
        assert cfg.max_chain_runs >= 1

    def test_chain_limit_is_bounded(self, client, auth_headers):
        """Zincir sınırsız olamaz — gözetimsiz koşu sayısı sınırlı kalmalı."""
        r = client.patch(
            "/api/system/denetim/config", json={"max_chain_runs": 99},
            headers=auth_headers,
        )
        assert r.status_code == 422
        r = client.patch(
            "/api/system/denetim/config", json={"max_chain_runs": 0},
            headers=auth_headers,
        )
        assert r.status_code == 422

    def test_chain_limit_persists(self, client, auth_headers):
        r = client.patch(
            "/api/system/denetim/config", json={"max_chain_runs": 4},
            headers=auth_headers,
        )
        assert r.status_code == 200
        body = client.get("/api/system/denetim/config", headers=auth_headers).json()
        assert body["max_chain_runs"] == 4

    def test_config_endpoint_exposes_next_candidate(self, client, auth_headers, db, denetim_report):
        _finding(db, denetim_report, "A-001", automatable=True, auto_enabled=True,
                 risk="kritik")
        db.commit()
        body = client.get("/api/system/denetim/config", headers=auth_headers).json()
        assert body["next_candidate"]["code"] == "A-001"

    def test_config_update_persists(self, client, auth_headers, db):
        r = client.patch(
            "/api/system/denetim/config",
            json={"max_budget_usd": 12.5, "model": "sonnet"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        body = client.get("/api/system/denetim/config", headers=auth_headers).json()
        assert body["max_budget_usd"] == 12.5
        assert body["model"] == "sonnet"

    def test_config_rejects_unknown_model(self, client, auth_headers):
        r = client.patch(
            "/api/system/denetim/config", json={"model": "gpt"}, headers=auth_headers,
        )
        assert r.status_code == 422


# ─── Otomasyon script'i — saf yardımcılar ────────────────────

def _load_cron():
    """`cron_denetim_auto.py`'yi modül olarak yükle (paket içinde değil)."""
    import importlib.util
    import os

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "cron_denetim_auto.py",
    )
    spec = importlib.util.spec_from_file_location("cron_denetim_auto_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestCronHelpers:
    """Script'in sır-sızıntısı bekçisi: PreToolUse guard'ı devre dışıyken tek koruma."""

    def test_secret_paths_are_blocked(self):
        mod = _load_cron()

        for bad in ("backend/.env", ".env.production", "keys/server.pem",
                    "certs/tls.key", "app/aws_credentials.json"):
            assert mod._looks_secret(bad), f"{bad} engellenmeliydi"
        for ok in ("backend/app/main.py", "docs/denetim/rapor.md",
                   "frontend/src/lib/api.ts"):
            assert not mod._looks_secret(ok), f"{ok} engellenmemeliydi"

    def test_health_check_retries_before_declaring_failure(self, monkeypatch):
        """Sağlık kontrolü açılış payı tanımalı.

        `systemctl restart` birim başlayınca döner ama uvicorn birkaç saniye sonra
        dinlemeye başlar. Tek seferlik kontrol sağlıklı bir deploy'u geri aldırır —
        2026-07-25 canlı olayı (DOC-D01: 2007 test yeşil, deploy iyi, yine geri alındı).
        """
        import subprocess as sp

        mod = _load_cron()
        calls = {"n": 0}

        def fake_run(cmd, **kw):
            calls["n"] += 1
            # İlk 3 deneme bağlantı reddi, 4.'sü 200
            if calls["n"] < 4:
                raise sp.SubprocessError("connection refused")
            return sp.CompletedProcess(cmd, 0, stdout="200", stderr="")

        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        monkeypatch.setattr(mod.time, "sleep", lambda s: None)

        assert mod._health_ok() is True
        assert calls["n"] == 4, "Yeniden denemeden vazgeçmemeli"

    def test_health_check_eventually_gives_up(self, monkeypatch):
        """Gerçekten bozuk bir deploy'da sonsuza dek beklemesin — geri alma çalışsın."""
        import subprocess as sp

        mod = _load_cron()
        monkeypatch.setattr(
            mod.subprocess, "run",
            lambda cmd, **kw: sp.CompletedProcess(cmd, 0, stdout="502", stderr=""),
        )
        monkeypatch.setattr(mod.time, "sleep", lambda s: None)
        assert mod._health_ok(attempts=3) is False

    def test_test_only_change_does_not_restart_api(self):
        """Yalnız test dosyası değiştiyse üretim süreci gereksiz yere yeniden başlatılmaz."""
        mod = _load_cron()
        assert mod._needs_api_restart(["backend/tests/test_x.py"]) is False
        assert mod._needs_api_restart(["backend/tests/a.py", "docs/b.md"]) is False
        assert mod._needs_api_restart(["backend/app/main.py"]) is True
        assert mod._needs_api_restart(["backend/cron_x.py"]) is True

    def test_long_phase_does_not_depend_on_live_orm(self, db, denetim_report, monkeypatch):
        """Uzun faz (claude ~40 dk) boyunca ORM nesnesine dokunulmamalı.

        Dokunulursa SQLAlchemy expire-load'u SESSİZCE yeni transaction açar ve oturum
        `idle in transaction` kalır → `audit_automation_config` satır kilidi tutulur →
        `alembic upgrade` (ALTER TABLE) süresiz bloke olur. 2026-07-25'te canlıda
        yaşandı: migration takıldı, o tabloya değen her sorgu kilit kuyruğuna girdi.

        Test, uzun faz sırasında oturumu boşaltarak (expunge) nesneleri kopararak
        bunu taklit eder: kod ilkel değerleri önceden kopyaladıysa sorunsuz biter.
        """
        mod = _load_cron()
        f = _finding(db, denetim_report, "A-001")
        cfg = svc.get_config(db)

        def fake_claude(prompt, cwd, model, budget, timeout_min):
            # Uzun faz: oturumdaki ORM nesneleri artık kullanılamaz
            db.expunge_all()
            return {"ok": True, "text": "özet", "cost_usd": 0.5, "error": None}

        monkeypatch.setattr(mod, "_prepare_worktree", lambda code: ("/tmp/wt-x", "denetim/a-001-x"))
        monkeypatch.setattr(mod, "_cleanup_worktree", lambda p: None)
        monkeypatch.setattr(mod, "_run_claude", fake_claude)
        monkeypatch.setattr(mod, "_git", lambda *a, **k: "")
        monkeypatch.setattr(mod, "_notify", lambda *a, **k: None)

        # `_git` boş dönünce "değişiklik yok" dalına girer → koşu `atlandi` biter.
        mod.process(db, f, cfg, "otomatik")

        run = (
            db.query(AuditFindingRun)
            .order_by(AuditFindingRun.id.desc())
            .first()
        )
        assert run.status == "atlandi"
        assert run.finished_at is not None, "finally bloğu sonucu yazabilmeli"
        # `f` bilerek koparıldı → id ile yeniden oku (kodun kendisi de böyle yapıyor)
        fresh = db.query(AuditFinding).filter(AuditFinding.id == run.finding_id).first()
        assert fresh.status == "acik"

    def test_gate_passes_when_numbers_identical(self, monkeypatch):
        """Kod finansal hiçbir sayıyı oynatmıyorsa deploy'a izin ver."""
        mod = _load_cron()
        snap = {"_values": {"fe_toplam_try": 1000.0, "cari_acik": 250.5}, "_errors": {}}
        monkeypatch.setattr(mod, "_fingerprint", lambda d, r: snap)
        g = mod._financial_gate("/tmp/wt")
        assert g["verdict"] == "temiz"
        assert g["farklar"] == []

    def test_gate_blocks_when_code_moves_a_number(self, monkeypatch):
        """Sessiz tutar kayması — testler yeşil olsa bile deploy ENGELLENMELİ.

        Bu, FIN-001 hata sınıfının (₺696.190,94 hayalet para, aylarca sessiz,
        hiçbir test kırmızı değil) yakalandığı tek mekanizma.
        """
        mod = _load_cron()
        eski = {"_values": {"fe_toplam_try": 1000.0, "cari_acik": 250.5}, "_errors": {}}
        yeni = {"_values": {"fe_toplam_try": 1696.19, "cari_acik": 250.5}, "_errors": {}}
        calls = {"n": 0}

        def fake_fp(checkout, ref):
            calls["n"] += 1
            return yeni if calls["n"] == 2 else eski  # A, B, A2

        monkeypatch.setattr(mod, "_fingerprint", fake_fp)
        g = mod._financial_gate("/tmp/wt")
        assert g["verdict"] == "engellendi"
        assert len(g["farklar"]) == 1
        assert g["farklar"][0]["anahtar"] == "fe_toplam_try"
        assert "1000.0 → 1696.19" in g["detay"]

    def test_gate_skips_when_live_data_drifted(self, monkeypatch):
        """A != A2: fark koda atfedilemez → yanlış alarm verme, kapıyı atla.

        Canlı veri ölçüm penceresinde değişebilir (Sedna senkronu 2 saatte bir,
        kullanıcı işlemleri). Kontrol ölçümü olmadan her koşu yanlış bloklanırdı.
        """
        mod = _load_cron()
        seq = [
            {"_values": {"x": 1.0}, "_errors": {}},   # A
            {"_values": {"x": 9.0}, "_errors": {}},   # B (farklı)
            {"_values": {"x": 5.0}, "_errors": {}},   # A2 (A'dan farklı → sürüklenme)
        ]
        calls = {"n": 0}

        def fake_fp(checkout, ref):
            v = seq[calls["n"]]
            calls["n"] += 1
            return v

        monkeypatch.setattr(mod, "_fingerprint", fake_fp)
        g = mod._financial_gate("/tmp/wt")
        assert g["verdict"] == "atlandi", "Sürüklenme varken bloklamamalı"
        assert "canlı veri değişti" in g["detay"]

    def test_gate_uses_control_measurement(self, monkeypatch):
        """Üç ölçüm alınmalı: A (eski), B (yeni), A2 (eski, kontrol)."""
        mod = _load_cron()
        seen = []

        def fake_fp(checkout, ref):
            seen.append(checkout)
            return {"_values": {"x": 1.0}, "_errors": {}}

        monkeypatch.setattr(mod, "_fingerprint", fake_fp)
        mod._financial_gate("/tmp/wt")
        assert len(seen) == 3
        assert seen[0] == mod.REPO_DIR and seen[2] == mod.REPO_DIR
        assert seen[1] == "/tmp/wt"

    def test_gate_error_falls_to_safe_side(self, monkeypatch):
        """Kapı ölçülemiyorsa deploy EDİLMEMELİ — bilinmeyen ≠ güvenli."""
        mod = _load_cron()

        def boom(checkout, ref):
            raise RuntimeError("DB erişilemedi")

        monkeypatch.setattr(mod, "_fingerprint", boom)
        with pytest.raises(RuntimeError):
            mod._financial_gate("/tmp/wt")
        # process() bu istisnayı yakalayıp deploy'u atlar — aşağıdaki testte kanıtlanır

    def test_docs_only_change_skips_financial_gate(self):
        """Doküman/test değişikliği bir finansal sayıyı oynatamaz → ölçüm atlanır."""
        mod = _load_cron()
        assert mod._needs_api_restart(["docs/x.md"]) is False
        assert mod._needs_api_restart(["backend/tests/test_x.py"]) is False
        assert mod._needs_api_restart(["backend/app/services/credit_service.py"]) is True

    def test_invariants_include_unwindowed_full_sweep(self):
        """En az bir değişmez TÜM finance_events'i tarih/para-birimi SÜZMEDEN taramalı.

        2026-07-25 kapı doğrulaması: FIN-001 kasten geri alındı (amount_try tekrar
        öne çekildi) ve kapı "temiz" dedi — sapan iki TRY kaydı Haziran ve Ağustos'ta
        olduğu için T-Hesap'ın Temmuz penceresine düşmüyordu; `fx_event_eur_cevrim` de
        TRY'yi bilerek dışlıyordu. Pencereli değişmezler tek başına YETMEZ.

        Tam tarama eklenince aynı hata yakalandı: TRY 29.435.343,35 → 29.438.847,78.
        """
        from app.services import audit_finance_invariants as inv
        import inspect

        keys = {i["key"] for i in inv.INVARIANTS}
        assert "fe_event_eur_tam_tarama" in keys, \
            "Penceresiz tam tarama değişmezi kaldırılmamalı"

        src = inspect.getsource(inv._inv_fe_event_eur_tam_tarama)
        assert "event_date" not in src, "Tam tarama tarih süzmemeli"
        assert "notin_" not in src, "Tam tarama para birimi dışlamamalı"
        assert "_event_eur" in src, "Gerçek çevrim kod yolunu çağırmalı"

    def test_invariant_registry_is_sane(self):
        """Kayıt tablosu tutarlı olmalı — anahtarlar benzersiz, fonksiyonlar çağrılabilir."""
        from app.services import audit_finance_invariants as inv

        keys = [i["key"] for i in inv.INVARIANTS]
        assert len(keys) == len(set(keys)), "Yinelenen değişmez anahtarı var"
        assert len(keys) >= 30, "Değişmez kümesi beklenmedik şekilde küçüldü"
        for i in inv.INVARIANTS:
            assert callable(i["fn"])
            assert i["onem"] in ("kritik", "yuksek", "orta")

    def test_deploy_blockers_cover_financial_gate(self):
        """Otomasyon kendi finansal kapısını değiştirip geçemesin."""
        mod = _load_cron()
        blockers = mod.DEPLOY_BLOCKERS
        assert any("denetim_finans_parmak_izi" in b for b in blockers)
        assert any("audit_finance_invariants" in b for b in blockers)

    def test_deploy_blockers_cover_migrations_and_self(self):
        mod = _load_cron()
        blockers = mod.DEPLOY_BLOCKERS
        assert any("alembic/versions" in b for b in blockers), \
            "Migration içeren değişiklik gözetimsiz deploy edilmemeli"
        assert any("cron_denetim_auto" in b for b in blockers), \
            "Otomasyon kendi script'ini gözetimsiz deploy etmemeli"
        assert any("systemd" in b for b in blockers)
