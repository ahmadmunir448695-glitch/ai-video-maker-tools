from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import EditorOptionsView, EditPreviewView, ExportJobViewSet

router = DefaultRouter()
router.register("exports", ExportJobViewSet, basename="export")

urlpatterns = [
    path("editor/options", EditorOptionsView.as_view(), name="editor-options"),
    path("editor/preview", EditPreviewView.as_view(), name="editor-preview"),
    *router.urls,
]
