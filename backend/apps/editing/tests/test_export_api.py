"""The export API end to end: validation, real renders, dedupe, retry, ownership."""

from __future__ import annotations

import pytest
from conftest import authenticate, requires_ffmpeg

from apps.editing.models import ExportJob, JobStatus
from apps.videos.models import AssetStatus, VideoAsset

# Renders are queued from a transaction.on_commit hook, which only fires when a
# real transaction commits — so these tests need real transactions rather than
# pytest-django's usual rolled-back one. With Celery in eager mode that means a
# job is fully rendered by the time the request returns.
pytestmark = [pytest.mark.django_db(transaction=True), requires_ffmpeg]

EXPORTS = "/api/exports/"
PREVIEW = "/api/editor/preview"
OPTIONS = "/api/editor/options"


def spec(**overrides) -> dict:
    base = {"speed": 1.0, "aspect": "original", "fit": "cover", "quality": "low", "mute": False}
    base.update(overrides)
    return base


def create_export(client, asset, **spec_overrides):
    return client.post(
        EXPORTS,
        {"source": str(asset.id), "spec": spec(**spec_overrides)},
        format="json",
    )


class TestEditorOptions:
    def test_the_editor_advertises_its_capabilities(self, auth_api):
        response = auth_api.get(OPTIONS)

        assert response.status_code == 200
        assert 0.25 in response.data["speeds"]
        assert 2.0 in response.data["speeds"]
        assert "9:16" in response.data["aspects"]
        assert response.data["max_output_duration_seconds"] > 0

    def test_options_require_a_signed_in_user(self, api):
        assert api.get(OPTIONS).status_code == 401


class TestExportCreation:
    def test_an_export_renders_and_produces_a_downloadable_file(self, auth_api, uploaded_asset):
        """Renders run eagerly in tests, so the job is finished when this returns."""
        response = create_export(auth_api, uploaded_asset)

        assert response.status_code == 201, response.data
        job = ExportJob.objects.get(pk=response.data["id"])
        assert job.status == JobStatus.SUCCEEDED, job.error_message
        assert job.progress == 100
        assert job.output, "a succeeded export must have a stored file"
        assert job.output_size_bytes > 0
        assert job.output_duration_seconds > 0
        assert job.finished_at is not None

    def test_a_vertical_export_really_is_vertical(self, auth_api, uploaded_asset):
        response = create_export(auth_api, uploaded_asset, aspect="9:16")

        job = ExportJob.objects.get(pk=response.data["id"])
        assert job.status == JobStatus.SUCCEEDED, job.error_message
        assert job.output_height > job.output_width
        assert job.output_width / job.output_height == pytest.approx(9 / 16, rel=0.02)

    def test_a_trim_and_speed_export_has_the_expected_duration(self, auth_api, uploaded_asset):
        response = create_export(auth_api, uploaded_asset, trim={"start": 0.0, "end": 2.0}, speed=2.0)

        job = ExportJob.objects.get(pk=response.data["id"])
        assert job.status == JobStatus.SUCCEEDED, job.error_message
        assert job.output_duration_seconds == pytest.approx(1.0, abs=0.3)

    def test_the_job_is_owned_by_its_creator(self, auth_api, uploaded_asset, user):
        response = create_export(auth_api, uploaded_asset)

        assert ExportJob.objects.get(pk=response.data["id"]).owner == user

    def test_a_title_is_kept(self, auth_api, uploaded_asset):
        response = auth_api.post(
            EXPORTS,
            {"source": str(uploaded_asset.id), "title": "My Reel", "spec": spec()},
            format="json",
        )

        assert response.data["title"] == "My Reel"
        assert response.data["display_title"] == "My Reel"


