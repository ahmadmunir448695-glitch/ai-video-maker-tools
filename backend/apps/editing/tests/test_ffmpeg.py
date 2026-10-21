"""Render tests that run the real FFmpeg binary and probe the real output.

These are the tests that would catch a wrong filter graph. Every assertion is
made against what FFprobe reads back off the finished file, not against what we
asked FFmpeg to do.
"""

from __future__ import annotations

import pytest
from conftest import make_test_video, requires_ffmpeg

from apps.editing.ffmpeg import RenderError, build_command, build_video_filters, render
from apps.editing.specs import EditSpec, Trim
from apps.videos.probe import probe

pytestmark = [pytest.mark.ffmpeg, requires_ffmpeg]

SOURCE_KWARGS = {
    "source_width": 640,
    "source_height": 360,
    "source_fps": 30.0,
    "source_duration": 4.0,
    "has_audio": True,
}


class TestFilterConstruction:
    """Cheap checks on the graph itself, before paying for a render."""

    def test_speed_change_adds_setpts_and_resamples_frame_rate(self):
        filters = build_video_filters(EditSpec(speed=0.5), 640, 360, 30.0)
        chain = ",".join(filters)
        assert "setpts=PTS/0.5" in chain
        # Without an fps resample, 0.5x would play at 15fps and look like a stutter.
        assert "fps=30" in chain

    def test_unchanged_speed_adds_no_timing_filters(self):
        chain = ",".join(build_video_filters(EditSpec(speed=1.0), 640, 360, 30.0))
        assert "setpts" not in chain

    def test_cover_fit_crops_and_contain_fit_pads(self):
        cover = ",".join(build_video_filters(EditSpec(aspect="9:16", fit="cover"), 1920, 1080, 30.0))
        contain = ",".join(build_video_filters(EditSpec(aspect="9:16", fit="contain"), 1920, 1080, 30.0))
        assert "crop=" in cover and "pad=" not in cover
        assert "pad=" in contain and "crop=" not in contain

    def test_square_pixels_are_forced(self):
        assert "setsar=1" in ",".join(build_video_filters(EditSpec(), 640, 360, 30.0))

    def test_command_never_uses_a_shell_string(self):
        command = build_command(EditSpec(), "in.mp4", "out.mp4", **SOURCE_KWARGS)
        assert isinstance(command, list)
        assert all(isinstance(part, str) for part in command)

    def test_trim_duration_is_an_input_option(self):
        """Regression: -t after -i caps the OUTPUT length instead of the input range.

        With -t on the output side, trimming 2s and then running at 2x produced
        1.5s of the remaining tail rather than 1s of the selected range.
        """
        command = build_command(
            EditSpec(trim=Trim(start=1.0, end=3.0), speed=2.0),
            "in.mp4",
            "out.mp4",
            **SOURCE_KWARGS,
        )
        assert "-t" in command and "-i" in command
        assert command.index("-t") < command.index("-i"), "-t must come before -i to bound the input"
        assert command[command.index("-t") + 1] == "2.000"

    def test_trim_start_is_an_input_option(self):
        command = build_command(EditSpec(trim=Trim(start=1.5)), "in.mp4", "out.mp4", **SOURCE_KWARGS)
        assert command.index("-ss") < command.index("-i")

    def test_muting_drops_the_audio_stream(self):
        command = build_command(EditSpec(mute=True), "in.mp4", "out.mp4", **SOURCE_KWARGS)
        assert "-an" in command

    def test_a_silent_source_is_encoded_without_audio(self):
        command = build_command(EditSpec(), "in.mp4", "out.mp4", **{**SOURCE_KWARGS, "has_audio": False})
        assert "-an" in command

    def test_source_metadata_is_stripped(self):
        """Source files can carry GPS and device identifiers; do not pass them on."""
        command = build_command(EditSpec(), "in.mp4", "out.mp4", **SOURCE_KWARGS)
        assert "-map_metadata" in command
        assert command[command.index("-map_metadata") + 1] == "-1"


