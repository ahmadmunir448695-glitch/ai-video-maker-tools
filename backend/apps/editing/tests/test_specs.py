"""Unit tests for the spec maths: no FFmpeg, no database."""

from __future__ import annotations

import pytest

from apps.editing.specs import (
    EditSpec,
    Trim,
    audio_tempo_chain,
    target_resolution,
)


class TestAudioTempoChain:
    def test_unchanged_speed_needs_no_filter(self):
        assert audio_tempo_chain(1.0) == []

    @pytest.mark.parametrize("speed", [0.25, 0.5, 0.75, 1.5, 2.0, 3.0, 4.0])
    def test_every_factor_is_within_ffmpeg_limits(self, speed):
        """atempo rejects anything outside 0.5-2.0, so each stage must fit."""
        for factor in audio_tempo_chain(speed):
            assert 0.5 <= factor <= 2.0

    @pytest.mark.parametrize("speed", [0.25, 0.4, 0.5, 0.75, 1.5, 2.0, 3.0, 4.0])
    def test_factors_multiply_back_to_the_requested_speed(self, speed):
        product = 1.0
        for factor in audio_tempo_chain(speed):
            product *= factor
        assert product == pytest.approx(speed, rel=1e-4)

    def test_quarter_speed_is_two_halvings(self):
        assert audio_tempo_chain(0.25) == [0.5, 0.5]


class TestTrim:
    def test_open_ended_trim_runs_to_the_end(self):
        assert Trim(start=2.0).duration(10.0) == 8.0

    def test_end_beyond_the_source_is_clamped(self):
        assert Trim(start=0.0, end=99.0).duration(10.0) == 10.0

    def test_inverted_range_is_zero_not_negative(self):
        assert Trim(start=8.0, end=2.0).duration(10.0) == 0.0


class TestTargetResolution:
    def test_vertical_conversion_produces_nine_by_sixteen(self):
        spec = EditSpec(aspect="9:16", quality="high")
        width, height = target_resolution(spec, 1920, 1080)
        assert (width, height) == (1080, 1920)
        assert width / height == pytest.approx(9 / 16, rel=1e-3)

    def test_square_conversion_is_square(self):
        spec = EditSpec(aspect="1:1", quality="medium")
        assert target_resolution(spec, 1920, 1080) == (720, 720)

    def test_landscape_conversion_is_sixteen_by_nine(self):
        spec = EditSpec(aspect="16:9", quality="medium")
        width, height = target_resolution(spec, 1080, 1920)
        assert height == 720
        assert width / height == pytest.approx(16 / 9, rel=1e-3)

    @pytest.mark.parametrize("aspect", ["original", "9:16", "1:1", "16:9", "4:5"])
    @pytest.mark.parametrize("quality", ["low", "medium", "high"])
    def test_dimensions_are_always_even(self, aspect, quality):
        """H.264 with yuv420p cannot encode odd dimensions."""
        spec = EditSpec(aspect=aspect, quality=quality)
        width, height = target_resolution(spec, 1281, 721)
        assert width % 2 == 0
        assert height % 2 == 0
        assert width > 0 and height > 0

    def test_a_small_source_is_never_upscaled(self):
        """Upscaling costs bytes and adds no detail."""
        spec = EditSpec(aspect="9:16", quality="high")
        _, height = target_resolution(spec, 360, 640)
        assert height <= 640

    def test_quarter_turn_swaps_the_source_dimensions(self):
        spec = EditSpec(aspect="original", quality="medium", rotate=90)
        width, height = target_resolution(spec, 1920, 1080)
        assert height > width


class TestFingerprint:
    def test_identical_specs_hash_the_same(self):
        a = EditSpec.from_dict({"speed": 2.0, "aspect": "9:16"})
        b = EditSpec.from_dict({"aspect": "9:16", "speed": 2.0})
        assert a.fingerprint("src-1") == b.fingerprint("src-1")

    def test_a_different_source_hashes_differently(self):
        spec = EditSpec(speed=2.0)
        assert spec.fingerprint("src-1") != spec.fingerprint("src-2")

    def test_a_different_edit_hashes_differently(self):
        assert EditSpec(speed=2.0).fingerprint("s") != EditSpec(speed=1.5).fingerprint("s")


class TestOutputDuration:
    def test_doubling_speed_halves_the_duration(self):
        assert EditSpec(speed=2.0).output_duration(10.0) == pytest.approx(5.0)

    def test_quarter_speed_quadruples_the_duration(self):
        assert EditSpec(speed=0.25).output_duration(10.0) == pytest.approx(40.0)

    def test_trim_applies_before_speed(self):
        spec = EditSpec(trim=Trim(start=2.0, end=6.0), speed=2.0)
        assert spec.output_duration(10.0) == pytest.approx(2.0)
