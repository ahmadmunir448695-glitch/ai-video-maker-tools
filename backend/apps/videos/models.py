from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel, UUIDModel


def source_upload_path(instance: VideoAsset, filename: str) -> str:
    """Namespace every object by owner, so one user's prefix holds only their files."""
    extension = Path(filename).suffix.lower() or ".mp4"
    return f"sources/{instance.owner_id}/{uuid.uuid4().hex}{extension}"


def thumbnail_upload_path(instance: VideoAsset, filename: str) -> str:
    return f"thumbnails/{instance.owner_id}/{instance.id}.jpg"


class AssetStatus(models.TextChoices):
    PROBING = "probing", "Reading video"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class VideoAsset(UUIDModel, TimestampedModel):
    """An uploaded source video, plus the properties FFprobe found in it."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="video_assets",
    )
    file = models.FileField(upload_to=source_upload_path)
    thumbnail = models.ImageField(upload_to=thumbnail_upload_path, blank=True, null=True)

    original_filename = models.CharField(max_length=255)
    size_bytes = models.BigIntegerField(default=0)

    status = models.CharField(max_length=20, choices=AssetStatus.choices, default=AssetStatus.PROBING)
    error_message = models.TextField(blank=True)

    duration_seconds = models.FloatField(default=0)
    width = models.IntegerField(default=0)
    height = models.IntegerField(default=0)
    fps = models.FloatField(default=0)
    video_codec = models.CharField(max_length=40, blank=True)
    audio_codec = models.CharField(max_length=40, blank=True)
    has_audio = models.BooleanField(default=False)
    container = models.CharField(max_length=80, blank=True)
    bitrate = models.BigIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "-created_at"]),
            models.Index(fields=["owner", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.original_filename} ({self.id})"

    @property
    def aspect_ratio(self) -> float:
        return round(self.width / self.height, 4) if self.height else 0.0

    @property
    def orientation(self) -> str:
        if not self.width or not self.height:
            return "unknown"
        if self.width > self.height:
            return "landscape"
        if self.width < self.height:
            return "portrait"
        return "square"

    def apply_media_info(self, info) -> None:
        """Copy FFprobe's findings onto the row (does not save)."""
        self.duration_seconds = info.duration_seconds
        self.width = info.width
        self.height = info.height
        self.fps = info.fps
        self.video_codec = info.video_codec
        self.audio_codec = info.audio_codec
        self.has_audio = info.has_audio
        self.container = info.container
        self.bitrate = info.bitrate
