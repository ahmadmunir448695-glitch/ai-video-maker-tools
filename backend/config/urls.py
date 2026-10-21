"""Top-level URL routing.

Everything the SPA talks to lives under ``/api/``. In development the media
files are served by Django; in production they come from object storage (or a
web server), never from here.
"""

from apps.core.views import HealthView
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("api/health", HealthView.as_view(), name="health"),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/", include("apps.videos.urls")),
    path("api/", include("apps.editing.urls")),
    path("admin/", admin.site.urls),
]

if settings.DEBUG and not settings.USE_OBJECT_STORAGE:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
