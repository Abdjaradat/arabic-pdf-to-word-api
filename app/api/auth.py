from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_token,
)
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.user import (
    PremiumUpgrade,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    UserStats,
    UserUpdate,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == payload.email))
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    await db.flush()

    access_token = create_access_token(
        subject=user.id,
        extra_claims={"email": user.email},
    )
    refresh_token = create_refresh_token(subject=user.id)

    logger.info("User registered: %s", user.email)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=60,
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    access_token = create_access_token(
        subject=user.id,
        extra_claims={"email": user.email},
    )
    refresh_token = create_refresh_token(subject=user.id)

    logger.info("User logged in: %s", user.email)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    payload_data = verify_token(payload.refresh_token, expected_type="refresh")
    if payload_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user_id = payload_data.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )

    access_token = create_access_token(
        subject=user.id,
        extra_claims={"email": user.email},
    )
    refresh_token = create_refresh_token(subject=user.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=60,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.put("/me", response_model=UserResponse)
async def update_me(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    if payload.full_name is not None:
        current_user.full_name = payload.full_name

    db.add(current_user)
    await db.flush()

    logger.info("User updated: %s", current_user.email)
    return UserResponse.model_validate(current_user)


@router.post("/forgot-password")
async def forgot_password(request: Request, payload: dict) -> dict:
    email = payload.get("email", "")
    logger.info("Password reset requested for: %s", email)

    return {
        "message": "If an account with that email exists, a password reset link has been sent.",
    }


@router.get("/stats", response_model=UserStats)
async def get_user_stats(
    current_user: User = Depends(get_current_user),
) -> UserStats:
    from datetime import date

    today = date.today()
    daily_limit = 5 if not current_user.is_premium_active else 999999

    return UserStats(
        total_conversions=current_user.conversion_count,
        daily_conversions=(
            current_user.daily_conversion_count
            if current_user.last_conversion_date == today
            else 0
        ),
        daily_limit=daily_limit,
        premium=current_user.is_premium_active,
        premium_until=current_user.premium_until,
    )


@router.post("/upgrade", response_model=UserResponse)
async def upgrade_to_premium(
    payload: PremiumUpgrade,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    from datetime import date, timedelta

    current_user.is_premium = True
    if current_user.premium_until and current_user.premium_until > date.today():
        current_user.premium_until += timedelta(days=payload.duration_days)
    else:
        current_user.premium_until = date.today() + timedelta(days=payload.duration_days)

    db.add(current_user)
    await db.flush()

    logger.info(
        "User upgraded to premium: %s until %s",
        current_user.email,
        current_user.premium_until,
    )
    return UserResponse.model_validate(current_user)
