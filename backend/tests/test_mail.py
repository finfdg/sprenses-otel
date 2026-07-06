"""SMTP e-posta gönderme + bildirim e-posta kanalı + deneme endpoint'i testleri."""

from unittest.mock import MagicMock, patch

import app.utils.mail as mail_mod
from app.utils.mail import is_mail_enabled, send_email
from app.utils.notification import _build_email_html

NOTIF_PREFIX = "/api/notifications"


def _enable_smtp(monkeypatch, use_ssl=True):
    monkeypatch.setattr(mail_mod.settings, "smtp_host", "smtp.turkticaret.net")
    monkeypatch.setattr(mail_mod.settings, "smtp_user", "bilgi@sprenses.com")
    monkeypatch.setattr(mail_mod.settings, "smtp_password", "secret")
    monkeypatch.setattr(mail_mod.settings, "smtp_use_ssl", use_ssl)


class TestMailEnabled:
    def test_disabled_when_no_password(self, monkeypatch):
        monkeypatch.setattr(mail_mod.settings, "smtp_password", "")
        assert is_mail_enabled() is False

    def test_enabled_when_configured(self, monkeypatch):
        _enable_smtp(monkeypatch)
        assert is_mail_enabled() is True


class TestSendEmail:
    def test_returns_false_when_disabled(self, monkeypatch):
        monkeypatch.setattr(mail_mod.settings, "smtp_password", "")
        assert send_email("x@y.com", "Konu", "<b>hi</b>") is False

    def test_ssl_path_sends(self, monkeypatch):
        _enable_smtp(monkeypatch, use_ssl=True)
        server = MagicMock()
        cm = MagicMock()
        cm.__enter__.return_value = server
        with patch.object(mail_mod.smtplib, "SMTP_SSL", return_value=cm) as smtp_ssl:
            ok = send_email("dest@x.com", "Konu", "<b>Merhaba</b>")
        assert ok is True
        smtp_ssl.assert_called_once()
        server.login.assert_called_once_with("bilgi@sprenses.com", "secret")
        server.send_message.assert_called_once()

    def test_starttls_path_sends(self, monkeypatch):
        _enable_smtp(monkeypatch, use_ssl=False)
        server = MagicMock()
        cm = MagicMock()
        cm.__enter__.return_value = server
        with patch.object(mail_mod.smtplib, "SMTP", return_value=cm):
            ok = send_email("dest@x.com", "Konu", "<b>Merhaba</b>")
        assert ok is True
        server.starttls.assert_called_once()
        server.login.assert_called_once()
        server.send_message.assert_called_once()

    def test_returns_false_on_smtp_error(self, monkeypatch):
        _enable_smtp(monkeypatch, use_ssl=True)
        with patch.object(mail_mod.smtplib, "SMTP_SSL", side_effect=OSError("bağlanamadı")):
            assert send_email("dest@x.com", "Konu", "<b>hi</b>") is False


class TestBuildEmailHtml:
    def test_escapes_html(self):
        html = _build_email_html("<script>alert(1)</script>", "gövde & <b>x</b>", None)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html
        assert "&amp;" in html

    def test_relative_link_becomes_absolute(self):
        html = _build_email_html("T", "B", "/dashboard/finans/onay")
        assert "https://sprenses.com/dashboard/finans/onay" in html
        assert "Görüntüle" in html

    def test_absolute_link_kept(self):
        html = _build_email_html("T", "B", "https://sprenses.com/x")
        assert "https://sprenses.com/x" in html

    def test_no_link_no_button(self):
        html = _build_email_html("T", "B", None)
        assert "Görüntüle" not in html


class TestTestEmailEndpoint:
    def test_requires_auth(self, client):
        assert client.post(f"{NOTIF_PREFIX}/test-email").status_code in (401, 403)

    def test_forbidden_without_permission(self, client, no_perm_user_headers):
        resp = client.post(f"{NOTIF_PREFIX}/test-email", headers=no_perm_user_headers)
        assert resp.status_code == 403

    def test_503_when_smtp_disabled(self, client, auth_headers):
        with patch("app.routers.notifications.is_mail_enabled", return_value=False):
            resp = client.post(f"{NOTIF_PREFIX}/test-email", headers=auth_headers)
        assert resp.status_code == 503

    def test_success_sends_to_system_mailbox(self, client, auth_headers):
        from app.config import settings

        with patch("app.routers.notifications.is_mail_enabled", return_value=True), patch(
            "app.routers.notifications.send_email", return_value=True
        ) as se:
            resp = client.post(f"{NOTIF_PREFIX}/test-email", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        # Deneme e-postası her zaman sistem kutusuna (SMTP kullanıcısı) gider
        assert data["sent_to"] == settings.smtp_user
        se.assert_called_once()
        assert se.call_args.kwargs["to"] == settings.smtp_user

    def test_502_when_send_fails(self, client, auth_headers):
        with patch("app.routers.notifications.is_mail_enabled", return_value=True), patch(
            "app.routers.notifications.send_email", return_value=False
        ):
            resp = client.post(f"{NOTIF_PREFIX}/test-email", headers=auth_headers)
        assert resp.status_code == 502

    def test_send_to_specific_user(self, client, auth_headers):
        recips = client.get(
            f"{NOTIF_PREFIX}/test-email/recipients", headers=auth_headers
        ).json()
        admin = next(r for r in recips if r["email"] == "admin@sprenses.com")
        with patch("app.routers.notifications.is_mail_enabled", return_value=True), patch(
            "app.routers.notifications.send_email", return_value=True
        ) as se:
            resp = client.post(
                f"{NOTIF_PREFIX}/test-email",
                json={"user_id": admin["id"]},
                headers=auth_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["sent_to"] == "admin@sprenses.com"
        assert se.call_args.kwargs["to"] == "admin@sprenses.com"

    def test_404_unknown_user(self, client, auth_headers):
        with patch("app.routers.notifications.is_mail_enabled", return_value=True), patch(
            "app.routers.notifications.send_email", return_value=True
        ):
            resp = client.post(
                f"{NOTIF_PREFIX}/test-email",
                json={"user_id": 999999},
                headers=auth_headers,
            )
        assert resp.status_code == 404


class TestTestEmailRecipients:
    def test_list_recipients(self, client, auth_headers):
        resp = client.get(f"{NOTIF_PREFIX}/test-email/recipients", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert any(r["email"] == "admin@sprenses.com" for r in data)
        for r in data:
            assert set(r.keys()) == {"id", "name", "email"}

    def test_recipients_forbidden_without_permission(self, client, no_perm_user_headers):
        resp = client.get(
            f"{NOTIF_PREFIX}/test-email/recipients", headers=no_perm_user_headers
        )
        assert resp.status_code == 403
