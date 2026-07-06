"""E-posta teyidi (doğrulama) testleri — token, gönderim endpoint'i, public verify, sıfırlama."""

from unittest.mock import patch

import pytest
from jose import JWTError

from app.models.role import Role
from app.models.user import User
from app.utils.security import (
    create_access_token,
    create_email_verification_token,
    decode_email_verification_token,
)

USERS_PREFIX = "/api/system/users"
AUTH_PREFIX = "/api/auth"


def _make_user(db, *, username, email, verified=False):
    role = db.query(Role).first()
    u = User(
        username=username,
        email=email,
        hashed_password="x",
        first_name="Ver",
        last_name="Target",
        role_id=role.id,
        is_active=True,
        email_verified=verified,
    )
    db.add(u)
    db.flush()
    return u


class TestVerificationToken:
    def test_roundtrip(self):
        t = create_email_verification_token(7, "a@b.com")
        assert decode_email_verification_token(t) == {"user_id": 7, "email": "a@b.com"}

    def test_wrong_purpose_rejected(self):
        # Normal access token (farklı amaç) teyit çözümünde reddedilmeli
        access = create_access_token({"sub": "7"})
        with pytest.raises(JWTError):
            decode_email_verification_token(access)

    def test_garbage_rejected(self):
        with pytest.raises(JWTError):
            decode_email_verification_token("not-a-real-token")


class TestSendVerification:
    def test_forbidden_without_permission(self, client, no_perm_user_headers, db):
        u = _make_user(db, username="sv_forbidden", email="svf@sprenses.com")
        resp = client.post(
            f"{USERS_PREFIX}/{u.id}/send-verification", headers=no_perm_user_headers
        )
        assert resp.status_code == 403

    def test_404_unknown_user(self, client, auth_headers):
        resp = client.post(f"{USERS_PREFIX}/999999/send-verification", headers=auth_headers)
        assert resp.status_code == 404

    def test_400_when_no_email(self, client, auth_headers, db):
        u = _make_user(db, username="sv_noemail", email="")
        resp = client.post(f"{USERS_PREFIX}/{u.id}/send-verification", headers=auth_headers)
        assert resp.status_code == 400

    def test_503_when_smtp_disabled(self, client, auth_headers, db):
        u = _make_user(db, username="sv_smtpoff", email="svs@sprenses.com")
        with patch("app.routers.system_users.is_mail_enabled", return_value=False):
            resp = client.post(f"{USERS_PREFIX}/{u.id}/send-verification", headers=auth_headers)
        assert resp.status_code == 503

    def test_success(self, client, auth_headers, db):
        u = _make_user(db, username="sv_ok", email="svok@sprenses.com")
        with patch("app.routers.system_users.is_mail_enabled", return_value=True), patch(
            "app.routers.system_users.send_email_background"
        ) as bg:
            resp = client.post(f"{USERS_PREFIX}/{u.id}/send-verification", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["email"] == "svok@sprenses.com"
        bg.assert_called_once()


class TestVerifyEmailPublic:
    def test_valid_token_verifies(self, client, db):
        u = _make_user(db, username="ve_valid", email="vv@sprenses.com")
        token = create_email_verification_token(u.id, u.email)
        resp = client.post(f"{AUTH_PREFIX}/verify-email", json={"token": token})
        assert resp.status_code == 200
        db.refresh(u)
        assert u.email_verified is True
        assert u.email_verified_at is not None

    def test_invalid_token(self, client):
        resp = client.post(f"{AUTH_PREFIX}/verify-email", json={"token": "garbage"})
        assert resp.status_code == 400

    def test_email_changed_invalidates_link(self, client, db):
        u = _make_user(db, username="ve_changed", email="old@sprenses.com")
        token = create_email_verification_token(u.id, "old@sprenses.com")
        u.email = "new@sprenses.com"
        db.flush()
        resp = client.post(f"{AUTH_PREFIX}/verify-email", json={"token": token})
        assert resp.status_code == 400
        db.refresh(u)
        assert u.email_verified is False

    def test_idempotent_when_already_verified(self, client, db):
        u = _make_user(db, username="ve_idem", email="already@sprenses.com", verified=True)
        token = create_email_verification_token(u.id, u.email)
        resp = client.post(f"{AUTH_PREFIX}/verify-email", json={"token": token})
        assert resp.status_code == 200


class TestEmailChangeResetsVerified:
    def test_update_email_resets_verified(self, client, auth_headers, db):
        u = _make_user(db, username="ec_reset", email="reset-me@sprenses.com", verified=True)
        db.flush()
        resp = client.patch(
            f"{USERS_PREFIX}/{u.id}",
            json={"email": "changed@sprenses.com"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["email_verified"] is False

    def test_update_other_field_keeps_verified(self, client, auth_headers, db):
        u = _make_user(db, username="ec_keep", email="keep@sprenses.com", verified=True)
        db.flush()
        resp = client.patch(
            f"{USERS_PREFIX}/{u.id}",
            json={"first_name": "Yeni"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["email_verified"] is True