class TestRealRenders:
    def test_passthrough_render_produces_a_playable_file(self, sample_video, tmp_path):
        out = tmp_path / "out.mp4"
        result = render(EditSpec(), sample_video, out, **SOURCE_KWARGS)

        assert out.exists() and result.size_bytes > 0
        info = probe(out)
        assert info.video_codec == "h264"
        assert info.duration_seconds == pytest.approx(4.0, abs=0.4)

    def test_trim_shortens_the_output(self, sample_video, tmp_path):
        out = tmp_path / "trimmed.mp4"
        render(EditSpec(trim=Trim(start=1.0, end=3.0)), sample_video, out, **SOURCE_KWARGS)

        info = probe(out)
        assert info.duration_seconds == pytest.approx(2.0, abs=0.3)

    @pytest.mark.parametrize(
        ("speed", "expected_seconds"),
        [(0.5, 8.0), (1.5, 2.667), (2.0, 2.0)],
    )
    def test_speed_changes_the_duration_as_requested(self, sample_video, tmp_path, speed, expected_seconds):
        out = tmp_path / f"speed-{speed}.mp4"
        render(EditSpec(speed=speed), sample_video, out, **SOURCE_KWARGS)

        info = probe(out)
        assert info.duration_seconds == pytest.approx(expected_seconds, rel=0.12)

    def test_slow_motion_keeps_audio_in_sync_with_video(self, sample_video, tmp_path):
        """The classic speed-change bug: video stretches, audio does not.

        Both streams must end up the same length, or the clip drifts out of sync.
        """
        out = tmp_path / "slowmo.mp4"
        render(EditSpec(speed=0.5), sample_video, out, **SOURCE_KWARGS)

        import json
        import subprocess

        from django.conf import settings

        raw = subprocess.run(
            [
                settings.FFPROBE_BINARY, "-v", "error", "-print_format", "json",
                "-show_streams", str(out),
            ],
            capture_output=True, text=True, check=True, timeout=60,
        )
        streams = json.loads(raw.stdout)["streams"]
        durations = {
            s["codec_type"]: float(s.get("duration") or 0)
            for s in streams
            if s["codec_type"] in ("video", "audio")
        }

        assert "audio" in durations, "slow motion must not silently drop the audio track"
        assert durations["video"] == pytest.approx(8.0, rel=0.12)
        assert durations["audio"] == pytest.approx(durations["video"], abs=0.35)

    def test_quarter_speed_chains_atempo_without_losing_audio(self, sample_video, tmp_path):
        """0.25x is outside atempo's range, so it must be applied as two stages."""
        out = tmp_path / "quarter.mp4"
        render(EditSpec(speed=0.25), sample_video, out, **SOURCE_KWARGS)

        info = probe(out)
        assert info.has_audio
        assert info.duration_seconds == pytest.approx(16.0, rel=0.12)

    def test_vertical_conversion_produces_a_nine_by_sixteen_file(self, sample_video, tmp_path):
        out = tmp_path / "vertical.mp4"
        render(EditSpec(aspect="9:16", quality="low"), sample_video, out, **SOURCE_KWARGS)

        info = probe(out)
        assert info.width / info.height == pytest.approx(9 / 16, rel=0.02)
        assert info.height > info.width

    def test_square_conversion_produces_a_square_file(self, sample_video, tmp_path):
        out = tmp_path / "square.mp4"
        render(EditSpec(aspect="1:1", quality="low"), sample_video, out, **SOURCE_KWARGS)

        info = probe(out)
        assert info.width == info.height

    def test_contain_fit_letterboxes_instead_of_cropping(self, sample_video, tmp_path):
        out = tmp_path / "contain.mp4"
        render(EditSpec(aspect="9:16", fit="contain", quality="low"), sample_video, out, **SOURCE_KWARGS)

        info = probe(out)
        assert info.width / info.height == pytest.approx(9 / 16, rel=0.02)

    def test_muting_removes_the_audio_track(self, sample_video, tmp_path):
        out = tmp_path / "muted.mp4"
        render(EditSpec(mute=True), sample_video, out, **SOURCE_KWARGS)

        assert probe(out).has_audio is False

    def test_a_silent_source_renders_without_error(self, silent_video, tmp_path):
        out = tmp_path / "from-silent.mp4"
        render(EditSpec(speed=2.0), silent_video, out, **{**SOURCE_KWARGS, "has_audio": False})

        info = probe(out)
        assert info.has_audio is False
        assert info.duration_seconds == pytest.approx(2.0, rel=0.15)

    def test_rotation_swaps_the_output_dimensions(self, sample_video, tmp_path):
        out = tmp_path / "rotated.mp4"
        render(EditSpec(rotate=90, quality="low"), sample_video, out, **SOURCE_KWARGS)

        info = probe(out)
        assert info.height > info.width, "a quarter turn of a landscape clip should be portrait"

    def test_combined_edit_applies_every_step(self, sample_video, tmp_path):
        """Trim 1s-3s, run it at 2x, and convert to vertical: 1 second of 9:16."""
        out = tmp_path / "combined.mp4"
        spec = EditSpec(trim=Trim(start=1.0, end=3.0), speed=2.0, aspect="9:16", quality="low")
        render(spec, sample_video, out, **SOURCE_KWARGS)

        info = probe(out)
        assert info.duration_seconds == pytest.approx(1.0, abs=0.3)
        assert info.width / info.height == pytest.approx(9 / 16, rel=0.02)

    def test_higher_quality_yields_a_larger_file(self, tmp_path):
        source = make_test_video(tmp_path / "hq-source.mp4", seconds=3.0, width=1280, height=720)
        kwargs = {**SOURCE_KWARGS, "source_width": 1280, "source_height": 720, "source_duration": 3.0}

        low = tmp_path / "low.mp4"
        high = tmp_path / "high.mp4"
        low_result = render(EditSpec(quality="low"), source, low, **kwargs)
        high_result = render(EditSpec(quality="high"), source, high, **kwargs)

        assert probe(high).height > probe(low).height
        assert high_result.size_bytes > low_result.size_bytes


