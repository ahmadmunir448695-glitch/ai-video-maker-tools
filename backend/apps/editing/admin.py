from django.contrib import admin

from .models import ExportJob


@admin.register(ExportJob)
class ExportJobAdmin(admin.ModelAdmin):
    list_display = ["id", "owner", "source", "status", "progress", "output_size_bytes", "created_at"]
    list_filter = ["status"]
    search_fields = ["id", "owner__email", "source__original_filename", "celery_task_id"]
    readonly_fields = [f.name for f in ExportJob._meta.fields]
    list_select_related = ["owner", "source"]
