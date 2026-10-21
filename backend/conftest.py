"""Shared test fixtures.

The suite renders with the real FFmpeg binary rather than a stand-in: a mocked
encoder would happily "pass" while the actual filter graph was wrong, which is
the one failure mode that matters most here.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

FIXTURE_PASSWORD = "Str0ng-Test-Passphrase!42"


def ffmpeg_available() -> bool:
    return bool(shutil.which(settings.FFMPEG_BINARY) and shutil.which(settings.FFPROBE_BINARY))


requires_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="FFmpeg/FFprobe not installed")


@pytest.fixture(autouse=True)
def _reset_throttles():
    """DRF keeps throttle counters in the cache, which outlives a single test.

    Without this, tests that sign in repeatedly start tripping the rate limit
    and failing for the wrong reason. Throttling itself is covered explicitly in
    ``test_throttling.py``.
    """
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _static_root(tmp_path, settings):
    """WhiteNoise warns on a missing STATIC_ROOT; give it a real empty directory."""
    static = tmp_path / "static"
    static.mkdir(exist_ok=True)
    settings.STATIC_ROOT = str(static)
    return static


@pytest.fixture(autouse=True)
def _media_root(tmp_path, settings):
    """Keep every test's uploads in its own throwaway directory."""
    media = tmp_path / "media"
    media.mkdir()
    settings.MEDIA_ROOT = str(media)
    settings.USE_OBJECT_STORAGE = False
    # Renders run inline so a test can assert on the finished output.
    settings.CELERY_TASK_ALWAYS_EAGER = True
    return media


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        email="creator@example.com", password=FIXTURE_PASSWORD, display_name="Creator"
    )


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(email="intruder@example.com", password=FIXTURE_PASSWORD)


@pytest.fixture
def api() -> APIClient:
    return APIClient()


def authenticate(client: APIClient, user) -> APIClient:
    """Attach a real access token, exercising the same path as the SPA."""
    from rest_framework_simplejwt.tokens import RefreshToken

    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    return client


@pytest.fixture
def auth_api(user) -> APIClient:
    """A signed-in client.

    Deliberately its own ``APIClient`` rather than credentials attached to the
    ``api`` fixture: sharing one client made ``api`` quietly authenticated in any
    test that also used a signed-in fixture, which silently defeated the
    "anonymous requests are rejected" tests.
    """
    return authenticate(APIClient(), user)


def make_test_video(
    path: Path,
    *,
    seconds: float = 4.0,
    width: int = 640,
    height: int = 360,
    fps: int = 30,
    with_audio: bool = True,
) -> Path:
    """Synthesise a real, decodable MP4 with FFmpeg's built-in test sources.

    A moving pattern plus a sine tone means trims, speed changes and audio sync
    can all be asserted against a genuine file.
    """
    command = [
        settings.FFMPEG_BINARY,
        "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "lavfi", "-i", f"testsrc=size={width}x{height}:rate={fps}:duration={seconds}",
    ]
    if with_audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}"]

    command += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if with_audio:
        command += ["-c:a", "aac", "-b:a", "96k", "-shortest"]
    command += ["-t", str(seconds), str(path)]

    subprocess.run(command, check=True, capture_output=True, timeout=180)
    return path


@pytest.fixture
def sample_video(tmp_path) -> Path:
    return make_test_video(tmp_path / "sample.mp4")


@pytest.fixture
def silent_video(tmp_path) -> Path:
    return make_test_video(tmp_path / "silent.mp4", with_audio=False)


@pytest.fixture
def uploaded_asset(auth_api, sample_video):
    """A VideoAsset created through the real upload endpoint."""
    from apps.videos.models import VideoAsset

    with open(sample_video, "rb") as handle:
        response = auth_api.post(
            "/api/videos/",
            {"file": handle},
            format="multipart",
        )
    assert response.status_code == 201, response.data
    return VideoAsset.objects.get(pk=response.data["id"])
