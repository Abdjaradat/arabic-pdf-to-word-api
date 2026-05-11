from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "arabic_pdf_converter",
    broker=settings.celery.celery_broker_url,
    backend=settings.celery.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=1800,
    task_soft_time_limit=1500,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=10,
    result_expires=86400,
)

celery_app.conf.task_routes = {
    "app.worker.tasks.process_conversion": {"queue": "conversions"},
    "app.worker.tasks.cleanup_old_files": {"queue": "maintenance"},
    "app.worker.tasks.send_conversion_complete_notification": {"queue": "notifications"},
}

celery_app.conf.beat_schedule = {
    "cleanup-old-files": {
        "task": "app.worker.tasks.cleanup_old_files",
        "schedule": crontab(hour=3, minute=0),
    },
}
