from __future__ import annotations

import os
from pathlib import Path
from typing import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.core.logging_config import get_logger
from app.core.rate_limiter import check_rate_limit, get_rate_limit_identifier
from app.core.security import generate_secure_filename, verify_token
from app.models.user import User

logger = get_logger(__name__)

_engine = None
_async_session_maker = None


async def init_db() -> None:
    global _engine, _async_session_maker
    if _engine is None:
        _engine = create_async_engine(
            settings.db.database_url,
            echo=settings.is_development,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
        )
        _async_session_maker = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        logger.info("Database engine initialized")


async def close_db() -> None:
    global _engine, _async_session_maker
    if _engine:
        await _engine.dispose()
        _engine = None
        _async_session_maker = None
        logger.info("Database engine disposed")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    if _async_session_maker is None:
        await init_db()

    session = _async_session_maker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_token(credentials.credentials, expected_type="access")
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )

    return user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None

    payload = verify_token(credentials.credentials, expected_type="access")
    if payload is None:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_rate_limiter(request: Request, user: User | None = Depends(get_optional_user)) -> None:
    identifier = await get_rate_limit_identifier(
        user_id=user.id if user else None,
        ip_address=request.client.host if request.client else "unknown",
    )

    max_requests = settings.rate_limit_per_minute
    if user and user.is_premium_active:
        max_requests = max_requests * 3

    result = await check_rate_limit(
        identifier=identifier,
        route=request.url.path,
        max_requests=max_requests,
    )

    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "message": "Rate limit exceeded",
                "remaining": result.remaining,
                "reset_after_seconds": result.reset_after_seconds,
            },
        )


_ALLOWED_EXTENSIONS = {".pdf"}
_MAX_FILE_SIZE = settings.storage.max_file_size_bytes


async def validate_file(
    filename: str,
    content_type: str | None = None,
    file_size: int | None = None,
) -> tuple[str, str]:
    ext = Path(filename).suffix.lower()

    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file extension '{ext}'. Only PDF files are allowed.",
        )

    if content_type and content_type not in (
        "application/pdf",
        "application/octet-stream",
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid content type '{content_type}'. Only PDF files are allowed.",
        )

    if file_size is not None and file_size > _MAX_FILE_SIZE:
        max_mb = _MAX_FILE_SIZE / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large ({file_size / (1024 * 1024):.1f} MB). "
            f"Maximum allowed size is {max_mb:.0f} MB.",
        )

    if file_size is not None and file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    safe_name, _ = generate_secure_filename(filename)

    return safe_name, ext
