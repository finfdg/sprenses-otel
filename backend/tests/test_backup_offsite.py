"""Off-site (S3) yedek — denetim DR-002 regresyon testleri.

BU TESTLERİN VAR OLMA SEBEBİ: DR-002 iki denetimde üst üste (v3 → v4) "Kritik/Açık"
kaldı. Kod yolu (`db-backup.sh` S3 bloğu) hiç koşulmadığı için hiç test de edilmedi;
içinde sessiz-hata (`UYARI` basıp exit 0), geri-yükleme yolunun hiç doğrulanmaması ve
"farklı bölge" kuralının hiçbir yerde zorlanmaması gibi kusurlar fark edilmeden durdu.

Gerçek AWS olmadan koşabilmesi için `tests/fixtures/fake_aws.py` sahte bir `aws` CLI
sağlar ve PATH'in başına konur; `s3://` URI'leri yerel bir dizine eşlenir. Böylece
YÜKLEME → LİSTELEME → İNDİRME → İÇERİK EŞİTLİĞİ zinciri gerçek dosya trafiğiyle sınanır.

Kapsanan davranışlar:
  1. Off-site yapılandırılmışsa DB dump'ı ve uploads dosyaları S3'e çıkar (içerik özdeş)
  2. Off-site BAŞARISIZ olursa iş de başarısız olur (exit != 0) — sessiz kalmaz
  3. Yerel yedek, off-site başarısız olsa bile korunur
  4. Durum dosyası (backup-state.json) gerçeği yazar — UI/eşik kontrolü buradan okur
  5. `--offsite` tatbikatı S3'ten indirip bütünlük doğrular
  6. "Farklı bölge" kuralı aynı-bölge bucket'ı REDDEDER (kapanış kriterinin ta kendisi)
  7. API `/backup/data-status` off-site yokluğunu KRİTİK olarak raporlar
"""

import json
import os
import shutil
import subprocess

import pytest

REPO = "/home/ec2-user/otel"
SCRIPTS = os.path.join(REPO, "scripts")
FAKE_AWS = os.path.join(REPO, "backend", "tests", "fixtures", "fake_aws.py")
API = "/api/system/backup"


# ─── Yardımcılar ─────────────────────────────────────────────────────────────


def _fake_aws_bin(tmp_path):
    """PATH'in başına konacak, fake_aws.py'ye yönlendiren bir `aws` kabuğu üret."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    aws = bindir / "aws"
    aws.write_text('#!/usr/bin/env bash\nexec python3 "%s" "$@"\n' % FAKE_AWS)
    aws.chmod(0o755)
    return str(bindir)


def _env(tmp_path, **extra):
    """db-backup.sh'ı geçici dizinlerle + sahte aws ile koşturacak ortam."""
    env = dict(os.environ)
    env["PATH"] = _fake_aws_bin(tmp_path) + os.pathsep + env["PATH"]
    env["SPRENSES_BACKUP_DIR"] = str(tmp_path / "db")
    env["SPRENSES_UPLOADS_DIR"] = str(tmp_path / "uploads-snap")
    env["SPRENSES_UPLOADS_SRC"] = str(tmp_path / "uploads-src")
    env["SPRENSES_BACKUP_STATE"] = str(tmp_path / "db" / "backup-state.json")
    env["SPRENSES_MIN_FREE_MB"] = "1"          # geçici dizinde disk bekçisi tetiklemesin
    env["SPRENSES_DB_NAME"] = "sprenses_test"  # ÜRETİM DB'sini asla dump etme
    env["FAKE_S3_ROOT"] = str(tmp_path / "s3")
    env["SPRENSES_INSTANCE_REGION"] = "eu-north-1"
    env["FAKE_S3_REGION"] = "eu-west-1"        # farklı bölge → kural sağlanır
    env.update(extra)
    return env


@pytest.fixture
def backup_env(tmp_path):
    """Örnek uploads içeriğiyle hazır bir yedek ortamı."""
    src = tmp_path / "uploads-src"
    (src / "cari").mkdir(parents=True)
    (src / "cari" / "ekstre.pdf").write_bytes(b"%PDF-1.4 sahte banka ekstresi\n")
    (src / "cari" / "liste.xlsx").write_bytes(b"PK\x03\x04 sahte excel")
    (src / "belge.pdf").write_bytes(b"%PDF-1.4 sahte cek goruntusu\n")
    return _env(tmp_path)


def _run_backup(env, s3=None):
    e = dict(env)
    if s3:
        e["SPRENSES_BACKUP_S3"] = s3
    return subprocess.run(
        [os.path.join(SCRIPTS, "db-backup.sh")],
        env=e, capture_output=True, text=True, timeout=300,
    )


