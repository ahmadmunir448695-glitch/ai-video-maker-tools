# Deployment

How to run this in production. It assumes the Phase 1 application as built:
a Django API, a Celery worker, PostgreSQL, Redis, object storage, and a static
SPA.

---

## 1. Shape of a deployment

```
        ┌──────────────┐
        │  CDN / nginx │  the built SPA (static files)
        └──────┬───────┘
               │ /api/*
        ┌──────▼───────┐
        │  API (N×)    │  gunicorn, stateless, autoscales on requests
        └──────┬───────┘
               ├────────────► PostgreSQL (managed, backups on)
               ├────────────► Redis (managed, AOF on)
               └────────────► S3-compatible bucket (private)
        ┌──────────────┐
        │ Worker (M×)  │  celery, CPU-bound, scales on queue depth
        │ Beat (1×)    │  exactly one, for the stalled-job reaper
        └──────────────┘
```

The API and the worker run the **same image**; only the command differs. The
worker is the component that needs CPU and FFmpeg throughput; the API barely
needs either.

**Run exactly one beat process.** Two will run the reaper twice — harmless here,
but it becomes a real problem once Phase 4 adds scheduled publishing.

---

## 2. Before the first deploy

### Generate a secret key

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Store it in your platform's secret manager — never in the image, the repo, or a
build argument.

### Required environment

```ini
DJANGO_DEBUG=false
DJANGO_SECRET_KEY=<from your secret manager>
DJANGO_ALLOWED_HOSTS=api.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://app.example.com
DJANGO_CORS_ALLOWED_ORIGINS=https://app.example.com

DATABASE_URL=postgres://user:password@host:5432/aivideo
REDIS_URL=redis://host:6379/0

AWS_STORAGE_BUCKET_NAME=your-bucket
AWS_S3_REGION_NAME=eu-west-1
AWS_ACCESS_KEY_ID=<key>
AWS_SECRET_ACCESS_KEY=<secret>
AWS_S3_URL_EXPIRE_SECONDS=900

REFRESH_COOKIE_SECURE=true
REFRESH_COOKIE_SAMESITE=Lax
```

With `DJANGO_DEBUG=false` the app **will not start** without
`DJANGO_SECRET_KEY`. That is deliberate.

### Same site or cross site?

The refresh cookie is scoped to `/api/auth/` and set `SameSite=Lax`.

- **Same site** (`app.example.com` serving the SPA and proxying `/api` to the
  API) — nothing more to do. This is the recommended setup.
- **Cross site** (`app.example.com` → `api.example.com`) — set
  `REFRESH_COOKIE_SAMESITE=None`. It then **must** also be `Secure`, so HTTPS is
  mandatory, and `DJANGO_CORS_ALLOWED_ORIGINS` must name the SPA origin exactly.

---

## 3. Build and run

```bash
docker build -f backend/Dockerfile -t reelcraft-api:TAG .
docker build -f frontend/Dockerfile -t reelcraft-web:TAG .
```

Commands per role, same API image:

```bash
# API
python manage.py migrate --noinput
python manage.py collectstatic --noinput
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120

# Worker — concurrency should be about the number of CPU cores, not more.
celery -A config worker --loglevel=info --concurrency=2 --max-tasks-per-child=50

# Beat — exactly one replica
celery -A config beat --loglevel=info
```

`--max-tasks-per-child` recycles workers periodically, which caps the damage
from any slow leak in long-running FFmpeg subprocesses.

Run migrations as a **release step**, before the new version takes traffic —
not on every container start, or N replicas will race.

---

## 4. Sizing

| Component | Start with | Scale on |
| --- | --- | --- |
| API | 2 × (0.5 vCPU, 512 MB) | Request latency |
| Worker | 2 × (2 vCPU, 2 GB) | Celery queue depth |
| Beat | 1 × (0.25 vCPU, 256 MB) | Never |
| PostgreSQL | Smallest managed tier | Connections, storage |
| Redis | Smallest managed tier, AOF on | Memory |

A render is roughly **0.3–1× realtime per core** at 720p `veryfast`. One
2-vCPU worker at `--concurrency=2` handles a few hundred one-minute 720p exports
a day. Watch queue wait time; add workers before users notice.

