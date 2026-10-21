from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.usage import active_renders, exports_today, storage_bytes_used
from apps.core.exceptions import ConflictError, InvalidMedia, QuotaExceeded
from apps.core.permissions import IsOwner
from apps.core.storage import signed_url

from .models import ACTIVE_STATUSES, ExportJob, JobStatus
from .serializers import (
    ExportJobCreateSerializer,
    ExportJobSerializer,
)
from .specs import (
    ASPECT_RATIOS,
    FIT_MODES,
    QUALITY_PRESETS,
    ROTATIONS,
    SPEED_PRESETS,
    target_resolution,
)
from .tasks import cleanup_job_files, delete_export_files, queue_render

logger = logging.getLogger("apps.editing")


class ExportJobViewSet(viewsets.ModelViewSet):
    """Render jobs. Every action is scoped to the requesting user's own rows."""

    serializer_class = ExportJobSerializer
    permission_classes = [IsOwner]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        queryset = ExportJob.objects.filter(owner=self.request.user).select_related("source")

        status_filter = self.request.query_params.get("status")
        if status_filter == "active":
            queryset = queryset.filter(status__in=ACTIVE_STATUSES)
        elif status_filter in JobStatus.values:
            queryset = queryset.filter(status=status_filter)

        source_filter = self.request.query_params.get("source")
        if source_filter:
            queryset = queryset.filter(source_id=source_filter)

        return queryset

    def get_throttles(self):
        self.throttle_scope = "render" if self.action in {"create", "retry"} else "read"
        return super().get_throttles()

    def _enforce_render_quotas(self, user) -> None:
        if active_renders(user) >= settings.MAX_CONCURRENT_RENDERS_PER_USER:
            raise QuotaExceeded(
                f"You already have {settings.MAX_CONCURRENT_RENDERS_PER_USER} renders running. "
                "Wait for one to finish before starting another.",
                code="too_many_active_renders",
            )
        if exports_today(user) >= settings.MAX_EXPORTS_PER_DAY:
            raise QuotaExceeded(
                f"You have reached today's limit of {settings.MAX_EXPORTS_PER_DAY} exports.",
                code="daily_export_limit",
            )
        if storage_bytes_used(user) >= settings.MAX_STORAGE_BYTES_PER_USER:
            raise QuotaExceeded(
                "You are out of storage. Delete a video or an export to free up room.",
                code="storage_quota_exceeded",
            )

    def create(self, request, *args, **kwargs):
        """Queue a render.

        If this user has already rendered the identical edit of the identical
        source, the finished export is returned instead of rendering it again.
        """
        serializer = ExportJobCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        asset = serializer.validated_data["source"]
        spec = serializer.validated_data["edit_spec"]
        fingerprint = spec.fingerprint(asset.id)

        existing = (
            ExportJob.objects.filter(owner=request.user, source=asset, fingerprint=fingerprint)
            .exclude(status__in=[JobStatus.FAILED, JobStatus.CANCELLED])
            .order_by("-created_at")
            .first()
        )
        if existing is not None:
            # Cost control: identical work is never paid for twice.
            logger.info("Reusing export %s for identical spec", existing.pk)
            response = Response(self.get_serializer(existing).data, status=status.HTTP_200_OK)
            response["X-Export-Reused"] = "true"
            return response

        self._enforce_render_quotas(request.user)

        with transaction.atomic():
            job = ExportJob.objects.create(
                owner=request.user,
                source=asset,
                title=serializer.validated_data.get("title", "").strip(),
                spec=spec.to_dict(),
                fingerprint=fingerprint,
                status=JobStatus.PENDING,
            )
            queue_render(job)

        job.refresh_from_db()
        return Response(self.get_serializer(job).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, *args, **kwargs):
        """Ask a running render to stop.

        The worker notices the status change within a couple of seconds and
        terminates FFmpeg, so this is a real cancellation, not just a flag.
        """
        job = self.get_object()
        if not job.is_cancellable:
            raise ConflictError(
                f"This export is already {job.get_status_display().lower()} and cannot be cancelled.",
                code="not_cancellable",
            )

        updated = ExportJob.objects.filter(pk=job.pk, status__in=ACTIVE_STATUSES).update(
            status=JobStatus.CANCELLED,
            error_message="Cancelled.",
            finished_at=timezone.now(),
        )
        if not updated:
            raise ConflictError("This export finished before it could be cancelled.", code="not_cancellable")

        job.refresh_from_db()
        return Response(self.get_serializer(job).data)

    @action(detail=True, methods=["post"])
    def retry(self, request, *args, **kwargs):
        """Re-queue a failed or cancelled render.

        The same row is reused and its previous output discarded, so a retry can
        never leave two files or two 'published' records behind.
        """
        job = self.get_object()
        if not job.can_retry:
            raise ConflictError(
                f"Only failed or cancelled exports can be retried; this one is {job.status}.",
                code="not_retryable",
            )

        self._enforce_render_quotas(request.user)
        cleanup_job_files(job)

        with transaction.atomic():
            ExportJob.objects.filter(pk=job.pk).update(
                status=JobStatus.PENDING,
                progress=0,
                output=None,
                output_size_bytes=0,
                output_width=0,
                output_height=0,
                output_duration_seconds=0,
                error_message="",
                error_log="",
                started_at=None,
                finished_at=None,
                celery_task_id="",
            )
            job.refresh_from_db()
            queue_render(job)

        job.refresh_from_db()
        return Response(self.get_serializer(job).data)

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, *args, **kwargs):
        """Mint a short-lived download URL, but only for this job's owner."""
        job = self.get_object()
        if job.status != JobStatus.SUCCEEDED or not job.output:
            raise ConflictError(
                "This export is not finished yet, so there is nothing to download.",
                code="not_ready",
            )
        url = signed_url(job.output)
        if not url:
            raise InvalidMedia("The exported file is missing from storage.", code="file_missing")

        safe_title = "".join(c for c in job.display_title if c.isalnum() or c in " -_").strip() or "export"
        return Response({"url": url, "filename": f"{safe_title}.mp4"})

    def destroy(self, request, *args, **kwargs):
        job = self.get_object()
        if job.is_active:
            raise ConflictError(
                "Cancel this export before deleting it.",
                code="render_in_progress",
            )

        output_name = job.output.name if job.output else ""
        job.delete()
        if output_name:
            transaction.on_commit(lambda: delete_export_files.delay([output_name]))
        return Response(status=status.HTTP_204_NO_CONTENT)


