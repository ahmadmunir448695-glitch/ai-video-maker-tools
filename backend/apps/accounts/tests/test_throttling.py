"""Rate limiting on the endpoints most worth abusing."""

from __future__ import annotations

import pytest
from rest_framework.settings import api_settings

pytestmark = pytest.mark.django_db


@pytest.fixture
def tight_auth_limit():
    """Temporarily shrink the auth throttle so a test can reach it quickly."""
    original = api_settings.DEFAULT_THROTTLE_RATES.copy()
    api_settings.DEFAULT_THROTTLE_RATES["auth"] = "3/hour"
    yield
    api_settings.DEFAULT_THROTTLE_RATES.clear()
    api_settings.DEFAULT_THROTTLE_RATES.update(original)


def test_password_guessing_is_cut_off_by_the_throttle(api, user, tight_auth_limit):
    """A credential-stuffing run must hit a wall rather than continue forever."""
    codes = [
        api.post("/api/auth/login", {"email": user.email, "password": "wrong-every-time"}).status_code
        for _ in range(6)
    ]

    assert 429 in codes, f"expected a 429 once the auth limit was passed, got {codes}"
    assert codes[0] == 400, "the first attempt should be a normal credential rejection"


def test_registration_shares_the_throttled_auth_scope(api, tight_auth_limit):
    codes = [
        api.post(
            "/api/auth/register", {"email": f"spam{index}@example.com", "password": "Str0ng-Passphrase!42"}
        ).status_code
        for index in range(6)
    ]

    assert 429 in codes, f"registration should be rate limited, got {codes}"