class TestRenderProgressAndFailure:
    def test_progress_is_reported_and_monotonic(self, sample_video, tmp_path):
        seen: list[int] = []
        render(
            EditSpec(quality="low"),
            sample_video,
            tmp_path / "progress.mp4",
            on_progress=seen.append,
            **SOURCE_KWARGS,
        )

        assert seen, "the render reported no progress at all"
        assert seen == sorted(seen), "progress must never go backwards"
        assert max(seen) <= 99, "100% is only set once the file is stored"

    def test_an_unreadable_source_fails_cleanly(self, tmp_path):
        """A failed render must raise, delete its partial output, and keep a log."""
        broken = tmp_path / "broken.mp4"
        broken.write_bytes(b"this is definitely not a video")
        out = tmp_path / "never.mp4"

        with pytest.raises(RenderError) as excinfo:
            render(EditSpec(), broken, out, **SOURCE_KWARGS)

        assert not out.exists(), "a failed render must not leave a partial file behind"
        assert excinfo.value.log_tail, "the FFmpeg error should be captured for diagnosis"

    def test_cancellation_stops_the_render_and_removes_the_output(self, tmp_path):
        from apps.editing.ffmpeg import RenderCancelled

        # Long and large enough that the cancellation poll fires mid-encode.
        source = make_test_video(tmp_path / "long.mp4", seconds=25.0, width=1280, height=720)
        out = tmp_path / "cancelled.mp4"

        with pytest.raises(RenderCancelled):
            render(
                EditSpec(quality="high", speed=0.5),
                source,
                out,
                on_progress=lambda _p: None,
                is_cancelled=lambda: True,
                **{**SOURCE_KWARGS, "source_width": 1280, "source_height": 720, "source_duration": 25.0},
            )

        assert not out.exists(), "a cancelled render must not leave its output behind"