class TestExportValidation:
    def test_an_unknown_source_is_rejected(self, auth_api):
        response = auth_api.post(
            EXPORTS,
            {"source": "00000000-0000-0000-0000-000000000000", "spec": spec()},
            format="json",
        )

        assert response.status_code == 400

    def test_another_users_source_cannot_be_rendered(self, api, user, other_user, uploaded_asset):
        """The source belongs to `user`; `other_user` must not be able to use it."""
        response = create_export(authenticate(api, other_user), uploaded_asset)

        assert response.status_code == 400
        assert not ExportJob.objects.filter(owner=other_user).exists()

    def test_a_source_that_is_not_ready_is_rejected(self, auth_api, uploaded_asset):
        VideoAsset.objects.filter(pk=uploaded_asset.pk).update(status=AssetStatus.FAILED)

        assert create_export(auth_api, uploaded_asset).status_code == 400

    @pytest.mark.parametrize("speed", [0, -1, 0.1, 10])
    def test_an_out_of_range_speed_is_rejected(self, auth_api, uploaded_asset, speed):
        assert create_export(auth_api, uploaded_asset, speed=speed).status_code == 400

    def test_an_unknown_aspect_ratio_is_rejected(self, auth_api, uploaded_asset):
        assert create_export(auth_api, uploaded_asset, aspect="3:7").status_code == 400

    def test_an_unknown_quality_is_rejected(self, auth_api, uploaded_asset):
        assert create_export(auth_api, uploaded_asset, quality="ultra").status_code == 400

    def test_an_inverted_trim_range_is_rejected(self, auth_api, uploaded_asset):
        response = create_export(auth_api, uploaded_asset, trim={"start": 3.0, "end": 1.0})

        assert response.status_code == 400
        assert not ExportJob.objects.exists(), "an invalid edit must not reach a worker"

    def test_a_trim_starting_past_the_end_is_rejected(self, auth_api, uploaded_asset):
        assert create_export(auth_api, uploaded_asset, trim={"start": 999.0}).status_code == 400

    def test_a_vanishingly_short_trim_is_rejected(self, auth_api, uploaded_asset):
        assert create_export(auth_api, uploaded_asset, trim={"start": 1.0, "end": 1.01}).status_code == 400

    def test_an_export_past_the_output_duration_limit_is_rejected(self, auth_api, uploaded_asset, settings):
        """Slowing a clip down multiplies render cost, so the cap applies to output."""
        settings.MAX_OUTPUT_DURATION_SECONDS = 5

        response = create_export(auth_api, uploaded_asset, speed=0.25)

        assert response.status_code == 400
        assert not ExportJob.objects.exists()

    def test_an_anonymous_export_request_is_rejected(self, api, uploaded_asset):
        assert create_export(api, uploaded_asset).status_code == 401


class TestDeduplication:
    def test_the_identical_edit_reuses_the_finished_export(self, auth_api, uploaded_asset):
        """Rendering the same thing twice is the easiest cost to avoid."""
        first = create_export(auth_api, uploaded_asset, aspect="1:1")
        assert first.status_code == 201

        second = create_export(auth_api, uploaded_asset, aspect="1:1")

        assert second.status_code == 200, "a repeat request should return the existing export"
        assert second["X-Export-Reused"] == "true"
        assert second.data["id"] == first.data["id"]
        assert ExportJob.objects.count() == 1

    def test_a_different_edit_renders_separately(self, auth_api, uploaded_asset):
        create_export(auth_api, uploaded_asset, aspect="1:1")
        second = create_export(auth_api, uploaded_asset, aspect="9:16")

        assert second.status_code == 201
        assert ExportJob.objects.count() == 2

    def test_a_failed_export_is_not_reused(self, auth_api, uploaded_asset):
        """A previous failure must not block a fresh attempt."""
        first = create_export(auth_api, uploaded_asset, aspect="1:1")
        ExportJob.objects.filter(pk=first.data["id"]).update(status=JobStatus.FAILED)

        second = create_export(auth_api, uploaded_asset, aspect="1:1")

        assert second.status_code == 201
        assert second.data["id"] != first.data["id"]

    def test_another_users_identical_edit_is_not_shared(self, api, user, other_user, uploaded_asset, sample_video):
        """Dedupe must never hand one user a file rendered for another."""
        create_export(authenticate(api, user), uploaded_asset, aspect="1:1")

        own = authenticate(api, other_user)
        with open(sample_video, "rb") as handle:
            created = own.post("/api/videos/", {"file": handle}, format="multipart")
        their_asset = VideoAsset.objects.get(pk=created.data["id"])

        response = create_export(own, their_asset, aspect="1:1")

        assert response.status_code == 201
        assert ExportJob.objects.filter(owner=other_user).count() == 1


