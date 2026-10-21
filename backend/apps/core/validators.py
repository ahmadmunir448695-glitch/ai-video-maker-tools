"""Upload validation that does not trust the client.

A filename extension and a browser-supplied ``Content-Type`` are both easy to
forge, so they are only a cheap first gate. The decisive check is that FFprobe
can actually read a video stream out of the bytes (see ``apps.videos.probe``).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings

from .exceptions import InvalidMedia, QuotaExceeded

# Container signatures we expect to see near the start of the file.
_MAGIC_PREFIXES: tuple[bytes, ...] = (
    b"\x1aE\xdf\xa3",  # Matroska / WebM
    b"RIFF",  # AVI
    b"FLV",  # Flash video
    b"\x00\x00\x01\xba",  # MPEG program stream
    b"\x00\x00\x01\xb3",  # MPEG sequence header
)


def _looks_like_video(head: bytes) -> bool:
    if any(head.startswith(prefix) for prefix in _MAGIC_PREFIXES):
        return True
    # ISO base media (MP4/MOV/M4V): a 'ftyp' box sits at offset 4.
    return len(head) >= 12 and head[4:8] == b"ftyp"


def validate_upload(uploaded_file) -> None:
    """Reject obviously-wrong uploads before any bytes are written to storage."""
    size = getattr(uploaded_file, "size", None)
    if not size:
        raise InvalidMedia("The uploaded file is empty.")

    if size > settings.MAX_UPLOAD_BYTES:
        limit_mb = settings.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise QuotaExceeded(
            f"That file is larger than the {limit_mb} MB upload limit.",
            code="upload_too_large",
        )

    extension = Path(uploaded_file.name or "").suffix.lower().lstrip(".")
    if extension not in settings.ALLOWED_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(settings.ALLOWED_UPLOAD_EXTENSIONS))
        raise InvalidMedia(f"'{extension or uploaded_file.name}' is not a supported format. Use one of: {allowed}.")

    content_type = (getattr(uploaded_file, "content_type", "") or "").split(";")[0].strip().lower()
    if content_type and content_type not in settings.ALLOWED_UPLOAD_CONTENT_TYPES:
        raise InvalidMedia(f"'{content_type}' is not a supported video content type.")

    head = uploaded_file.read(32)
    uploaded_file.seek(0)
    if not _looks_like_video(head):
        raise InvalidMedia("That file does not look like a video. Please upload an MP4, MOV, WebM or MKV file.")
