"""Sistem — Dokümanlar modülü testleri (liste / görüntüle / indir / güvenlik / izin)."""

PREFIX = "/api/system/docs"


class TestSystemDocs:
    def test_list_documents(self, client, auth_headers):
        r = client.get(f"{PREFIX}/", headers=auth_headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["total"] > 0
        paths = {it["path"] for it in data["items"]}
        assert "CLAUDE.md" in paths  # kök rehber listede
        # her öğede zorunlu alanlar
        first = data["items"][0]
        for k in ("path", "title", "category", "size", "modified"):
            assert k in first

    def test_raw_content(self, client, auth_headers):
        r = client.get(f"{PREFIX}/raw", headers=auth_headers, params={"path": "CLAUDE.md"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["path"] == "CLAUDE.md"
        assert len(body["content"]) > 100  # gerçek içerik döndü

    def test_raw_path_traversal_blocked(self, client, auth_headers):
        # İzinli kümede olmayan / traversal yolu → 404 (asla dosya sızdırmaz)
        for bad in ("../../etc/passwd", "/etc/passwd", "backend/.env", "../backend/.env"):
            r = client.get(f"{PREFIX}/raw", headers=auth_headers, params={"path": bad})
            assert r.status_code == 404, f"{bad} → {r.status_code}"

    def test_download(self, client, auth_headers):
        r = client.get(f"{PREFIX}/download", headers=auth_headers, params={"path": "CLAUDE.md"})
        assert r.status_code == 200, r.text
        assert "attachment" in r.headers.get("content-disposition", "")

    def test_export_word(self, client, auth_headers):
        r = client.get(f"{PREFIX}/export/word", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.content[:2] == b"PK"  # geçerli .docx (ZIP)
        assert "wordprocessingml" in r.headers.get("content-type", "")

    def test_requires_permission(self, client, no_perm_user_headers):
        # system.docs view izni olmayan kullanıcı → 403
        for path in ("/", "/raw?path=CLAUDE.md", "/export/word"):
            r = client.get(f"{PREFIX}{path}", headers=no_perm_user_headers)
            assert r.status_code == 403, f"{path} → {r.status_code}"
