"""Django settings for the AI Video Editor backend.

Every deployment-specific value is read from the environment. Nothing secret has
a usable default: ``DJANGO_SECRET_KEY`` is required whenever ``DEBUG`` is off, and
the storage/AI/OAuth credentials simply stay empty until they are provided.

Infrastructure degrades gracefully so a beginner can run the app with no Docker:
  * no ``DATABASE_URL``        -> SQLite file under ``var/``
  * no ``REDIS_URL``           -> Celery runs tasks eagerly, in-process
  * no ``AWS_STORAGE_BUCKET_NAME`` -> uploads land on local disk under ``var/media``
"""

from __future__ import annotations

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent

env = environ.Env()
for candidate in (REPO_DIR / ".env", BASE_DIR / ".env"):
    if candidate.exists():
        env.read_env(str(candidate))
        break

# --------------------------------------------------------------------------- core

DEBUG = env.bool("DJANGO_DEBUG", default=False)

if DEBUG:
    SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-development-key-do-not-deploy")
else:
    # Deliberately no default: refuse to boot in production without a real key.
    SECRET_KEY = env("DJANGO_SECRET_KEY")

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "[::1]"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "apps.core",
    "apps.accounts",
    "apps.videos",
    "apps.editing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ----------------------------------------------------------------------- database

VAR_DIR = Path(env("APP_VAR_DIR", default=str(REPO_DIR / "var")))
VAR_DIR.mkdir(parents=True, exist_ok=True)

if env("DATABASE_URL", default=""):
    DATABASES = {"default": env.db("DATABASE_URL")}
    DATABASES["default"].setdefault("CONN_MAX_AGE", 60)
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(VAR_DIR / "db.sqlite3"),
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

# --------------------------------------------------------------------------- auth

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

# ------------------------------------------------------------------- i18n / static

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("DJANGO_TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = VAR_DIR / "static"
STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# ------------------------------------------------------------------------ storage

AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="")

if AWS_STORAGE_BUCKET_NAME:
    # S3-compatible object storage (AWS S3, MinIO, Backblaze B2, Cloudflare R2...).
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": AWS_STORAGE_BUCKET_NAME,
            "region_name": env("AWS_S3_REGION_NAME", default="us-east-1"),
            "endpoint_url": env("AWS_S3_ENDPOINT_URL", default=None) or None,
            "access_key": env("AWS_ACCESS_KEY_ID", default=None) or None,
            "secret_key": env("AWS_SECRET_ACCESS_KEY", default=None) or None,
            # Private by default: every object is reached through a signed URL that
            # we only mint after checking the requesting user owns the row.
            "default_acl": None,
            "querystring_auth": True,
            "querystring_expire": env.int("AWS_S3_URL_EXPIRE_SECONDS", default=900),
            "addressing_style": env("AWS_S3_ADDRESSING_STYLE", default="virtual"),
            "file_overwrite": False,
            "signature_version": "s3v4",
        },
    }
    MEDIA_URL = env("MEDIA_URL", default="")
else:
    STORAGES["default"] = {"BACKEND": "django.core.files.storage.FileSystemStorage"}
    MEDIA_ROOT = VAR_DIR / "media"
    MEDIA_URL = "media/"

USE_OBJECT_STORAGE = bool(AWS_STORAGE_BUCKET_NAME)

# Uploads larger than this are streamed to a temp file instead of held in memory.
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# -------------------------------------------------------------- DRF / JWT settings

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_THROTTLE_CLASSES": ("rest_framework.throttling.ScopedRateThrottle",),
    "DEFAULT_THROTTLE_RATES": {
        "auth": env("THROTTLE_AUTH", default="20/hour"),
        "upload": env("THROTTLE_UPLOAD", default="30/hour"),
        "render": env("THROTTLE_RENDER", default="60/hour"),
        "read": env("THROTTLE_READ", default="2000/hour"),
    },
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.DefaultPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

