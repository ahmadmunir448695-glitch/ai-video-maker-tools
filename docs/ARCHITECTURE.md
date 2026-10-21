# Architecture, dependencies, risks and MVP checklist

This document is the plan the code follows. It was written before Phase 1 was
built and updated to match what actually shipped.

---

## 1. What this is

A web application where someone uploads a video, edits it with server-side
FFmpeg, and (from Phase 3) publishes it to TikTok, Instagram Reels and YouTube
Shorts through each platform's official API.

**Phase 1 is built and working.** Phases 2-4 are planned, not implemented.
Nothing in the running app pretends otherwise: the dashboard labels unbuilt
features with the phase they belong to, and there are no fake buttons.

---

## 2. Chosen stack and why

| Layer | Choice | Why |
| --- | --- | --- |
| Frontend | Vue 3 + Vite + Tailwind 4 + Pinia | Asked for; Vite's dev server makes the edit loop fast, Pinia keeps render-progress state in one place. |
| Backend | Django 5.1 + Django REST Framework | Asked for; the admin, auth, ORM and migrations remove a lot of SaaS boilerplate. |
| Database | PostgreSQL 16 | Asked for; JSONB holds the edit spec without a migration per new edit feature. |
| Video | FFmpeg 6 (subprocess) | Asked for; it does every Phase 1-2 edit natively, which is the main cost control. |
| Queue | Celery 5 + Redis 7 | Asked for; renders are minutes long and must never sit inside an HTTP request. |
| Storage | S3-compatible via django-storages | Asked for; works with AWS S3, Cloudflare R2, Backblaze B2 or MinIO. |
| Auth | SimpleJWT, refresh token in an HttpOnly cookie | A token in `localStorage` is readable by any XSS payload. See §5. |

### Environment inspection before choosing

The container was checked before anything was installed:

```
Python 3.13.16    FFmpeg 6.1.1 (libx264, aac, atempo, setpts, scale, crop, pad,
Node 22.22.0       transpose, drawtext, subtitles, overlay, concat — all present)
PostgreSQL 16.15  Redis 7.0.15      Docker available
```

Every tool the stack needs was already present, so nothing had to be swapped
for an alternative. Django itself was not installed and was added.

The repository was empty before this work, so there was no existing codebase to
conform to.

---

## 3. Application layout

```
backend/
  config/            settings, URLs, WSGI/ASGI, Celery app
  apps/
    core/            shared: UUID/timestamp models, ownership permission,
                     error shape, storage helpers, upload validators, health
    accounts/        custom user (email login), JWT views, usage/quota counters
    videos/          VideoAsset, FFprobe wrapper, thumbnails, upload endpoint
    editing/         EditSpec, FFmpeg pipeline, ExportJob, Celery tasks, API
frontend/
  src/lib/           API client (token refresh, upload progress), formatting
  src/stores/        Pinia: auth, videos, exports, toasts
  src/views/         Auth, Dashboard, Upload, Editor, Videos, Exports, Settings
  src/components/    nav, status pill, progress bar, trim control, toasts
```

### Why apps are split this way

`videos` owns *source material*; `editing` owns *derived output*. They are
separate because Phase 2 adds captions and music to `editing` without touching
upload, and Phase 3 adds a `social` app that consumes finished exports and
knows nothing about FFmpeg.

---

## 4. Data model

```
User (accounts)
 ├── id (UUID), email (unique, the login), display_name, plan, is_active
 └── Argon2 password hash

VideoAsset (videos)            one uploaded source file
 ├── owner → User (CASCADE)
 ├── file, thumbnail
 ├── original_filename, size_bytes, status (probing/ready/failed)
 └── FFprobe findings: duration, width, height, fps, codecs, has_audio, bitrate

ExportJob (editing)            one render of one source with one edit
 ├── owner → User (CASCADE), source → VideoAsset (CASCADE)
 ├── spec (JSONB), fingerprint (sha256 of source + canonical spec)
 ├── status, progress, celery_task_id
 ├── output, output_size/width/height/duration
 └── error_message, error_log, started_at, finished_at
```

### The edit spec

An edit is **data**, not columns:

```json
{
  "trim":    { "start": 1.0, "end": 5.0 },
  "speed":   2.0,
  "rotate":  0,
  "aspect":  "9:16",
  "fit":     "cover",
  "quality": "medium",
  "mute":    false
}
```

It is validated by a serializer before a worker is woken, and normalised before
being stored. Phase 2 extends this schema (overlays, captions, music) and the
filter builder, with no migration per feature.

