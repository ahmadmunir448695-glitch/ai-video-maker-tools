"""A single, predictable error shape for the whole API.

Every failure the SPA can encounter comes back as::

    {"detail": "...", "code": "...", "fields": {...}}

``fields`` is only present for validation errors.
"""

from __future__ import annotations

import logging
import uuid

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("apps.core.exceptions")


class DomainError(Exception):
    """Base class for business-rule failures that map onto an HTTP status."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The request could not be completed."
    code = "domain_error"

    def __init__(self, detail: str | None = None, *, code: str | None = None):
        self.detail = detail or self.default_detail
        if code:
            self.code = code
        super().__init__(self.detail)


class QuotaExceeded(DomainError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_detail = "You have reached a usage limit on your plan."
    code = "quota_exceeded"


class InvalidMedia(DomainError):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The uploaded file is not a video we can process."
    code = "invalid_media"


class ConflictError(DomainError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "That action conflicts with the current state of the resource."
    code = "conflict"


def api_exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return Response({"detail": exc.detail, "code": exc.code}, status=exc.status_code)

    if isinstance(exc, DjangoPermissionDenied):
        return Response(
            {"detail": "You do not have permission to perform this action.", "code": "permission_denied"},
            status=status.HTTP_403_FORBIDDEN,
        )

    if isinstance(exc, Http404):
        return Response({"detail": "Not found.", "code": "not_found"}, status=status.HTTP_404_NOT_FOUND)

    response = drf_exception_handler(exc, context)

    if response is None:
        # Something we did not anticipate: log it with a reference the user can
        # quote, but never leak the traceback or internals to the client.
        reference = uuid.uuid4().hex[:12]
        logger.exception("Unhandled API error [ref=%s] in %s", reference, context.get("view"))
        return Response(
            {
                "detail": "Something went wrong on our side. Please try again.",
                "code": "server_error",
                "reference": reference,
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    data = response.data
    if isinstance(data, dict) and "detail" in data and len(data) == 1:
        code = getattr(exc, "default_code", "error")
        response.data = {"detail": str(data["detail"]), "code": code}
    elif isinstance(data, dict):
        response.data = {
            "detail": "Some of the values you sent are not valid.",
            "code": "validation_error",
            "fields": data,
        }
    elif isinstance(data, list):
        response.data = {"detail": " ".join(str(item) for item in data), "code": "validation_error"}

    return response