def _s3_files(env, sub=""):
    root = os.path.join(env["FAKE_S3_ROOT"], "kova", "sprenses", sub)
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            out.append(os.path.relpath(os.path.join(dirpath, name), root))
    return sorted(out)


pytestmark = pytest.mark.skipif(
    shutil.which("pg_dump") is None, reason="pg_dump yok — yedek script'i koşturulamaz"
)


# ─── 1-4: yedek script'i ─────────────────────────────────────────────────────


class TestOffsiteUpload:
    def test_db_and_uploads_reach_offsite(self, backup_env):
        """DB dump'ı + uploads dosyaları S3'e çıkar ve içerikleri ÖZDEŞ olur."""
        r = _run_backup(backup_env, s3="s3://kova/sprenses")
        assert r.returncode == 0, r.stdout + r.stderr

        dumps = _s3_files(backup_env, "db")
        assert len(dumps) == 1 and dumps[0].endswith(".dump"), dumps

        uploaded = _s3_files(backup_env, "uploads")
        assert sorted(uploaded) == ["belge.pdf", "cari/ekstre.pdf", "cari/liste.xlsx"]

        # İçerik eşitliği — "dosya adı orada" kanıt değildir
        off = os.path.join(backup_env["FAKE_S3_ROOT"], "kova", "sprenses",
                           "uploads", "cari", "ekstre.pdf")
        src = os.path.join(backup_env["SPRENSES_UPLOADS_SRC"], "cari", "ekstre.pdf")
        assert open(off, "rb").read() == open(src, "rb").read()

        # S3'e giden dump gerçekten geri yüklenebilir bir pg_dump arşivi mi?
        s3_dump = os.path.join(backup_env["FAKE_S3_ROOT"], "kova", "sprenses", "db", dumps[0])
        assert subprocess.run(["pg_restore", "--list", s3_dump],
                              capture_output=True).returncode == 0

    def test_offsite_failure_fails_the_job(self, backup_env):
        """REGRESYON: off-site çökerse iş de çöker (exit != 0) — eskiden sessizce exit 0 idi.

        Bu, DR-002'nin iki denetim boyunca fark edilmeden AÇIK kalmasını sağlayan
        sessizlik sınıfı. Çıkış kodu 0 olursa systemd OnFailure alarmı ATEŞLEMEZ ve
        off-site aylarca bozuk kalır.
        """
        env = dict(backup_env)
        env["FAKE_S3_FAIL"] = "s3://kova"
        r = _run_backup(env, s3="s3://kova/sprenses")
        assert r.returncode != 0, "off-site hatası işi başarısız yapmalı:\n" + r.stdout

    def test_local_backup_survives_offsite_failure(self, backup_env):
        """Off-site çökse bile YEREL yedek tamamlanır ve korunur."""
        env = dict(backup_env)
        env["FAKE_S3_FAIL"] = "s3://kova"
        _run_backup(env, s3="s3://kova/sprenses")

        dumps = [f for f in os.listdir(env["SPRENSES_BACKUP_DIR"]) if f.endswith(".dump")]
        assert len(dumps) == 1, "off-site hatası yerel yedeği götürmemeli"
        snaps = os.listdir(env["SPRENSES_UPLOADS_DIR"])
        assert len(snaps) == 1, "uploads snapshot'ı da korunmalı"


class TestBackupState:
    def test_state_file_reports_success(self, backup_env):
        _run_backup(backup_env, s3="s3://kova/sprenses")
        state = json.load(open(backup_env["SPRENSES_BACKUP_STATE"]))
        assert state["db"]["ok"] is True
        assert state["uploads"]["ok"] is True
        assert state["uploads"]["files"] == 3
        assert state["offsite"]["configured"] is True
        assert state["offsite"]["ok"] is True
        assert state["offsite"]["last_ok"]

    def test_state_file_reports_offsite_failure(self, backup_env):
        env = dict(backup_env)
        env["FAKE_S3_FAIL"] = "s3://kova"
        _run_backup(env, s3="s3://kova/sprenses")
        state = json.load(open(env["SPRENSES_BACKUP_STATE"]))
        assert state["db"]["ok"] is True, "yerel yedek yine başarılı olmalı"
        assert state["offsite"]["ok"] is False
        assert state["offsite"]["error"]

    def test_state_file_reports_offsite_not_configured(self, backup_env):
        """Off-site hiç kurulmamışsa durum dosyası bunu AÇIKÇA söyler (UI kırmızı gösterir)."""
        r = _run_backup(backup_env)  # SPRENSES_BACKUP_S3 yok
        assert r.returncode == 0, "off-site yoksa iş başarısız SAYILMAZ (yerel yedek geçerli)"
        state = json.load(open(backup_env["SPRENSES_BACKUP_STATE"]))
        assert state["offsite"]["configured"] is False
        assert state["offsite"]["ok"] is False

    def test_last_ok_survives_a_later_failure(self, backup_env):
        """Son BAŞARILI off-site zamanı, sonraki başarısız koşumda kaybolmaz."""
        _run_backup(backup_env, s3="s3://kova/sprenses")
        first = json.load(open(backup_env["SPRENSES_BACKUP_STATE"]))["offsite"]["last_ok"]
        assert first

        env = dict(backup_env)
        env["FAKE_S3_FAIL"] = "s3://kova"
        _run_backup(env, s3="s3://kova/sprenses")
        after = json.load(open(env["SPRENSES_BACKUP_STATE"]))["offsite"]
        assert after["ok"] is False
        assert after["last_ok"] == first, "başarısız koşum son başarı zamanını silmemeli"