Give the worker **disk**: it needs room for a source plus an output
simultaneously. Several GB of ephemeral scratch is plenty, and it is cleaned up
after every job.

---

## 5. Storage

Create the bucket **private**. The app never sets a public ACL and mints a
signed URL only after checking ownership.

CORS on the bucket, so the browser can fetch previews and downloads:

```json
[{
  "AllowedOrigins": ["https://app.example.com"],
  "AllowedMethods": ["GET", "HEAD"],
  "AllowedHeaders": ["*"],
  "ExposeHeaders": ["Content-Length", "Content-Range"],
  "MaxAgeSeconds": 3000
}]
```

Lifecycle rules are the main lever on storage cost. A reasonable start:

- Move exports to infrequent-access after 30 days.
- Expire exports after 180 days, having warned users.
- Expire `sources/` for deleted accounts immediately.

The app deletes objects when a user deletes a video or export, so lifecycle
rules are a backstop, not the primary mechanism.

---

## 6. Health, logging and monitoring

`GET /api/health` returns 200 when healthy and **503 when degraded**, with a
per-dependency breakdown:

```json
{"status":"ok","checks":{"database":"ok","ffmpeg":"ok","ffprobe":"ok",
                         "queue":"ok","storage":"object-storage"}}
```

Point the load balancer's readiness probe at it. A worker image missing FFmpeg
reports `degraded`, which is exactly the failure you want caught at deploy time
rather than by the first user.

Logs go to stdout as structured lines. Unhandled API errors are logged with a
short reference that is also returned to the client, so a user's report can be
matched to a log line without exposing the traceback.

Worth alerting on:

- `/api/health` non-200 on any replica
- Celery queue depth, and oldest-task age
- Export failure rate over a rolling window
- `reap_stalled_jobs` returning non-zero repeatedly (workers are dying)
- Storage growth against budget

Add Sentry by installing `sentry-sdk` and initialising it in `config/settings.py`;
the logging configuration is already structured for it.

---

## 7. Securing the worker

The worker runs FFmpeg over files uploaded by strangers. FFmpeg is mature but
has had parser vulnerabilities, so treat the worker as the exposed component:

- It already runs as a **non-root** user in the image.
- Give it **no inbound** network and the **minimum outbound** it needs
  (database, Redis, object storage). It never needs the public internet.
- Run it on a **separate node pool** from the API where your platform allows.
- Apply a seccomp profile and drop all Linux capabilities.
- Keep the base image patched — FFmpeg updates matter more here than elsewhere.
- Keep `RENDER_PROCESS_TIMEOUT_SECONDS` and the Celery time limits set, so a
  pathological file cannot occupy a worker indefinitely.

---

## 8. Backups

- **PostgreSQL** — managed automated backups, point-in-time recovery on. This
  holds accounts, jobs and every edit spec.
- **Object storage** — enable versioning. Re-rendering from a lost source is
  impossible; re-rendering an export from its stored spec is trivial.
- **Redis** — nothing irreplaceable. A lost queue means some jobs stop
  progressing; the reaper marks them failed and users retry.

**Rehearse a restore.** A backup you have never restored is a hypothesis.

---

## 9. Deploy checklist

Before the first production deploy:

- [ ] `DJANGO_DEBUG=false` and a real `DJANGO_SECRET_KEY` from a secret manager
- [ ] `DJANGO_ALLOWED_HOSTS` set to the real hostname
- [ ] HTTPS terminated; `REFRESH_COOKIE_SECURE=true`
- [ ] `python manage.py check --deploy` reviewed
- [ ] Database is managed, with backups and PITR enabled
- [ ] Bucket is private, with CORS and lifecycle rules configured
- [ ] Worker image verified to contain FFmpeg (`/api/health` says `ok`)
- [ ] Exactly one beat replica
- [ ] Migrations run as a release step, not on container start
- [ ] Limits in §Configuration reviewed against your budget
- [ ] Monitoring and alerts wired up
- [ ] A superuser created (`python manage.py createsuperuser`) and `/admin/`
      restricted by IP or put behind SSO

Before Phase 3 (publishing):

- [ ] OAuth tokens encrypted at rest, not merely stored
- [ ] A developer application submitted and approved per platform
- [ ] Idempotency keys on every publish, so a retry cannot double-post
