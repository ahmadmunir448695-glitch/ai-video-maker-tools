from __future__ import annotations

from rest_framework import serializers

from apps.core.storage import signed_url

from .models import VideoAsset


class VideoAssetSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    aspect_ratio = serializers.FloatField(read_only=True)
    orientation = serializers.CharField(read_only=True)

    class Meta:
        model = VideoAsset
        fields = [
            "id",
            "original_filename",
            "size_bytes",
            "status",
            "error_message",
            "duration_seconds",
            "width",
            "height",
            "fps",
            "video_codec",
            "audio_codec",
            "has_audio",
            "container",
            "bitrate",
            "aspect_ratio",
            "orientation",
            "file_url",
            "thumbnail_url",
            "created_at",
        ]
        read_only_fields = fields

    def get_file_url(self, obj) -> str | None:
        return signed_url(obj.file)

    def get_thumbnail_url(self, obj) -> str | None:
        return signed_url(obj.thumbnail)


class VideoUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