`fingerprint = sha256(source_id + canonical_json(spec))` identifies "this exact
edit of this exact source". A create request matching an existing non-failed job
returns that job instead of rendering again — the single largest cost saving
available, and the reason the editor can tell you "you already exported this".

---

## 5. Authentication design

The access token is **returned in the response body** and held in the SPA's
memory only. The refresh token is set as an **HttpOnly, SameSite cookie scoped
to `/api/auth/`**.

Why not `localStorage`: any XSS bug would hand an attacker a 14-day credential
they could exfiltrate. An HttpOnly cookie is unreadable from JavaScript, and the
in-memory access token dies with the tab.

Refresh tokens **rotate and are blacklisted on use**, so a stolen cookie is good
for at most one exchange, and the theft is likely to surface as the real user
being logged out.

Consequences handled in code:
- The SPA calls `POST /api/auth/refresh` on boot to discover an existing session
  (401 when signed out — an authentication state, not a malformed request).
- A 401 on any other endpoint triggers one refresh-and-replay. Concurrent 401s
  share a single in-flight refresh, since rotation would reject the second.
- Logout and password change both blacklist the current refresh token.

---

## 6. The render pipeline

```
POST /api/exports/
   ├─ validate spec against the source's real duration
   ├─ fingerprint → return the existing export if there is one
   ├─ check quotas (concurrent renders, exports today, storage)
   ├─ create ExportJob (pending)
   └─ transaction.on_commit → Celery
                                  │
                           worker picks it up
                                  │
   ├─ claim: UPDATE ... WHERE status IN (pending, queued)   ← 0 rows = someone
   │                                                           else has it
   ├─ pull the source to a local path (no-op on local storage)
   ├─ FFmpeg: filter graph from the spec, progress on `-progress pipe:1`
   │     every ~2s: has the row been set to CANCELLED? → SIGTERM
   ├─ FFprobe the finished file; store what it actually is, not what we asked for
   └─ save output, status=succeeded, progress=100
```

### Filter graph order, and why

1. **Rotation** (`transpose`) first, so later size maths sees the final orientation.
2. **Speed**: `setpts=PTS/N`, then `fps=N`. The `fps` stage matters — `setpts`
   alone turns a 30fps clip at 0.25x into 7.5fps playback, which looks broken.
3. **Aspect**: `scale` + `crop` (cover) or `scale` + `pad` (contain), then `setsar=1`.
4. **Audio**: `atempo` only accepts 0.5-2.0, so 0.25x becomes `atempo=0.5,atempo=0.5`,
   followed by `asetpts=N/SR/TB` to keep audio locked to the re-timed video.

Two details that are easy to get wrong and are covered by tests:

- `-ss` **and** `-t` go **before** `-i`. After `-i`, `-t` caps the *output*
  length, so a 2-second trim at 2x produced 1.5s of the wrong footage instead of
  1s of the right footage. This was a real bug caught by a test.
- Output is re-probed rather than assumed, so the stored width/height/duration
  describe the actual downloadable file.

### Never upscale

A 480p source asked for "high" stays 480p. Upscaling costs bytes and render time
and adds no detail.

---

## 7. Reliability

| Failure | Handling |
| --- | --- |
| Worker killed mid-render | `reap_stalled_jobs` (Celery beat, every 15 min) fails jobs older than 2h so they become retryable instead of stuck at 40% forever. |
| Two workers take one job | Claim is a conditional `UPDATE ... WHERE status IN (pending, queued)`; a zero-row result means stand down. |
| Broker unreachable | Queueing failure marks the job failed with a readable message, rather than leaving it pending forever. |
| User cancels | API sets `CANCELLED`; the worker polls that status every ~2s and terminates FFmpeg, then deletes the partial file. |
| Retry | Reuses the **same row** and deletes the old output, so a retry cannot produce two files — which is how duplicate publishing starts in Phase 3. |
| Rejected upload | File and row are both deleted, so bad bytes never count against a quota. |
| Transaction rollback | Storage deletion runs in `transaction.on_commit`, so a rolled-back delete cannot orphan a row from its file. |
| Deterministic FFmpeg error | Recorded as failed, not retried — retrying burns CPU on the same error. Only `OSError` (storage blip, worker restart) auto-retries, twice, with backoff. |

---

## 8. Security

- **Ownership on every resource.** Two locks: the queryset filters by owner, and
  `IsOwner` re-checks the object. Another user's row returns **404, not 403**, so
  IDs cannot be probed.
