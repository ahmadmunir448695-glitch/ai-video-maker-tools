from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.usage import storage_bytes_used
from apps.core.exceptions import InvalidMedia, QuotaExceeded
from apps.core.permissions import IsOwner
from apps.core.storage import delete_quietly, local_copy, signed_url
from apps.core.validators import validate_upload

from .models import AssetStatus, VideoAsset
from .probe import ProbeError, probe
from .serializers import VideoAssetSerializer, VideoUploadSerializer
from .thumbnails import attach_thumbnail

logger = logging.getLogger("apps.videos")


class VideoAssetViewSet(viewsets.ReadOnlyModelViewSet, viewsets.GenericViewSet):
    """Source videos. Users only ever see and touch their own."""

    serializer_class = VideoAssetSerializer
    permission_classes = [IsOwner]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        # First lock: the queryset itself can never reach another user's rows.
        return VideoAsset.objects.filter(owner=self.request.user)

    def get_throttles(self):
        self.throttle_scope = "upload" if self.action in {"create", "destroy"} else "read"
        return super().get_throttles()

    def create(self, request, *args, **kwargs):
        """Accept an upload, verify it is really a video, and record its properties.

        The file is probed before the row is reported ready, so a client never
        sees an asset we cannot actually edit.
        """
        upload_serializer = VideoUploadSerializer(data=request.data)
        upload_serializer.is_valid(raise_exception=True)
        uploaded = upload_serializer.validated_data["file"]

        # Cheap, client-independent gates first: size, extension, magic bytes.
        validate_upload(uploaded)

        used = storage_bytes_used(request.user)
        if used + uploaded.size > settings.MAX_STORAGE_BYTES_PER_USER:
            limit_gb = settings.MAX_STORAGE_BYTES_PER_USER / (1024**3)
            raise QuotaExceeded(
                f"This upload would put you over your {limit_gb:.1f} GB storage limit. "
                "Delete a video or an export to free up room.",
                code="storage_quota_exceeded",
            )

        asset = VideoAsset(
            owner=request.user,
            original_filename=(uploaded.name or "video.mp4")[:255],
            size_bytes=uploaded.size,
            status=AssetStatus.PROBING,
        )
        asset.file.save(uploaded.name or "video.mp4", uploaded, save=False)
        asset.save()

        try:
            with local_copy(asset.file) as path:
                info = probe(path)

                if info.duration_seconds > settings.MAX_UPLOAD_DURATION_SECONDS:
                    limit = settings.MAX_UPLOAD_DURATION_SECONDS
                    raise InvalidMedia(
                        f"That video is {info.duration_seconds:.0f} seconds long. "
                        f"The limit is {limit} seconds ({limit // 60} minutes).",
                        code="duration_too_long",
                    )

                asset.apply_media_info(info)
                asset.status = AssetStatus.READY
                asset.error_message = ""
                attach_thumbnail(asset, path)
                asset.save()

        except (ProbeError, InvalidMedia) as exc:
            # The bytes are unusable, so do not keep them or bill them against
            # the user's quota — delete the object and the row together.
            logger.info("Rejected upload %s: %s", asset.id, exc)
            delete_quietly(asset.file)
            delete_quietly(asset.thumbnail)
            asset.delete()
            detail = exc.detail if isinstance(exc, InvalidMedia) else str(exc)
            code = exc.code if isinstance(exc, InvalidMedia) else "invalid_media"
            raise InvalidMedia(detail, code=code) from exc

        except Exception:
            logger.exception("Upload processing failed for %s", asset.id)
            delete_quietly(asset.file)
            asset.delete()
            raise

        return Response(self.get_serializer(asset).data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        """Delete a source video and everything derived from it."""
        asset = self.get_object()

        from apps.editing.models import ExportJob, JobStatus

        active = ExportJob.objects.filter(
            source=asset, status__in=[JobStatus.PENDING, JobStatus.QUEUED, JobStatus.PROCESSING]
        ).exists()
        if active:
            raise QuotaExceeded(
                "This video has an export still running. Cancel it first, or wait for it to finish.",
                code="render_in_progress",
            )

        exports = list(ExportJob.objects.filter(source=asset))
        files = [asset.file, asset.thumbnail, *(job.output for job in exports)]

        asset.delete()  # cascades to the export rows

        # Storage cleanup happens only once the database change is committed, so
        # a rolled-back transaction can never leave the rows pointing at nothing.
        def _cleanup() -> None:
            for handle in files:
                delete_quietly(handle)

        transaction.on_commit(_cleanup)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, *args, **kwargs):
        """Hand back a short-lived URL for the original file, after an ownership check."""
        asset = self.get_object()
        url = signed_url(asset.file)
        if not url:
            raise InvalidMedia("This video has no stored file.", code="file_missing")
        return Response({"url": url, "filename": asset.original_filename})
