"""Per-user usage counters, used for quota enforcement and the dashboard."""

from __future__ import annotations

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone


def storage_bytes_used(user) -> int:
    from apps.editing.models import ExportJob
    from apps.videos.models import VideoAsset

    sources = VideoAsset.objects.filter(owner=user).aggregate(total=Sum("size_bytes"))["total"] or 0
    exports = ExportJob.objects.filter(owner=user).aggregate(total=Sum("output_size_bytes"))["total"] or 0
    return int(sources) + int(exports)


def exports_today(user) -> int:
    from apps.editing.models import ExportJob

    start_of_day = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return ExportJob.objects.filter(owner=user, created_at__gte=start_of_day).count()


def active_renders(user) -> int:
    from apps.editing.models import ExportJob, JobStatus

    return ExportJob.objects.filter(
        owner=user,
        status__in=[JobStatus.PENDING, JobStatus.QUEUED, JobStatus.PROCESSING],
    ).count()


def usage_summary(user) -> dict:
    """Everything the dashboard needs to show a user where they stand."""
    used = storage_bytes_used(user)
    return {
        "storage_bytes_used": used,
        "storage_bytes_limit": settings.MAX_STORAGE_BYTES_PER_USER,
        "exports_today": exports_today(user),
        "exports_per_day_limit": settings.MAX_EXPORTS_PER_DAY,
        "active_renders": active_renders(user),
        "concurrent_render_limit": settings.MAX_CONCURRENT_RENDERS_PER_USER,
        "max_upload_bytes": settings.MAX_UPLOAD_BYTES,
        "max_upload_duration_seconds": settings.MAX_UPLOAD_DURATION_SECONDS,
    }
