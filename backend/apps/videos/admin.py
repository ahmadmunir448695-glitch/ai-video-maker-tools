from django.contrib import admin

from .models import VideoAsset


@admin.register(VideoAsset)
class VideoAssetAdmin(admin.ModelAdmin):
    list_display = ["original_filename", "owner", "status", "duration_seconds", "width", "height", "created_at"]
    list_filter = ["status", "has_audio"]
    search_fields = ["original_filename", "owner__email", "id"]
    readonly_fields = [f.name for f in VideoAsset._meta.fields]
    list_select_related = ["owner"]
