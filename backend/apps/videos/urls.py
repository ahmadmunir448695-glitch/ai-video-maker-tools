from rest_framework.routers import DefaultRouter

from .views import VideoAssetViewSet

router = DefaultRouter()
router.register("videos", VideoAssetViewSet, basename="video")

urlpatterns = router.urls
