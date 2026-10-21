"""Helpers for getting bytes in and out of the configured storage backend.

Two backends are supported and the rest of the code never has to know which is
in play: an S3-compatible bucket (production) or the local filesystem (dev).
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

from django.conf import settings


def signed_url(file_field, *, expire_seconds: int | None = None) -> str | None:
    """Return a time-limited URL for a stored file, or ``None`` if there is none.

    Callers MUST check ownership before handing this to a client: the URL itself
    carries no identity, so anyone holding it can fetch the object until it expires.
    """
    if not file_field:
        return None

    if settings.USE_OBJECT_STORAGE:
        storage = file_field.storage
        if expire_seconds is not None and hasattr(storage, "url"):
            with contextlib.suppress(TypeError):
                return storage.url(file_field.name, expire=expire_seconds)
        return storage.url(file_field.name)

    return file_field.url


@contextlib.contextmanager
def local_copy(file_field, *, suffix: str = "") -> Iterator[Path]:
    """Yield a real filesystem path for a stored file.

    On local storage this is the file itself (no copy). On object storage the
    object is streamed to a temporary file, which is removed on exit — FFmpeg
    needs a seekable path, not a stream.
    """
    if not settings.USE_OBJECT_STORAGE:
        yield Path(file_field.path)
        return

    tmp_dir = tempfile.mkdtemp(prefix="avm-src-")
    tmp_path = Path(tmp_dir) / f"source{suffix or Path(file_field.name).suffix or '.mp4'}"
    try:
        with file_field.storage.open(file_field.name, "rb") as remote, open(tmp_path, "wb") as local:
            shutil.copyfileobj(remote, local, length=1024 * 1024)
        yield tmp_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@contextlib.contextmanager
def scratch_dir(prefix: str = "avm-work-") -> Iterator[Path]:
    """A temporary working directory that is always cleaned up."""
    path = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def delete_quietly(file_field) -> None:
    """Remove a stored file, ignoring the case where it is already gone."""
    if not file_field:
        return
    with contextlib.suppress(Exception):
        file_field.storage.delete(file_field.name)


def storage_free_bytes() -> int | None:
    """Free bytes on the local media volume, or ``None`` on object storage."""
    if settings.USE_OBJECT_STORAGE:
        return None
    root = Path(settings.MEDIA_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(os.fspath(root)).free