- `IsOwner` implements `has_permission` as well as `has_object_permission`.
  Without it, a view setting `permission_classes = [IsOwner]` silently replaces
  the global `IsAuthenticated` default and lets anonymous requests into list and
  create. This was a real bug caught by a test.
- **Uploads are not trusted.** Extension and content-type are a cheap gate,
  magic bytes a second, and FFprobe successfully reading a video stream is the
  decisive check. A renamed `.exe` or a text file called `.mp4` is rejected.
- **No shell.** Every FFmpeg/FFprobe call is an argument list, never a shell
  string, so a hostile filename cannot inject a command.
- **Source metadata is stripped** (`-map_metadata -1`); phone video can carry
  GPS coordinates and device identifiers.
- **Private objects, signed URLs.** Nothing is public-read; a URL is minted only
  after the ownership check, and expires (default 15 minutes).
- **Rate limits** per scope: auth 20/h, upload 30/h, render 60/h, reads 2000/h.
- **Argon2** password hashing, Django's validators, a 10-character minimum.
- **Login does not reveal who has an account**: a wrong password and an unknown
  email return byte-identical responses.
- **Secrets only from the environment.** `.env` is gitignored; `DJANGO_SECRET_KEY`
  has no usable default and the app refuses to boot without it when `DEBUG=false`.

---

## 9. Cost control

Designed for a small budget, because video is the expensive kind of workload.

1. **FFmpeg does the editing, not an AI model.** Trim, speed, crop, pad, rotate
   and overlays are all native filters. AI is reserved for text generation.
2. **Never render the same thing twice** — the fingerprint check above.
3. **A free preview endpoint** answers "how long and what size will this be?"
   without spending a worker slot.
4. **Never upscale.**
5. **Hard limits**, all environment-configurable: 512 MB upload, 10-minute
   source, 10-minute output, 5 GB per user, 50 exports/day, 2 concurrent renders.
6. **Output duration is capped, not just input** — 0.25x turns a 4-minute clip
   into 16 minutes of encoding.
7. **Quality tiers** cap resolution (480p/720p/1080p) and set CRF, so a user
   cannot ask for a 4K render of a 10-minute video.
8. **AI is off by default** (`AI_PROVIDER=disabled`) with a per-user daily cap.

---

## 10. Dependency plan

Everything is pinned. Bumps should be deliberate.

**Backend** — Django 5.1.4, DRF 3.15.2, simplejwt 5.3.1, django-cors-headers
4.6.0, django-environ 0.11.2, psycopg 3.2.3, Celery 5.4.0, redis 5.2.1,
django-storages 1.14.4, boto3 1.35.81, Pillow 11.0.0, argon2-cffi 23.1.0,
gunicorn 23.0.0, whitenoise 6.8.2. Dev: pytest 8.3.4, pytest-django 4.9.0,
pytest-cov 6.0.0, ruff 0.8.4.

**Frontend** — vue 3.5.44, vue-router 4.5.1, pinia 3.0.4. Dev: vite 7.3.7,
@vitejs/plugin-vue 6.0.10, tailwindcss 4.3.3, @tailwindcss/postcss 4.3.3,
postcss 8.5.31, vitest 5.0.5, @vue/test-utils 2.5.1, jsdom 30.1.3.

**System** — FFmpeg ≥ 6 with libx264 and aac, PostgreSQL ≥ 14, Redis ≥ 6.

`npm audit` reports **0 vulnerabilities**. The first version set chosen had a
Vue XSS advisory, a critical `tinypool` RCE and an esbuild dev-server issue; the
pins above are the patched versions.

### Deferred on purpose

- No `djangorestframework-simplejwt` cookie package: 30 lines of explicit cookie
  handling is clearer than a dependency here.
- No `django-filter`: three query parameters do not justify it.
- No WebSockets/Channels: polling is enough for a progress bar, and avoids
  running an ASGI stack. Revisit if renders routinely exceed a few minutes.
- No Sentry wired up, but `LOGGING` is structured so adding it is a settings change.

---

