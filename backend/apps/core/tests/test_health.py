"""The health probe, and the reaper that rescues jobs from a dead worker."""

from __future__ import annotations

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


class TestHealth:
    def test_health_is_public_and_reports_each_dependency(self, api):
        """Load balancers call this unauthenticated."""
        response = api.get("/api/health")

        assert response.status_code in (200, 503)
        checks = response.data["checks"]
        assert checks["database"] == "ok"
        assert set(checks) >= {"database", "ffmpeg", "ffprobe", "queue", "storage"}

    def test_a_missing_ffmpeg_makes_the_probe_degraded(self, api, settings):
        """A worker that cannot encode is not healthy, even if Django responds."""
        settings.FFMPEG_BINARY = "/nonexistent/ffmpeg-binary"

        response = api.get("/api/health")

        assert response.status_code == 503
        assert response.data["status"] == "degraded"
        assert response.data["checks"]["ffmpeg"] == "missing"


class TestStalledJobReaper:
    def test_a_long_abandoned_job_is_marked_failed_so_it_can_be_retried(self, user, db):
        """A worker killed mid-render leaves PROCESSING forever without this."""
        from apps.editing.models import ExportJob, JobStatus
        from apps.editing.tasks import reap_stalled_jobs
        from apps.videos.models import AssetStatus, VideoAsset

        asset = VideoAsset.objects.create(
            owner=user, original_filename="x.mp4", status=AssetStatus.READY, duration_seconds=5
        )
        job = ExportJob.objects.create(
            owner=user, source=asset, spec={}, fingerprint="abc", status=JobStatus.PROCESSING
        )
        ExportJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timezone.timedelta(hours=6))

        assert reap_stalled_jobs(max_age_minutes=120) == 1

        job.refresh_from_db()
        assert job.status == JobStatus.FAILED
        assert job.can_retry

    def test_a_recent_job_is_left_alone(self, user, db):
        from apps.editing.models import ExportJob, JobStatus
        from apps.editing.tasks import reap_stalled_jobs
        from apps.videos.models import AssetStatus, VideoAsset

        asset = VideoAsset.objects.create(
            owner=user, original_filename="x.mp4", status=AssetStatus.READY, duration_seconds=5
        )
        job = ExportJob.objects.create(
            owner=user, source=asset, spec={}, fingerprint="abc", status=JobStatus.PROCESSING
        )

        assert reap_stalled_jobs(max_age_minutes=120) == 0

        job.refresh_from_db()
        assert job.status == JobStatus.PROCESSING

    def test_a_finished_job_is_never_reaped(self, user, db):
        from apps.editing.models import ExportJob, JobStatus
        from apps.editing.tasks import reap_stalled_jobs
        from apps.videos.models import AssetStatus, VideoAsset

        asset = VideoAsset.objects.create(
            owner=user, original_filename="x.mp4", status=AssetStatus.READY, duration_seconds=5
        )
        job = ExportJob.objects.create(
            owner=user, source=asset, spec={}, fingerprint="abc", status=JobStatus.SUCCEEDED
        )
        ExportJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timezone.timedelta(days=30))

        assert reap_stalled_jobs(max_age_minutes=120) == 0

        job.refresh_from_db()
        assert job.status == JobStatus.SUCCEEDED


class TestValidators:
    def test_magic_byte_detection_accepts_an_mp4_header(self):
        from apps.core.validators import _looks_like_video

        assert _looks_like_video(b"\x00\x00\x00 ftypisom" + b"\x00" * 12)

    def test_magic_byte_detection_accepts_a_matroska_header(self):
        from apps.core.validators import _looks_like_video

        assert _looks_like_video(b"\x1aE\xdf\xa3" + b"\x00" * 28)

    @pytest.mark.parametrize(
        "payload",
        [b"<html>hello</html>", b"PK\x03\x04zipfile", b"\x7fELF binary", b"", b"#!/bin/sh\nrm -rf /"],
    )
    def test_magic_byte_detection_rejects_non_video_payloads(self, payload):
        from apps.core.validators import _looks_like_video

        assert not _looks_like_video(payload)
