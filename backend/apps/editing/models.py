from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel, UUIDModel

from .specs import EditSpec


def export_upload_path(instance: ExportJob, filename: str) -> str:
    return f"exports/{instance.owner_id}/{uuid.uuid4().hex}.mp4"


class JobStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    QUEUED = "queued", "Queued"
    PROCESSING = "processing", "Processing"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


#: Statuses that still occupy a worker slot or are waiting for one.
ACTIVE_STATUSES = (JobStatus.PENDING, JobStatus.QUEUED, JobStatus.PROCESSING)
#: Statuses from which a user may cancel.
CANCELLABLE_STATUSES = ACTIVE_STATUSES


class ExportJob(UUIDModel, TimestampedModel):
    """One render of one source video with one edit spec.

    ``fingerprint`` identifies "this exact edit of this exact source". A
    succeeded job can therefore be handed back instead of paying to render the
    same thing twice, which is the single biggest cost saving available.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="export_jobs",
    )
    source = models.ForeignKey(
        "videos.VideoAsset",
        on_delete=models.CASCADE,
        related_name="export_jobs",
    )

    title = models.CharField(max_length=140, blank=True)
    spec = models.JSONField(default=dict)
    fingerprint = models.CharField(max_length=64, db_index=True)

    status = models.CharField(max_length=20, choices=JobStatus.choices, default=JobStatus.PENDING, db_index=True)
    progress = models.PositiveSmallIntegerField(default=0)
    celery_task_id = models.CharField(max_length=255, blank=True)

    output = models.FileField(upload_to=export_upload_path, blank=True, null=True)
    output_size_bytes = models.BigIntegerField(default=0)
    output_width = models.IntegerField(default=0)
    output_height = models.IntegerField(default=0)
    output_duration_seconds = models.FloatField(default=0)

    error_message = models.TextField(blank=True)
    error_log = models.TextField(blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "-created_at"]),
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["source", "fingerprint"]),
        ]

    def __str__(self) -> str:
        return f"{self.display_title} [{self.status}]"

    @property
    def display_title(self) -> str:
        return self.title or f"Export of {self.source.original_filename}"

    @property
    def edit_spec(self) -> EditSpec:
        return EditSpec.from_dict(self.spec or {})

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def is_cancellable(self) -> bool:
        return self.status in CANCELLABLE_STATUSES

    @property
    def can_retry(self) -> bool:
        return self.status in (JobStatus.FAILED, JobStatus.CANCELLED)

    def refresh_status(self) -> str:
        """Re-read just the status column — used by the render cancellation check."""
        return ExportJob.objects.filter(pk=self.pk).values_list("status", flat=True).first() or self.status