class TestPreview:
    def test_preview_reports_the_output_shape_without_rendering(self, auth_api, uploaded_asset):
        response = auth_api.post(
            PREVIEW,
            {"source": str(uploaded_asset.id), "spec": spec(aspect="9:16", speed=2.0)},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["output_height"] > response.data["output_width"]
        assert response.data["output_duration_seconds"] == pytest.approx(2.0, abs=0.2)
        assert not ExportJob.objects.exists(), "a preview must not queue any work"

    def test_preview_points_at_an_existing_export_when_there_is_one(self, auth_api, uploaded_asset):
        created = create_export(auth_api, uploaded_asset, aspect="1:1")

        response = auth_api.post(
            PREVIEW, {"source": str(uploaded_asset.id), "spec": spec(aspect="1:1")}, format="json"
        )

        assert response.data["existing_export_id"] == created.data["id"]

    def test_preview_rejects_an_invalid_edit(self, auth_api, uploaded_asset):
        response = auth_api.post(
            PREVIEW,
            {"source": str(uploaded_asset.id), "spec": spec(trim={"start": 5.0, "end": 1.0})},
            format="json",
        )

        assert response.status_code == 400


class TestQuotas:
    def test_the_daily_export_limit_is_enforced(self, auth_api, uploaded_asset, settings):
        settings.MAX_EXPORTS_PER_DAY = 1
        assert create_export(auth_api, uploaded_asset, aspect="1:1").status_code == 201

        response = create_export(auth_api, uploaded_asset, aspect="9:16")

        assert response.status_code == 429
        assert response.data["code"] == "daily_export_limit"

    def test_the_concurrent_render_limit_is_enforced(self, auth_api, uploaded_asset, settings):
        settings.MAX_CONCURRENT_RENDERS_PER_USER = 1
        first = create_export(auth_api, uploaded_asset, aspect="1:1")
        # Pin the first job as still running.
        ExportJob.objects.filter(pk=first.data["id"]).update(status=JobStatus.PROCESSING)

        response = create_export(auth_api, uploaded_asset, aspect="9:16")

        assert response.status_code == 429
        assert response.data["code"] == "too_many_active_renders"


class TestListingAndOwnership:
    def test_the_list_only_shows_your_own_exports(self, api, user, other_user, uploaded_asset):
        create_export(authenticate(api, user), uploaded_asset)

        response = authenticate(api, other_user).get(EXPORTS)

        assert response.status_code == 200
        assert response.data["results"] == []

    def test_another_users_export_is_not_readable(self, api, user, other_user, uploaded_asset):
        created = create_export(authenticate(api, user), uploaded_asset)

        response = authenticate(api, other_user).get(f"{EXPORTS}{created.data['id']}/")

        assert response.status_code == 404

    def test_another_users_export_cannot_be_downloaded(self, api, user, other_user, uploaded_asset):
        created = create_export(authenticate(api, user), uploaded_asset)

        response = authenticate(api, other_user).get(f"{EXPORTS}{created.data['id']}/download/")

        assert response.status_code == 404

    def test_another_users_export_cannot_be_cancelled_or_retried_or_deleted(
        self, api, user, other_user, uploaded_asset
    ):
        created = create_export(authenticate(api, user), uploaded_asset)
        intruder = authenticate(api, other_user)
        job_id = created.data["id"]

        assert intruder.post(f"{EXPORTS}{job_id}/cancel/").status_code == 404
        assert intruder.post(f"{EXPORTS}{job_id}/retry/").status_code == 404
        assert intruder.delete(f"{EXPORTS}{job_id}/").status_code == 404
        assert ExportJob.objects.filter(pk=job_id).exists()

    def test_exports_can_be_filtered_by_source(self, auth_api, uploaded_asset):
        create_export(auth_api, uploaded_asset)

        response = auth_api.get(EXPORTS, {"source": str(uploaded_asset.id)})

        assert len(response.data["results"]) == 1

    def test_exports_can_be_filtered_by_status(self, auth_api, uploaded_asset):
        create_export(auth_api, uploaded_asset)

        assert len(auth_api.get(EXPORTS, {"status": "succeeded"}).data["results"]) == 1
        assert auth_api.get(EXPORTS, {"status": "failed"}).data["results"] == []


class TestDownload:
    def test_the_owner_can_mint_a_download_url(self, auth_api, uploaded_asset):
        created = create_export(auth_api, uploaded_asset)

        response = auth_api.get(f"{EXPORTS}{created.data['id']}/download/")

        assert response.status_code == 200
        assert response.data["url"]
        assert response.data["filename"].endswith(".mp4")

    def test_an_unfinished_export_cannot_be_downloaded(self, auth_api, uploaded_asset):
        created = create_export(auth_api, uploaded_asset)
        ExportJob.objects.filter(pk=created.data["id"]).update(status=JobStatus.PROCESSING)

        response = auth_api.get(f"{EXPORTS}{created.data['id']}/download/")

        assert response.status_code == 409
        assert response.data["code"] == "not_ready"


class TestCancelAndRetry:
    def test_a_finished_export_cannot_be_cancelled(self, auth_api, uploaded_asset):
        created = create_export(auth_api, uploaded_asset)

        response = auth_api.post(f"{EXPORTS}{created.data['id']}/cancel/")

        assert response.status_code == 409
        assert response.data["code"] == "not_cancellable"

    def test_a_running_export_can_be_cancelled(self, auth_api, uploaded_asset):
        created = create_export(auth_api, uploaded_asset)
        ExportJob.objects.filter(pk=created.data["id"]).update(status=JobStatus.PROCESSING)

        response = auth_api.post(f"{EXPORTS}{created.data['id']}/cancel/")

        assert response.status_code == 200
        assert response.data["status"] == JobStatus.CANCELLED

    def test_a_failed_export_can_be_retried_and_succeeds(self, auth_api, uploaded_asset):
        created = create_export(auth_api, uploaded_asset)
        ExportJob.objects.filter(pk=created.data["id"]).update(
            status=JobStatus.FAILED, error_message="boom", progress=0
        )

        response = auth_api.post(f"{EXPORTS}{created.data['id']}/retry/")

        assert response.status_code == 200
        job = ExportJob.objects.get(pk=created.data["id"])
        assert job.status == JobStatus.SUCCEEDED, job.error_message
        assert job.error_message == "", "a successful retry must clear the old error"

    def test_retrying_reuses_the_same_row_so_nothing_is_duplicated(self, auth_api, uploaded_asset):
        """Retry must not create a second job — that is how double-publishing starts."""
        created = create_export(auth_api, uploaded_asset)
        ExportJob.objects.filter(pk=created.data["id"]).update(status=JobStatus.FAILED)

        auth_api.post(f"{EXPORTS}{created.data['id']}/retry/")

        assert ExportJob.objects.count() == 1

    def test_a_succeeded_export_cannot_be_retried(self, auth_api, uploaded_asset):
        created = create_export(auth_api, uploaded_asset)

        response = auth_api.post(f"{EXPORTS}{created.data['id']}/retry/")

        assert response.status_code == 409
        assert response.data["code"] == "not_retryable"


class TestDeletion:
    def test_an_export_can_be_deleted(self, auth_api, uploaded_asset):
        created = create_export(auth_api, uploaded_asset)

        response = auth_api.delete(f"{EXPORTS}{created.data['id']}/")

        assert response.status_code == 204
        assert not ExportJob.objects.exists()

    def test_a_running_export_cannot_be_deleted(self, auth_api, uploaded_asset):
        created = create_export(auth_api, uploaded_asset)
        ExportJob.objects.filter(pk=created.data["id"]).update(status=JobStatus.PROCESSING)

        response = auth_api.delete(f"{EXPORTS}{created.data['id']}/")

        assert response.status_code == 409
        assert ExportJob.objects.exists()

    def test_deleting_a_source_video_with_a_running_export_is_refused(self, auth_api, uploaded_asset):
        created = create_export(auth_api, uploaded_asset)
        ExportJob.objects.filter(pk=created.data["id"]).update(status=JobStatus.PROCESSING)

        response = auth_api.delete(f"/api/videos/{uploaded_asset.pk}/")

        assert response.status_code == 429
        assert VideoAsset.objects.filter(pk=uploaded_asset.pk).exists()

    def test_deleting_a_source_video_removes_its_exports(self, auth_api, uploaded_asset):
        create_export(auth_api, uploaded_asset)

        response = auth_api.delete(f"/api/videos/{uploaded_asset.pk}/")

        assert response.status_code == 204
        assert not ExportJob.objects.exists(), "exports cannot outlive the source they came from"
