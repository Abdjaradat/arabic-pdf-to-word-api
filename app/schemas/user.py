from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str | None = Field(None, max_length=255)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str | None = None
    is_premium: bool = False
    premium_until: date | None = None
    is_active: bool = True
    conversion_count: int = 0
    daily_conversion_count: int = 0
    last_conversion_date: date | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, max_length=255)


class PremiumUpgrade(BaseModel):
    duration_days: int = Field(..., ge=1, le=365)


class UserStats(BaseModel):
    total_conversions: int
    daily_conversions: int
    daily_limit: int
    premium: bool
    premium_until: date | None = None
