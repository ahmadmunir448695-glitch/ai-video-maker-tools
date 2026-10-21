"""Celery entry point.

Imported by ``config/__init__.py`` so that ``@shared_task`` decorators bind to
this app, and used by the worker command in the Procfile / docker-compose.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("aivideo")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