from datetime import timedelta

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=30)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=14)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": env("JWT_SIGNING_KEY", default=SECRET_KEY),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# The refresh token lives in an HttpOnly cookie so JavaScript (and therefore any
# XSS payload) cannot read it. The short-lived access token is held in memory by
# the SPA only — never in localStorage.
REFRESH_COOKIE_NAME = "avm_refresh"
REFRESH_COOKIE_PATH = "/api/auth/"
REFRESH_COOKIE_SECURE = env.bool("REFRESH_COOKIE_SECURE", default=not DEBUG)
REFRESH_COOKIE_SAMESITE = env("REFRESH_COOKIE_SAMESITE", default="Lax")

# ---------------------------------------------------------------------- CORS / SPA

CORS_ALLOWED_ORIGINS = env.list("DJANGO_CORS_ALLOWED_ORIGINS", default=["http://localhost:5173"])
CORS_ALLOW_CREDENTIALS = True

# ------------------------------------------------------------------------- Celery

REDIS_URL = env("REDIS_URL", default="")
CELERY_BROKER_URL = REDIS_URL or "memory://"
CELERY_RESULT_BACKEND = REDIS_URL or "cache+memory://"
# With no Redis configured, run tasks inline so the app still works end to end.
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=not REDIS_URL)
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = env.int("CELERY_TASK_TIME_LIMIT", default=3600)
CELERY_TASK_SOFT_TIME_LIMIT = env.int("CELERY_TASK_SOFT_TIME_LIMIT", default=3300)
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_TRACK_STARTED = True

# ------------------------------------------------------- media limits (cost control)

FFMPEG_BINARY = env("FFMPEG_BINARY", default="ffmpeg")
FFPROBE_BINARY = env("FFPROBE_BINARY", default="ffprobe")

MAX_UPLOAD_BYTES = env.int("MAX_UPLOAD_BYTES", default=512 * 1024 * 1024)
MAX_UPLOAD_DURATION_SECONDS = env.int("MAX_UPLOAD_DURATION_SECONDS", default=600)
MAX_OUTPUT_DURATION_SECONDS = env.int("MAX_OUTPUT_DURATION_SECONDS", default=600)
MAX_STORAGE_BYTES_PER_USER = env.int("MAX_STORAGE_BYTES_PER_USER", default=5 * 1024 * 1024 * 1024)
MAX_EXPORTS_PER_DAY = env.int("MAX_EXPORTS_PER_DAY", default=50)
MAX_CONCURRENT_RENDERS_PER_USER = env.int("MAX_CONCURRENT_RENDERS_PER_USER", default=2)
RENDER_PROCESS_TIMEOUT_SECONDS = env.int("RENDER_PROCESS_TIMEOUT_SECONDS", default=3000)

ALLOWED_UPLOAD_EXTENSIONS = env.list(
    "ALLOWED_UPLOAD_EXTENSIONS",
    default=["mp4", "mov", "m4v", "webm", "mkv", "avi"],
)
ALLOWED_UPLOAD_CONTENT_TYPES = env.list(
    "ALLOWED_UPLOAD_CONTENT_TYPES",
    default=[
        "video/mp4",
        "video/quicktime",
        "video/x-m4v",
        "video/webm",
        "video/x-matroska",
        "video/x-msvideo",
        "application/octet-stream",
    ],
)

# ----------------------------------------------------------------- AI (Phase 2+)

AI_PROVIDER = env("AI_PROVIDER", default="disabled")
AI_API_KEY = env("AI_API_KEY", default="")
AI_MODEL = env("AI_MODEL", default="")
AI_MAX_CALLS_PER_USER_PER_DAY = env.int("AI_MAX_CALLS_PER_USER_PER_DAY", default=20)

# ------------------------------------------------------------------------ security

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False

if not DEBUG:
    SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ------------------------------------------------------------------------ logging

LOG_LEVEL = env("DJANGO_LOG_LEVEL", default="INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "apps": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}
