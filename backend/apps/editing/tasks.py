"""Celery tasks for rendering.

A render never runs inside an HTTP request: the view creates the row, queues
this task and returns immediately. With no Redis configured, Celery's eager mode
runs the task inline so the app still works for a beginner on a laptop — the
status transitions and progress are identical either way.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.core.files.base import File
from django.db import transaction
from django.utils import timezone

from apps.core.storage import delete_quietly, local_copy, scratch_dir

from .ffmpeg import RenderCancelled, RenderError, render
from .models import ACTIVE_STATUSES, ExportJob, JobStatus

logger = logging.getLogger("apps.editing.tasks")

#: Progress is written to the database at most this often, so a long render does
#: not turn into thousands of UPDATE statements.
PROGRESS_WRITE_STEP = 5


class _ProgressWriter:
    """Throttles progress updates down to meaningful steps."""

    def __init__(self, job_id):
        self.job_id = job_id
        self._last_written = -1

    def __call__(self, percent: int) -> None:
        if percent < self._last_written + PROGRESS_WRITE_STEP and percent < 99:
            return
        self._last_written = percent
        # A targeted UPDATE: never overwrite a status another process just set.
        ExportJob.objects.filter(pk=self.job_id, status=JobStatus.PROCESSING).update(progress=percent)


@shared_task(
    bind=True,
    name="editing.render_export",
    acks_late=True,
    # Retries cover transient infrastructure faults (storage blip, worker
    # restart). A genuine FFmpeg failure is deterministic, so it is recorded as
    # failed rather than retried — retrying would just burn CPU on the same error.
    autoretry_for=(OSError,),
    retry_backoff=10,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=2,
)
def render_export(self, job_id: str) -> str:
    """Render one export job. Returns the final status."""
    job = ExportJob.objects.select_related("source", "owner").filter(pk=job_id).first()
    if job is None:
        logger.warning("Render asked for a job that no longer exists: %s", job_id)
        return "missing"

    # Claim the job: only move PENDING/QUEUED -> PROCESSING. If this returns 0,
    # another worker already has it, or the user cancelled before we started, so
    # this run must not touch the row.
    claimed = ExportJob.objects.filter(
        pk=job.pk, status__in=[JobStatus.PENDING, JobStatus.QUEUED]
    ).update(
        status=JobStatus.PROCESSING,
        progress=0,
        started_at=timezone.now(),
        celery_task_id=self.request.id or "",
        error_message="",
        error_log="",
    )
    if not claimed:
        current = job.refresh_status()
        logger.info("Skipping job %s: already %s", job_id, current)
        return current

    job.refresh_from_db()
    spec = job.edit_spec
    source = job.source

    def _cancelled() -> bool:
        return job.refresh_status() == JobStatus.CANCELLED

    try:
        with local_copy(source.file) as source_path, scratch_dir(prefix="avm-render-") as work:
            destination = work / "export.mp4"
            result = render(
                spec,
                source_path,
                destination,
                source_width=source.width,
                source_height=source.height,
                source_fps=source.fps,
                source_duration=source.duration_seconds,
                has_audio=source.has_audio,
                on_progress=_ProgressWriter(job.pk),
                is_cancelled=_cancelled,
            )

            with open(result.path, "rb") as handle:
                job.output.save(f"{job.pk}.mp4", File(handle), save=False)

            job.output_size_bytes = result.size_bytes
            job.output_width = result.width
            job.output_height = result.height
            job.output_duration_seconds = result.duration_seconds
            job.status = JobStatus.SUCCEEDED
            job.progress = 100
            job.finished_at = timezone.now()
            job.error_message = ""
            job.error_log = ""
            job.save(
                update_fields=[
                    "output",
                    "output_size_bytes",
                    "output_width",
                    "output_height",
                    "output_duration_seconds",
                    "status",
                    "progress",
                    "finished_at",
                    "error_message",
                    "error_log",
                    "updated_at",
                ]
            )

        logger.info("Render finished: job=%s size=%s bytes", job.pk, result.size_bytes)
        return JobStatus.SUCCEEDED

    except RenderCancelled:
        ExportJob.objects.filter(pk=job.pk).update(
            status=JobStatus.CANCELLED,
            progress=0,
            finished_at=timezone.now(),
            error_message="Cancelled.",
        )
        logger.info("Render cancelled: job=%s", job.pk)
        return JobStatus.CANCELLED

    except RenderError as exc:
        ExportJob.objects.filter(pk=job.pk).update(
            status=JobStatus.FAILED,
            progress=0,
            finished_at=timezone.now(),
            error_message=exc.message,
            error_log=exc.log_tail,
        )
        logger.warning("Render failed: job=%s error=%s", job.pk, exc.message)
        return JobStatus.FAILED

    except Exception as exc:
        logger.exception("Unexpected render error: job=%s", job.pk)
        ExportJob.objects.filter(pk=job.pk).update(
            status=JobStatus.FAILED,
            progress=0,
            finished_at=timezone.now(),
            error_message="The render failed unexpectedly. Please try again.",
            error_log=str(exc)[:4000],
        )
        return JobStatus.FAILED


@shared_task(name="editing.reap_stalled_jobs")
def reap_stalled_jobs(max_age_minutes: int = 120) -> int:
    """Fail jobs that have sat in an active state far longer than any render should.

    A worker that is killed mid-render (OOM, redeploy, lost spot instance) leaves
    its row in PROCESSING forever. Run this periodically so such rows become
    visibly failed, and therefore retryable, instead of silently stuck.
    """
    cutoff = timezone.now() - timezone.timedelta(minutes=max_age_minutes)
    stalled = ExportJob.objects.filter(status__in=ACTIVE_STATUSES, created_at__lt=cutoff)
    count = stalled.count()
    if count:
        stalled.update(
            status=JobStatus.FAILED,
            progress=0,
            finished_at=timezone.now(),
            error_message="This render stopped responding and was abandoned. You can try it again.",
        )
        logger.warning("Reaped %s stalled render job(s)", count)
    return count


@shared_task(name="editing.delete_export_files")
def delete_export_files(names: list[str]) -> int:
    """Remove orphaned output objects from storage after their rows are gone."""
    from django.core.files.storage import default_storage

    removed = 0
    for name in names:
        try:
            if name and default_storage.exists(name):
                default_storage.delete(name)
                removed += 1
        except Exception:
            logger.exception("Could not delete stored object %s", name)
    return removed


def queue_render(job: ExportJob) -> None:
    """Queue a render once the surrounding transaction commits.

    Queueing inside the transaction would let a worker pick the job up before
    the row is visible to it, which shows up as a mysterious 'job not found'.
    """

    def _send() -> None:
        try:
            async_result = render_export.delay(str(job.pk))
            ExportJob.objects.filter(pk=job.pk, status=JobStatus.PENDING).update(
                status=JobStatus.QUEUED, celery_task_id=async_result.id or ""
            )
        except Exception as exc:
            logger.exception("Could not queue render for job %s", job.pk)
            ExportJob.objects.filter(pk=job.pk, status=JobStatus.PENDING).update(
                status=JobStatus.FAILED,
                error_message="The render queue is unavailable right now. Please try again shortly.",
                error_log=str(exc)[:2000],
                finished_at=timezone.now(),
            )

    transaction.on_commit(_send)


def cleanup_job_files(job: ExportJob) -> None:
    """Delete a job's output object (used on retry and on delete)."""
    delete_quietly(job.output)
