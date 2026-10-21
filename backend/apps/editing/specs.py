"""The edit spec: a small, validated description of what to render.

Keeping the edit as data (rather than a pile of model columns) means Phase 2
can add overlays, captions and music by extending this schema and the filter
builder, without a migration per feature.

Phase 1 understands: trim, speed, rotation, aspect/fit, mute and quality.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

# FFmpeg's atempo filter only accepts 0.5 to 2.0, so anything outside that is
# applied as a chain of factors (see ``audio_tempo_chain``).
MIN_SPEED = 0.25
MAX_SPEED = 4.0

SPEED_PRESETS: tuple[float, ...] = (0.25, 0.5, 1.0, 1.5, 2.0)

ASPECT_RATIOS: dict[str, tuple[int, int] | None] = {
    "original": None,
    "9:16": (9, 16),
    "1:1": (1, 1),
    "16:9": (16, 9),
    "4:5": (4, 5),
}

#: ``short_side`` is the smaller output dimension; CRF is x264's quality knob
#: (lower is better and bigger). These three tiers keep render cost predictable.
QUALITY_PRESETS: dict[str, dict] = {
    "low": {"short_side": 480, "crf": 28, "preset": "veryfast", "audio_bitrate": "96k"},
    "medium": {"short_side": 720, "crf": 23, "preset": "veryfast", "audio_bitrate": "128k"},
    "high": {"short_side": 1080, "crf": 20, "preset": "medium", "audio_bitrate": "192k"},
}

FIT_MODES = ("cover", "contain")
ROTATIONS = (0, 90, 180, 270)


@dataclass(frozen=True)
class Trim:
    start: float = 0.0
    end: float | None = None

    def duration(self, source_duration: float) -> float:
        end = source_duration if self.end is None else min(self.end, source_duration)
        return max(end - self.start, 0.0)


@dataclass(frozen=True)
class EditSpec:
    """A normalised, already-validated edit."""

    trim: Trim = field(default_factory=Trim)
    speed: float = 1.0
    rotate: int = 0
    aspect: str = "original"
    fit: str = "cover"
    quality: str = "medium"
    mute: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> EditSpec:
        trim_data = data.get("trim") or {}
        return cls(
            trim=Trim(
                start=float(trim_data.get("start") or 0.0),
                end=None if trim_data.get("end") in (None, "") else float(trim_data["end"]),
            ),
            speed=float(data.get("speed", 1.0)),
            rotate=int(data.get("rotate", 0)),
            aspect=str(data.get("aspect", "original")),
            fit=str(data.get("fit", "cover")),
            quality=str(data.get("quality", "medium")),
            mute=bool(data.get("mute", False)),
        )

    def to_dict(self) -> dict:
        return {
            "trim": {"start": self.trim.start, "end": self.trim.end},
            "speed": self.speed,
            "rotate": self.rotate,
            "aspect": self.aspect,
            "fit": self.fit,
            "quality": self.quality,
            "mute": self.mute,
        }

    def canonical_json(self) -> str:
        """A stable string form, so the same edit always hashes the same way."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def fingerprint(self, source_id) -> str:
        """Identifies 'this exact edit of this exact source' for reuse."""
        return hashlib.sha256(f"{source_id}:{self.canonical_json()}".encode()).hexdigest()

    def output_duration(self, source_duration: float) -> float:
        return self.trim.duration(source_duration) / self.speed

    @property
    def is_passthrough(self) -> bool:
        """True when nothing about the picture or timing is being changed."""
        return (
            self.speed == 1.0
            and self.rotate == 0
            and self.aspect == "original"
            and self.trim.start == 0.0
            and self.trim.end is None
            and not self.mute
        )


def audio_tempo_chain(speed: float) -> list[float]:
    """Decompose a speed into atempo factors that each sit inside 0.5 to 2.0.

    ``atempo`` refuses anything outside that window, so 0.25x becomes two
    0.5x stages and 4x becomes two 2x stages.

    >>> audio_tempo_chain(1.0)
    []
    >>> audio_tempo_chain(0.25)
    [0.5, 0.5]
    """
    if speed == 1.0:
        return []

    factors: list[float] = []
    remaining = speed
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    if abs(remaining - 1.0) > 1e-6:
        factors.append(round(remaining, 6))
    return factors


def _even(value: float) -> int:
    """Round to a positive even integer — H.264 with yuv420p needs even dimensions."""
    return max(2, round(value / 2) * 2)


def target_resolution(spec: EditSpec, source_width: int, source_height: int) -> tuple[int, int]:
    """Work out the output frame size for a spec and a given source.

    Never upscales: a 480p source asked for "high" stays 480p rather than being
    stretched into a bigger, more expensive file with no extra detail.
    """
    preset = QUALITY_PRESETS[spec.quality]
    short_side = preset["short_side"]

    # Rotating by a quarter turn swaps the source's width and height.
    if spec.rotate in (90, 270):
        source_width, source_height = source_height, source_width

    ratio = ASPECT_RATIOS.get(spec.aspect)

    if ratio is None:
        source_short = min(source_width, source_height) or short_side
        scale = min(1.0, short_side / source_short)
        return _even(source_width * scale), _even(source_height * scale)

    ratio_w, ratio_h = ratio
    if ratio_w <= ratio_h:  # portrait or square: width is the short side
        width = short_side
        height = short_side * ratio_h / ratio_w
    else:  # landscape: height is the short side
        height = short_side
        width = short_side * ratio_w / ratio_h

    # Do not produce an output larger than the source's own short side.
    source_short = min(source_width, source_height)
    if source_short and source_short < short_side:
        shrink = source_short / short_side
        width, height = width * shrink, height * shrink

    return _even(width), _even(height)
