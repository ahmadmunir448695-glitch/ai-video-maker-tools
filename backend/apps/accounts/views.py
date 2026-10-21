"""Authentication endpoints.

Token strategy: the short-lived **access token** is returned in the response body
for the SPA to keep in memory, and the long-lived **refresh token** is set as an
HttpOnly cookie scoped to ``/api/auth/``. JavaScript can never read the refresh
token, so an XSS bug cannot walk away with a 14-day credential, and the access
token dies with the browser tab.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import (
    ChangePasswordSerializer,
    LoginSerializer,
    RegisterSerializer,
    UserSerializer,
)
from .usage import usage_summary

logger = logging.getLogger("apps.accounts")


def _issue_tokens(user) -> tuple[str, str]:
    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token), str(refresh)


def _auth_response(user, *, created: bool = False) -> Response:
    access, refresh = _issue_tokens(user)
    response = Response(
        {"access": access, "user": UserSerializer(user).data},
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )
    _set_refresh_cookie(response, refresh)
    return response


def _set_refresh_cookie(response: Response, refresh: str) -> None:
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        refresh,
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
        path=settings.REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        settings.REFRESH_COOKIE_NAME,
        path=settings.REFRESH_COOKIE_PATH,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )


class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    @transaction.atomic
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        logger.info("Account created: %s", user.id)
        return _auth_response(user, created=True)


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        return _auth_response(serializer.validated_data["user"])


class RefreshView(APIView):
    """Exchange the refresh cookie for a fresh access token.

    The SPA calls this on boot and whenever a request comes back 401, which is
    how a signed-in user survives a page reload without any token in storage.
    """

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        raw = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if not raw:
            # 401, not 400: a missing cookie is an authentication state, not a
            # malformed request. The SPA calls this on every boot to find out
            # whether a session exists, and treats 401 as "signed out".
            return Response(
                {"detail": "You are not signed in.", "code": "no_refresh_token"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            token = RefreshToken(raw)
            access = str(token.access_token)
            user_id = token.payload.get(settings.SIMPLE_JWT["USER_ID_CLAIM"])
        except TokenError as exc:
            response = Response(
                {"detail": "Your session has expired. Please sign in again.", "code": "refresh_expired"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            _clear_refresh_cookie(response)
            logger.info("Refresh rejected: %s", exc)
            return response

        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
        if user is None:
            response = Response(
                {"detail": "Your session is no longer valid.", "code": "refresh_expired"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            _clear_refresh_cookie(response)
            return response

        response = Response({"access": access, "user": UserSerializer(user).data})

        # ROTATE_REFRESH_TOKENS is on: blacklist the token just used and hand the
        # client its successor, so a stolen cookie is good for one use at most.
        if settings.SIMPLE_JWT.get("ROTATE_REFRESH_TOKENS"):
            try:
                token.blacklist()
            except AttributeError:  # pragma: no cover - blacklist app always installed
                pass
            _set_refresh_cookie(response, str(RefreshToken.for_user(user)))

        return response


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        raw = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if raw:
            try:
                RefreshToken(raw).blacklist()
            except (TokenError, AttributeError):
                # Already expired or already revoked — the user is logged out either way.
                pass
        response = Response(status=status.HTTP_204_NO_CONTENT)
        _clear_refresh_cookie(response)
        return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "read"

    def get(self, request):
        return Response({"user": UserSerializer(request.user).data, "usage": usage_summary(request.user)})

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"user": serializer.data})


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "auth"

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])

        # Changing a password invalidates the old session: issue a new pair.
        old = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if old:
            try:
                RefreshToken(old).blacklist()
            except (TokenError, AttributeError):
                pass

        access, refresh = _issue_tokens(user)
        response = Response({"access": access, "user": UserSerializer(user).data})
        _set_refresh_cookie(response, refresh)
        return response
