from __future__ import annotations

import shutil

from django.conf import settings
from django.db import connection
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Liveness and readiness probe for load balancers and deploy checks.

    Reports each dependency separately so a failing probe says what is wrong,
    and returns 503 when something the app genuinely needs is unavailable.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []

    def get(self, request):
        checks: dict[str, str] = {}
        healthy = True

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {type(exc).__name__}"
            healthy = False

        checks["ffmpeg"] = "ok" if shutil.which(settings.FFMPEG_BINARY) else "missing"
        checks["ffprobe"] = "ok" if shutil.which(settings.FFPROBE_BINARY) else "missing"
        if "missing" in (checks["ffmpeg"], checks["ffprobe"]):
            healthy = False

        if settings.CELERY_TASK_ALWAYS_EAGER:
            checks["queue"] = "eager (no broker configured)"
        else:
            try:
                from config.celery import app as celery_app

                with celery_app.connection_for_read() as conn:
                    conn.ensure_connection(max_retries=0, timeout=2)
                checks["queue"] = "ok"
            except Exception as exc:
                checks["queue"] = f"error: {type(exc).__name__}"
                healthy = False

        checks["storage"] = "object-storage" if settings.USE_OBJECT_STORAGE else "local-disk"

        return Response(
            {"status": "ok" if healthy else "degraded", "checks": checks},
            status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )
