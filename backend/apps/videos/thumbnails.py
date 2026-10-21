"""Single-frame JPEG posters, so the library can show something at a glance."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile

logger = logging.getLogger("apps.videos.thumbnails")

THUMBNAIL_TIMEOUT_SECONDS = 60
THUMBNAIL_WIDTH = 640


def generate_thumbnail(source_path: Path, destination: Path, *, at_seconds: float = 0.0) -> bool:
    """Grab one frame and write it as a JPEG. Returns ``False`` if FFmpeg declined."""
    command = [
        settings.FFMPEG_BINARY,
        "-hide_banner",
        "-loglevel", "error",
        "-nostdin",
        "-y",
        "-ss", f"{max(at_seconds, 0):.3f}",
        "-i", str(source_path),
        "-frames:v", "1",
        # Keep the aspect ratio and force an even height for broad decoder support.
        "-vf", f"scale={THUMBNAIL_WIDTH}:-2:flags=bilinear",
        "-q:v", "4",
        str(destination),
    ]
    try:
        completed = subprocess.run(  # noqa: S603 - fixed binary, list args, no shell
            command, capture_output=True, text=True, timeout=THUMBNAIL_TIMEOUT_SECONDS, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("Thumbnail generation failed: %s", exc)
        return False

    if completed.returncode != 0 or not destination.exists() or destination.stat().st_size == 0:
        logger.warning("Thumbnail generation produced nothing: %s", (completed.stderr or "").strip()[:300])
        return False
    return True


def attach_thumbnail(asset, source_path: Path, *, at_seconds: float | None = None) -> bool:
    """Generate a poster frame for ``asset`` and save it to storage.

    A failure here is not fatal — the video is still perfectly editable without
    a poster — so this reports success rather than raising.
    """
    from apps.core.storage import scratch_dir

    # A frame from one second in is usually more representative than a black
    # first frame, but never seek past the end of a very short clip.
    if at_seconds is None:
        at_seconds = 1.0 if asset.duration_seconds > 2 else 0.0

    with scratch_dir(prefix="avm-thumb-") as work:
        out = work / "poster.jpg"
        if not generate_thumbnail(source_path, out, at_seconds=at_seconds):
            return False
        asset.thumbnail.save(f"{asset.id}.jpg", ContentFile(out.read_bytes()), save=False)
    return True
