from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import redis as sync_redis

from app.config import settings
from app.core.logging_config import get_logger
from app.services.conversion_pipeline import ConversionPipeline
from app.worker.queue import celery_app

logger = get_logger(__name__)

_redis_client: sync_redis.Redis | None = None


def _get_redis() -> sync_redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = sync_redis.from_url(
            settings.celery.celery_result_backend,
            decode_responses=True,
        )
    return _redis_client


def _update_progress(conversion_id: str, progress: float, message: str) -> None:
    try:
        redis = _get_redis()
        progress_key = f"conversion:progress:{conversion_id}"
        redis.setex(
            progress_key,
            3600,
            json.dumps({"progress": progress, "message": message}),
        )
    except Exception as e:
        logger.warning("Failed to update progress: %s", str(e))


@celery_app.task(bind=True, name="app.worker.tasks.process_conversion", max_retries=3)
def process_conversion(
    self,
    file_path: str,
    conversion_id: str,
    language: str = "ara",
    force_ocr: bool = False,
) -> dict:
    logger.info("Starting conversion task: id=%s", conversion_id)

    def progress_callback(progress: float, message: str) -> None:
        _update_progress(conversion_id, progress, message)
        self.update_state(
            state="PROGRESS",
            meta={"progress": progress, "message": message},
        )

    try:
        pipeline = ConversionPipeline(
            file_path=file_path,
            conversion_id=conversion_id,
            language=language,
            force_ocr=force_ocr,
            progress_callback=progress_callback,
        )

        result = pipeline.run()
        logger.info("Conversion task completed: id=%s", conversion_id)

        return {
            "success": True,
            "conversion_id": conversion_id,
            "output_path": result["output_path"],
            "output_size": result["output_size"],
            "page_count": result["page_count"],
            "ocr_used": result["ocr_used"],
            "ocr_engine": result.get("ocr_engine"),
        }
    except Exception as exc:
        logger.error("Conversion task failed: id=%s, error=%s", conversion_id, str(exc))

        try:
            self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
        except Exception:
            return {
                "success": False,
                "conversion_id": conversion_id,
                "error": str(exc),
            }

        return {
            "success": False,
            "conversion_id": conversion_id,
            "error": str(exc),
        }


@celery_app.task(name="app.worker.tasks.cleanup_old_files")
def cleanup_old_files() -> dict:
    logger.info("Starting cleanup of old files")

    cleaned = 0
    errors = 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    for directory in [settings.storage.upload_path, settings.storage.output_path]:
        if not directory.exists():
            continue

        for item in directory.iterdir():
            if not item.is_file():
                continue

            try:
                mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    item.unlink()
                    cleaned += 1
                    logger.debug("Cleaned up: %s", item.name)
            except Exception as e:
                errors += 1
                logger.warning("Failed to clean up %s: %s", item.name, str(e))

    temp_dir = Path("/tmp")
    if temp_dir.exists():
        for item in temp_dir.glob("conv_*"):
            if item.is_dir():
                try:
                    shutil.rmtree(item)
                    cleaned += 1
                except Exception as e:
                    errors += 1
                    logger.warning("Failed to clean up temp dir %s: %s", item.name, str(e))

    logger.info("Cleanup complete: %d files removed, %d errors", cleaned, errors)

    return {
        "files_removed": cleaned,
        "errors": errors,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@celery_app.task(name="app.worker.tasks.send_conversion_complete_notification")
def send_conversion_complete_notification(
    user_id: str,
    conversion_id: str,
    email: str,
) -> dict:
    logger.info(
        "Notification placeholder: conversion complete for user=%s, id=%s",
        user_id,
        conversion_id,
    )

    return {
        "success": True,
        "message": "Notification sent",
        "user_id": user_id,
        "conversion_id": conversion_id,
    }
