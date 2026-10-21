# Reelcraft — AI Video Editor & Social Media Auto Publisher

Upload a video, edit it with server-side FFmpeg, and export it ready for
TikTok, Instagram Reels and YouTube Shorts.

**Phase 1 is built and working.** You can register, upload a video, trim it,
change its speed, convert it to vertical/square/landscape, and download the
rendered result. Rendering is real FFmpeg work on a background worker.

Publishing to social platforms, AI captions, music and scheduling are **not
built yet** — see [the roadmap](docs/ARCHITECTURE.md#12-mvp-checklist). The app
labels those features with the phase they belong to rather than showing buttons
that do nothing.

---

## What Phase 1 does

- **Accounts** — register and sign in. The access token lives in memory only;
  the refresh token is an HttpOnly cookie that JavaScript cannot read.
- **Upload** — MP4, MOV, WebM, MKV, M4V and AVI, with a real progress bar.
  Files are checked by type, magic bytes, size and duration, and rejected unless
  FFprobe can actually read a video stream out of them.
- **Edit** — trim with draggable in/out points, speed from 0.25x to 2x (audio
  stays in sync), convert to vertical 9:16, square 1:1, landscape 16:9 or
  portrait 4:5, crop or letterbox, rotate, mute, three quality tiers.
- **Preview** — see the edit in the browser before spending a render, and see
  the exact output size and duration the server will produce.
- **Export** — rendering runs on a background worker with live progress. Cancel
  it, retry a failure, download the result through an expiring signed URL.
- **Limits** — per-user storage, daily exports and concurrent renders, all shown
  in the app and all configurable.

Works on a phone: a bottom tab bar, large tap targets and no horizontal scroll.

---

## Quick start

### What you need

- **Python 3.11+**
- **Node.js 20+**
- **FFmpeg 6+** (with `libx264` and `aac`) — `ffmpeg -version` must work
- Optionally **Docker**, for PostgreSQL, Redis and MinIO

> No Docker? It still runs. With no `DATABASE_URL` it uses a SQLite file, with
> no `REDIS_URL` it renders in-process, and with no bucket it stores files on
> local disk. That is enough to use every Phase 1 feature on a laptop.

### 1. Configure

```bash
git clone https://github.com/ahmadmunir448695-glitch/ai-video-maker-tools.git
cd ai-video-maker-tools
cp .env.example .env
```

Open `.env` and set a secret key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Paste it as `DJANGO_SECRET_KEY`. **Never commit `.env`** — it is gitignored.

### 2. Start the infrastructure (optional but recommended)

```bash
docker compose up -d
```

That gives you PostgreSQL, Redis and a MinIO bucket. Then uncomment these in
`.env`:

```ini
DATABASE_URL=postgres://aivideo:aivideo@localhost:5432/aivideo
REDIS_URL=redis://localhost:6379/0
```

### 3. Backend

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r backend/requirements-dev.txt

cd backend
python manage.py migrate
python manage.py runserver
```

The API is now on <http://localhost:8000>. Check it:

```bash
curl http://localhost:8000/api/health
```

### 4. Worker (only if you set `REDIS_URL`)

In a second terminal:

```bash
source .venv/bin/activate
cd backend
celery -A config worker --loglevel=info --concurrency=2
```

And optionally a third for the periodic cleanup of abandoned jobs:

```bash
celery -A config beat --loglevel=info
```

### 5. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173> and create an account.

---

## Tests

```bash
# Backend — 185 tests, including real FFmpeg renders verified with FFprobe
source .venv/bin/activate
cd backend && python -m pytest

# Skip the slower render tests
python -m pytest -m "not ffmpeg"

# Frontend — 23 tests
cd frontend && npm test

# Lint
ruff check .
```

The backend suite covers authentication, authorization on every resource,
upload validation, quotas, rate limits, the job lifecycle, and the FFmpeg
pipeline itself — trims, speed changes, audio sync, aspect conversion,
cancellation and failure handling — by rendering real files and probing them.

---

## How it fits together

```
Vue SPA  ──HTTP──>  Django REST API  ──enqueue──>  Redis  ──>  Celery worker
                          │                                        │
                          └────────── PostgreSQL ──────────────────┘
                                           │
                                  S3-compatible storage
                                  (or local disk in dev)
```

A render never happens inside a web request. The API validates the edit, checks
quotas, writes a job row and returns; a worker picks it up, runs FFmpeg, reports
progress, and stores the output. The SPA polls while anything is running.

Full detail — data model, filter-graph order, failure handling, security and
cost design — is in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.
Deploying it is in **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

---

## API

All routes need a signed-in user except `health` and the auth routes, and every
route only ever touches the requesting user's own rows.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Dependency check for load balancers |
| POST | `/api/auth/register`, `/api/auth/login`, `/api/auth/logout` | Accounts |
| POST | `/api/auth/refresh` | Exchange the refresh cookie for an access token |
| GET / PATCH | `/api/auth/me` | Profile and current usage |
| POST | `/api/auth/password` | Change password |
| GET / POST | `/api/videos/` | List or upload source videos |
| GET / DELETE | `/api/videos/{id}/` | One video; delete it and its exports |
| GET | `/api/videos/{id}/download/` | Signed URL for the original |
| GET | `/api/editor/options` | Speeds, aspects, qualities and limits |
| POST | `/api/editor/preview` | Predict output size and duration — renders nothing |
| GET / POST | `/api/exports/` | List (`?status=`, `?source=`) or queue a render |
| GET / DELETE | `/api/exports/{id}/` | One export |
| POST | `/api/exports/{id}/cancel/`, `/api/exports/{id}/retry/` | Job control |
| GET | `/api/exports/{id}/download/` | Signed URL for the rendered file |

Posting an edit identical to one already exported returns the existing export
(HTTP 200 with `X-Export-Reused: true`) instead of rendering it twice.

---

## Configuration

Every setting comes from the environment. `.env.example` lists all of them with
comments; the ones worth knowing:

| Variable | Default | What it does |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | *(required unless DEBUG)* | Signing key. The app refuses to boot in production without it. |
| `DATABASE_URL` | SQLite under `var/` | PostgreSQL connection string. |
| `REDIS_URL` | *(empty → run inline)* | Celery broker. |
| `AWS_STORAGE_BUCKET_NAME` | *(empty → local disk)* | S3-compatible bucket. |
| `MAX_UPLOAD_BYTES` | 512 MB | Largest upload accepted. |
| `MAX_UPLOAD_DURATION_SECONDS` | 600 | Longest source accepted. |
| `MAX_OUTPUT_DURATION_SECONDS` | 600 | Longest export — slow motion multiplies this. |
| `MAX_STORAGE_BYTES_PER_USER` | 5 GB | Sources plus exports. |
| `MAX_EXPORTS_PER_DAY` | 50 | Per user. |
| `MAX_CONCURRENT_RENDERS_PER_USER` | 2 | Stops one user occupying every worker. |
| `AI_PROVIDER` | `disabled` | Phase 2. Nothing calls an AI provider yet. |

---

## Honest limitations

- One source video per export; merging clips is Phase 2.
- No social publishing. Each platform needs its own reviewed developer
  application, so it is built one platform at a time in Phase 3.
- No AI features are wired up, despite the configuration placeholders.
- Progress is polled every 2.5 seconds, not pushed over a WebSocket.
- Rendering is CPU-only. Fine at this scale; revisit if volume grows.

## Licence

No licence has been chosen yet. Add one before distributing.
