from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.api import auth, convert, health
from app.config import settings
from app.core.logging_config import get_logger, setup_logging
from app.core.rate_limiter import close_rate_limiter, init_rate_limiter
from app.dependencies import close_db, init_db

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting application in %s mode",
        settings.environment,
    )

    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            integrations=[
                StarletteIntegration(),
                FastApiIntegration(),
            ],
            traces_sample_rate=0.1 if settings.is_production else 1.0,
        )
        logger.info("Sentry initialized")

    await init_db()
    await init_rate_limiter()

    instrumentator = Instrumentator().instrument(app)
    instrumentator.expose(app, endpoint="/api/v1/metrics")
    logger.info("Prometheus metrics enabled at /api/v1/metrics")

    yield

    await close_rate_limiter()
    await close_db()
    logger.info("Application shutdown complete")


app = FastAPI(
    title="Arabic PDF To Word AI Converter API",
    description="Convert Arabic PDF files to DOCX format with OCR support",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.is_development else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start_time = time.monotonic()

    body = None
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            body = await request.body()
        except Exception:
            pass

    response = await call_next(request)

    process_time = (time.monotonic() - start_time) * 1000

    log_data = {
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "duration_ms": round(process_time, 2),
        "ip": request.client.host if request.client else "unknown",
    }

    if response.status_code >= 500:
        logger.error("Request failed", **log_data)
    elif response.status_code >= 400:
        logger.warning("Request warning", **log_data)
    else:
        logger.info("Request completed", **log_data)

    response.headers["X-Process-Time-Ms"] = str(round(process_time, 2))
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception: %s", str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred",
            "path": request.url.path,
        },
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    logger.warning("Value error: %s", str(exc))
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc), "path": request.url.path},
    )


@app.exception_handler(PermissionError)
async def permission_error_handler(request: Request, exc: PermissionError) -> JSONResponse:
    logger.warning("Permission error: %s", str(exc))
    return JSONResponse(
        status_code=403,
        content={"detail": "Access denied", "path": request.url.path},
    )


@app.exception_handler(FileNotFoundError)
async def file_not_found_handler(request: Request, exc: FileNotFoundError) -> JSONResponse:
    logger.warning("File not found: %s", str(exc))
    return JSONResponse(
        status_code=404,
        content={"detail": "Resource not found", "path": request.url.path},
    )


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(convert.router)
