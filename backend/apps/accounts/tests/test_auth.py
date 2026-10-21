"""Authentication: registration, login, refresh-cookie handling and logout."""

from __future__ import annotations

import pytest
from conftest import FIXTURE_PASSWORD
from django.conf import settings
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db

User = get_user_model()
REGISTER = "/api/auth/register"
LOGIN = "/api/auth/login"
REFRESH = "/api/auth/refresh"
LOGOUT = "/api/auth/logout"
ME = "/api/auth/me"


class TestRegistration:
    def test_registering_creates_an_account_and_signs_the_user_in(self, api):
        response = api.post(
            REGISTER,
            {"email": "New.User@Example.com", "password": FIXTURE_PASSWORD, "display_name": "New"},
        )

        assert response.status_code == 201, response.data
        assert response.data["access"]
        assert response.data["user"]["email"] == "new.user@example.com", "emails are normalised to lowercase"
        assert User.objects.filter(email="new.user@example.com").exists()

    def test_the_refresh_token_is_an_httponly_cookie(self, api):
        """The refresh token must be unreachable from JavaScript, so XSS cannot steal it."""
        response = api.post(REGISTER, {"email": "cookie@example.com", "password": FIXTURE_PASSWORD})

        cookie = response.cookies[settings.REFRESH_COOKIE_NAME]
        assert cookie["httponly"], "the refresh cookie must be HttpOnly"
        assert cookie["path"] == settings.REFRESH_COOKIE_PATH
        assert cookie["samesite"] == settings.REFRESH_COOKIE_SAMESITE

    def test_the_password_is_never_returned_or_stored_in_clear(self, api):
        response = api.post(REGISTER, {"email": "hash@example.com", "password": FIXTURE_PASSWORD})

        assert "password" not in response.data
        user = User.objects.get(email="hash@example.com")
        assert user.password != FIXTURE_PASSWORD
        assert user.check_password(FIXTURE_PASSWORD)

    @pytest.mark.parametrize("weak", ["short", "password123", "12345678901", "aaaaaaaaaa"])
    def test_weak_passwords_are_rejected(self, api, weak):
        response = api.post(REGISTER, {"email": "weak@example.com", "password": weak})

        assert response.status_code == 400
        assert not User.objects.filter(email="weak@example.com").exists()

    def test_a_duplicate_email_is_rejected(self, api, user):
        response = api.post(REGISTER, {"email": user.email, "password": FIXTURE_PASSWORD})

        assert response.status_code == 400
        assert User.objects.filter(email=user.email).count() == 1

    def test_a_duplicate_email_in_different_case_is_rejected(self, api, user):
        response = api.post(REGISTER, {"email": user.email.upper(), "password": FIXTURE_PASSWORD})

        assert response.status_code == 400

    def test_an_invalid_email_is_rejected(self, api):
        assert api.post(REGISTER, {"email": "not-an-email", "password": FIXTURE_PASSWORD}).status_code == 400


class TestLogin:
    def test_correct_credentials_return_an_access_token(self, api, user):
        response = api.post(LOGIN, {"email": user.email, "password": FIXTURE_PASSWORD})

        assert response.status_code == 200
        assert response.data["access"]
        assert response.data["user"]["id"] == str(user.id)

    def test_the_wrong_password_is_rejected(self, api, user):
        response = api.post(LOGIN, {"email": user.email, "password": "definitely-not-it-9999"})

        assert response.status_code == 400
        assert "access" not in response.data

    def test_an_unknown_email_is_indistinguishable_from_a_wrong_password(self, api, user):
        """Otherwise the endpoint becomes a way to find out who has an account."""
        unknown = api.post(LOGIN, {"email": "nobody@example.com", "password": FIXTURE_PASSWORD})
        wrong = api.post(LOGIN, {"email": user.email, "password": "definitely-not-it-9999"})

        assert unknown.status_code == wrong.status_code
        assert unknown.data == wrong.data

    def test_a_disabled_account_cannot_sign_in(self, api, user):
        user.is_active = False
        user.save(update_fields=["is_active"])

        assert api.post(LOGIN, {"email": user.email, "password": FIXTURE_PASSWORD}).status_code == 400

    def test_login_is_case_insensitive_on_the_email(self, api, user):
        assert api.post(LOGIN, {"email": user.email.upper(), "password": FIXTURE_PASSWORD}).status_code == 200