# ─── 5: off-site'tan geri yükleme (kapanış kriterinin ikinci yarısı) ─────────


class TestOffsiteRestore:
    def test_offsite_dump_is_downloadable_and_valid(self, backup_env):
        """S3'teki dump indirilebilir ve bütünlük kontrolünü geçer.

        `db-restore.sh --offsite`'ın tam tatbikatı `sudo -u postgres` gerektirdiği için
        (geçici DB oluşturma) burada onun AYIRT EDİCİ adımı koşulur: en son nesneyi bul →
        indir → pg_restore --list. Tam tatbikat operatör tarafından canlıda yapılır.
        """
        _run_backup(backup_env, s3="s3://kova/sprenses")

        lib = os.path.join(SCRIPTS, "_offsite-lib.sh")
        probe = (
            '. "%s"; key="$(offsite_latest_key s3://kova/sprenses/db)"; '
            'echo "KEY=$key"; aws s3 cp "s3://kova/sprenses/db/$key" "$1" >/dev/null'
        ) % lib
        dest = os.path.join(backup_env["SPRENSES_BACKUP_DIR"], "indirilen.dump")
        r = subprocess.run(["bash", "-c", probe, "_", dest],
                           env=backup_env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "KEY=sprenses-" in r.stdout, r.stdout
        assert subprocess.run(["pg_restore", "--list", dest],
                              capture_output=True).returncode == 0

    def test_offsite_uploads_are_listable_recursively(self, backup_env):
        """Aynalanan belgeler ALT DİZİNLERİYLE listelenebilir ve geri indirilebilir.

        `db-restore.sh --offsite` belge tatbikatını `aws s3 ls --recursive` çıktısı
        üzerinden yapar. Özyineleme çalışmazsa liste yalnız üst düzey ön ekleri döndürür,
        örneklem BOŞ kalır ve tatbikat "hiç belge yok" der — yani off-site belgeler
        sağlamken bile DR yanlış alarm verir (canlı tatbikatta bir kez yaşandı).
        """
        _run_backup(backup_env, s3="s3://kova/sprenses")
        r = subprocess.run(
            ["bash", "-c",
             'aws s3 ls s3://kova/sprenses/uploads/ --recursive | awk \'{print $NF}\' '
             '| sed "s|^.*/uploads/||" | grep -E "\\.(pdf|xlsx?)$"'],
            env=backup_env, capture_output=True, text=True)
        listed = sorted(line for line in r.stdout.split() if line)
        assert listed == ["belge.pdf", "cari/ekstre.pdf", "cari/liste.xlsx"], r.stdout

    def test_latest_key_picks_newest_by_name(self, backup_env):
        """En son nesne ADA göre seçilir — S3 LastModified replikasyonda değişebilir."""
        d = os.path.join(backup_env["FAKE_S3_ROOT"], "kova", "sprenses", "db")
        os.makedirs(d)
        for name in ("sprenses-20260101-000000.dump", "sprenses-20260725-000000.dump",
                     "sprenses-20260430-000000.dump"):
            open(os.path.join(d, name), "w").write("x")
        r = subprocess.run(
            ["bash", "-c", '. "%s/_offsite-lib.sh"; offsite_latest_key s3://kova/sprenses/db'
             % SCRIPTS],
            env=backup_env, capture_output=True, text=True)
        assert r.stdout.strip() == "sprenses-20260725-000000.dump"


# ─── 6: farklı bölge kuralı (kapanış kriteri) ────────────────────────────────


class TestCrossRegionGuard:
    def _assert_region(self, env, instance, bucket):
        e = dict(env)
        e["SPRENSES_INSTANCE_REGION"] = instance
        e["FAKE_S3_REGION"] = bucket
        return subprocess.run(
            ["bash", "-c",
             '. "%s/_offsite-lib.sh"; offsite_assert_cross_region s3://kova/sprenses' % SCRIPTS],
            env=e, capture_output=True, text=True)

    def test_same_region_is_rejected(self, backup_env):
        """Aynı bölgedeki bucket REDDEDİLİR — DR-002 açıkça FARKLI bölge ister."""
        r = self._assert_region(backup_env, "eu-north-1", "eu-north-1")
        assert r.returncode != 0
        assert "AYNI bölgede" in r.stderr

    def test_different_region_is_accepted(self, backup_env):
        r = self._assert_region(backup_env, "eu-north-1", "eu-west-1")
        assert r.returncode == 0, r.stderr
        assert "farklı-bölge OK" in r.stdout

    def test_same_region_allowed_with_explicit_override(self, backup_env):
        """Bilinçli kabul mümkün ama SESSİZ değil — uyarı basılır."""
        e = dict(backup_env)
        e["SPRENSES_ALLOW_SAME_REGION"] = "1"
        r = self._assert_region(e, "eu-north-1", "eu-north-1")
        assert r.returncode == 0
        assert "bilerek kabul" in r.stderr


# ─── 7: API görünürlüğü ──────────────────────────────────────────────────────


class TestDataStatusApi:
    def test_missing_offsite_is_reported_critical(self, client, auth_headers, tmp_path,
                                                  monkeypatch):
        """Off-site yoksa API bunu KRİTİK olarak söyler — ekranda kırmızı görünsün."""
        state = tmp_path / "backup-state.json"
        state.write_text(json.dumps({
            "ts": "2026-07-25T03:00:00+03:00",
            "db": {"ok": True, "file": "/x/sprenses-1.dump", "bytes": 4600000},
            "uploads": {"ok": True, "snapshot": "/y/1", "files": 1969},
            "offsite": {"configured": False, "ok": False, "target": "",
                        "last_ok": "", "error": "yapılandırılmamış"},
        }))
        monkeypatch.setenv("SPRENSES_BACKUP_STATE", str(state))
        monkeypatch.setenv("SPRENSES_BACKUP_DIR", str(tmp_path))
        monkeypatch.setenv("SPRENSES_UPLOADS_DIR", str(tmp_path))

        r = client.get(f"{API}/data-status", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["offsite"]["configured"] is False
        assert body["offsite"]["level"] == "critical"
        assert "DR-002" in body["offsite"]["message"]

    def test_working_offsite_is_ok(self, client, auth_headers, tmp_path, monkeypatch):
        from datetime import datetime
        state = tmp_path / "backup-state.json"
        now = datetime.now().astimezone().isoformat()
        state.write_text(json.dumps({
            "ts": now,
            "db": {"ok": True, "file": "/x/sprenses-1.dump", "bytes": 4600000},
            "uploads": {"ok": True, "snapshot": "/y/1", "files": 1969},
            "offsite": {"configured": True, "ok": True, "target": "s3://kova/sprenses",
                        "last_ok": now, "error": ""},
        }))
        monkeypatch.setenv("SPRENSES_BACKUP_STATE", str(state))
        monkeypatch.setenv("SPRENSES_BACKUP_DIR", str(tmp_path))
        monkeypatch.setenv("SPRENSES_UPLOADS_DIR", str(tmp_path))

        body = client.get(f"{API}/data-status", headers=auth_headers).json()
        assert body["offsite"]["level"] == "ok"
        assert body["offsite"]["target"] == "s3://kova/sprenses"

    def test_broken_offsite_is_critical(self, client, auth_headers, tmp_path, monkeypatch):
        """Yapılandırılmış ama başarısız off-site = KRİTİK (yedek var sanılır, yoktur)."""
        state = tmp_path / "backup-state.json"
        state.write_text(json.dumps({
            "ts": "2026-07-25T03:00:00+03:00",
            "db": {"ok": True, "file": "", "bytes": 0},
            "uploads": {"ok": True, "snapshot": "", "files": 0},
            "offsite": {"configured": True, "ok": False, "target": "s3://kova/sprenses",
                        "last_ok": "2026-07-01T03:00:00+03:00",
                        "error": "DB yuklenemedi"},
        }))
        monkeypatch.setenv("SPRENSES_BACKUP_STATE", str(state))
        monkeypatch.setenv("SPRENSES_BACKUP_DIR", str(tmp_path))
        monkeypatch.setenv("SPRENSES_UPLOADS_DIR", str(tmp_path))

        body = client.get(f"{API}/data-status", headers=auth_headers).json()
        assert body["offsite"]["level"] == "critical"
        assert "BAŞARISIZ" in body["offsite"]["message"]

    def test_requires_view_permission(self, client, no_perm_user_headers):
        assert client.get(f"{API}/data-status",
                          headers=no_perm_user_headers).status_code == 403

    def test_unauthorized(self, client):
        assert client.get(f"{API}/data-status").status_code == 401
