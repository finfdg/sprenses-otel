"""Sistem Yedekleme (system.backup) — izin + restore hash doğrulama + status.

GÜVENLİ: yalnız salt-okuma git (status) + restore'un erken-dönüş yolları (400 geçersiz hash,
404 var olmayan commit) + izin 403'leri test edilir. Gerçek commit/push/checkout TETİKLENMEZ
(run_backup başarı yolu ve geçerli-commit restore ÇAĞRILMAZ). Audit'te 'testi yok' (🟡) idi.
"""

API = "/api/system/backup"


class TestBackupStatus:
    def test_status_shape(self, client, auth_headers):
        r = client.get(f"{API}/status", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        for key in ("last_commit", "ahead", "history"):
            assert key in body
        assert isinstance(body["history"], list)

    def test_status_requires_view(self, client, no_perm_user_headers):
        assert client.get(f"{API}/status", headers=no_perm_user_headers).status_code == 403

    def test_status_unauthorized(self, client):
        assert client.get(f"{API}/status").status_code == 401


class TestBackupRestoreValidation:
    def test_invalid_hash_400(self, client, auth_headers):
        # hex olmayan → git'e HİÇ gitmeden 400 (mutasyon yok)
        r = client.post(f"{API}/restore", headers=auth_headers, json={"commit": "not-a-hash!!"})
        assert r.status_code == 400

    def test_too_long_hash_400(self, client, auth_headers):
        r = client.post(f"{API}/restore", headers=auth_headers, json={"commit": "a" * 65})
        assert r.status_code == 400

    def test_unknown_commit_404(self, client, auth_headers):
        # geçerli formatta ama var olmayan commit → yalnız `git cat-file` (salt-okuma) → 404
        r = client.post(f"{API}/restore", headers=auth_headers, json={"commit": "0" * 40})
        assert r.status_code == 404

    def test_restore_requires_use(self, client, viewer_user_headers):
        # viewer (yalnız view) restore (use) yapamaz → fonksiyon gövdesine/git'e hiç ulaşmaz
        r = client.post(f"{API}/restore", headers=viewer_user_headers, json={"commit": "0" * 40})
        assert r.status_code == 403


class TestBackupRunPermission:
    def test_run_requires_use(self, client, viewer_user_headers):
        # viewer use yapamaz → gerçek commit/push TETİKLENMEZ (403 fonksiyon öncesi)
        assert client.post(f"{API}/run", headers=viewer_user_headers).status_code == 403

    def test_run_unauthorized(self, client):
        assert client.post(f"{API}/run").status_code == 401
