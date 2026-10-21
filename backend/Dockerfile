# Backend image, shared by the API, the Celery worker and beat.
#
# FFmpeg is the one heavyweight dependency and it must be in the image: the
# worker cannot render without it, and the API uses FFprobe to validate uploads.

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so a code change does not invalidate the install layer.
COPY backend/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY backend/ /app/

# Run as a non-root user: a render is a subprocess handling untrusted media.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/var \
    && chown -R appuser:appuser /app
USER appuser

ENV DJANGO_SETTINGS_MODULE=config.settings \
    APP_VAR_DIR=/app/var

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
