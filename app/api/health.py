from __future__ import annotations

import shutil
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging_config import get_logger
from app.core.rate_limiter import get_redis
from app.dependencies import get_db

logger = get_logger(__name__)
router = APIRouter(tags=["health"])


@router.get("/api/v1/health")
async def health_check() -> dict:
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "environment": settings.environment,
    }


@router.get("/api/v1/health/detailed")
async def detailed_health(db: AsyncSession = Depends(get_db)) -> dict:
    checks = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "environment": settings.environment,
    }

    db_status = "unknown"
    db_latency = None
    try:
        start = time.monotonic()
        await db.execute(text("SELECT 1"))
        db_latency = (time.monotonic() - start) * 1000
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
        checks["status"] = "degraded"

    checks["database"] = {
        "status": db_status,
        "latency_ms": round(db_latency, 2) if db_latency else None,
    }

    redis_status = "unknown"
    try:
        redis = get_redis()
        if redis:
            await redis.ping()
            redis_status = "healthy"
        else:
            redis_status = "not_configured"
    except Exception as e:
        redis_status = f"unhealthy: {str(e)}"
        checks["status"] = "degraded"

    checks["redis"] = {"status": redis_status}

    disk_usage = shutil.disk_usage(settings.storage.upload_path)
    disk_free_mb = disk_usage.free / (1024 * 1024)
    disk_total_mb = disk_usage.total / (1024 * 1024)
    disk_used_percent = (disk_usage.used / disk_usage.total) * 100

    checks["storage"] = {
        "upload_dir": str(settings.storage.upload_path),
        "output_dir": str(settings.storage.output_path),
        "free_mb": round(disk_free_mb, 2),
        "total_mb": round(disk_total_mb, 2),
        "used_percent": round(disk_used_percent, 2),
        "status": "healthy" if disk_free_mb > 100 else "warning",
    }

    checks["api"] = {
        "base_url": settings.storage.upload_path,
        "max_file_size_mb": settings.storage.max_file_size_mb,
        "rate_limit_per_minute": settings.rate_limit_per_minute,
    }

    return checks