class TestRefresh:
    def test_the_cookie_is_exchanged_for_a_fresh_access_token(self, api, user):
        api.post(LOGIN, {"email": user.email, "password": FIXTURE_PASSWORD})

        response = api.post(REFRESH)

        assert response.status_code == 200
        assert response.data["access"]
        assert response.data["user"]["id"] == str(user.id)

    def test_refreshing_without_a_cookie_is_refused(self, api):
        assert api.post(REFRESH).status_code == 400

    def test_a_forged_cookie_is_refused_and_cleared(self, api):
        api.cookies[settings.REFRESH_COOKIE_NAME] = "not.a.real.token"

        response = api.post(REFRESH)

        assert response.status_code == 401
        assert response.data["code"] == "refresh_expired"

    def test_a_refresh_token_cannot_be_replayed_after_rotation(self, api, user):
        """Rotation plus blacklisting means a stolen cookie is good for one use."""
        login = api.post(LOGIN, {"email": user.email, "password": FIXTURE_PASSWORD})
        stolen = login.cookies[settings.REFRESH_COOKIE_NAME].value

        assert api.post(REFRESH).status_code == 200  # rotates the cookie

        api.cookies[settings.REFRESH_COOKIE_NAME] = stolen
        assert api.post(REFRESH).status_code == 401, "the old refresh token must be dead"

    def test_a_deactivated_user_cannot_refresh(self, api, user):
        api.post(LOGIN, {"email": user.email, "password": FIXTURE_PASSWORD})
        user.is_active = False
        user.save(update_fields=["is_active"])

        assert api.post(REFRESH).status_code == 401


class TestLogout:
    def test_logout_clears_the_cookie_and_kills_the_refresh_token(self, api, user):
        api.post(LOGIN, {"email": user.email, "password": FIXTURE_PASSWORD})

        assert api.post(LOGOUT).status_code == 204
        assert api.post(REFRESH).status_code in (400, 401)

    def test_logging_out_when_not_signed_in_is_harmless(self, api):
        assert api.post(LOGOUT).status_code == 204


class TestMe:
    def test_an_anonymous_request_is_rejected(self, api):
        assert api.get(ME).status_code == 401

    def test_a_signed_in_user_sees_their_profile_and_usage(self, auth_api, user):
        response = auth_api.get(ME)

        assert response.status_code == 200
        assert response.data["user"]["email"] == user.email
        usage = response.data["usage"]
        assert usage["storage_bytes_limit"] > 0
        assert usage["max_upload_bytes"] == settings.MAX_UPLOAD_BYTES

    def test_a_user_can_change_their_display_name(self, auth_api):
        response = auth_api.patch(ME, {"display_name": "Renamed"})

        assert response.status_code == 200
        assert response.data["user"]["display_name"] == "Renamed"

    def test_a_user_cannot_promote_themselves(self, auth_api, user):
        """plan is read-only: upgrading is a billing decision, not a PATCH."""
        auth_api.patch(ME, {"plan": "studio", "email": "hijack@example.com"})

        user.refresh_from_db()
        assert user.plan == "free"
        assert user.email == "creator@example.com"


class TestChangePassword:
    def test_a_user_can_change_their_password_with_the_current_one(self, auth_api, user):
        response = auth_api.post(
            "/api/auth/password",
            {"current_password": FIXTURE_PASSWORD, "new_password": "An0ther-Gr8-Passphrase!"},
        )

        assert response.status_code == 200
        user.refresh_from_db()
        assert user.check_password("An0ther-Gr8-Passphrase!")

    def test_the_wrong_current_password_is_refused(self, auth_api, user):
        response = auth_api.post(
            "/api/auth/password",
            {"current_password": "wrong-one-entirely", "new_password": "An0ther-Gr8-Passphrase!"},
        )

        assert response.status_code == 400
        user.refresh_from_db()
        assert user.check_password(FIXTURE_PASSWORD)

    def test_a_weak_new_password_is_refused(self, auth_api):
        response = auth_api.post(
            "/api/auth/password", {"current_password": FIXTURE_PASSWORD, "new_password": "short"}
        )

        assert response.status_code == 400

    def test_anonymous_users_cannot_change_a_password(self, api):
        response = api.post(
            "/api/auth/password", {"current_password": FIXTURE_PASSWORD, "new_password": "whatever-long-1"}
        )
        assert response.status_code == 401
