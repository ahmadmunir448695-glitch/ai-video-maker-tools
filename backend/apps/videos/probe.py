"""FFprobe wrapper: the authoritative check that an upload really is a video.

Everything here runs FFprobe as a subprocess with an argument list (never a
shell string), so a hostile filename cannot turn into a shell injection.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from django.conf import settings

logger = logging.getLogger("apps.videos.probe")

PROBE_TIMEOUT_SECONDS = 60


class ProbeError(Exception):
    """FFprobe could not read a usable video stream out of the file."""


@dataclass(frozen=True)
class MediaInfo:
    duration_seconds: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str
    has_audio: bool
    container: str
    bitrate: int

    def as_dict(self) -> dict:
        return asdict(self)


def _parse_fps(rate: str | None) -> float:
    """Turn FFprobe's ``"30000/1001"`` rational into a float."""
    if not rate:
        return 0.0
    try:
        if "/" in rate:
            numerator, denominator = rate.split("/", 1)
            denominator_value = float(denominator)
            if denominator_value == 0:
                return 0.0
            return round(float(numerator) / denominator_value, 3)
        return round(float(rate), 3)
    except (TypeError, ValueError):
        return 0.0


def _run_ffprobe(path: Path) -> dict:
    command = [
        settings.FFPROBE_BINARY,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        completed = subprocess.run(  # noqa: S603 - fixed binary, list args, no shell
            command,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ProbeError(
            "FFprobe is not installed or not on PATH. Set FFPROBE_BINARY or install FFmpeg."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeError("Reading that file timed out. It may be corrupt or far too large.") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        logger.warning("ffprobe failed on %s: %s", path.name, detail[-1] if detail else "unknown error")
        raise ProbeError("That file could not be read as a video. It may be corrupt or in an unsupported format.")

    try:
        return json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ProbeError("Unexpected response while inspecting the video.") from exc


def probe(path: Path | str) -> MediaInfo:
    """Inspect a local video file and return its real properties.

    Raises :class:`ProbeError` for anything that is not a readable video.
    """
    path = Path(path)
    if not path.exists():
        raise ProbeError("The uploaded file could not be found on disk.")

    payload = _run_ffprobe(path)
    streams = payload.get("streams") or []
    container = payload.get("format") or {}

    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    if not video_streams:
        raise ProbeError("That file has no video track. Please upload a video, not an audio file or image.")

    video = video_streams[0]

    # Prefer the container duration; fall back to the stream's own.
    duration = 0.0
    for candidate in (container.get("duration"), video.get("duration")):
        try:
            duration = float(candidate)
        except (TypeError, ValueError):
            continue
        if duration > 0:
            break

    if duration <= 0:
        raise ProbeError("The video's duration could not be determined, so it cannot be edited.")

    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ProbeError("The video's dimensions could not be determined.")

    # A rotation side-data entry means the display orientation is swapped
    # relative to the coded frame; report what a player would actually show.
    rotation = 0
    for side in video.get("side_data_list") or []:
        if "rotation" in side:
            try:
                rotation = abs(int(side["rotation"])) % 180
            except (TypeError, ValueError):
                rotation = 0
    if rotation == 90:
        width, height = height, width

    fps = _parse_fps(video.get("avg_frame_rate")) or _parse_fps(video.get("r_frame_rate"))

    try:
        bitrate = int(container.get("bit_rate") or 0)
    except (TypeError, ValueError):
        bitrate = 0

    return MediaInfo(
        duration_seconds=round(duration, 3),
        width=width,
        height=height,
        fps=fps,
        video_codec=str(video.get("codec_name") or ""),
        audio_codec=str(audio_streams[0].get("codec_name") or "") if audio_streams else "",
        has_audio=bool(audio_streams),
        container=str(container.get("format_name") or ""),
        bitrate=bitrate,
    )
