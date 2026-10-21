"""FFmpeg render pipeline.

Builds a filter graph from an :class:`~apps.editing.specs.EditSpec`, runs FFmpeg
as a subprocess, reports real progress parsed from FFmpeg's own ``-progress``
stream, and supports cooperative cancellation.

Nothing here shells out through a string: every command is an argument list, so
filenames cannot be used for injection.
"""

from __future__ import annotations

import logging
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from .specs import (
    QUALITY_PRESETS,
    EditSpec,
    audio_tempo_chain,
    target_resolution,
)

logger = logging.getLogger("apps.editing.ffmpeg")

#: How often the cancellation callback is consulted while a render runs.
CANCEL_POLL_INTERVAL_SECONDS = 2.0
#: Seconds to wait for a graceful shutdown before escalating to SIGKILL.
TERMINATE_GRACE_SECONDS = 5.0
#: Tail of FFmpeg's stderr kept for diagnostics (bounded, so a chatty failure
#: cannot fill the database).
STDERR_KEEP_CHARS = 4000


class RenderCancelled(Exception):
    """Raised when a caller's cancellation check asked us to stop."""


class RenderError(Exception):
    """FFmpeg exited non-zero, or produced no usable output."""

    def __init__(self, message: str, *, log_tail: str = ""):
        super().__init__(message)
        self.message = message
        self.log_tail = log_tail


@dataclass
class RenderResult:
    path: Path
    size_bytes: int
    width: int
    height: int
    duration_seconds: float
    command: list[str]


def build_video_filters(spec: EditSpec, source_width: int, source_height: int, source_fps: float) -> list[str]:
    """The ``-vf`` chain, in the order the frames must flow through it."""
    filters: list[str] = []

    # 1. Rotation first, so every later size calculation sees the final orientation.
    if spec.rotate == 90:
        filters.append("transpose=1")  # 90 degrees clockwise
    elif spec.rotate == 180:
        filters.append("transpose=1,transpose=1")
    elif spec.rotate == 270:
        filters.append("transpose=2")  # 90 degrees counter-clockwise

    # 2. Speed. setpts rescales presentation timestamps: dividing by the factor
    #    stretches time for slow motion and compresses it for speed-ups.
    if spec.speed != 1.0:
        filters.append(f"setpts=PTS/{spec.speed:.6g}")
        # setpts alone would leave a 30fps clip playing at 7.5fps when slowed to
        # 0.25x, which looks like a stutter. Resampling to a constant frame rate
        # duplicates (or drops) frames so playback stays smooth.
        out_fps = source_fps if 1 < source_fps <= 60 else 30.0
        filters.append(f"fps={out_fps:.6g}")

    # 3. Frame size and aspect ratio.
    width, height = target_resolution(spec, source_width, source_height)
    if spec.fit == "contain":
        # Fit the whole frame inside the target and letterbox the remainder.
        filters.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease")
        filters.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")
    else:
        # "cover": fill the target completely, then centre-crop the overflow.
        filters.append(f"scale={width}:{height}:force_original_aspect_ratio=increase")
        filters.append(f"crop={width}:{height}")

    # Square pixels, so no player stretches the result.
    filters.append("setsar=1")
    return filters


def build_audio_filters(spec: EditSpec) -> list[str]:
    """The ``-af`` chain. Empty when the speed is unchanged."""
    filters = [f"atempo={factor:.6g}" for factor in audio_tempo_chain(spec.speed)]
    if filters:
        # Rebuild timestamps from the resampled sample count, which keeps the
        # audio locked to the re-timed video instead of drifting.
        filters.append("asetpts=N/SR/TB")
    return filters


def build_command(
    spec: EditSpec,
    source: Path,
    destination: Path,
    *,
    source_width: int,
    source_height: int,
    source_fps: float,
    source_duration: float,
    has_audio: bool,
) -> list[str]:
    """Assemble the full FFmpeg argument list for a render."""
    preset = QUALITY_PRESETS[spec.quality]
    keep_audio = has_audio and not spec.mute

    command: list[str] = [
        settings.FFMPEG_BINARY,
        "-hide_banner",
        "-loglevel", "error",
        "-nostdin",  # never let FFmpeg try to read the worker's stdin
        "-y",
    ]

    # Seeking before -i is fast (FFmpeg skips to a nearby keyframe) and still
    # frame-accurate here, because we re-encode rather than stream-copy.
    if spec.trim.start > 0:
        command += ["-ss", f"{spec.trim.start:.3f}"]

    # -t must stay an INPUT option, before -i: it then bounds how much of the
    # SOURCE is read, which is what a trim means. After -i it would instead cap
    # the OUTPUT length, and a trim combined with a speed change would come out
    # wrong (trimming 2s at 2x would yield 1.5s of a 3s tail, not 1s).
    trimmed = spec.trim.duration(source_duration)
    if spec.trim.end is not None and trimmed > 0:
        command += ["-t", f"{trimmed:.3f}"]

    command += ["-i", str(source)]

    video_filters = build_video_filters(spec, source_width, source_height, source_fps)
    if video_filters:
        command += ["-vf", ",".join(video_filters)]

    if keep_audio:
        audio_filters = build_audio_filters(spec)
        if audio_filters:
            command += ["-af", ",".join(audio_filters)]
        command += ["-c:a", "aac", "-b:a", preset["audio_bitrate"], "-ar", "48000", "-ac", "2"]
    else:
        command += ["-an"]

    command += [
        "-c:v", "libx264",
        "-preset", preset["preset"],
        "-crf", str(preset["crf"]),
        "-pix_fmt", "yuv420p",  # the format every phone and browser can decode
        "-movflags", "+faststart",  # metadata up front, so playback starts while downloading
        "-map_metadata", "-1",  # strip source metadata (may hold location/device data)
        "-max_muxing_queue_size", "2048",
        "-progress", "pipe:1",
        "-nostats",
        str(destination),
    ]
    return command