class EditorOptionsView(APIView):
    """What the editor can do, and the limits it must respect.

    The SPA reads its control choices from here so the two can never disagree
    about, say, the maximum speed or the allowed aspect ratios.
    """

    throttle_scope = "read"

    def get(self, request):
        return Response(
            {
                "speeds": list(SPEED_PRESETS),
                "aspects": list(ASPECT_RATIOS),
                "fits": list(FIT_MODES),
                "qualities": list(QUALITY_PRESETS),
                "rotations": list(ROTATIONS),
                "quality_detail": {
                    name: {"short_side": preset["short_side"]} for name, preset in QUALITY_PRESETS.items()
                },
                "max_output_duration_seconds": settings.MAX_OUTPUT_DURATION_SECONDS,
                "max_upload_bytes": settings.MAX_UPLOAD_BYTES,
                "max_upload_duration_seconds": settings.MAX_UPLOAD_DURATION_SECONDS,
                "allowed_extensions": list(settings.ALLOWED_UPLOAD_EXTENSIONS),
            }
        )


class EditPreviewView(APIView):
    """Tell the user what an edit will produce, without rendering anything.

    This keeps the obvious question ("what size and how long will this be?")
    free, instead of answering it by spending a worker slot.
    """

    throttle_scope = "read"

    def post(self, request):
        serializer = ExportJobCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        asset = serializer.validated_data["source"]
        spec = serializer.validated_data["edit_spec"]
        width, height = target_resolution(spec, asset.width, asset.height)
        fingerprint = spec.fingerprint(asset.id)

        already = (
            ExportJob.objects.filter(
                owner=request.user, source=asset, fingerprint=fingerprint, status=JobStatus.SUCCEEDED
            )
            .values_list("id", flat=True)
            .first()
        )

        return Response(
            {
                "source_duration_seconds": asset.duration_seconds,
                "trimmed_duration_seconds": round(spec.trim.duration(asset.duration_seconds), 3),
                "output_duration_seconds": round(spec.output_duration(asset.duration_seconds), 3),
                "output_width": width,
                "output_height": height,
                "keeps_audio": asset.has_audio and not spec.mute,
                "existing_export_id": str(already) if already else None,
                "spec": spec.to_dict(),
            }
        )
