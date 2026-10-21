"""Upload: real validation against real files, and per-user isolation."""

from __future__ import annotations

import pytest
from conftest import authenticate, make_test_video, requires_ffmpeg
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.videos.models import AssetStatus, VideoAsset

pytestmark = pytest.mark.django_db

VIDEOS = "/api/videos/"


def upload(client, path, *, filename=None, content_type="video/mp4"):
    with open(path, "rb") as handle:
        payload = SimpleUploadedFile(filename or path.name, handle.read(), content_type=content_type)
    return client.post(VIDEOS, {"file": payload}, format="multipart")


@requires_ffmpeg
class TestSuccessfulUpload:
    def test_uploading_a_real_video_records_its_true_properties(self, auth_api, sample_video):
        response = upload(auth_api, sample_video)

        assert response.status_code == 201, response.data
        data = response.data
        assert data["status"] == AssetStatus.READY
        # These come from FFprobe reading the actual file, not from the client.
        assert data["duration_seconds"] == pytest.approx(4.0, abs=0.3)
        assert (data["width"], data["height"]) == (640, 360)
        assert data["video_codec"] == "h264"
        assert data["has_audio"] is True
        assert data["orientation"] == "landscape"

    def test_a_thumbnail_is_generated(self, auth_api, sample_video):
        response = upload(auth_api, sample_video)

        asset = VideoAsset.objects.get(pk=response.data["id"])
        assert asset.thumbnail, "an uploaded video should get a poster frame"
        assert asset.thumbnail.size > 0

    def test_a_portrait_video_is_reported_as_portrait(self, auth_api, tmp_path):
        source = make_test_video(tmp_path / "portrait.mp4", width=360, height=640, seconds=2)

        response = upload(auth_api, source)

        assert response.data["orientation"] == "portrait"

    def test_a_silent_video_is_accepted_and_flagged(self, auth_api, silent_video):
        response = upload(auth_api, silent_video)

        assert response.status_code == 201
        assert response.data["has_audio"] is False

    def test_the_upload_is_owned_by_the_uploader(self, auth_api, sample_video, user):
        response = upload(auth_api, sample_video)

        assert VideoAsset.objects.get(pk=response.data["id"]).owner == user


class TestRejectedUploads:
    def test_a_text_file_renamed_to_mp4_is_rejected(self, auth_api):
        """Extension and content-type are client-controlled; the bytes decide."""
        payload = SimpleUploadedFile("sneaky.mp4", b"I am not a video at all", content_type="video/mp4")

        response = auth_api.post(VIDEOS, {"file": payload}, format="multipart")

        assert response.status_code == 400
        assert response.data["code"] == "invalid_media"
        assert not VideoAsset.objects.exists(), "a rejected upload must not leave a row behind"

    def test_a_disallowed_extension_is_rejected(self, auth_api, sample_video):
        response = upload(auth_api, sample_video, filename="payload.exe", content_type="video/mp4")

        assert response.status_code == 400
        assert not VideoAsset.objects.exists()

    def test_a_disallowed_content_type_is_rejected(self, auth_api, sample_video):
        response = upload(auth_api, sample_video, content_type="text/html")

        assert response.status_code == 400

    def test_an_empty_file_is_rejected(self, auth_api):
        payload = SimpleUploadedFile("empty.mp4", b"", content_type="video/mp4")

        assert auth_api.post(VIDEOS, {"file": payload}, format="multipart").status_code == 400

    def test_a_request_with_no_file_is_rejected(self, auth_api):
        assert auth_api.post(VIDEOS, {}, format="multipart").status_code == 400

    @requires_ffmpeg
    def test_a_file_over_the_size_limit_is_rejected(self, auth_api, sample_video, settings):
        settings.MAX_UPLOAD_BYTES = 1024

        response = upload(auth_api, sample_video)

        assert response.status_code == 429
        assert response.data["code"] == "upload_too_large"
        assert not VideoAsset.objects.exists()

    @requires_ffmpeg
    def test_a_video_over_the_duration_limit_is_rejected_and_not_kept(self, auth_api, sample_video, settings):
        """The limit is about render cost, so the bytes must not be kept either."""
        settings.MAX_UPLOAD_DURATION_SECONDS = 2

        response = upload(auth_api, sample_video)

        assert response.status_code == 400
        assert response.data["code"] == "duration_too_long"
        assert not VideoAsset.objects.exists()

    @requires_ffmpeg
    def test_an_upload_past_the_storage_quota_is_rejected(self, auth_api, sample_video, settings):
        settings.MAX_STORAGE_BYTES_PER_USER = 100

        response = upload(auth_api, sample_video)

        assert response.status_code == 429
        assert response.data["code"] == "storage_quota_exceeded"

    def test_an_anonymous_upload_is_rejected(self, api, sample_video):
        with open(sample_video, "rb") as handle:
            response = api.post(VIDEOS, {"file": handle}, format="multipart")

        assert response.status_code == 401


@requires_ffmpeg
class TestOwnershipIsolation:
    """Every route must be scoped to the requesting user's own rows."""

    def test_the_list_only_shows_your_own_videos(self, api, user, other_user, sample_video):
        upload(authenticate(api, user), sample_video)

        response = authenticate(api, other_user).get(VIDEOS)

        assert response.status_code == 200
        assert response.data["results"] == []

    def test_another_users_video_is_not_readable(self, api, user, other_user, sample_video):
        created = upload(authenticate(api, user), sample_video)
        asset_id = created.data["id"]

        response = authenticate(api, other_user).get(f"{VIDEOS}{asset_id}/")

        assert response.status_code == 404, "another user's row must look absent, not forbidden"

    def test_another_users_video_cannot_be_deleted(self, api, user, other_user, sample_video):
        created = upload(authenticate(api, user), sample_video)
        asset_id = created.data["id"]

        response = authenticate(api, other_user).delete(f"{VIDEOS}{asset_id}/")

        assert response.status_code == 404
        assert VideoAsset.objects.filter(pk=asset_id).exists(), "the owner's video must survive"

    def test_another_users_download_url_cannot_be_minted(self, api, user, other_user, sample_video):
        created = upload(authenticate(api, user), sample_video)

        response = authenticate(api, other_user).get(f"{VIDEOS}{created.data['id']}/download/")

        assert response.status_code == 404


@requires_ffmpeg
class TestDeletion:
    @pytest.mark.django_db(transaction=True)
    def test_deleting_a_video_removes_the_row_and_the_stored_files(self, auth_api, sample_video):
        """Storage cleanup is deferred to transaction commit, so this test needs
        a real transaction rather than the usual rolled-back one."""
        created = upload(auth_api, sample_video)
        asset = VideoAsset.objects.get(pk=created.data["id"])
        file_name, thumb_name = asset.file.name, asset.thumbnail.name
        storage = asset.file.storage

        response = auth_api.delete(f"{VIDEOS}{asset.pk}/")

        assert response.status_code == 204
        assert not VideoAsset.objects.filter(pk=asset.pk).exists()
        assert not storage.exists(file_name), "the source object should be deleted too"
        assert not storage.exists(thumb_name)

    def test_the_owner_can_mint_a_download_url(self, auth_api, sample_video):
        created = upload(auth_api, sample_video)

        response = auth_api.get(f"{VIDEOS}{created.data['id']}/download/")

        assert response.status_code == 200
        assert response.data["url"]
        assert response.data["filename"].endswith(".mp4")