def _parse_progress_line(line: str) -> tuple[str, str] | None:
    if "=" not in line:
        return None
    key, _, value = line.partition("=")
    return key.strip(), value.strip()


def render(
    spec: EditSpec,
    source: Path,
    destination: Path,
    *,
    source_width: int,
    source_height: int,
    source_fps: float,
    source_duration: float,
    has_audio: bool,
    on_progress: Callable[[int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    timeout_seconds: int | None = None,
) -> RenderResult:
    """Run the render and return where the output landed.

    ``on_progress`` receives an integer percentage (0-99 while running).
    ``is_cancelled`` is polled every couple of seconds; returning ``True`` stops
    FFmpeg and raises :class:`RenderCancelled`.
    """
    command = build_command(
        spec,
        source,
        destination,
        source_width=source_width,
        source_height=source_height,
        source_fps=source_fps,
        source_duration=source_duration,
        has_audio=has_audio,
    )

    expected_duration = max(spec.output_duration(source_duration), 0.001)
    timeout_seconds = timeout_seconds or settings.RENDER_PROCESS_TIMEOUT_SECONDS

    logger.info("Starting render -> %s", destination.name)
    logger.debug("FFmpeg command: %s", " ".join(command))

    try:
        process = subprocess.Popen(  # noqa: S603 - fixed binary, list args, no shell
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,  # own process group, so we can signal children too
        )
    except FileNotFoundError as exc:
        raise RenderError(
            "FFmpeg is not installed or not on PATH. Set FFMPEG_BINARY or install FFmpeg."
        ) from exc

    started = time.monotonic()
    last_cancel_check = started
    last_reported = -1
    cancelled = False
    timed_out = False

    def _stop(sig: int) -> None:
        try:
            process.send_signal(sig)
        except (ProcessLookupError, OSError):
            pass

    try:
        assert process.stdout is not None
        for raw_line in process.stdout:
            parsed = _parse_progress_line(raw_line)
            if parsed and on_progress is not None:
                key, value = parsed
                if key == "out_time_us":
                    try:
                        seconds = int(value) / 1_000_000
                    except ValueError:
                        seconds = 0.0
                    # Cap at 99: the job is only 100% once the file is stored.
                    percent = min(99, max(0, int(seconds / expected_duration * 100)))
                    if percent != last_reported:
                        last_reported = percent
                        on_progress(percent)

            now = time.monotonic()

            if now - started > timeout_seconds:
                timed_out = True
                _stop(signal.SIGTERM)
                break

            if is_cancelled is not None and now - last_cancel_check >= CANCEL_POLL_INTERVAL_SECONDS:
                last_cancel_check = now
                if is_cancelled():
                    cancelled = True
                    _stop(signal.SIGTERM)
                    break

        try:
            process.wait(timeout=TERMINATE_GRACE_SECONDS if (cancelled or timed_out) else timeout_seconds)
        except subprocess.TimeoutExpired:
            _stop(signal.SIGKILL)
            process.wait(timeout=TERMINATE_GRACE_SECONDS)

    finally:
        stderr_output = ""
        if process.stderr is not None:
            try:
                stderr_output = process.stderr.read() or ""
            except (ValueError, OSError):
                stderr_output = ""
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except (ValueError, OSError):
                    pass
        if process.poll() is None:  # pragma: no cover - defensive
            _stop(signal.SIGKILL)
            process.wait(timeout=TERMINATE_GRACE_SECONDS)

    log_tail = stderr_output.strip()[-STDERR_KEEP_CHARS:]

    if cancelled:
        destination.unlink(missing_ok=True)
        raise RenderCancelled("The render was cancelled.")

    if timed_out:
        destination.unlink(missing_ok=True)
        raise RenderError(
            f"The render took longer than {timeout_seconds} seconds and was stopped.",
            log_tail=log_tail,
        )

    if process.returncode != 0:
        destination.unlink(missing_ok=True)
        logger.warning("FFmpeg exited %s: %s", process.returncode, log_tail[-500:])
        raise RenderError(
            "The video could not be rendered. It may use an unsupported codec, or the "
            "selected trim range may be empty.",
            log_tail=log_tail,
        )

    if not destination.exists() or destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise RenderError("The render finished but produced an empty file.", log_tail=log_tail)

    # Read the real properties back off the finished file rather than trusting
    # our own arithmetic — this is what the user will actually download.
    from apps.videos.probe import ProbeError, probe

    try:
        info = probe(destination)
        width, height, duration = info.width, info.height, info.duration_seconds
    except ProbeError:
        width, height = target_resolution(spec, source_width, source_height)
        duration = expected_duration

    if on_progress is not None:
        on_progress(99)

    return RenderResult(
        path=destination,
        size_bytes=destination.stat().st_size,
        width=width,
        height=height,
        duration_seconds=duration,
        command=command,
    )
