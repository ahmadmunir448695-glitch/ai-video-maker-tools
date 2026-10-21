from __future__ import annotations

from django.conf import settings
from rest_framework import serializers

from apps.core.storage import signed_url
from apps.videos.models import AssetStatus, VideoAsset

from .models import ExportJob
from .specs import (
    ASPECT_RATIOS,
    FIT_MODES,
    MAX_SPEED,
    MIN_SPEED,
    QUALITY_PRESETS,
    ROTATIONS,
    EditSpec,
    target_resolution,
)


class TrimSerializer(serializers.Serializer):
    start = serializers.FloatField(required=False, min_value=0, default=0.0)
    end = serializers.FloatField(required=False, allow_null=True, min_value=0, default=None)


class EditSpecSerializer(serializers.Serializer):
    """Validates an edit before any worker time is spent on it."""

    trim = TrimSerializer(required=False)
    speed = serializers.FloatField(required=False, default=1.0, min_value=MIN_SPEED, max_value=MAX_SPEED)
    rotate = serializers.ChoiceField(choices=ROTATIONS, required=False, default=0)
    aspect = serializers.ChoiceField(choices=sorted(ASPECT_RATIOS), required=False, default="original")
    fit = serializers.ChoiceField(choices=FIT_MODES, required=False, default="cover")
    quality = serializers.ChoiceField(choices=sorted(QUALITY_PRESETS), required=False, default="medium")
    mute = serializers.BooleanField(required=False, default=False)

    def validate_speed(self, value: float) -> float:
        # Guard against a float that would make setpts/atempo degenerate.
        if value <= 0:
            raise serializers.ValidationError("Speed must be greater than zero.")
        return round(value, 4)


class ExportJobSerializer(serializers.ModelSerializer):
    source_id = serializers.UUIDField(source="source.id", read_only=True)
    source_filename = serializers.CharField(source="source.original_filename", read_only=True)
    display_title = serializers.CharField(read_only=True)
    output_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    can_retry = serializers.BooleanField(read_only=True)
    is_cancellable = serializers.BooleanField(read_only=True)

    class Meta:
        model = ExportJob
        fields = [
            "id",
            "source_id",
            "source_filename",
            "title",
            "display_title",
            "spec",
            "status",
            "progress",
            "output_url",
            "thumbnail_url",
            "output_size_bytes",
            "output_width",
            "output_height",
            "output_duration_seconds",
            "error_message",
            "can_retry",
            "is_cancellable",
            "started_at",
            "finished_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_output_url(self, obj) -> str | None:
        return signed_url(obj.output)

    def get_thumbnail_url(self, obj) -> str | None:
        return signed_url(obj.source.thumbnail)


class ExportJobCreateSerializer(serializers.Serializer):
    source = serializers.UUIDField()
    title = serializers.CharField(max_length=140, required=False, allow_blank=True, default="")
    spec = EditSpecSerializer()

    def validate_source(self, value):
        user = self.context["request"].user
        asset = VideoAsset.objects.filter(pk=value, owner=user).first()
        if asset is None:
            # Same message whether the row is missing or someone else's, so this
            # cannot be used to probe for other users' asset IDs.
            raise serializers.ValidationError("That video could not be found.")
        if asset.status != AssetStatus.READY:
            raise serializers.ValidationError("That video is not ready to edit yet.")
        return asset

    def validate(self, attrs):
        asset: VideoAsset = attrs["source"]
        spec = EditSpec.from_dict(attrs["spec"])

        duration = asset.duration_seconds

        if spec.trim.start >= duration:
            raise serializers.ValidationError(
                {"spec": {"trim": f"The start point must be before the end of the video ({duration:.1f}s)."}}
            )

        if spec.trim.end is not None and spec.trim.end <= spec.trim.start:
            raise serializers.ValidationError(
                {"spec": {"trim": "The end point must come after the start point."}}
            )

        trimmed = spec.trim.duration(duration)
        if trimmed < 0.1:
            raise serializers.ValidationError(
                {"spec": {"trim": "The selected range is too short to export (minimum 0.1 seconds)."}}
            )

        output_duration = spec.output_duration(duration)
        if output_duration > settings.MAX_OUTPUT_DURATION_SECONDS:
            limit = settings.MAX_OUTPUT_DURATION_SECONDS
            raise serializers.ValidationError(
                {
                    "spec": {
                        "speed": (
                            f"At {spec.speed}x this export would be {output_duration:.0f} seconds long, "
                            f"over the {limit} second limit. Trim the clip or choose a faster speed."
                        )
                    }
                }
            )

        if spec.mute and not asset.has_audio:
            # Not an error, just redundant — normalise it away so the fingerprint
            # matches an otherwise-identical unmuted request.
            spec = EditSpec.from_dict({**spec.to_dict(), "mute": False})

        attrs["edit_spec"] = spec
        attrs["predicted_resolution"] = target_resolution(spec, asset.width, asset.height)
        return attrs


class EditorOptionsSerializer(serializers.Serializer):
    """Static editor capabilities, so the UI never hardcodes server limits."""

    speeds = serializers.ListField(child=serializers.FloatField())
    aspects = serializers.ListField(child=serializers.CharField())
    fits = serializers.ListField(child=serializers.CharField())
    qualities = serializers.ListField(child=serializers.CharField())
    rotations = serializers.ListField(child=serializers.IntegerField())
    max_output_duration_seconds = serializers.IntegerField()