## 11. Risks

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| **Platform API approval** — TikTok, Instagram and YouTube all require a reviewed developer app, and Instagram needs a Business/Creator account via the Graph API. Review can take weeks and can be refused. | High | Blocks Phase 3 entirely | Build Phases 1-2 to full value without publishing. Start each application early. Keep each platform a separate, independently shippable integration. Surface approval state in the UI instead of failing silently. |
| **Render cost** — CPU encoding is the dominant cost and scales with duration × resolution × users. | High | Margin | Limits in §9; quality tiers; dedupe; `veryfast` preset at low/medium; output-duration cap. Measure before buying GPUs. |
| **Storage growth** — sources and exports both accumulate. | High | Margin | Per-user quota; deleting a source deletes its exports; lifecycle rules documented for production. |
| **A long render blocks a worker** | Medium | Throughput | Hard process timeout (50 min), `--concurrency=2`, `acks_late` with prefetch 1. Split queues by expected duration when needed. |
| **Malicious upload** — FFmpeg has had parser CVEs. | Medium | Severe | Validate before storing; run workers as non-root in a container; no shell; strip metadata. **Production should also sandbox the worker** (seccomp, a separate node pool, no outbound network) and keep FFmpeg patched. |
| **Duplicate publishing on retry** | Medium | User trust | Retry reuses the same row. Phase 3 adds an idempotency key per platform and records the platform's own post ID before reporting success. |
| **Token theft via XSS** | Medium | Severe | No token in web storage; HttpOnly refresh cookie; rotation with blacklist. |
| **Celery/Redis loss** — Redis is not durable by default. | Low | Queued jobs lost | `acks_late`; the reaper surfaces stuck jobs; enable AOF (compose does). Jobs are reconstructable from the database. |
| **Cost of the AI provider** | Low | Margin | Disabled by default, per-user daily cap, provider configurable. |
| **Music licensing** — Phase 2. | Medium | Legal | Only ship a library the project holds rights to, or integrate a licensed provider. Never scrape audio. |

---

## 12. MVP checklist

### Phase 1 — foundation ✅ **complete**

- [x] Vue 3 + Vite + Tailwind + Pinia frontend, mobile responsive
- [x] Registration, sign-in, sign-out, password change
- [x] Secure session: in-memory access token, HttpOnly rotating refresh cookie
- [x] Upload with real progress, validated by type, magic bytes, size, duration
- [x] FFprobe metadata extraction and poster-frame thumbnails
- [x] In-browser preview reflecting the current edit
- [x] Trim with draggable in/out points
- [x] Speed 0.25x / 0.5x / 1x / 1.5x / 2x with audio kept in sync
- [x] Aspect conversion: 9:16, 1:1, 16:9, 4:5, original — crop or letterbox
- [x] Rotation and mute
- [x] Three quality tiers
- [x] Background rendering via Celery with live progress, cancel and retry
- [x] Downloadable exports through expiring signed URLs
- [x] Export library, failed-job list with retry, storage/usage display
- [x] Ownership enforced on every resource; rate limits; quotas
- [x] Dedupe of identical edits; free preview endpoint
- [x] Health endpoint; stalled-job reaper
- [x] 208 automated tests (185 backend, 23 frontend) + browser and
      full-stack end-to-end verification
- [x] Docker Compose, `.env.example`, setup and deployment docs

### Phase 2 — richer editing and AI text

- [ ] Multi-clip merge and transitions
- [ ] Text overlays, titles, logo/watermark
- [ ] Subtitles with timing; burned-in captions
- [ ] Music and sound effects from a properly licensed source, with ducking
- [ ] AI captions, titles, descriptions, hashtags, hooks, thumbnail text —
      all editable and approved by the user before use
- [ ] Per-platform text variants
- [ ] Per-user AI usage accounting

### Phase 3 — publishing (one platform at a time)

- [ ] OAuth connection flow, token encryption at rest, refresh handling
- [ ] Connection and permission status surfaced in the UI, with the exact steps
      when an account type or app review is required
- [ ] YouTube Shorts via the YouTube Data API (resumable upload)
- [ ] TikTok via the Content Posting API
- [ ] Instagram Reels via the Graph API (Business/Creator accounts only)
- [ ] Idempotency keys; a post is only "published" once the platform confirms it
      and returns an ID
- [ ] Publish job history with errors and safe retries

### Phase 4 — commercial readiness

- [ ] Scheduling and a content calendar
- [ ] Subscription plans, billing, per-plan quotas
- [ ] Usage analytics and admin tooling
- [ ] Storage lifecycle rules, backups, restore drill
- [ ] Error tracking, metrics, alerting
- [ ] Load testing and worker autoscaling

---

## 13. What Phase 1 deliberately does not do

Stated plainly so nothing here is mistaken for working:

- **No social publishing.** No OAuth, no posting. Each platform requires its own
  approved developer application; this is Phase 3.
- **No AI.** `AI_PROVIDER` defaults to `disabled` and no AI endpoint exists.
- **No scheduling, calendar or billing.**
- **No music library or subtitles.**
- **No multi-clip merge.** One source per export.
- **No reach or engagement claims anywhere in the product.**
